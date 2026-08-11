from config import NORMALIZED_DATA_DIR
from curating import AriaRoleData, AttributeData
from util import read_ndjson

description = "add the 'role' attribute"


def emend(section: str, data: list) -> bool:
    """Add a new `role` AttributeData.

    Source:      https://w3c.github.io/aria/ pages (see `parse_aria_roles()` in `curating.py` for full URL list)
    Explanation: synthesize the `role` attribute from the retrieved data

    Returns:
        True if the input type values were added or False if not
    """
    if section != 'attributes':
        return False

    roles = read_ndjson(NORMALIZED_DATA_DIR / 'aria_roles.ndjson', AriaRoleData)
    data.append(AttributeData(
        name='role',
        description='ARIA semantic role',
        value_enum={x.name for x in roles},
        separator=' ',
        urls={x.url for x in roles},
    ))

    return True
