import logging
import re
from collections.abc import Iterator

from bs4 import BeautifulSoup, element

from curating.nodes import concat_text_nodes, get_cell_nodes
from schema import AriaRoleData

logger = logging.getLogger(__name__)


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
            description = concat_text_nodes(get_cell_nodes(row))
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
