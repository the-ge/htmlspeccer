from config import TERSE_DATA_DIR
from filtering_engine import InputTypeTerseData
from normalizing_engine import AttributeData, parse_input_types
from util import parse_section


def emend(section: str, data: list) -> None:
    if section != 'attributes':
        return False

    parsed = list(parse_section(TERSE_DATA_DIR, 'input', 'input_types', InputTypeTerseData, parse_input_types))
    data.append(AttributeData(
        name='type',
        tag_scope={'input'},
        description='Type of form control',
        value_enum={x.name for x in parsed},
        value_info='An input type e.g. "text", "number", or "week".',
        urls={x.url for x in parsed},
    ))
    return True
