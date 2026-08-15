import json
import logging

from config import (
    CURATED_DATA_CACHE_DIR,
    CURATED_DATA_DIR,
    CURATED_DATA_MANIFEST,
    DUMP_JSON_KWARGS,
    LOG_LEVEL,
    RAW_DATA_DIR,
)
from curating.handler import Curator
from util.serializing import write_ndjson
from util.transforming import short_path

logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def write_curated_data(results: dict) -> None:
    """Write each section's entities to CURATED_DATA_DIR as its own NDJSON file."""
    for section, entries in results.items():
        path = CURATED_DATA_DIR / f'{section}.ndjson'
        count = write_ndjson(path, entries)
        logger.info('🔀 Curated %s (%s -> %s)', count, section, path.name)


def main() -> None:
    CURATED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    curator = Curator(raw_data_dir=RAW_DATA_DIR, cache_dir=CURATED_DATA_CACHE_DIR)
    results, manifest = curator.get_all()
    write_curated_data(results)
    CURATED_DATA_MANIFEST.write_text(
        json.dumps(manifest, **DUMP_JSON_KWARGS),
        encoding='utf-8',
    )
    logger.info('📝 Wrote %s', short_path(CURATED_DATA_MANIFEST))


if __name__ == '__main__':
    main()
