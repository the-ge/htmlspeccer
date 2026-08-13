import dataclasses
import json
import logging
import re
import string
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from inspect import currentframe
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, element
from slugify import slugify

from config import DUMP_JSON_KWARGS, NORMALIZED_DATA_DIR
from emending import Emender
from util import dataclass_to_dict, deduplicate, dict_merge, dict_to_dataclass, normalize_url, write_ndjson

logger = logging.getLogger(__name__)


# ---- Typed entities (curate-stage output shape) ----


@dataclass(frozen=True, slots=True)
class AriaRoleData:
    name: str
    url: str = ''
    description: str = ''
    is_abstract: bool = False
    parents: dict[str, str] = field(default_factory=dict)
    children: dict[str, str] = field(default_factory=dict)
    states: dict[str, dict[str, str]] = field(default_factory=dict)
    properties: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AttributeData:
    name: str
    tag: str | None = None
    value_type: str = 'string'
    value_enum: set[str] = field(default_factory=set)
    separator: str = ''
    tag_url: str = ''
    value_info: list[tuple[str, str]] = field(default_factory=list)
    is_more_value_info_required: bool = False
    description: list[tuple[str, str]] = field(default_factory=list)


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


# section name -> (page, entity dataclass); drives Curator.get_all() and Publisher.read_data_domains().
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

# Sentinel used as the dict key (in place of `tag`) for attributes with no tag restriction.
_ALL_TAGS = 'all'

# Expected cell count in each domain of the online HTML sources
_HTML_CELL_COUNT = {
    'attributes':         4,
    'content_categories': 3,
    'elements':           7,
    'event_handlers':     4,
    'input_types':        4,
}

_RECOVERABLE_ERRORS = (AttributeError, ValueError, OSError)

_SEPARATOR_BY_STRING = {
    'Valid list of floating-point numbers': ',',
    'Valid source size list':               ',',
}

_SEPARATOR_BY_SUBSTRING = {
    'space-separated tokens':                       ' ',
    'ordered set of unique space-separated tokens': ' ',
    'comma-separated list of':                      ',',
    'set of comma-separated tokens':                ',',
}

# Base URL for relative spec links
_SPEC_BASE_URL = 'https://html.spec.whatwg.org/multipage/'

# Special cases: phrase -> list of yielded tokens (empty list yields nothing). Used by gen_tags(), which
# still serves parse_content_categories() and parse_elements(); parse_attributes() no longer uses gen_tags().
_TAGS_BY_STRING = {
    'autonomous custom elements': [],
    'HTML elements': [],
    'form-associated custom elements': ['custom'],
    'MathML math': ['math'],
    'SVG svg': ['svg'],
}

# Bare (non-<code>-wrapped) anchor text found in an attribute's elements cell -> tag-group name, or
# None for "no tag restriction". Any other bare anchor text is unrecognized (warned and skipped).
_SPECIAL_SCOPES = {'HTML elements': None, 'form-associated custom elements': 'formcustom'}

_TYPE_BY_STRING = {
    'Boolean attribute':                    'bool',
    'Valid integer':                        'int',
    'Valid date string with optional time': 'datetime',
}

_TYPE_BY_PREFIX = {
    'Valid non-negative integer':  'int',
    'Valid floating-point number': 'float',
}

# ---- Regex ---

# Match a list of one-or-more keywords such as `"foo"; "bar"; "the empty string"`
_ATTRIBUTE_VALUE_REGEX = re.compile(r'^(?:"[a-zA-Z0-9/-]*"|the empty string)(?:; (?:"[a-zA-Z0-9/-]*"|the empty string))*$')

# Match element exceptions like "element (if ...)"
_TAG_IF_REGEX = re.compile(r'([a-zA-Z0-9-]+) \(if [a-zA-Z0-9\' -]+\)')


# ---- Generators for splitting spec strings ----


def gen_attribute_names(input_str: str) -> Iterator[str]:
    for attribute in input_str.strip(string.whitespace + ';').split(';'):
        yield attribute.strip('*').strip()


def gen_attribute_value_enums(input_str: str) -> Iterator[str]:
    if _ATTRIBUTE_VALUE_REGEX.fullmatch(input_str):

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
    if input_str in _TAGS_BY_STRING:
        yield from _TAGS_BY_STRING[input_str]
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
        matches = _TAG_IF_REGEX.fullmatch(x.strip())
        if matches:
            yield matches.group(1)


# ---- Per-section extract-and-parse functions ----
# Each function takes the soup for its source page and yields typed entities directly. Extraction
# (cell/anchor text out of the soup, stripped of surrounding whitespace only) and interpretation
# (splitting, typing, spec-specific logic) are no longer separate stages.


def _parse_aria_role_relations(table: element.Tag, td_class: str) -> dict[str, str]:
    td = table.find('td', {'class': td_class})
    if td is None:
        return {}
    return {a.get_text().strip(): a['href'].strip() for a in td.find_all('a')}


def _parse_aria_role_states_properties(table: element.Tag) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    states: dict[str, dict[str, str]] = {}
    properties: dict[str, dict[str, str]] = {}
    for td_class in ('role-properties', 'role-inherited'):
        td = table.find('td', {'class': td_class})
        if td is None:
            continue
        for li in td.find_all('li'):
            a = li.find('a')
            if a is None:
                continue
            strong = li.find('strong')
            deprecated = ''
            if strong is not None:
                match = re.search(r'(?<=ARIA )\d+\.\d+', strong.get_text())
                deprecated = match[0] if match else ''
            entry = {'url': a['href'].strip(), 'deprecated_since': deprecated}
            target = states if 'state-reference' in a.get('class', []) else properties
            target[a.get_text().strip()] = entry
    return states, properties


def parse_aria_roles(soup: BeautifulSoup) -> Iterator[AriaRoleData]:
    # https://w3c.github.io/aria/#index_role
    # https://w3c.github.io/aria/#<ROLE_NAME>
    rows = soup.find('dl', {'id': 'index_role'}).find_all(['dt', 'dd'], recursive=False)
    prev = None
    name = url = role_id = None
    for row in rows:
        if row.name == 'dt':
            if prev not in {None, 'dd'}:
                logger.error('❌ <dt> not preceded by a <dd>: %s', row)
            href = row.a['href'].strip()
            name = row.a.code.get_text().strip()
            role_id = href.removeprefix('#')
            url = f'https://w3c.github.io/aria/{href}'
            prev = 'dt'
        elif row.name == 'dd':
            if prev != 'dt':
                logger.error('❌ <dd> not preceded by a <dt>: %s', row)
                continue
            description = row.get_text().strip()
            prev = 'dd'

            role_section = soup.find('section', {'id': role_id})
            table = role_section.find('table', {'class': 'def'}) if role_section is not None else None
            if table is None:
                logger.warning('⚠️ aria_roles: no structural data table found for role %r; role omitted', name)
                continue

            is_abstract_td = table.find('td', {'class': 'role-abstract'})
            is_abstract = is_abstract_td is not None and is_abstract_td.get_text().strip() == 'True'

            states, properties = _parse_aria_role_states_properties(table)

            yield AriaRoleData(
                name=name,
                url=url,
                description=description,
                is_abstract=is_abstract,
                parents=_parse_aria_role_relations(table, 'role-parent'),
                children=_parse_aria_role_relations(table, 'role-children'),
                states=states,
                properties=properties,
            )
    if prev == 'dt':
        logger.error('❌ Trailing <dt> with no following <dd>: %s', name)


def _gen_cell_nodes(cell: element.Tag) -> Iterator[tuple[str, str]]:
    """Recursively decompose `cell` into (text, url) leaf nodes.

    An <a> tag is an atomic (text, url) leaf using its own href, not descended into. Any other tag is
    transparent: recurse into its children instead of emitting a node for it. Bare text runs become
    (text, '') nodes; whitespace-only text nodes are dropped. Concatenating the first elements with
    spaces approximately restores the cell's text (whitespace is not preserved exactly).

    Yields:
        (text, url) tuples in document order
    """
    for child in cell.children:
        if isinstance(child, element.Tag):
            if child.name == 'a':
                text = child.get_text().strip()
                if text:
                    yield text, normalize_url(child['href'].strip(), _SPEC_BASE_URL)
            else:
                yield from _gen_cell_nodes(child)
        else:
            text = str(child).strip()
            if text:
                yield text, ''


def _apply_value_info_marker(nodes: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], bool]:
    """Strip a leading '*' marker (meaning "more info needed") from a value-info node list.

    The marker is a '*' character found as the leading character of a plain-text node's (url == '')
    text, immediately following an anchor node (url != ''). Only that leading character is stripped;
    if the remainder is empty, the node is dropped entirely.

    Returns:
        (nodes with the marker(s) stripped/removed, True if at least one marker was found)
    """
    result: list[tuple[str, str]] = []
    found = False
    prev_was_anchor = False
    for text, url in nodes:
        if prev_was_anchor and not url and text.startswith('*'):
            found = True
            text = text[1:]  # noqa: PLW2901
            if text:
                result.append((text, url))
            prev_was_anchor = False
            continue
        result.append((text, url))
        prev_was_anchor = bool(url)
    return result, found


def _parse_attribute_cells(
    name: str, elements_cell: element.Tag, description_cell: element.Tag, value_cell: element.Tag
) -> Iterator[AttributeData]:
    """Parse one attribute row's cells into one or more AttributeData entries, split by tag/scope.

    `description` and `value_info` are decomposed via _gen_cell_nodes() into (text, url) node lists.
    A leading '*' marker on the value cell is stripped and sets `is_more_value_info_required` (see
    _apply_value_info_marker()). value_type/value_enum/separator are classified from the value cell's
    joined node text; `value_info` is reset to [] when value_enum ends up populated.

    Yields:
        One AttributeData per (tag, tag_url) scope found in the elements cell (see
        _parse_attribute_scopes()); nothing if the elements cell yields no scope at all
    """
    description = list(_gen_cell_nodes(description_cell))

    value_nodes, is_more_value_info_required = _apply_value_info_marker(list(_gen_cell_nodes(value_cell)))
    value_type_str = ' '.join(text for text, _ in value_nodes).strip()

    value_enum = set(gen_attribute_value_enums(value_type_str))
    if value_enum:
        value_type, separator, value_info = 'enum', '', []
    else:
        value_type, separator = _parse_attribute_value(value_type_str)
        value_info = value_nodes

    scopes = list(_parse_attribute_scopes(elements_cell, name))
    if not scopes:
        logger.warning('⚠️ Attribute %r: no tag or scope found in elements cell; row skipped', name)
        return

    for tag, tag_url in scopes:
        yield AttributeData(
            name=name,
            tag=tag,
            value_type=value_type,
            value_enum=value_enum,
            separator=separator,
            tag_url=tag_url,
            value_info=value_info,
            description=description,
            is_more_value_info_required=is_more_value_info_required,
        )


def _parse_attribute_value(value_type_str: str) -> tuple[str, str]:
    value_type = _TYPE_BY_STRING.get(value_type_str)
    if value_type is None:
        for prefix, mapped_type in _TYPE_BY_PREFIX.items():
            if value_type_str.startswith(prefix):
                value_type = mapped_type
                break
        else:
            value_type = 'string'

    value_separator = _SEPARATOR_BY_STRING.get(value_type_str)
    if value_separator is None:
        value_type_lower = value_type_str.lower()
        for substring, sep in _SEPARATOR_BY_SUBSTRING.items():
            if substring in value_type_lower:
                value_separator = sep
                break
    if value_separator is None:
        value_separator = ''

    return value_type, value_separator


def _parse_attribute_scopes(cell: element.Tag, name: str) -> Iterator[tuple[str | None, str]]:
    """Extract (tag, tag_url) pairs from an attribute row's elements cell.

    A <code>-wrapped anchor is a real tag: its own text is the tag name, its own href is tag_url. A
    bare (non-<code>-wrapped) anchor is looked up in _SPECIAL_SCOPES: found gives one additional scope
    (None for "no tag restriction", or a tag-group name); not found is warned and skipped. More than
    one bare anchor in a cell is unexpected: only the first is used, others are warned and ignored. A
    bare anchor resolving to "no tag restriction" alongside real tags is a contradiction: warned and
    skipped.

    Yields:
        (tag, tag_url) pairs; tag is None (no restriction), a tag-group name, or a real tag name
    """
    real_tags: list[tuple[str, str]] = []
    bare_anchors: list[element.Tag] = []
    for a in cell.find_all('a'):
        if a.find_parent('code') is not None:
            real_tags.append((a.get_text().strip(), normalize_url(a['href'].strip(), _SPEC_BASE_URL)))
        else:
            bare_anchors.append(a)

    yield from real_tags

    if not bare_anchors:
        return

    chosen = bare_anchors[0]
    if len(bare_anchors) > 1:
        ignored = ', '.join(repr(a.get_text().strip()) for a in bare_anchors[1:])
        logger.warning(
            '⚠️ Attribute %r: multiple tag-group anchors in one cell; using %r, ignoring: %s',
            name, chosen.get_text().strip(), ignored,
        )

    text = chosen.get_text().strip()
    if text not in _SPECIAL_SCOPES:
        logger.warning('⚠️ Attribute %r: unrecognized tag-group phrase %r', name, text)
        return

    scope = _SPECIAL_SCOPES[text]
    if scope is None and real_tags:
        logger.warning(
            "⚠️ Attribute %r: bare anchor %r resolves to 'no tag restriction' alongside real tags; skipping it",
            name, text,
        )
        return

    yield scope, normalize_url(chosen['href'].strip(), _SPEC_BASE_URL)


def parse_attributes(soup: BeautifulSoup) -> Iterator[AttributeData]:
    # https://html.spec.whatwg.org/multipage/indices.html#attributes-1
    rows = soup.find('table', {'id': 'attributes-1'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT['attributes']
    for row in rows:
        cells = row.find_all(['th', 'td'])
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        name_cell, elements_cell, description_cell, value_cell = cells
        yield from _parse_attribute_cells(name_cell.get_text().strip(), elements_cell, description_cell, value_cell)


def parse_content_categories(soup: BeautifulSoup) -> Iterator[ContentCategoryData]:
    # https://html.spec.whatwg.org/multipage/indices.html#element-content-categories
    rows = soup.find('h3', {'id': 'element-content-categories'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT['content_categories']
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


def parse_elements(soup: BeautifulSoup) -> Iterator[ElementData]:
    # https://html.spec.whatwg.org/multipage/indices.html#elements-3
    rows = soup.find('h3', {'id': 'elements-3'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT['elements']
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


def parse_event_handlers(soup: BeautifulSoup) -> Iterator[EventHandlerData]:
    # https://html.spec.whatwg.org/multipage/indices.html#ix-event-handlers
    rows = soup.find('table', {'id': 'ix-event-handlers'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT['event_handlers']
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        attribute, elements, _, _ = cells
        urls = deduplicate(normalize_url(x['href'].strip(), _SPEC_BASE_URL) for x in row.find_all('a'))
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
    count = _HTML_CELL_COUNT['input_types']
    for row in rows:
        cells = [x.get_text().strip() for x in row.contents]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        keyword, _, data_type, control_type = cells
        yield InputTypeData(
            name=keyword,
            value_type=data_type,
            control_type=control_type,
            url=f'https://html.spec.whatwg.org/dev/input.html{row.a['href'].strip()}',
        )


def dictify_attributes(attribute_list: list[AttributeData]) -> dict[str, dict[str, Any]]:
    """Convert a list of AttributeData into a dict keyed by name, then by tag (_ALL_TAGS for `tag is None`).

    Returns:
        JSON-serializable dict of HTML attribute data
    """
    result: dict[str, dict[str, Any]] = {}
    for attribute in attribute_list:
        r = dataclasses.asdict(attribute)
        del r['name']
        del r['tag']
        tag_key = _ALL_TAGS if attribute.tag is None else attribute.tag
        by_tag = result.setdefault(attribute.name, {})
        if tag_key in by_tag:
            logger.debug('Duplicate attribute name + tag pair: (%r, %r)', attribute.name, tag_key)
            dict_merge(by_tag[tag_key], r, concat_fields=('description', 'value_info'))
        else:
            by_tag[tag_key] = r
    return result


class Curator:
    """Converts raw spec HTML to typed entities, with validation and fallback cache."""

    def __init__(
        self,
        raw_data_dir: Path,
        cache_dir: Path,
        emender: Emender | None = None,
    ) -> None:
        self.raw_data_dir = raw_data_dir
        self.cache_dir = cache_dir
        self.emender = emender if emender is not None else Emender()
        self._soup_cache: dict[str, BeautifulSoup | None] = {}
        self._manifest: dict[str, dict] = {}
        self._fallback_sections: set[str] = set()

    # ---- internal helpers ----

    def _load_soup(self, page: str) -> BeautifulSoup | None:
        """Load and cache the soup for `page` (shared across every section of that page).

        Returns:
            - A BeautifulSoup object or
            - None if the raw HTML is missing or unreadable (also logs)
        """
        if page not in self._soup_cache:
            try:
                with (self.raw_data_dir / f'{page}.html').open('r') as fp:
                    soup = BeautifulSoup(fp, 'lxml')
                self.emender.emend(currentframe().f_code.co_name, page, soup)
                self._soup_cache[page] = soup
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
        """Load the raw (still plain-dict) cached entries for `key`; return None if missing.

        Returns:
            The cached list of dicts or None if not found in cache
        """
        path = self.cache_dir / f'{key}.json'
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def _load_cache(self, key: str, cls: type) -> list | None:
        """Load the cached entries for `key`, reconstructed as `cls` instances.

        Returns:
            The cached list of dataclass objects or None if not found in cache
        """
        raw = self._load_cache_raw(key)
        return None if raw is None else [dict_to_dataclass(cls, d) for d in raw]

    def _validate(self, key: str, count: int) -> dict:
        """Compare `count` against the previous cached run for `key` (if any) and decide pass/warn/raise.

        No fixed floor: a category may legitimately grow or shrink a little as the spec evolves,
        but a bigger jump either way is more likely a broken extraction/parse than a real change upstream.
        Stores the manifest entry. Warns if the source row count changes.

        Returns:
            The manifest entry for `key`: {status, row_count} plus delta
        """
        previous = self._load_cache_raw(key)
        previous_count = len(previous) if previous is not None else None
        delta = 0 if previous_count is None else count - previous_count

        if abs(delta) >= 1:
            logger.warning('⚠️ %s: count changed by %d since last run (%d -> %d)', key, delta, previous_count, count)

        entry = {'status': 'ok', 'row_count': count, 'delta': delta}
        self._output_manifest[key] = entry
        return entry

    def _log_parse_error_and_fallback(self, e: Exception, section: str, cls: type) -> list:
        """Load `section`'s previously cached (already fully emended) data after a recoverable parse error.

        Records a manifest entry with `input_row_count: None`, and marks `section` as a fallback so
        `get_all()` skips re-running emendations and re-caching over data that's already final.

        Returns:
            The cached list of dataclass objects

        Raises:
            RuntimeError: if no cache is available for `section`
        """
        logger.error('❌ Parsing failed: %s', e)

        cached = self._load_cache(section, cls)

        if cached is None:
            msg = f'No cache available for {section}'
            raise RuntimeError(msg) from e

        logger.info('📂 Loaded %s from cache', section)
        self._manifest[section] = {'input_row_count': None}
        self._fallback_sections.add(section)
        return cached

    def _get_parsed_section(self, section: str) -> list:
        """Parse `section` from its page's soup and apply its input emendations.

        Records `input_row_count` (the row count straight out of parse_X(), before any emendation) in the
        manifest. On a recoverable parse/extraction error, falls back to the previous cached run for
        `section` instead (see `_log_parse_error_and_fallback`).

        Returns:
            List of data JSON objects

        Raises:
            FileNotFoundError: if section raw source not found
        """
        page, cls = SECTION_SOURCES[section]
        soup = self._load_soup(page)

        try:
            if soup is None:
                msg = f'No raw HTML available for page {SECTION_SOURCES[section][0]!r}'
                raise FileNotFoundError(msg)

            parser = getattr(sys.modules[__name__], f'parse_{section}')
            parsed = list(parser(soup))
            input_row_count = len(parsed)
            self.emender.emend(currentframe().f_code.co_name, section, parsed)
        except _RECOVERABLE_ERRORS as e:
            return self._log_parse_error_and_fallback(e, section, cls)

        self._manifest[section] = {'input_row_count': input_row_count}
        logger.info('🏗️ Built %s %s', len(parsed), section)
        return parsed

    # ---- public builders ----

    def get_all(self) -> tuple[dict[str, list], dict]:
        """Run all section builders, apply external emendations, then finalize the manifest and cache.

        Non-fallback sections get their normalized-data write, external emendation, and cache save;
        fallback sections already hold final (post-emendation) cached data, so all three are skipped for
        them. `output_row_count` and `delta` are recorded for every section once all entries are final.

        Returns:
            {section: [entities]} and the manifest
        """
        results = {section: self._get_parsed_section(section) for section in SECTION_SOURCES}

        NORMALIZED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        for section, entries in results.items():
            if section not in self._fallback_sections:
                write_ndjson(NORMALIZED_DATA_DIR / f'{section}.ndjson', entries)

        for section, entries in results.items():
            if section not in self._fallback_sections:
                self.emender.emend(currentframe().f_code.co_name, section, entries)

        for section, entries in results.items():
            count = len(entries)
            previous = self._load_cache_raw(section)
            previous_count = len(previous) if previous is not None else None
            delta = 0 if previous_count is None else count - previous_count
            self._manifest[section]['output_row_count'] = count
            if delta:
                logger.warning(
                    '⚠️ %s: count changed by %d since last run (%d -> %d)', section, delta, previous_count, count
                )
                self._manifest[section]['delta'] = delta

        for section, entries in results.items():
            if section not in self._fallback_sections:
                self._save_cache(section, entries)

        return results, dict(self._manifest)
