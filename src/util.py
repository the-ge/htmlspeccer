import dataclasses
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

from config import DUMP_NDJSON_KWARGS, PROJECT_ROOT

T = TypeVar('T')
JSONType: TypeAlias = bool | int | float | str | list['JSONType'] | dict[str, 'JSONType'] | None


def dictify(xs: list[Any], *, merge: bool) -> dict[str, Any]:
    """Convert a dataclass objects list/generator to a dict with unique keys as the the first field in each object."""
    result = {}

    for x in xs:
        # Get field names and values using dataclasses
        fields = dataclasses.fields(x)
        key_field = fields[0].name
        key = getattr(x, key_field)
        r = dataclasses.asdict(x)
        del r[key_field]  # remove the key field from the value dict

        if key in result:
            # Existing entry
            if merge:
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
                # Create a linked-list
                tail = key
                count = 2
                while result[tail].get('next'):
                    tail = result[tail].get('next')
                    count += 1
                newkey = f'{key}({count})'
                result[tail]['next'] = newkey
                result[newkey] = r
        else:
            result[key] = r

    return result


def sort_top_level(d: dict) -> dict:
    """Return a new dict with only the top-level keys sorted; inner key order is left untouched."""
    return dict(sorted(d.items()))


def write_ndjson(path: Path, rows: Iterable[Any]) -> int:
    """Write dataclass instances to path, one JSON object per line. Return the number of rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open('w', encoding='utf-8') as fp:
        for row in rows:
            fp.write(json.dumps(dataclasses.asdict(row), **DUMP_NDJSON_KWARGS))
            fp.write('\n')
            count += 1
    return count


def read_ndjson(path: Path, cls: type[T]) -> list[T]:
    """Read an NDJSON file back into a list of `cls` instances. Return a list of JSON objects. Raises FileNotFoundError if path doesn't exist."""
    with path.open('r', encoding='utf-8') as fp:
        return [cls(**json.loads(line)) for line in fp if line.strip()]


def make_serializable(obj: object) -> JSONType:
    """Recursively convert sets, lists, and dicts into a JSON serializable form."""
    if isinstance(obj, set):
        return sorted(make_serializable(v) for v in obj)
    if isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    return obj


def short_path(path: Path) -> str:
    """Format a path relative to PROJECT_ROOT for logging."""
    return str(path.relative_to(PROJECT_ROOT))
