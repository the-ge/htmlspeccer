import dataclasses
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

from config import DUMP_NDJSON_KWARGS, PROJECT_ROOT

R = TypeVar('R')
T = TypeVar('T')
JSONType: TypeAlias = bool | int | float | str | list['JSONType'] | dict[str, 'JSONType'] | None


# Base URL for relative spec links
_SPEC_BASE_URL = 'https://html.spec.whatwg.org/multipage/'


def dictify(xs: list[Any]) -> dict[str, Any]:
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


def parse_section(dir_path: Path, page: str, section: str, cls: type[T], parser: Callable[..., R], **kwargs: object) -> R:
    """Load the terse (page, section) NDJSON file from dir_path and run its rows through `parser`.
    Returns whatever `parser` returns (a generator, list, or set, depending on the parser).
    """
    rows = read_ndjson(dir_path / f'{page}.{section}.ndjson', cls)
    return parser(rows, **kwargs)


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
    """Format a path relative to PROJECT_ROOT for logging, or as an absolute path if outside it."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def deduplicate(items: Iterable[str]) -> list[str]:
    """Deduplicate items, preserving first-seen order."""
    return list(dict.fromkeys(items))


def normalize_url(url: str) -> str:
    """Prefix relative spec URLs with the multipage base."""
    return url if url.startswith('https://') else _SPEC_BASE_URL + url
