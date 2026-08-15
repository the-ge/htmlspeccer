import json
import logging

from config import (
    CURATED_DATA_DIR,
    CURATED_DATA_MANIFEST,
    DIST_DATA_MANIFEST,
    DIST_JSON_DATA_DIR,
    DIST_YAML_DATA_DIR,
    DUMP_JSON_KWARGS,
    LOG_LEVEL,
)
from publishing.handler import Publisher
from publishing.hash import hash_update
from publishing.license import DIST_COPYRIGHT_FILE, DIST_W3C_LICENSE_FILE, copy_licenses
from publishing.output import build_manifest
from util.transforming import short_path

logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def main() -> None:
    publisher = Publisher(input_data_dir=CURATED_DATA_DIR, manifest_path=CURATED_DATA_MANIFEST)
    counts = publisher.publish()

    if not hash_update([DIST_JSON_DATA_DIR, DIST_YAML_DATA_DIR]):
        return

    # Static legal notice, copied once — no per-file duplication
    copy_licenses()
    logger.info('📝 Wrote %s, %s', short_path(DIST_COPYRIGHT_FILE), short_path(DIST_W3C_LICENSE_FILE))

    # Single manifest capturing per-source fetch times, generation time, and item counts
    manifest = build_manifest(counts)
    DIST_DATA_MANIFEST.write_text(json.dumps(manifest, **DUMP_JSON_KWARGS), encoding='utf-8')
    logger.info('📝 Wrote %s', short_path(DIST_DATA_MANIFEST))


if __name__ == '__main__':
    main()
