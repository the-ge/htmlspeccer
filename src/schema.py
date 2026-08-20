import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

type InputData = AriaRoleData | AttributeData | ContentCategoryData | ElementData | ElementKindData | EventHandlerData | GlobalAttributeData | InputTypeData
type OutputData = AriaRoleDocs | AriaRoleSpec


# ---- Typed entities (curate-stage output shape) ----


@dataclass(frozen=True, slots=True)
class AriaRoleData:
    name: str
    is_abstract: bool = False
    url: str = ''
    description: str = ''
    parents: dict[str, str] = field(default_factory=dict)
    children: dict[str, str] = field(default_factory=dict)
    states: dict[str, dict[str, str]] = field(default_factory=dict)
    properties: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AriaRoleDocs:
    name: str
    url: str = ''
    description: list[tuple[str, str]] = field(default_factory=list)
    states: dict[str, str] = field(default_factory=dict)
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AriaRoleSpec:
    name: str
    is_abstract: bool = False
    parents: set[str] = field(default_factory=set)
    children: set[str] = field(default_factory=set)
    states: dict[str, str] = field(default_factory=dict)
    properties: dict[str, str] = field(default_factory=dict)


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
    title: str = ''
    url: str = ''
    elements: list[tuple[str, str]] = field(default_factory=list)
    elements_if: list[tuple[str, str, list[tuple[str, str]]]] | None = None


@dataclass(frozen=True, slots=True)
class ElementData:
    name: str
    summary_url: str = ''
    semantics_url: str = ''
    description: str = ''
    categories: dict[str, str] = field(default_factory=dict)
    parents: dict[str, str] = field(default_factory=dict)
    children: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    interface: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ElementKindData:
    name: str
    title: str = ''
    tags: dict[str, str] = field(default_factory=dict)
    info: str = ''


@dataclass(frozen=True, slots=True)
class EventHandlerData:
    name: str
    scope: dict[str, str] = field(default_factory=dict)
    description: list[tuple[str, str]] = field(default_factory=list)


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


# Data domain name -> (page, entity dataclass).
CURATION_MAP: dict[str, tuple[str, type]] = {
    'aria_roles': ('aria', AriaRoleData),
    'attributes': ('indices', AttributeData),
    'content_categories': ('indices', ContentCategoryData),
    'elements': ('indices', ElementData),
    'element_kinds': ('syntax', ElementKindData),
    'event_handlers': ('indices', EventHandlerData),
    'global_attributes': ('dom', GlobalAttributeData),
    'input_types': ('input', InputTypeData),
}

# Publishing data domain name -> entity dataclass.
CLASS_FROM_DOMAIN: dict[str, type] = {domain: cls for domain, (_, cls) in CURATION_MAP.items()}

# Data domain name -> (page, entity dataclass, datatypeclass to fields dict).
DATA_MAP: dict[str, dict[str, str | type | tuple[type, set[str]]]] = {
    'aria_roles': {
        'page': 'aria',
        'source_cls': AriaRoleData,
        'spec': (AriaRoleSpec, {
            'is_abstract',
            'parents',
            'children',
            'states.deprecated_since',
            'properties.deprecated_since',
        }),
        'docs': (AriaRoleDocs, {
            'url',
            'description',
            'states.url',
            'properties.url',
        }),
    },
}
