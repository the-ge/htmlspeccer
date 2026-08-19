import logging
from collections.abc import Iterator

from bs4 import BeautifulSoup

from schema import GlobalAttributeData

logger = logging.getLogger(__name__)


# Expected cell count in each domain of the online HTML sources
_HTML_CELL_COUNT = 4

_SUPER_GLOBALS = {
    'class': 'https://html.spec.whatwg.org/dev/dom.html#classes',
    'id': 'https://html.spec.whatwg.org/dev/dom.html#the-id-attribute',
    'role': 'https://w3c.github.io/aria/#introroles',
    'slot': 'https://html.spec.whatwg.org/dev/dom.html#attr-slot',
}

# ---- Per-section extract-and-parse functions ----
# Each function takes the soup for its source page and yields typed entities directly. Extraction
# (cell/anchor text out of the soup, stripped of surrounding whitespace only) and interpretation
# (splitting, typing, spec-specific logic) are no longer separate stages.


def parse_global_attributes(soup: BeautifulSoup) -> Iterator[GlobalAttributeData]:
    # https://html.spec.whatwg.org/dev/dom.html#global-attributes
    for name, url in _SUPER_GLOBALS.items():
        yield GlobalAttributeData(name=name, url=url)
    anchors = soup.find('h4', {'id': 'global-attributes'}).find_next('ul', {'class': 'brief'}).find_all('a')
    for a in anchors:
        yield GlobalAttributeData(
            name=a.get_text().strip(),
            url=f'https://html.spec.whatwg.org/dev/{a['href'].strip()}',
        )
