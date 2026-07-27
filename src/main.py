import json
import logging
import shutil
import subprocess  # noqa: S404
from pathlib import Path

import yaml

from config import (
    ATOMIC_DATA_DIR,
    ATOMIC_DATA_MANIFEST,
    DIST_DATA_MANIFEST,
    DIST_JSON_DATA_DIR,
    DIST_ROOT_DIR,
    DIST_YAML_DATA_DIR,
    DUMP_JSON_KWARGS,
    DUMP_YAML_KWARGS,
    LOG_LEVEL,
    PROJECT_ROOT,
    RAW_DATA_MANIFEST,
)
from util import short_path, sort_top_level

logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ---- Licenses (single consumer: this driver) ----
LICENSES_DIR = PROJECT_ROOT / 'licenses'
COPYRIGHT_FILE = LICENSES_DIR / 'COPYRIGHT'  # static, copied verbatim to DIST_ROOT_DIR/COPYRIGHT
DIST_COPYRIGHT_FILE = DIST_ROOT_DIR / 'COPYRIGHT'
W3C_LICENSE_FILE = LICENSES_DIR / 'W3C-Document-License.html'  # static, copied verbatim alongside COPYRIGHT
DIST_W3C_LICENSE_FILE = DIST_ROOT_DIR / 'W3C-Document-License.html'


def copy_licenses() -> None:
    """Copy the static licenses/NOTICE file to dist/NOTICE, unmodified."""
    DIST_ROOT_DIR.mkdir(parents=True, exist_ok=True)
    DIST_COPYRIGHT_FILE.write_text(COPYRIGHT_FILE.read_text(encoding='utf-8'), encoding='utf-8')
    DIST_W3C_LICENSE_FILE.write_text(W3C_LICENSE_FILE.read_text(encoding='utf-8'), encoding='utf-8')


def read_data_domains() -> dict[str, object]:
    """Load categories produced by the normalize stage from ATOMIC_DATA_DIR, using its manifest as the index."""
    manifest = json.loads(ATOMIC_DATA_MANIFEST.read_text(encoding='utf-8'))
    results = {}
    for category in manifest:
        path = ATOMIC_DATA_DIR / f'{category}.json'
        results[category] = json.loads(path.read_text(encoding='utf-8'))
    return results


def get_repo_version() -> dict[str, str]:
    """Return the repo's official_release (nearest tag, empty if none exist),
    current_tag (nearest tag plus distance/dirty suffix), and current_commit_id (full HEAD SHA).
    """
    git = shutil.which('git')
    if git is None:
        msg = 'git executable not found on PATH'
        raise FileNotFoundError(msg)

    try:
        official_release = subprocess.run(  # noqa: S603
            [git, 'describe', '--tags', '--abbrev=0'],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        official_release = ''

    current_tag = subprocess.run(  # noqa: S603
        [git, 'describe', '--tags', '--always', '--dirty'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    current_commit_id = subprocess.run(  # noqa: S603
        [git, 'rev-parse', 'HEAD'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    return {
        'generator_release': official_release,
        'generator_tag': current_tag,
        'generator_commit_id': current_commit_id,
    }


def build_manifest(counts: dict[str, int]) -> dict:
    """Combine the raw manifest written by make into RAW_DATA_DIR with category counts and repository version info."""
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


def write_output(data: dict, path: Path) -> None:
    """Write the aggregate result for one category as JSON. Data is already JSON-serializable."""
    if isinstance(data, dict):
        data = sort_top_level(data)
    path.write_text(
        json.dumps(data, **DUMP_JSON_KWARGS),
        encoding='utf-8',
    )


def write_yaml_file(data: list, path: Path) -> None:
    """Write a list category (global_attributes) to a single YAML file."""
    path.write_text(
        yaml.dump(data, **DUMP_YAML_KWARGS),
        encoding='utf-8',
    )


def write_yaml_items(data: dict, dir_path: Path) -> int:
    """Write each item as its own YAML file, named after its key, e.g. dir_path/abbr.yaml.
    Returns the number of files written.
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


def main() -> None:
    # Prepare output directories
    DIST_JSON_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DIST_YAML_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Assemble from the atomic data layer; this stage only formats and writes.
    results = read_data_domains()

    # Write each result
    counts = {}
    for name, data in results.items():
        output_path = DIST_JSON_DATA_DIR / f'{name}.json'
        write_output(data, output_path)
        logger.info('📦 Published %s', short_path(output_path))

        if isinstance(data, dict):
            yaml_subdir = DIST_YAML_DATA_DIR / name
            item_count = write_yaml_items(data, yaml_subdir)
            counts[name] = item_count
            logger.info('📦 Published %s individual YAML files to %s', item_count, short_path(yaml_subdir))
        else:
            yaml_path = DIST_YAML_DATA_DIR / f'{name}.yaml'
            write_yaml_file(data, yaml_path)
            counts[name] = len(data)
            logger.info('📦 Published %s', short_path(yaml_path))

    # Static legal notice, copied once — no per-file duplication
    copy_licenses()
    logger.info('📝 Wrote %s, %s', short_path(DIST_COPYRIGHT_FILE), short_path(DIST_W3C_LICENSE_FILE))

    # Single manifest capturing per-source fetch times, generation time, and item counts
    manifest = build_manifest(counts)
    DIST_DATA_MANIFEST.write_text(json.dumps(manifest, **DUMP_JSON_KWARGS), encoding='utf-8')
    logger.info('📝 Wrote %s', short_path(DIST_DATA_MANIFEST))


if __name__ == '__main__':
    main()
