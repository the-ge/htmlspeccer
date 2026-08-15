import json
import logging
from pathlib import Path

from config import (
    DIST_JSON_DATA_DIR,
    DIST_YAML_DATA_DIR,
)
from publishing.output import write_json_file, write_yaml_file, write_yaml_files
from schema import SECTION_SOURCES
from util.dictifying import dictify, dictify_attributes
from util.serializing import make_serializable, read_ndjson
from util.transforming import short_path

logger = logging.getLogger(__name__)


class Publisher:
    """Publish stage: curated entity NDJSON -> grouped, dictified dist/ JSON + YAML."""

    def __init__(self, input_data_dir: Path, manifest_path: Path) -> None:
        self.input_data_dir = input_data_dir
        self.manifest_path = manifest_path

    def read_data_domains(self) -> dict[str, dict]:
        """Load each section's entities from CURATED_DATA_DIR.

        Is using its manifest as the index, and group them by name (and by scope, for attributes)
        into the published shape.

        Returns:
            JSON-serializable dict (sets become sorted lists)
        """
        manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        results = {}
        for section in manifest:
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
            write_json_file(data, output_path)
            logger.info('📦 Published %s', short_path(output_path))

            if isinstance(data, dict):
                yaml_subdir = DIST_YAML_DATA_DIR / name
                item_count = write_yaml_files(data, yaml_subdir)
                counts[name] = item_count
                logger.info('📦 Published %s individual YAML files to %s', item_count, short_path(yaml_subdir))
            else:
                yaml_path = DIST_YAML_DATA_DIR / f'{name}.yaml'
                write_yaml_file(data, yaml_path)
                counts[name] = len(data)
                logger.info('📦 Published %s', short_path(yaml_path))

        return counts
