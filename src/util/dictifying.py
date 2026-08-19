import dataclasses
import logging
import re
from collections.abc import Iterable
from typing import Any, get_origin

from schema import (
    CLASS_FROM_DOMAIN,
    CURATION_MAP,
    AriaRoleData,
    AriaRoleDocs,
    AriaRoleSpec,
    AttributeData,
    ContentCategoryData,
    ElementData,
    ElementKindData,
    EventHandlerData,
    GlobalAttributeData,
    InputTypeData,
)

type InputData = AriaRoleData | AttributeData | ContentCategoryData | ElementData | ElementKindData | EventHandlerData | GlobalAttributeData | InputTypeData
type OutputData = AriaRoleDocs | AriaRoleSpec

logger = logging.getLogger(__name__)

# Sentinel used as the dict key (in place of `scope`) for attributes with no tag restriction.
_ALL_TAGS = 'all'


def dictify(xs: list[Any]) -> dict[str, Any]:
    """Convert a dataclass objects list/generator to a dict with unique keys as the the first field in each object.

    Returns:
        Dict with unique keys
    """
    result = {}

    for x in xs:
        # Get field names and values using dataclasses
        fields = dataclasses.fields(x)
        key_field = fields[0].name
        key = getattr(x, key_field)
        r = dataclasses.asdict(x)
        del r[key_field]  # remove the key field from the value dict

        if key in result:
            # Merge each value with existing entry
            t = result[key]
            for subkey in t:
                match t[subkey]:
                    case str():
                        t[subkey] += '. ' + r[subkey]
                    case set():
                        t[subkey] = t[subkey].union(r[subkey])
                    case list():
                        t[subkey].extend(r[subkey])
                    case _:
                        msg = f"Don't know how to merge type '{type(t[subkey]).__name__}' for '{type(x).__name__}.{subkey}' "
                        raise NotImplementedError(msg)
        else:
            result[key] = r

    return result


def dictify_attributes(attribute_list: list[AttributeData]) -> dict[str, dict[str, Any]]:
    """Convert a list of AttributeData into a dict keyed by name, then by scope (_ALL_TAGS for `scope is None`).

    Returns:
        JSON-serializable dict of HTML attribute data
    """
    result: dict[str, dict[str, Any]] = {}
    for attribute in attribute_list:
        r = dataclasses.asdict(attribute)
        del r['name']
        del r['scope']
        scope_key = _ALL_TAGS if attribute.scope is None else attribute.scope
        by_scope = result.setdefault(attribute.name, {})
        if scope_key in by_scope:
            logger.debug('Duplicate attribute name + scope pair: (%r, %r)', attribute.name, scope_key)
            _dict_merge(by_scope[scope_key], r, concat_fields=('description', 'value_info'))
        else:
            by_scope[scope_key] = r
    return result


def _dict_merge(existing: dict, new: dict, concat_fields: Iterable[str] = ()) -> None:
    """Merge `new` into `existing` in place, for resolving a key collision in dictify()-style output.

    Fields named in `concat_fields` are concatenated (list + list, preserving order and duplicates).
    Every other field keeps its first-seen (`existing`) value; a differing `new` value is discarded
    and logged.
    """
    concat_fields = set(concat_fields)
    for key, value in new.items():
        if key in concat_fields:
            existing[key] += value
        elif existing[key] != value:
            logger.warning('⚠️ Merge conflict for field %r: keeping %r, discarding %r', key, existing[key], value)


def segregate_by_datatype(entries: list[Any], by_datatype: dict[str, set[str]]) -> dict[str, dict[str, list[Any]]]:
    """Split a list of dataclass instances into 'spec' or 'docs' datatype-specific dataclasses.

    The source dataclass's data domain name (as registered in schema.CURATION_MAP) is reused to key
    each datatype's output. The target class for each datatype is resolved from the source class's
    name (its trailing 'Data' stripped, snake_cased, then suffixed with `_{datatype}`, e.g.
    'AriaRoleData' + 'spec' -> 'aria_role_spec') via schema.CLASS_FROM_DOMAIN.

    Each specifier in `by_datatype[datatype]` is either a bare field name (copied from the entry,
    coerced to the target field's declared type: a dict source narrowed to a set keeps its keys
    only, otherwise copied as-is) or a dotted `field.subkey` (extracts `subkey` from each value of
    a `dict[str, dict]`-typed source field into a flat `dict[str, subkey-value]`).

    Returns:
        {datatype: {domain: [instances]}}, one inner list per datatype in `by_datatype`
    """
    if not entries:
        return {datatype: {} for datatype in by_datatype}

    source_cls = type(entries[0])
    domain = next(key for key, (_, cls) in CURATION_MAP.items() if cls is source_cls)
    stem = _stem_from_class_name(source_cls)

    result: dict[str, dict[str, list[Any]]] = {}
    for datatype, field_specs in by_datatype.items():
        target_cls = CLASS_FROM_DOMAIN[f'{stem}_{datatype}']
        result[datatype] = {domain: [_segregate_item_by_datatype(entry, target_cls, field_specs) for entry in entries]}

    return result


def _segregate_item_by_datatype(item: InputData, target_cls: type, field_specs: set[str]) -> OutputData:
    """Build one `target_cls` instance from `item`, using `field_specs` (see segregate_by_datatype()).

    Returns:
        Dataclass

    Raises:
        ValueError: if the item subfield (from a dotted specifier) is not a dict
    """
    target_fields = {f.name: f for f in dataclasses.fields(target_cls)}
    kwargs = {}
    for spec in field_specs:
        if '.' in spec:
            field_name, subkey = spec.split('.', 1)
            source_value = getattr(item, field_name)
            if not isinstance(source_value, dict) or not all(isinstance(v, dict) for v in source_value.values()):
                msg = f"Dotted specifier {spec!r} requires a dict[str, dict] field, got {type(source_value).__name__}"
                raise ValueError(msg)
            kwargs[field_name] = {k: v[subkey] for k, v in source_value.items()}
        else:
            source_value = getattr(item, spec)
            if isinstance(source_value, dict) and get_origin(target_fields[spec].type) is set:
                source_value = set(source_value)
            kwargs[spec] = source_value
    kwargs.setdefault('name', item.name)
    return target_cls(**kwargs)


def _stem_from_class_name(cls: type) -> str:
    """Derive a snake_case stem from a dataclass name, stripping a trailing 'Data' suffix.

    Returns:
        Snake-cased stem, e.g. 'AriaRoleData' -> 'aria_role'
    """
    name = cls.__name__.removesuffix('Data')
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
