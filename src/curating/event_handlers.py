import logging
from collections.abc import Iterator

from bs4 import BeautifulSoup

from config import SPEC_BASE_URL
from schema import EventHandlerData
from util.transforming import deduplicate, normalize_url

logger = logging.getLogger(__name__)


# Expected cell count in each domain of the online HTML sources
_HTML_CELL_COUNT = 4


# ---- Per-section extract-and-parse functions ----
# Each function takes the soup for its source page and yields typed entities directly. Extraction
# (cell/anchor text out of the soup, stripped of surrounding whitespace only) and interpretation
# (splitting, typing, spec-specific logic) are no longer separate stages.


def parse_event_handlers(soup: BeautifulSoup) -> Iterator[EventHandlerData]:
    # https://html.spec.whatwg.org/multipage/indices.html#ix-event-handlers
    rows = soup.find('table', {'id': 'ix-event-handlers'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT
    for row in rows:
        cells = [x.get_text().strip() for x in row.find_all(['th', 'td'])]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        attribute, elements, _, _ = cells
        urls = deduplicate(normalize_url(x['href'].strip(), SPEC_BASE_URL) for x in row.find_all('a'))
        yield EventHandlerData(
            name=attribute,
            applies_to=elements,
            urls=set(urls),
        )
