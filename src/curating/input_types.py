import logging
from collections.abc import Iterator

from bs4 import BeautifulSoup

from schema import InputTypeData

logger = logging.getLogger(__name__)

# Expected cell count in each domain of the online HTML sources
_HTML_CELL_COUNT = 4

_INPUT_BASE_URL = 'https://html.spec.whatwg.org/dev/input.html'


def parse_input_types(soup: BeautifulSoup) -> Iterator[InputTypeData]:
    """Takes the soup for its data source page and yields typed entities directly.

    Data source page: https://html.spec.whatwg.org/dev/input.html#attr-input-type-keywords.

    Returns:
        Typed entities
    """
    rows = soup.find('table', {'id': 'attr-input-type-keywords'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT
    for row in rows:
        cells = [x.get_text().strip() for x in row.contents]
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        keyword, state, data_type, control_type = cells
        yield InputTypeData(
            name=keyword,
            url=f'{_INPUT_BASE_URL}#{row.dfn['id']}',
            state={'name': state, 'url': f'{_INPUT_BASE_URL}{row.a['href'].strip()}'},
            value_type=data_type,
            control_type=control_type,
        )
