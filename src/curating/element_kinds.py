import logging
from collections.abc import Iterator

from bs4 import BeautifulSoup

from schema import ElementKindData
from util.transforming import slugify_by_vocabulary

logger = logging.getLogger(__name__)


def parse_element_kinds(soup: BeautifulSoup) -> Iterator[ElementKindData]:
    """Takes the soup for its data source page and yields typed entities directly.

    Data source page: https://html.spec.whatwg.org/dev/syntax.html#elements-2.

    Yields:
        Typed entities
    """
    rows = soup.find('h4', {'id': 'elements-2'}).find_next('dl').find_all(['dt', 'dd'], recursive=False)
    prev = None  # tag name of the last row seen: None, 'dt', or 'dd'
    title = None
    slug = None
    for row in rows:
        if row.name == 'dt':
            if prev not in {None, 'dd'}:
                logger.error('❌ <dt> not preceded by a <dd>: %s', row)
            title = row.dfn.get_text().strip()  # literal text; slugify() happens below
            slug = slugify_by_vocabulary(title, {
                'Escapable raw text elements': 'escapable',
                'Foreign elements': 'foreign',
                'Normal elements': 'normal',
                'Raw text elements': 'raw',
                'The template element': 'template',
                'Void elements': 'void',
            })
            prev = 'dt'
        elif row.name == 'dd':
            if prev != 'dt':
                logger.error('❌ <dd> not preceded by a <dt>: %s', row)
                continue
            tags = {x.get_text().strip(): x.a['href'].strip() for x in row.find_all('code')}
            info = '' if tags else row.get_text().strip()
            prev = 'dd'
            yield ElementKindData(
                name=slug,
                title=title,
                tags=tags,
                info=info,
            )
    if prev == 'dt':
        logger.error('❌ Trailing <dt> with no following <dd>: %s', title)
