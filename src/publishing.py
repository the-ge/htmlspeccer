import json
import logging
import shutil
import subprocess  # noqa: S404
from hashlib import sha256
from pathlib import Path

import yaml

from config import (
    DIST_HASH_FILE,
    DIST_JSON_DATA_DIR,
    DIST_ROOT_DIR,
    DIST_YAML_DATA_DIR,
    DUMP_JSON_KWARGS,
    DUMP_YAML_KWARGS,
    PROJECT_ROOT,
    RAW_DATA_MANIFEST,
)
from curating import SECTION_SOURCES, dictify_attributes
from util import dictify, make_serializable, read_ndjson, short_path, sort_top_level

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


def hash_compute(dirs: list[Path]) -> str:
    """Hash file paths and contents across dirs, sorted for determinism.

    Used to detect real data changes between publish runs, since DIST_DATA_MANIFEST always changes
    (source timestamps, git version info), even when the actual published data has not.

    Returns:
        Hash computed for the content and file paths in the input path
    """
    digest = sha256()
    for d in dirs:
        for path in sorted(d.rglob('*')):
            if path.is_file():
                digest.update(str(path.relative_to(d)).encode('utf-8'))
                digest.update(path.read_bytes())
    return digest.hexdigest()


def hash_update(dirs: list[Path]) -> bool:
    """Compare a fresh content hash of dirs against the stored stamp; rewrite the stamp only if it changed.

    Returns:
        True if the content changed since the last run, False if not.
    """
    new_hash = hash_compute(dirs)
    old_hash = DIST_HASH_FILE.read_text(encoding='utf-8').strip() if DIST_HASH_FILE.exists() else None
    if new_hash == old_hash:
        return False
    DIST_HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    DIST_HASH_FILE.write_text(new_hash, encoding='utf-8')
    return True


def get_repo_version() -> dict[str, str]:
    """Get repo version information.

    Returns:
        - official_release (nearest repo tag, empty if none exist),
        - current_tag (nearest repo tag plus distance/dirty suffix), and
        - current_commit_id (full HEAD SHA).

    Raises:
        FileNotFoundError: if `git` not found
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


class Publisher:
    """Publish stage: curated entity NDJSON -> grouped, dictified dist/ JSON + YAML."""

    def __init__(self, input_data_dir: Path, manifest_path: Path) -> None:
        self.input_data_dir = input_data_dir
        self.manifest_path = manifest_path

    def read_data_domains(self) -> dict[str, dict]:
        """Load each section's entities from CURATED_DATA_DIR.

        Is using its manifest as the index, and group them by name (and by tag, for attributes)
        into the published shape.

        Returns:
            JSON-serializable dict (sets become sorted lists)
        """
        manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        results = {}
        for section in manifest['output']:
            cls = SECTION_SOURCES[section][1]
            entries = read_ndjson(self.input_data_dir / f'{section}.ndjson', cls)
            dictifier = dictify_attributes if section == 'attributes' else dictify
            results[section] = make_serializable(dictifier(entries))
        return results

    def publish(self) -> dict[str, int]:
        """Write dist JSON+YAML for each domain.

        Returns:
            Per-domain item counts (manifest entries)
        """
        DIST_JSON_DATA_DIR.mkdir(parents=True, exist_ok=True)
        DIST_YAML_DATA_DIR.mkdir(parents=True, exist_ok=True)

        results = self.read_data_domains()
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

        return counts
