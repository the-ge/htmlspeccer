import json
import logging

from config import (
    DUMP_JSON_KWARGS,
    LOG_LEVEL,
    NORMALIZED_DATA_CACHE_DIR,
    NORMALIZED_DATA_DIR,
    NORMALIZED_DATA_MANIFEST,
    RAW_DATA_DIR,
)
from normalizing import Normalizer
from util import short_path, write_ndjson

logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def write_normalized_data(results: dict) -> None:
    """Write each section's entities to NORMALIZED_DATA_DIR as its own NDJSON file."""
    for section, entries in results.items():
        path = NORMALIZED_DATA_DIR / f'{section}.ndjson'
        count = write_ndjson(path, entries)
        logger.info('🔀 Normalized %s (%s -> %s)', count, section, path.name)


def main() -> None:
    NORMALIZED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    normalizer = Normalizer(raw_data_dir=RAW_DATA_DIR, cache_dir=NORMALIZED_DATA_CACHE_DIR)
    results, manifest = normalizer.get_all()
    write_normalized_data(results)
    NORMALIZED_DATA_MANIFEST.write_text(
        json.dumps(manifest, **DUMP_JSON_KWARGS),
        encoding='utf-8',
    )
    logger.info('📝 Wrote %s', short_path(NORMALIZED_DATA_MANIFEST))


if __name__ == '__main__':
    main()
