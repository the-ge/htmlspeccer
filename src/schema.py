import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---- Typed entities (curate-stage output shape) ----


@dataclass(frozen=True, slots=True)
class AriaRoleData:
    name: str
    url: str = ''
    description: str = ''
    is_abstract: bool = False
    parents: dict[str, str] = field(default_factory=dict)
    children: dict[str, str] = field(default_factory=dict)
    states: dict[str, dict[str, str]] = field(default_factory=dict)
    properties: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AttributeData:
    name: str
    scope: str | None = None
    scope_url: str = ''
    separator: str = ''
    value_type: str = 'string'
    value_enum: set[str] = field(default_factory=set)
    value_info: list[tuple[str, str]] = field(default_factory=list)
    is_more_value_info_required: bool = False
    description: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ContentCategoryData:
    name: str
    url: str = ''
    elements: list[tuple[str, str]] = field(default_factory=list)
    elements_if: list[tuple[str, str, list[tuple[str, str]]]] | None = None


@dataclass(frozen=True, slots=True)
class ElementData:
    name: str
    description: str = ''
    categories: set[str] = field(default_factory=set)
    attributes: set[str] = field(default_factory=set)
    children: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ElementKindData:
    name: str
    tags: set[str] = field(default_factory=set)
    info: str = ''


@dataclass(frozen=True, slots=True)
class EventHandlerData:
    name: str
    applies_to: str = ''
    urls: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class GlobalAttributeData:
    name: str
    url: str = ''


@dataclass(frozen=True, slots=True)
class InputTypeData:
    name: str
    url: str = ''
    state: dict[str, str] = field(default_factory=dict)
    value_type: str = ''
    control_type: str = ''


# section name -> (page, entity dataclass); drives Curator.get_all() and Publisher.read_data_domains().
# Keys match config.PAGE_SECTIONS values.
SECTION_SOURCES: dict[str, tuple[str, type]] = {
    'aria_roles': ('aria', AriaRoleData),
    'attributes': ('indices', AttributeData),
    'content_categories': ('indices', ContentCategoryData),
    'elements': ('indices', ElementData),
    'element_kinds': ('syntax', ElementKindData),
    'event_handlers': ('indices', EventHandlerData),
    'global_attributes': ('dom', GlobalAttributeData),
    'input_types': ('input', InputTypeData),
}
