from config import FILTERED_DATA_DIR
from filtering_engine import RawAriaRole
from normalizing_engine import Attribute, parse_aria_roles
from util import parse_section


def emend(section, data) -> bool:
    if section != 'attributes':
        return False

    data.append(Attribute(
        name='role',
        tag_scope=set(),
        description='ARIA semantic role',
        value_type='string',
        value_enum=set(parse_section(
            FILTERED_DATA_DIR, 'aria', 'aria_roles', RawAriaRole, parse_aria_roles,
        )),
        value_info='',
        separator=' ',
    ))
    return True
