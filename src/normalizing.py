import dataclasses
import json
import logging
import re
import string
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from slugify import slugify

from config import DUMP_JSON_KWARGS
from emending import Emender
from util import dataclass_to_dict, deduplicate, dict_to_dataclass, normalize_url

logger = logging.getLogger(__name__)


# ---- Typed entities (normalize-stage output shape) ----


@dataclass(frozen=True, slots=True)
class AriaRoleData:
    name: str
    url: str = ''
    deprecated_since_version: str = ''


@dataclass(frozen=True, slots=True)
class AttributeData:
    name: str
    tag: str | None = None
    description: str = ''
    value_type: str = 'string'
    value_enum: set[str] = field(default_factory=set)
    value_info: str = ''
    is_more_value_info_required: bool = False
    separator: str = ''
    urls: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ContentCategoryData:
    name: str
    elements: set[str] = field(default_factory=set)
    elements_maybe: list[str] = field(default_factory=list)
    exceptions: str = ''
    url: str = ''


@dataclass(frozen=True, slots=True)
class ElementData:
    name: str
    description: str = ''
    categories: set[str] = field(default_factory=set)
    attributes: set[str] = field(default_factory=set)
    children: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ElementKindData:
    name: str
    tags: set[str] = field(default_factory=set)
    info: str = ''


@dataclass(frozen=True, slots=True)
class EventHandlerData:
    name: str
    applies_to: str = ''
    urls: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class GlobalAttributeData:
    name: str
    url: str = ''


@dataclass(frozen=True, slots=True)
class InputTypeData:
    name: str
    value_type: str = ''
    control_type: str = ''
    url: str = ''


RECOVERABLE_ERRORS = (AttributeError, ValueError, OSError)

# Match a list of one-or-more keywords such as `"foo"; "bar"; "the empty string"`
ATTRIBUTE_VALUE_REGEX = re.compile(r'^(?:"[a-zA-Z0-9/-]*"|the empty string)(?:; (?:"[a-zA-Z0-9/-]*"|the empty string))*$')

# Match element exceptions like "element (if ...)"
TAG_IF_REGEX = re.compile(r'([a-zA-Z0-9-]+) \(if [a-zA-Z0-9\' -]+\)')

_SPLITTABLE_REGEX = re.compile(r'\b([a-zA-Z][a-zA-Z0-9-]*)\b[ \t]*\n[ \t]*\b([a-zA-Z][a-zA-Z0-9-]*)\b')

# Sentinel used as the dict key (in place of `tag`) for attributes with no tag restriction.
ALL_TAGS = 'all'

SEPARATOR_BY_STRING = {
    'Valid list of floating-point numbers': ',',
    'Valid source size list':               ',',
}

SEPARATOR_BY_SUBSTRING = {
    'space-separated tokens':                       ' ',
    'ordered set of unique space-separated tokens': ' ',
    'comma-separated list of':                      ',',
    'set of comma-separated tokens':                ',',
}

# Special cases: phrase -> list of yielded tokens (empty list yields nothing)
TAGS_BY_STRING = {
    'autonomous custom elements': [],
    'HTML elements': [],
    'form-associated custom elements': ['custom'],
    'MathML math': ['math'],
    'SVG svg': ['svg'],
}

TYPE_BY_STRING = {
    'Boolean attribute':                    'bool',
    'Valid integer':                        'int',
    'Valid date string with optional time': 'datetime',
}

TYPE_BY_PREFIX = {
    'Valid non-negative integer':  'int',
    'Valid floating-point number': 'float',
}

# Fragment keyword to search for when splitting a shared URL list across a row's tags, in addition to
# the tag's own name. Needed only where a URL fragment doesn't literally contain the tag name (e.g. `a`
# and `area` share fragments under "hyperlink"; `audio`/`video` under "media"; `del`/`ins` under "mod").
# Validated against indices.attributes.ndjson on 2026-08-06: every multi-tag row where a generic fragment's
# real audience is a strict subset of the row's tags requires an entry here; rows where the fragment is
# genuinely shared by every tag in the row need no entry (the no-match-shares-to-all-tags fallback covers
# them). Matching is additive: a tag always still matches its own name, this only adds a second candidate.
URL_BY_STRING = {
    'a': 'hyperlink',
    'area': 'hyperlink',
    'audio': 'media',
    'video': 'media',
    'del': 'mod',
    'ins': 'mod',
}

# Expected cell count in each domain of the online HTML sources
HTML_CELL_COUNT = {
    'attributes':         4,
    'content_categories': 3,
    'elements':           7,
    'event_handlers':     4,
    'input_types':        4,
}


# ---- Generators for splitting spec strings ----


def gen_attribute_names(input_str: str) -> Iterator[str]:
    for attribute in input_str.strip(string.whitespace + ';').split(';'):
        yield attribute.strip('*').strip()


def gen_attribute_value_enums(input_str: str) -> Iterator[str]:
    if ATTRIBUTE_VALUE_REGEX.fullmatch(input_str):

        def process_keyword(keyword: str) -> str:
            keyword = keyword.strip()
            return '' if keyword == 'the empty string' else keyword.strip('"')

        yield from map(process_keyword, input_str.split(';'))


def gen_content_categories(input_str: str) -> Iterator[str]:
    for category in input_str.strip(string.whitespace + ';').split(';'):
        cat = category.strip().strip('*')
        if cat != 'empty':
            yield cat


def gen_tags(input_str: str) -> Iterator[str]:
    input_str = input_str.strip()
    if not input_str:
        return

    # 1) Handle known special phrases
    if input_str in TAGS_BY_STRING:
        yield from TAGS_BY_STRING[input_str]
        return

    if ';' in input_str:
        for e in re.split(r'\s*;\s*', input_str.strip(string.whitespace + ';')):
            yield from gen_tags(e.strip())
    elif ',' in input_str:
        for e in re.split(r'\s*,\s*', input_str.strip(string.whitespace + ',')):
            yield from gen_tags(e)
    else:
        yield input_str


def gen_tag_ifs(input_str: str) -> Iterator[str]:
    if not input_str:
        return
    parts = input_str.split(';') if ';' in input_str else [input_str]
    for x in parts:
        matches = TAG_IF_REGEX.fullmatch(x.strip())
        if matches:
            yield matches.group(1)


def split_splittables(text: str, context: str) -> str:
    """Detect and repair words missing a separator in the whitespace. Returns the words in a semicolon-separated string.
    First issue of this kind: `controls` "Element(s)" cell has no semicolon between 'video' and 'img' <code> elements in
    https://html.spec.whatwg.org/multipage/indices.html#attributes-3:attr-media-controls (still active on 2026-07-22).
    """

    def repair(match: re.Match) -> str:
        word_a, word_b = match.group(1), match.group(2)
        logger.warning("⚠️ %s: missing separator between '%s' and '%s'.", context, word_a, word_b)
        return f'{word_a};{word_b}'

    return _SPLITTABLE_REGEX.sub(repair, text)


# ---- Per-section extract-and-parse functions ----
# Each function takes the soup for its source page and yields typed entities directly. Extraction
# (cell/anchor text out of the soup, stripped of surrounding whitespace only) and interpretation
# (splitting, typing, spec-specific logic) are no longer separate stages.


def parse_aria_roles(soup: BeautifulSoup) -> Iterator[AriaRoleData]:
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
            yield AriaRoleData(
                name=row.code.get_text().strip(),
                url=row.a['href'].strip(),
                deprecated_since_version=deprecated,
            )


def _parse_attribute_cells(
    name: str, elements_info: str, description: str, value_info: str, urls: list[str]
) -> Iterator[AttributeData]:
    """Parse one attribute row's cells into one or more AttributeData entries, split by tag.

    Splits `elements_info` into tags via gen_tags(), tracking a per-tag scope note (`tag_notes`) for
    tags with a `(if ...)`/`(in ...)` qualifier -- siblings from the same row don't inherit that note.
    Parses the value description into value_type/value_enum/separator, and sets
    `is_more_value_info_required` when the value description carries a trailing '*' (shared across
    every tag split from this row, since it describes the value, not scope).

    Yields:
        - if the row has no tag restriction: a single tagless AttributeData;
        - otherwise splits the row's shared URL list across tags and yields one AttributeData per tag.
    """
    elements_info = split_splittables(elements_info, f'Attribute {name!r} element(s)')
    is_more_value_info_required = value_info.endswith('*')
    if is_more_value_info_required:
        value_info = value_info[:-1]
    value_type = ' '.join(x.strip().strip('*') for x in value_info.split('\n')).strip()
    value_info = value_type

    tag_notes: dict[str, str] = {}
    for token in gen_tags(elements_info):
        tmp = token.strip()
        idx = tmp.find('(')
        if idx != -1:
            tag = tmp[:idx].strip()
            tag_notes[tag] = f'Special tag scope: {token}'
        elif tmp not in tag_notes:
            tag_notes[tmp] = ''
    tags = set(tag_notes)

    value_enum = set(gen_attribute_value_enums(value_type))
    if value_enum:
        value_type, value_info, separator = 'enum', '', ''
    else:
        value_type, separator = _parse_attribute_value(value_type)

    if not tags:
        # No tag restriction (e.g. 'HTML elements'): single entry, no URL split needed.
        yield AttributeData(
            name=name,
            tag=None,
            description=description,
            value_type=value_type,
            value_enum=value_enum,
            value_info=value_info,
            is_more_value_info_required=is_more_value_info_required,
            separator=separator,
            urls=set(urls),
        )
        return

    url_by_tag = _parse_attribute_urls(urls, tags)
    for tag in sorted(tags):
        yield AttributeData(
            name=name,
            tag=tag,
            description=description,
            value_type=value_type,
            value_enum=value_enum,
            value_info=value_info,
            is_more_value_info_required=is_more_value_info_required,
            separator=separator,
            urls=set(url_by_tag[tag]),
        )


def _parse_attribute_urls(urls: list[str], tags: set[str]) -> dict[str, list[str]]:
    """Partition a row's shared URL list across its tags. A URL goes to every tag whose keyword (its own
    name, plus an URL_BY_STRING override if one exists) appears as an exact segment of the URL's
    fragment (the part after '#'). A URL matching no tag's keyword is shared by every tag in the row.
    """
    keywords = {tag: {tag, URL_BY_STRING[tag]} if tag in URL_BY_STRING else {tag} for tag in tags}
    result: dict[str, list[str]] = {tag: [] for tag in tags}
    for url in urls:
        fragment = url.split('#', 1)[-1] if '#' in url else ''
        segments = set(re.split(r'[^a-z0-9]+', fragment.lower()))
        matched = {tag for tag, kws in keywords.items() if kws & segments}
        for tag in matched or tags:
            result[tag].append(url)  # URL matches multiple tags; adding it to all matches.
    return result


def _parse_attribute_value(value_type_str: str) -> tuple[str, str]:
    value_type = TYPE_BY_STRING.get(value_type_str)
    if value_type is None:
        for prefix, mapped_type in TYPE_BY_PREFIX.items():
            if value_type_str.startswith(prefix):
                value_type = mapped_type
                break
        else:
            value_type = 'string'

    value_separator = SEPARATOR_BY_STRING.get(value_type_str)
    if value_separator is None:
        value_type_lower = value_type_str.lower()
        for substring, sep in SEPARATOR_BY_SUBSTRING.items():
            if substring in value_type_lower:
                value_separator = sep
                break
    if value_separator is None:
        value_separator = ''

    return value_type, value_separator


def parse_attributes(soup: BeautifulSoup) -> Iterator[AttributeData]:
    # https://html.spec.whatwg.org/multipage/indices.html#attributes-3
    rows = soup.find('h3', {'id': 'attributes-3'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['attributes']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        attribute, elements, description, value = cells
        urls = deduplicate(normalize_url(x['href'].strip()) for x in row.find_all('a'))
        yield from _parse_attribute_cells(attribute, elements, description, value, urls)


def parse_content_categories(soup: BeautifulSoup) -> Iterator[ContentCategoryData]:
    # https://html.spec.whatwg.org/multipage/indices.html#element-content-categories
    rows = soup.find('h3', {'id': 'element-content-categories'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['content_categories']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        category, elements, exceptions = cells
        url = f'https://html.spec.whatwg.org/multipage/{row.td.a['href']}'

        category = ' '.join(category.split())
        exceptions = '; '.join(x.strip() for x in exceptions.split(';'))
        if exceptions == '—':
            exceptions = ''
        if category.endswith('*'):
            exceptions += '; The tabindex attribute can also make any element into interactive content.'
        category = category.rstrip('*').strip()

        elements_set = set(gen_tags(elements))
        elements_maybe = list(gen_tag_ifs(exceptions))

        yield ContentCategoryData(
            name=category,
            url=url,
            elements=elements_set,
            elements_maybe=elements_maybe,
            exceptions=exceptions,
        )


def parse_elements(soup: BeautifulSoup) -> Iterator[ElementData]:
    # https://html.spec.whatwg.org/multipage/indices.html#elements-3
    rows = soup.find('h3', {'id': 'elements-3'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['elements']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        element, description, categories, _, children, attributes, _ = cells

        elements = gen_tags(element)
        categories_set = set(gen_content_categories(categories))
        attributes_set = set(gen_attribute_names(attributes))
        attributes_set.discard('globals')
        children_set = set(gen_content_categories(children))

        for e in sorted(elements):
            yield ElementData(
                name=e,
                description=description.strip(),
                categories=categories_set,
                attributes=attributes_set,
                children=children_set,
            )


def parse_element_kinds(soup: BeautifulSoup) -> Iterator[ElementKindData]:
    # https://html.spec.whatwg.org/dev/syntax.html#elements-2
    rows = soup.find('h4', {'id': 'elements-2'}).find_next('dl').find_all(['dt', 'dd'], recursive=False)
    prev = None  # tag name of the last row seen: None, 'dt', or 'dd'
    name = None
    for row in rows:
        if row.name == 'dt':
            if prev not in {None, 'dd'}:
                logger.error('❌ <dt> not preceded by a <dd>: %s', row)
            name = row.dfn.get_text().strip()  # literal text; slugify() happens below
            prev = 'dt'
        elif row.name == 'dd':
            if prev != 'dt':
                logger.error('❌ <dd> not preceded by a <dt>: %s', row)
                continue
            tags = deduplicate(tag.get_text().strip() for tag in row.find_all('code'))
            info = '' if tags else row.get_text().strip()
            prev = 'dd'
            yield ElementKindData(name=slugify(name), tags=set(tags), info=info)
    if prev == 'dt':
        logger.error('❌ Trailing <dt> with no following <dd>: %s', name)


def parse_event_handlers(soup: BeautifulSoup) -> Iterator[EventHandlerData]:
    # https://html.spec.whatwg.org/multipage/indices.html#ix-event-handlers
    rows = soup.find('table', {'id': 'ix-event-handlers'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['event_handlers']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        attribute, elements, _, _ = cells
        urls = deduplicate(normalize_url(x['href'].strip()) for x in row.find_all('a'))
        yield EventHandlerData(
            name=attribute,
            applies_to=elements,
            urls=set(urls),
        )


def parse_global_attributes(soup: BeautifulSoup) -> Iterator[GlobalAttributeData]:
    # https://html.spec.whatwg.org/dev/dom.html#global-attributes
    for name in ('class', 'id', 'role', 'slot'):
        yield GlobalAttributeData(name=name)
    anchors = soup.find('h4', {'id': 'global-attributes'}).find_next('ul', {'class': 'brief'}).find_all('a')
    for a in anchors:
        yield GlobalAttributeData(
            name=a.get_text().strip(),
            url=f'https://html.spec.whatwg.org/dev/{a['href'].strip()}',
        )


def parse_input_types(soup: BeautifulSoup) -> Iterator[InputTypeData]:
    # https://html.spec.whatwg.org/dev/input.html#attr-input-type-keywords
    rows = soup.find('table', {'id': 'attr-input-type-keywords'}).find_next('tbody').find_all('tr')
    count = HTML_CELL_COUNT['input_types']
    for row in rows:
        cells = [x.get_text().strip() for x in row.contents]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        keyword, state, data_type, control_type = cells
        yield InputTypeData(
            name=keyword,
            value_type=data_type,
            control_type=control_type,
            url=f'https://html.spec.whatwg.org/dev/input.html{row.a['href'].strip()}',
        )


def dictify_attributes(attribute_list: list[AttributeData]) -> dict[str, dict[str, Any]]:
    """Convert a list of AttributeData into a dict keyed by name, then by tag (ALL_TAGS for `tag is None`).
    Raises ValueError on a genuine (name, tag) collision, since that indicates a parsing bug rather than
    legitimate data -- unlike dictify(), there's no merge path here.
    """
    result: dict[str, dict[str, Any]] = {}
    for attribute in attribute_list:
        r = dataclasses.asdict(attribute)
        del r['name']
        del r['tag']
        tag_key = ALL_TAGS if attribute.tag is None else attribute.tag
        by_tag = result.setdefault(attribute.name, {})
        if tag_key in by_tag:
            logger.warning('⚠️ Duplicate name+tag pair: (%r, %r)', attribute.name, tag_key)
        by_tag[tag_key] = r
    return result


# section name -> (page, entity dataclass); drives Normalizer.get_all() and Publisher.read_data_domains().
# Keys match config.PAGE_SECTIONS values.
SECTION_SOURCES: dict[str, tuple[str, type]] = {
    'aria_roles': ('aria', AriaRoleData),
    'attributes': ('indices', AttributeData),
    'content_categories': ('indices', ContentCategoryData),
    'elements': ('indices', ElementData),
    'element_kinds': ('syntax', ElementKindData),
    'event_handlers': ('indices', EventHandlerData),
    'global_attributes': ('dom', GlobalAttributeData),
    'input_types': ('input', InputTypeData),
}


class Normalizer:
    """Merged extract+normalize stage: raw spec HTML -> typed entities, with validation and fallback cache."""

    def __init__(
        self,
        raw_data_dir: Path,
        cache_dir: Path,
        emender: Emender | None = None,
    ) -> None:
        self.raw_data_dir = raw_data_dir
        self.cache_dir = cache_dir
        self.emender = emender if emender is not None else Emender(domain='normalizing')
        self._soup_cache: dict[str, BeautifulSoup | None] = {}
        self._input_manifest: dict[str, dict] = {}
        self._output_manifest: dict[str, dict] = {}

    # ---- internal helpers ----

    def _load_soup(self, page: str) -> BeautifulSoup | None:
        """Load and cache the soup for `page` (shared across every section of that page); return None
        (and log) if the raw HTML is missing or unreadable.
        """
        if page not in self._soup_cache:
            try:
                with (self.raw_data_dir / f'{page}.html').open('r') as fp:
                    self._soup_cache[page] = BeautifulSoup(fp, 'lxml')
            except OSError:
                logger.exception('❌ Could not read %s.html', page)
                self._soup_cache[page] = None
        return self._soup_cache[page]

    def _save_cache(self, key: str, entries: list) -> None:
        """Save a list of entity dataclass instances to the cache directory as JSON."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        serialized = [dataclass_to_dict(e) for e in entries]
        (self.cache_dir / f'{key}.json').write_text(
            json.dumps(serialized, **DUMP_JSON_KWARGS),
            encoding='utf-8',
        )

    def _load_cache_raw(self, key: str) -> list | None:
        """Load the raw (still plain-dict) cached entries for `key`; return None if missing."""
        path = self.cache_dir / f'{key}.json'
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def _load_cache(self, key: str, cls: type) -> list | None:
        """Load the cached entries for `key`, reconstructed as `cls` instances; return None if missing."""
        raw = self._load_cache_raw(key)
        return None if raw is None else [dict_to_dataclass(cls, d) for d in raw]

    def _validate(self, key: str, count: int) -> dict:
        """Compare `count` against the previous cached run for `key` (if any) and decide pass/warn/raise. No fixed floor:
        a category may legitimately grow or shrink a little as the spec evolves, but a bigger jump either way is more
        likely a broken extraction/parse than a real change upstream.

        delta ==  0 or no previous run -> pass, silent
        abs(delta) == 1                -> pass, warn
        abs(delta) >= 2                -> raise

        Stores and returns the manifest entry for `key`: {status, row_count} plus delta.
        """
        delta_warn = 1
        delta_fatal = 2
        previous = self._load_cache_raw(key)
        previous_count = len(previous) if previous is not None else None
        delta = 0 if previous_count is None else count - previous_count

        if abs(delta) >= delta_fatal:
            msg = f'{key}: count changed by {delta:+d} since last run ({previous_count} -> {count})'
            raise ValueError(msg)
        if abs(delta) == delta_warn:
            logger.warning('⚠️ %s: count changed by %d since last run (%d -> %d)', key, delta, previous_count, count)

        entry = {'status': 'ok', 'row_count': count, 'delta': delta}
        self._output_manifest[key] = entry
        return entry

    def _build_cached(self, key: str, cls: type, builder: Callable[[], list]) -> list:
        """Run `builder`, validate and cache its result under `key`; on a recoverable error, fall back to the cache."""
        try:
            result = builder()
            self._validate(key, len(result))
        except RECOVERABLE_ERRORS as e:
            return self._log_parse_error_and_fallback(e, key, cls)
        else:
            self._save_cache(key, result)
            logger.info('🏗️ Built and cached %s %s', len(result), key)
            return result

    def _log_parse_error_and_fallback(self, e: Exception, cache_key: str, cls: type) -> list:
        logger.error('❌ Extraction/parsing failed: %s', e)
        cached = self._load_cache(cache_key, cls)
        if cached is None:
            msg = f'No cache available for {cache_key}'
            raise RuntimeError(msg) from e
        logger.info('📂 Loaded %s from cache', cache_key)
        self._output_manifest[cache_key] = {'status': 'fallback', 'row_count': len(cached)}
        return cached

    def _get_section_entries(self, section: str) -> list:
        page, cls = SECTION_SOURCES[section]
        input_key = f'{page}.{section}'
        soup = self._load_soup(page)

        def builder() -> list:
            if soup is None:
                msg = f'No raw HTML available for page {page!r}'
                raise FileNotFoundError(msg)
            parser = getattr(sys.modules[__name__], f'parse_{section}')
            entries = list(parser(soup))
            self.emender.emend_normalizing_section(section, entries)
            return entries

        entries = self._build_cached(section, cls, builder)
        self._input_manifest[input_key] = {
            'status': 'ok' if soup is not None else 'fallback',
            'row_count': len(entries),
        }
        return entries

    # ---- public builders ----

    def get_all(self) -> tuple[dict[str, list], dict]:
        """Run all section builders. Returns {section: [entities]} and the {'input', 'output'} manifest."""
        results = {section: self._get_section_entries(section) for section in SECTION_SOURCES}
        manifest = {'input': dict(self._input_manifest), 'output': dict(self._output_manifest)}
        return results, manifest
