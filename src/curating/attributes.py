import logging
import re
from collections.abc import Iterator

from bs4 import BeautifulSoup, element

from config import SPEC_BASE_URL
from curating.nodes import concat_text_nodes, get_cell_nodes
from schema import AttributeData
from util.transforming import normalize_url

logger = logging.getLogger(__name__)

# Expected cell count
_HTML_CELL_COUNT = 4

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

# Bare (non-<code>-wrapped) anchor text found in an attribute's elements cell -> special scope key, or
# None for "no tag restriction". Any other bare anchor text is unrecognized (warned and skipped).
_SPECIAL_NODES = {'HTML elements': None, 'form-associated custom elements': 'formcustom'}

# Match a list of one-or-more keywords such as `"foo"; "bar"; "the empty string"`
_VALUE_REGEX = re.compile(r'^(?:"[a-zA-Z0-9/-]*"|the empty string)(?:; (?:"[a-zA-Z0-9/-]*"|the empty string))*$')

_VALUE_TYPE_BY_PREFIX = {
    'Valid non-negative integer':  'int',
    'Valid floating-point number': 'float',
}

_VALUE_TYPE_BY_STRING = {
    'Boolean attribute':                    'bool',
    'Valid integer':                        'int',
    'Valid date string with optional time': 'datetime',
}


def parse_attributes(soup: BeautifulSoup) -> Iterator[AttributeData]:
    """Takes the soup for its data source page and yields typed entities directly.

    Data source page: https://html.spec.whatwg.org/multipage/indices.html#attributes-1.

    Yields:
        Typed entities
    """
    rows = soup.find('table', {'id': 'attributes-1'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT
    for row in rows:
        cells = row.find_all(['th', 'td'])
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        name_cell, elements_cell, description_cell, value_cell = cells
        yield from _parse_attribute_cells(name_cell.get_text().strip(), elements_cell, description_cell, value_cell)


def _parse_attribute_cells(
    name: str, elements_cell: element.Tag, description_cell: element.Tag, value_cell: element.Tag
) -> Iterator[AttributeData]:
    """Parse one attribute row's cells into one or more AttributeData entries, split by scope.

    `description` and `value_info` are decomposed via get_cell_nodes() into (text, url) node lists.
    A leading '*' marker on the value cell is stripped and sets `is_more_value_info_required` (see
    _apply_value_info_marker()). value_type/value_enum/separator are classified from the value cell's
    joined node text; `value_info` is reset to [] when value_enum ends up populated.

    Yields:
        One AttributeData per (scope, scope_url) scope found in the elements cell (see
        _parse_attribute_scopes()); nothing if the elements cell yields no scope at all
    """
    description = concat_text_nodes(get_cell_nodes(description_cell))

    value_nodes, is_more_value_info_required = _apply_value_info_marker(get_cell_nodes(value_cell))
    value_nodes = concat_text_nodes(value_nodes)
    value_type_str = ' '.join(text for text, _ in value_nodes).strip()

    value_enum = set(_gen_attribute_value_enums(value_type_str))
    if value_enum:
        value_type, separator, value_info = 'enum', '', []
    else:
        value_type, separator = _parse_attribute_value(value_type_str)
        value_info = value_nodes

    scopes = list(_parse_attribute_scopes(elements_cell, name))
    if not scopes:
        logger.warning('⚠️ Attribute %r: no tag found in elements cell; row skipped', name)
        return

    for scope, scope_url in scopes:
        yield AttributeData(
            name=name,
            scope=scope,
            value_type=value_type,
            value_enum=value_enum,
            separator=separator,
            scope_url=scope_url,
            value_info=value_info,
            description=description,
            is_more_value_info_required=is_more_value_info_required,
        )


def _parse_attribute_value(value_type_str: str) -> tuple[str, str]:
    value_type = _VALUE_TYPE_BY_STRING.get(value_type_str)
    if value_type is None:
        for prefix, mapped_type in _VALUE_TYPE_BY_PREFIX.items():
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
    """Extract (scope, scope_url) pairs from an attribute row's elements cell.

    A <code>-wrapped anchor is a real tag: its own text is the tag name (scope), its own href is
    scope_url. A bare (non-<code>-wrapped) anchor is looked up in _SPECIAL_NODES: found gives one
    additional scope (None for "no tag restriction", or a tag-group name); not found is warned and
    skipped. More than one bare anchor in a cell is unexpected: only the first is used, others are
    warned and ignored. A bare anchor resolving to "no tag restriction" alongside real tags is a
    contradiction: warned and skipped.

    Yields:
        (scope, scope_url) pairs; scope is None (no restriction), a tag-group name, or a real tag name
    """
    real_tags: list[tuple[str, str]] = []
    bare_anchors: list[element.Tag] = []
    for a in cell.find_all('a'):
        if a.find_parent('code') is not None:
            real_tags.append((a.get_text().strip(), normalize_url(a['href'].strip(), SPEC_BASE_URL)))
        else:
            bare_anchors.append(a)

    yield from real_tags

    if not bare_anchors:
        return

    chosen = bare_anchors[0]
    if len(bare_anchors) > 1:
        ignored = ', '.join(repr(a.get_text().strip()) for a in bare_anchors[1:])
        logger.warning(
            '⚠️ Attribute %r: multiple special scope anchors in one cell; using %r, ignoring: %s',
            name, chosen.get_text().strip(), ignored,
        )

    text = chosen.get_text().strip()
    if text not in _SPECIAL_NODES:
        logger.warning('⚠️ Attribute %r: unrecognized special scope phrase %r', name, text)
        return

    scope = _SPECIAL_NODES[text]
    if scope is None and real_tags:
        logger.warning(
            "⚠️ Attribute %r: bare anchor %r resolves to 'no tag restriction' alongside real tags; skipping it",
            name, text,
        )
        return

    yield scope, normalize_url(chosen['href'].strip(), SPEC_BASE_URL)


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


# ---- Generators for splitting spec strings ----


def _gen_attribute_value_enums(input_str: str) -> Iterator[str]:
    if _VALUE_REGEX.fullmatch(input_str):

        def process_keyword(keyword: str) -> str:
            keyword = keyword.strip()
            return '' if keyword == 'the empty string' else keyword.strip('"')

        yield from map(process_keyword, input_str.split(';'))
