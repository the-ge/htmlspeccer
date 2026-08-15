import logging
from collections.abc import Iterator

from bs4 import BeautifulSoup
from slugify import slugify

from schema import ElementKindData
from util.transforming import deduplicate

logger = logging.getLogger(__name__)


# ---- Per-section extract-and-parse functions ----
# Each function takes the soup for its source page and yields typed entities directly. Extraction
# (cell/anchor text out of the soup, stripped of surrounding whitespace only) and interpretation
# (splitting, typing, spec-specific logic) are no longer separate stages.


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
