import logging
import re
import string
from collections.abc import Iterator

from bs4 import BeautifulSoup

from schema import ElementData

logger = logging.getLogger(__name__)


# Expected cell count in each domain of the online HTML sources
_HTML_CELL_COUNT = 7

# Special cases: phrase -> list of yielded tokens (empty list yields nothing). Used by gen_tags(), which
# still serves parse_elements(); parse_attributes() and parse_content_categories() no longer use gen_tags().
_TAGS_BY_STRING = {
    'autonomous custom elements': [],
    'HTML elements': [],
    'form-associated custom elements': ['custom'],
    'MathML math': ['math'],
    'SVG svg': ['svg'],
}


# ---- Generators for splitting spec strings ----


def gen_attribute_names(input_str: str) -> Iterator[str]:
    for attribute in input_str.strip(string.whitespace + ';').split(';'):
        yield attribute.strip('*').strip()


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


# ---- Per-section extract-and-parse functions ----
# Each function takes the soup for its source page and yields typed entities directly. Extraction
# (cell/anchor text out of the soup, stripped of surrounding whitespace only) and interpretation
# (splitting, typing, spec-specific logic) are no longer separate stages.


def parse_elements(soup: BeautifulSoup) -> Iterator[ElementData]:
    # https://html.spec.whatwg.org/multipage/indices.html#elements-3
    rows = soup.find('h3', {'id': 'elements-3'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT
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
