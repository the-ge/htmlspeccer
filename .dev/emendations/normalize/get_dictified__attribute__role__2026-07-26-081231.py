from config import TERSE_DATA_DIR
from filtering_engine import AriaRoleTerseData
from normalizing_engine import AttributeData, parse_aria_roles
from util import parse_section


def emend(section: str, data: list) -> bool:
    if section != 'attributes':
        return False

    data.append(AttributeData(
        name='role',
        tag_scope=set(),
        description='ARIA semantic role',
        value_type='string',
        value_enum=set(parse_section(
            TERSE_DATA_DIR, 'aria', 'aria_roles', AriaRoleTerseData, parse_aria_roles,
        )),
        value_info='',
        separator=' ',
    ))
    return True
