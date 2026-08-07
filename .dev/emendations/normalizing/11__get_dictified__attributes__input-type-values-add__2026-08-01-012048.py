import dataclasses
import logging

from config import TERSE_DATA_DIR
from filtering import InputTypeTerseData
from normalizing import parse_input_types
from util import parse_section

logger = logging.getLogger(__name__)


def emend(section: str, data: list) -> bool:
    """Add input type values into the existing type/input entry enum; absorbs the former append-type emendation.

    Issue location: https://html.spec.whatwg.org/multipage/indices.html#attributes-3:attr-input-type.
    Explanation: data will be updated with `enum` value type and enum values from
                 https://html.spec.whatwg.org/dev/input.html#attr-input-type-keywords.
    """
    if section != 'attributes':
        return False

    entry = next((e for e in data if e.name == 'type' and e.tag == 'input'), None)
    if entry is None:
        return False

    parsed = list(parse_section(TERSE_DATA_DIR, 'input', 'input_types', InputTypeTerseData, parse_input_types))
    new_entry = dataclasses.replace(
        entry,
        value_type='enum',
        value_enum=entry.value_enum | {x.name for x in parsed},
        value_info='',
        separator='',
        urls=entry.urls | {x.url for x in parsed},
    )
    data[data.index(entry)] = new_entry
    logger.info('🩹 Emended duplicate %r/%r pair: merged input type values into enum', 'type', 'input')
    return True
