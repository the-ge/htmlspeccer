from filtering import AriaRoleTerseData

from config import TERSE_DATA_DIR
from normalizing import AttributeData, parse_aria_roles
from util import parse_section


def emend(section: str, data: list) -> bool:
    """Add a new `role` AttributeData.

    Source:      https://w3c.github.io/aria/ pages (see `parse_aria_roles()` in `normalizing.py` for full URL list)
    Explanation: synthesize the `role` attribute from the retrieved data

    Returns:
        True if the input type values were added or False if not
    """
    if section != 'attributes':
        return False

    parsed = list(parse_section(TERSE_DATA_DIR, 'aria', 'aria_roles', AriaRoleTerseData, parse_aria_roles))
    data.append(AttributeData(
        name='role',
        description='ARIA semantic role',
        value_enum={x.name for x in parsed},
        separator=' ',
        urls={x.url for x in parsed},
    ))

    return True
