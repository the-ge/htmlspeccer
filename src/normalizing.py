import json
import logging

from config import (
    ATOMIC_DATA_CACHE_DIR,
    ATOMIC_DATA_DIR,
    ATOMIC_DATA_MANIFEST,
    DUMP_JSON_KWARGS,
    LOG_LEVEL,
    TERSE_DATA_DIR,
)
from normalizing_engine import Normalizer
from util import make_serializable, short_path, sort_top_level

logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def write_data_domains(results: dict) -> None:
    """Write each data domain result to ATOMIC_DATA_DIR as its own JSON file."""
    for category, data in results.items():
        path = ATOMIC_DATA_DIR / f'{category}.json'
        serializable = make_serializable(data)
        if isinstance(serializable, dict):
            serializable = sort_top_level(serializable)
        path.write_text(json.dumps(serializable, **DUMP_JSON_KWARGS), encoding='utf-8')
        logger.info('🔀 Normalized %s (%s -> %s)', len(data), category, path.name)


def main() -> None:
    ATOMIC_DATA_DIR.mkdir(parents=True, exist_ok=True)

    normalizer = Normalizer(terse_data_dir=TERSE_DATA_DIR, cache_dir=ATOMIC_DATA_CACHE_DIR)
    results, manifest = normalizer.get_all()
    write_data_domains(results)
    ATOMIC_DATA_MANIFEST.write_text(
        json.dumps(manifest, **DUMP_JSON_KWARGS),
        encoding='utf-8',
    )
    logger.info('📝 Wrote %s', short_path(ATOMIC_DATA_MANIFEST))


if __name__ == '__main__':
    main()
