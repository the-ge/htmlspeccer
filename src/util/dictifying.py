import dataclasses
import logging
from collections.abc import Iterable
from typing import Any

from schema import AttributeData

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
                if isinstance(t[subkey], str):
                    t[subkey] += '. ' + r[subkey]
                elif isinstance(t[subkey], set):
                    t[subkey] = t[subkey].union(r[subkey])
                elif isinstance(t[subkey], list):
                    t[subkey].extend(r[subkey])
                else:
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
