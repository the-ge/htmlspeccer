from config import FILTERED_DATA_DIR
from filtering_engine import RawInputType
from normalizing_engine import Attribute, parse_input_types
from util import parse_section


def emend(section: str, data: list) -> None:
    if section != 'attributes':
        return False

    data.append(Attribute(
        name='type',
        tag_scope={'input'},
        description='Type of form control',
        value_type='string',
        value_enum=set(parse_section(
            FILTERED_DATA_DIR, 'input', 'input_types', RawInputType, parse_input_types,
        )),
        value_info='An input type e.g. "text", "number", or "week".',
        separator='',
    ))
    return True
