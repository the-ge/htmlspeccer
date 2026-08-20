import json
import logging
from pathlib import Path

from config import (
    DIST_JSON_DATA_DIR,
    DIST_YAML_DATA_DIR,
)
from publishing.output import write_domain
from schema import CLASS_FROM_DOMAIN, DATA_MAP
from util.dictifying import dictify, dictify_attributes, segregate_by_datatype
from util.serializing import make_serializable, read_ndjson

logger = logging.getLogger(__name__)


class Publisher:
    """Publish stage: curated entity NDJSON -> grouped, dictified dist/ JSON + YAML."""

    def __init__(self, input_data_dir: Path, manifest_path: Path) -> None:
        self.input_data_dir = input_data_dir
        self.manifest_path = manifest_path

    def read_data_domains(self) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
        """Load each data domain's entities from CURATED_DATA_DIR, group into the published shape.

        Uses the data domain's manifest entry as the index. Entities are grouped by name (and by scope,
        for attributes) into the published shape. A data domain registered in schema.DATA_MAP with a
        'spec' and/or 'docs' entry is further segregated by property type into those datatypes rather
        than added to the flat `results` dict.

        Returns:
            (results, segregated_results): `results` is a JSON-serializable dict of unsegregated data domains;
            `segregated_results` is {domain: {datatype: JSON-serializable dict}} for segregated data domains
            (sets become sorted lists in both)
        """
        manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        results = {}
        segregated_results = {}
        for domain in manifest:
            data_map_entry = DATA_MAP.get(domain)
            cls = data_map_entry['source_cls'] if data_map_entry is not None else CLASS_FROM_DOMAIN[domain]
            entries = read_ndjson(self.input_data_dir / f'{domain}.ndjson', cls)

            if data_map_entry is not None and ('spec' in data_map_entry or 'docs' in data_map_entry):
                segregated_domains = segregate_by_datatype(entries)
                segregated_results[domain] = {
                    datatype: make_serializable(dictify(domains[domain]))
                    for datatype, domains in segregated_domains.items()
                }
                continue

            dictifier = dictify_attributes if domain == 'attributes' else dictify
            results[domain] = make_serializable(dictifier(entries))
        return results, segregated_results

    def publish(self) -> dict[str, int]:
        """Write dist JSON+YAML for each domain, segregated or not.

        Returns:
            Per-domain item counts (manifest entries); segregated data domains get two entries each,
            keyed f'{domain}_{datatype}' (e.g. 'aria_roles_spec', 'aria_roles_docs')
        """
        DIST_JSON_DATA_DIR.mkdir(parents=True, exist_ok=True)
        DIST_YAML_DATA_DIR.mkdir(parents=True, exist_ok=True)

        results, segregated_results = self.read_data_domains()
        counts = {}

        for name, data in results.items():
            counts[name] = write_domain(name, data, DIST_JSON_DATA_DIR, DIST_YAML_DATA_DIR)

        for domain, by_datatype in segregated_results.items():
            for datatype, data in by_datatype.items():
                json_dir = DIST_JSON_DATA_DIR / datatype
                yaml_dir = DIST_YAML_DATA_DIR / datatype
                json_dir.mkdir(parents=True, exist_ok=True)
                yaml_dir.mkdir(parents=True, exist_ok=True)
                counts[f'{domain}_{datatype}'] = write_domain(domain, data, json_dir, yaml_dir)

        return counts
