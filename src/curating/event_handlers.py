import logging
from collections.abc import Iterator

from bs4 import BeautifulSoup

from curating.nodes import concat_text_nodes, get_cell_nodes, prune_nodes
from schema import EventHandlerData

logger = logging.getLogger(__name__)


# Expected cell count in each domain of the online HTML sources
_HTML_CELL_COUNT = 4


def parse_event_handlers(soup: BeautifulSoup) -> Iterator[EventHandlerData]:
    """Takes the soup for its data source page and yields typed entities directly.

    Data source page: https://html.spec.whatwg.org/multipage/indices.html#ix-event-handlers.

    Returns:
        Typed entities
    """
    rows = soup.find('table', {'id': 'ix-event-handlers'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT
    for row in rows:
        cells = row.find_all(['th', 'td'])
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        name_cell, scope_cell, description_cell, _ = cells
        yield EventHandlerData(
            name=name_cell.get_text().strip(),
            scope={a.get_text().strip(): a['href'].strip() for a in scope_cell.find_all('a')},
            description=concat_text_nodes(prune_nodes(get_cell_nodes(description_cell), {'match': {'event handler'}}))
        )
