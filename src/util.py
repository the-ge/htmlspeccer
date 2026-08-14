import dataclasses
import json
import logging
import types
from collections.abc import Iterable
from itertools import starmap
from pathlib import Path
from typing import Any, TypeAlias, TypeVar, Union, get_args, get_origin

from config import DUMP_NDJSON_KWARGS, PROJECT_ROOT

logger = logging.getLogger(__name__)

R = TypeVar('R')
T = TypeVar('T')
JSONType: TypeAlias = bool | int | float | str | list['JSONType'] | dict[str, 'JSONType'] | None


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
                    msg = "Don't know how to merge type %s for key %s"
                    raise NotImplementedError(msg, type(t[subkey]).__name__, subkey)
        else:
            result[key] = r

    return result


def dict_merge(existing: dict, new: dict, concat_fields: Iterable[str] = ()) -> None:
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


def sort_top_level(d: dict) -> dict:
    """Sort the input dict by the top-level keys (inner key order is left untouched).

    Returns:
        New dict with the top-level keys sorted
    """
    return dict(sorted(d.items()))


def make_serializable(obj: object) -> JSONType:
    """Recursively convert sets, lists, and dicts into a JSON-serializable form.

    Returns:
        JSON-serializable form of the input object
    """
    if isinstance(obj, set):
        return sorted(make_serializable(v) for v in obj)
    if isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    return obj


def dataclass_to_dict(obj: T) -> dict:
    """Convert a dataclass instance to a JSON-serializable dict (set fields become sorted lists).

    Returns:
        JSON-serializable dict
    """
    return make_serializable(dataclasses.asdict(obj))


def _unwrap_optional(tp: Any) -> Any:
    """Return X from `X | None` (or `Optional[X]`), unchanged if `tp` isn't such a two-member union.

    Returns:
        The non-None union member, or `tp` itself if it isn't an Optional-shaped union
    """
    if get_origin(tp) in {types.UnionType, Union}:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def _tuple_list_item_type(tp: Any) -> Any:
    """Return the tuple item type if `tp` (after unwrapping an Optional union) is list[tuple[...]].

    Returns:
        The tuple's parametrized type, or None if `tp` isn't a list-of-tuples shape
    """
    tp = _unwrap_optional(tp)
    if get_origin(tp) is not list:
        return None
    item_type = next(iter(get_args(tp)), None)
    return item_type if get_origin(item_type) is tuple else None


def _restore_tuple_lists(value: list | str | None, tp: Any) -> Any:
    """Recursively restore a list[tuple[...]] shape (optionally `| None`) from JSON's list-of-lists form.

    Each tuple element is itself recursively restored, so a nested shape like
    list[tuple[str, str, list[tuple[str, str]]]] round-trips correctly, not just one level deep.

    Returns:
        `value` with list[tuple[...]] shapes converted back to tuples; unchanged if `value` is None or
        `tp` isn't a list-of-tuples shape
    """
    if value is None:
        return None
    item_type = _tuple_list_item_type(tp)
    if item_type is None:
        return value
    elem_types = get_args(item_type)
    return [tuple(starmap(_restore_tuple_lists, zip(item, elem_types, strict=True))) for item in value]


def dict_to_dataclass(cls: type[T], d: dict) -> T:
    """Reconstruct a `cls` instance from a plain dict, restoring set- and tuple-list-typed fields.

    Set-typed fields (default_factory produces a set) are restored from their JSON list form. Fields
    annotated `list[tuple[...]]`, optionally wrapped in `| None`, are restored from JSON's list-of-lists
    form (JSON has no tuple type), recursively, so nested list[tuple[...]] shapes round-trip correctly.

    Returns:
        Dataclass object
    """
    kwargs = dict(d)
    for f in dataclasses.fields(cls):
        if f.default_factory is not dataclasses.MISSING and isinstance(f.default_factory(), set):
            kwargs[f.name] = set(kwargs[f.name])
        elif _tuple_list_item_type(f.type) is not None:
            kwargs[f.name] = _restore_tuple_lists(kwargs[f.name], f.type)
    return cls(**kwargs)


def write_ndjson(path: Path, rows: Iterable[Any]) -> int:
    """Write dataclass instances to path, one JSON object per line.

    Returns:
        Written rows count
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open('w', encoding='utf-8') as fp:
        for row in rows:
            fp.write(json.dumps(dataclass_to_dict(row), **DUMP_NDJSON_KWARGS))
            fp.write('\n')
            count += 1
    return count


def read_ndjson(path: Path, cls: type[T]) -> list[T]:
    """Read an NDJSON file back into a list of `cls` instances.

    Returns:
        List of dataclass objects

    Raises:
        FileNotFoundError if path doesn't exist.
    """
    with path.open('r', encoding='utf-8') as fp:
        return [dict_to_dataclass(cls, json.loads(line)) for line in fp if line.strip()]


def short_path(path: Path) -> str:
    """Format a path relative to PROJECT_ROOT for logging, or as an absolute path if outside it.

    Returns:
        Path relative to PROJECT_ROOT
    """
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def deduplicate(items: Iterable[str]) -> list[str]:
    """Deduplicate items, preserving first-seen order.

    Returns:
        Deduplicated input Iterable
    """
    return list(dict.fromkeys(items))


def normalize_url(url: str, base: str) -> str:
    """Prefix relative spec URLs with the multipage base.

    Returns:
        Full URL
    """
    return url if url.startswith('https://') else base + url
