import logging
import re
import string
from collections.abc import Iterator

from bs4 import BeautifulSoup, element

from config import SPEC_BASE_URL
from curating.nodes import get_cell_nodes
from schema import ElementData
from util.transforming import normalize_url

logger = logging.getLogger(__name__)


# Expected cell count in each domain of the online HTML sources
_HTML_CELL_COUNT = 7

# Base URL (with trailing '#') for building each element's own anchor in the indices.html summary table
_INDICES_BASE_URL = 'https://html.spec.whatwg.org/multipage/indices.html#'

# Special cases: phrase -> list of yielded tokens (empty list yields nothing).
_TAGS_BY_STRING = {
    'autonomous custom elements': [],
    'HTML elements': [],
    'form-associated custom elements': ['custom'],
    'MathML math': ['math'],
    'SVG svg': ['svg'],
}


def parse_elements(soup: BeautifulSoup) -> Iterator[ElementData]:
    """Takes the soup for its data source page and yields typed entities directly.

    Data source page: https://html.spec.whatwg.org/multipage/indices.html#elements-3.

    Yields:
        Typed entities
    """
    rows = soup.find('h3', {'id': 'elements-3'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT
    for row in rows:
        cells = row.find_all(['th', 'td'])
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        name_cell, description_cell, categories_cell, parents_cell, children_cell, attributes_cell, interface_cell = cells

        names = list(_gen_tags(name_cell.get_text().strip()))
        urls_by_name = dict(zip(names, _parse_element_name_urls(name_cell, names), strict=True))

        attributes = _cell_dict(attributes_cell)
        attributes.pop('globals', None)

        for e in sorted(names):
            summary_url, semantics_url = urls_by_name[e]
            yield ElementData(
                name=e,
                summary_url=summary_url,
                semantics_url=semantics_url,
                description=description_cell.get_text().strip(),
                categories=_cell_dict(categories_cell),
                parents=_cell_dict(parents_cell),
                children=_cell_dict(children_cell),
                attributes=attributes,
                interface=_cell_dict(interface_cell),
            )


# ---- Cell parsing helpers ----


def _parse_element_name_urls(name_cell: element.Tag, names: list[str]) -> list[tuple[str, str]]:
    """Resolve (summary_url, semantics_url) for each of `names`, in the same order.

    Prefers each id-bearing <code> descendant of `name_cell`, zipped against `names` in document
    order (covers real single- and multi-tag rows, e.g. the shared `h1`...`h6` row, each of whose
    <code> tags carries its own id). Falls back to the cell's own outer <a> for id/href, applied to
    every name (covers bare-anchor special-phrase rows, and MathML/SVG rows whose inner <code> has
    no id of its own).

    Returns:
        (summary_url, semantics_url) pairs, one per name in `names`, in the same order

    Warns:
        If the id-bearing <code> count doesn't match len(names); reuses the first code's id/href for
        every name in that case.
    """
    codes = [c for c in name_cell.find_all('code') if c.get('id')]
    if codes:
        if len(codes) != len(names):
            logger.warning(
                '⚠️ Element %s: %s id-bearing <code> tags for %s split names; reusing the first for all',
                names, len(codes), len(names),
            )
            codes = [codes[0]] * len(names)
        return [
            (
                normalize_url(code['id'].strip(), _INDICES_BASE_URL),
                normalize_url(code.a['href'].strip(), SPEC_BASE_URL),
            )
            for code in codes
        ]

    a = name_cell.a
    return [
        (
            normalize_url(a['id'].strip(), _INDICES_BASE_URL),
            normalize_url(a['href'].strip(), SPEC_BASE_URL),
        )
    ] * len(names)


def _cell_dict(cell: element.Tag) -> dict[str, str]:
    """Build a {name: url} dict from a cell's nodes, via get_cell_nodes().

    A cell with no linked node at all (e.g. a literal 'none'/'empty'/'—' parents/content-model cell)
    yields {}. Otherwise every node is kept: linked nodes as (text, url); bare nodes (footnote
    markers, ';' separators, or genuine bare keywords like embed's attributes cell 'any') as
    (text, '') once stripped of surrounding whitespace/';'/'*' noise, dropped only if nothing
    remains after that strip.

    Returns:
        {name: url} dict, in document order
    """
    nodes = get_cell_nodes(cell)
    if not any(url for _, url in nodes):
        return {}

    result = {}
    for text, url in nodes:
        if not url:
            text = text.strip(string.whitespace + ';*')  # noqa: PLW2901
            if not text:
                continue
        result[text] = url
    return result


# ---- Generators for splitting spec strings ----


def _gen_tags(input_str: str) -> Iterator[str]:
    input_str = input_str.strip()
    if not input_str:
        return

    # 1) Handle known special phrases
    if input_str in _TAGS_BY_STRING:
        yield from _TAGS_BY_STRING[input_str]
        return

    if ';' in input_str:
        for e in re.split(r'\s*;\s*', input_str.strip(string.whitespace + ';')):
            yield from _gen_tags(e.strip())
    elif ',' in input_str:
        for e in re.split(r'\s*,\s*', input_str.strip(string.whitespace + ',')):
            yield from _gen_tags(e)
    else:
        yield input_str
