import dataclasses
import json
import types
from collections.abc import Iterable
from itertools import starmap
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from config import DUMP_NDJSON_KWARGS

type JSONType = bool | int | float | str | list[JSONType] | dict[str, JSONType] | None


def dataclass_to_dict[T](obj: T) -> dict:
    """Convert a dataclass instance to a JSON-serializable dict (set fields become sorted lists).

    Returns:
        JSON-serializable dict
    """
    return make_serializable(dataclasses.asdict(obj))


def dict_to_dataclass[T](cls: type[T], d: dict) -> T:
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


def read_ndjson[T](path: Path, cls: type[T]) -> list[T]:
    """Read an NDJSON file back into a list of `cls` instances.

    Returns:
        List of dataclass objects

    Raises:
        FileNotFoundError if path doesn't exist.
    """
    with path.open('r', encoding='utf-8') as fp:
        return [dict_to_dataclass(cls, json.loads(line)) for line in fp if line.strip()]


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


def _restore_tuple_lists(value: list | str | None, tp: Any) -> Any:  # noqa: ANN401 (@todo tighten types)
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


def _tuple_list_item_type(tp: Any) -> Any:  # noqa: ANN401 (@todo tighten types)
    """Return the tuple item type if `tp` (after unwrapping an Optional union) is list[tuple[...]].

    Returns:
        The tuple's parametrized type, or None if `tp` isn't a list-of-tuples shape
    """
    tp = _unwrap_optional(tp)
    if get_origin(tp) is not list:
        return None
    item_type = next(iter(get_args(tp)), None)
    return item_type if get_origin(item_type) is tuple else None


def _unwrap_optional(tp: Any) -> Any:  # noqa: ANN401 (@todo tighten types)
    """Return X from `X | None` (or `Optional[X]`), unchanged if `tp` isn't such a two-member union.

    Returns:
        The non-None union member, or `tp` itself if it isn't an Optional-shaped union
    """
    if get_origin(tp) in {types.UnionType, Union}:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp
