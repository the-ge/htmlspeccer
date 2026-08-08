import logging

from filtering import GlobalAttributeTerseData

from config import TERSE_DATA_DIR
from normalizing import parse_global_attributes
from util import dictify, parse_section

logger = logging.getLogger(__name__)


def emend(section: str, data: list) -> bool:
    """Expand the synthetic 'globals' token into real global attribute names on each element's attributes set.

    Returns:
        True if any expanding occured or False if not
    """
    if section != 'elements':
        return False

    rows = parse_section(TERSE_DATA_DIR, 'dom', 'global_attributes', GlobalAttributeTerseData, parse_global_attributes)
    global_attribute_names = dictify(list(rows))

    has_fired = False
    for entry in data:
        if 'globals' in entry.attributes:
            entry.attributes.discard('globals')
            entry.attributes.update(global_attribute_names)
            has_fired = True

    return has_fired
