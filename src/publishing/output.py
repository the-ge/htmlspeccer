import json
import logging
from pathlib import Path

import yaml

from config import (
    DUMP_JSON_KWARGS,
    DUMP_YAML_KWARGS,
    RAW_DATA_MANIFEST,
)
from publishing.version import get_repo_version
from util.transforming import short_path, sort_top_level

logger = logging.getLogger(__name__)


def build_manifest(counts: dict[str, int]) -> dict:
    """Combine the raw manifest written by make into RAW_DATA_DIR with category counts and repository version info.

    Returns:
        Dict containing input and output data stats
    """
    sources = {}
    if not RAW_DATA_MANIFEST.exists():
        logger.error('❌ File missing: %s; did you run `make -C acquire` first?', short_path(RAW_DATA_MANIFEST))
    else:
        try:
            sources = json.loads(RAW_DATA_MANIFEST.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            logger.exception('❌ Failed to parse %s', short_path(RAW_DATA_MANIFEST))

    return {
        'sources': sources,
        'counts': counts,
        **get_repo_version(),
    }


def write_domain(name: str, data: dict | list, json_dir: Path, yaml_dir: Path) -> int:
    """Write one domain's dist JSON (and per-item or single YAML) into `json_dir`/`yaml_dir`.

    Returns:
        Item count for the manifest
    """
    output_path = json_dir / f'{name}.json'
    _write_json_file(data, output_path)
    logger.info('📦 Published %s', short_path(output_path))

    if isinstance(data, dict):
        yaml_subdir = yaml_dir / name
        item_count = _write_yaml_files(data, yaml_subdir)
        logger.info('📦 Published %s individual YAML files to %s', item_count, short_path(yaml_subdir))
    else:
        yaml_path = yaml_dir / f'{name}.yaml'
        _write_yaml_file(data, yaml_path)
        item_count = len(data)
        logger.info('📦 Published %s', short_path(yaml_path))

    return item_count


def _write_json_file(data: dict, path: Path) -> None:
    """Write the aggregate result for one category as JSON. Data is already JSON-serializable."""
    if isinstance(data, dict):
        data = sort_top_level(data)
    path.write_text(
        json.dumps(data, **DUMP_JSON_KWARGS),
        encoding='utf-8',
    )


def _write_yaml_file(data: list, path: Path) -> None:
    """Write a list category (global_attributes) to a single YAML file."""
    path.write_text(
        yaml.dump(data, **DUMP_YAML_KWARGS),
        encoding='utf-8',
    )


def _write_yaml_files(data: dict, dir_path: Path) -> int:
    """Write each item as its own YAML file, named after its key, e.g. dir_path/abbr.yaml.

    Returns:
        Written files count
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    count = 0
    for key, value in data.items():
        filename = key.replace('/', '_')  # guard against path traversal via item keys
        (dir_path / f'{filename}.yaml').write_text(
            yaml.dump(value, **DUMP_YAML_KWARGS),
            encoding='utf-8',
        )
        count += 1
    return count
