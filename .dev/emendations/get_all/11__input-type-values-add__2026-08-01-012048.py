import dataclasses

from config import NORMALIZED_DATA_DIR
from schema import InputTypeData
from util.serializing import read_ndjson

description = "add values to 'type'/'input' value enum"


def emend(section: str, data: list) -> bool:
    """Add input type values into the existing type/input entry enum; absorbs the former append-type emendation.

    Source:      https://html.spec.whatwg.org/multipage/indices.html#attributes-3:attr-input-type.
    Explanation: data will be updated with `enum` value type and enum values from
                 https://html.spec.whatwg.org/dev/input.html#attr-input-type-keywords.

    Returns:
        True if the input type values were added or False if not
    """
    if section != 'attributes':
        return False

    entry = next((e for e in data if e.name == 'type' and e.scope == 'input'), None)
    if entry is None:
        return False

    parsed = read_ndjson(NORMALIZED_DATA_DIR / 'input_types.ndjson', InputTypeData)
    new_entry = dataclasses.replace(
        entry,
        value_type='enum',
        value_enum=entry.value_enum | {x.name for x in parsed},
        value_info=[(x.name, x.url) for x in parsed],
    )
    data[data.index(entry)] = new_entry
    return True
