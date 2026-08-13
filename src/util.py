import dataclasses
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeAlias, TypeVar, get_args, get_origin

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


def dict_to_dataclass(cls: type[T], d: dict) -> T:
    """Reconstruct a `cls` instance from a plain dict, restoring set- and tuple-list-typed fields.

    Set-typed fields (default_factory produces a set) are restored from their JSON list form. Fields
    annotated `list[tuple[...]]` are restored from JSON's list-of-lists form (JSON has no tuple type):
    each inner list is converted back to a tuple.

    Returns:
        Dataclass object
    """
    kwargs = dict(d)
    for f in dataclasses.fields(cls):
        if f.default_factory is not dataclasses.MISSING and isinstance(f.default_factory(), set):
            kwargs[f.name] = set(kwargs[f.name])
        elif get_origin(f.type) is list and get_origin(next(iter(get_args(f.type)), None)) is tuple:
            kwargs[f.name] = [tuple(x) for x in kwargs[f.name]]
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
