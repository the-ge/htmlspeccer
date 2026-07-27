import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from util import write_ndjson

logger = logging.getLogger(__name__)

# ---- Raw records (stage 1: faithful extraction, one dataclass per NDJSON file) ----
# Field values are cell/anchor text, stripped of surrounding whitespace only.
# No splitting, typing, or spec-specific interpretation happens here — that's
# stage 2's job (parser.py), operating on these same dataclasses.


@dataclass(frozen=True, slots=True)
class RawAriaRole:
    name: str
    url: str
    deprecated_since_version: str


@dataclass(frozen=True, slots=True)
class RawAttribute:
    attribute: str
    elements: str
    description: str
    value: str
    urls: list[str]


@dataclass(frozen=True, slots=True)
class RawContentCategory:
    category: str
    url: str
    elements: str
    exceptions: str


@dataclass(frozen=True, slots=True)
class RawElement:
    element: str
    description: str
    categories: str
    children: str
    attributes: str


@dataclass(frozen=True, slots=True)
class RawElementKind:
    name: str  # literal <dfn> text, pre-slugify — slugified in stage 2
    tags: list[str]
    info: str


@dataclass(frozen=True, slots=True)
class RawEventHandler:
    attribute: str
    elements: str


@dataclass(frozen=True, slots=True)
class RawGlobalAttribute:
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class RawInputType:
    keyword: str
    state: str
    data_type: str
    control_type: str
    url: str


# Expected cell count in each domain of the online HTML sources
HTML_CELL_COUNT = {
    'attributes':         4,
    'content_categories': 3,
    'elements':           7,
    'event_handlers':     4,
    'input_types':        4,
}


# ---- Per-section extractors ----
# Each function pulls literal cell/anchor text out of the soup, stripped of
# surrounding whitespace only. No splitting, typing, or spec-specific
# interpretation happens here — that belongs to stage 2 (parser.py), which
# consumes these same dataclasses from disk instead of a live soup.


def extract_aria_roles(soup: BeautifulSoup) -> Iterator[RawAriaRole]:
    # https://w3c.github.io/aria/#widget
    # https://w3c.github.io/aria/#document_structure_roles
    # https://w3c.github.io/aria/#landmark_roles
    # https://w3c.github.io/aria/#live_region_roles
    # https://w3c.github.io/aria/#window_roles
    concrete_roles = (
        'widget',
        'document_structure_roles',
        'landmark_roles',
        'live_region_roles',
        'window_roles',
    )
    for role in concrete_roles:
        rows = soup.find('section', {'id': role}).find_next('ul').find_all('li')
        for row in rows:
            deprecated = '' if row.strong is None else row.strong.get_text().strip()
            if deprecated != '':
                deprecated = re.search(r'(?<=ARIA )\d+\.\d+', deprecated)
                deprecated = deprecated[0] if deprecated else ''
            yield RawAriaRole(
                name=row.code.get_text().strip(),
                url=row.a['href'].strip(),
                deprecated_since_version=deprecated,
            )


def extract_attributes(soup: BeautifulSoup) -> Iterator[RawAttribute]:
    # https://html.spec.whatwg.org/multipage/indices.html#attributes-3
    rows = soup.find('h3', {'id': 'attributes-3'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['attributes']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        attribute, elements, description, value = cells
        urls = [('' if x['href'].strip().startswith('https://') else 'https://html.spec.whatwg.org/multipage/') + x['href'].strip() for x in row.find_all('a')]
        yield RawAttribute(
            attribute=attribute,
            elements=elements,
            description=description,
            value=value,
            urls=urls,
        )


def extract_content_categories(soup: BeautifulSoup) -> Iterator[RawContentCategory]:
    # https://html.spec.whatwg.org/multipage/indices.html#element-content-categories
    rows = soup.find('h3', {'id': 'element-content-categories'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['content_categories']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        category, elements, exceptions = cells
        yield RawContentCategory(
            category=category,
            url=f'https://html.spec.whatwg.org/multipage/{row.td.a['href']}',
            elements=elements,
            exceptions=exceptions,
        )


def extract_elements(soup: BeautifulSoup) -> Iterator[RawElement]:
    # https://html.spec.whatwg.org/multipage/indices.html#elements-3
    rows = soup.find('h3', {'id': 'elements-3'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['elements']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        element, description, categories, _, children, attributes, _ = cells
        yield RawElement(
            element=element, description=description, categories=categories, children=children, attributes=attributes
        )


def extract_element_kinds(soup: BeautifulSoup) -> Iterator[RawElementKind]:
    # https://html.spec.whatwg.org/dev/syntax.html#elements-2
    rows = soup.find('h4', {'id': 'elements-2'}).find_next('dl').find_all(['dt', 'dd'], recursive=False)
    prev = None  # tag name of the last row seen: None, 'dt', or 'dd'
    name = None
    for row in rows:
        if row.name == 'dt':
            if prev not in {None, 'dd'}:
                logger.error('❌ <dt> not preceded by a <dd>: %s', row)
            name = row.dfn.get_text().strip()  # literal text; slugify() happens in stage 2
            prev = 'dt'
        elif row.name == 'dd':
            if prev != 'dt':
                logger.error('❌ <dd> not preceded by a <dt>: %s', row)
                continue
            tags = [tag.get_text().strip() for tag in row.find_all('code')]
            info = '' if tags else row.get_text().strip()
            prev = 'dd'
            yield RawElementKind(name=name, tags=tags, info=info)
    if prev == 'dt':
        logger.error('❌ Trailing <dt> with no following <dd>: %s', name)


def extract_event_handlers(soup: BeautifulSoup) -> Iterator[RawEventHandler]:
    # https://html.spec.whatwg.org/multipage/indices.html#ix-event-handlers
    rows = soup.find('table', {'id': 'ix-event-handlers'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['event_handlers']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        attribute, elements, _, _ = cells
        yield RawEventHandler(attribute=attribute, elements=elements)


def extract_global_attributes(soup: BeautifulSoup) -> Iterator[RawGlobalAttribute]:
    # https://html.spec.whatwg.org/dev/dom.html#global-attributes
    anchors = soup.find('h4', {'id': 'global-attributes'}).find_next('ul', {'class': 'brief'}).find_all('a')
    for a in anchors:
        yield RawGlobalAttribute(
            name=a.get_text().strip(),
            url=f'https://html.spec.whatwg.org/dev/{a['href'].strip()}',
        )


def extract_input_types(soup: BeautifulSoup) -> Iterator[RawInputType]:
    # https://html.spec.whatwg.org/dev/input.html#attr-input-type-keywords
    rows = soup.find('table', {'id': 'attr-input-type-keywords'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['input_types']
    for row in rows:
        cells = [x.get_text().strip() for x in row.contents]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        keyword, state, data_type, control_type = cells
        yield RawInputType(
            keyword=keyword,
            state=state,
            data_type=data_type,
            control_type=control_type,
            url=f'https://html.spec.whatwg.org/dev/input.html{row.a['href'].strip()}',
        )


# section name -> extractor function; keys match config.PAGE_SECTIONS values
EXTRACTORS = {
    'aria_roles': extract_aria_roles,
    'attributes': extract_attributes,
    'content_categories': extract_content_categories,
    'elements': extract_elements,
    'element_kinds': extract_element_kinds,
    'event_handlers': extract_event_handlers,
    'global_attributes': extract_global_attributes,
    'input_types': extract_input_types,
}


class Extractor:
    """Stage 1: raw spec HTML -> faithful NDJSON records, one file per (page, section)."""

    def __init__(self, raw_data_dir: Path, terse_data_dir: Path) -> None:
        self.raw_data_dir = raw_data_dir
        self.terse_data_dir = terse_data_dir

    def _load_soup(self, page: str) -> BeautifulSoup:
        with (self.raw_data_dir / f'{page}.html').open('r') as fp:
            return BeautifulSoup(fp, 'lxml')

    def _ndjson_path(self, page: str, section: str) -> Path:
        return self.terse_data_dir / f'{page}.{section}.ndjson'

    def extract_page(self, page: str, sections: tuple[str, ...]) -> dict[str, dict]:
        """Extract sections belonging to one source page. Returns one manifest entry per (page, section)."""
        entries: dict[str, dict] = {}
        try:
            soup = self._load_soup(page)
        except OSError:
            logger.exception('❌ Could not read %s.html', page)
            soup = None

        for section in sections:
            key = f'{page}.{section}'
            path = self._ndjson_path(page, section)

            if soup is not None:
                rows = list(EXTRACTORS[section](soup))
                if not rows:
                    msg = 'No rows extracted for %s. Spec structure may have changed'
                    raise ValueError(msg, key)
                count = write_ndjson(path, rows)
                entries[key] = {
                    'status': 'ok',
                    'row_count': count,
                }
                logger.info('🧲 Extracted %s rows -> %s', count, path.name)
                continue

            # Extraction unavailable this run (missing page or a broken section) —
            # fall back to whatever was written last time, so stage 2 always has
            # *something* faithful to build from, even if it's stale.
            if path.exists():
                row_count = sum(1 for _ in path.open())
                logger.info('🛟 Kept previous %s (%s rows, extraction unavailable this run)', path.name, row_count)
                entries[key] = {'status': 'fallback', 'row_count': row_count}
            else:
                logger.error('❌ No terse data available for %s (no previous file to fall back to)', key)
                entries[key] = {'status': 'missing', 'row_count': 0}

        return entries

    def extract_all(self, page_sections: dict[str, tuple[str, ...]]) -> dict[str, dict]:
        manifest_entries: dict[str, dict] = {}
        for page, sections in page_sections.items():
            manifest_entries.update(self.extract_page(page, sections))
        return manifest_entries
