import json
import logging

from config import (
    DUMP_JSON_KWARGS,
    LOG_LEVEL,
    PAGE_SECTIONS,
    RAW_DATA_DIR,
    TERSE_DATA_DIR,
    TERSE_DATA_MANIFEST,
)
from filtering import Sieve
from util import short_path

logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def main() -> None:
    TERSE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    sieve = Sieve(raw_data_dir=RAW_DATA_DIR, terse_data_dir=TERSE_DATA_DIR)
    sections = sieve.filter_all(PAGE_SECTIONS)

    TERSE_DATA_MANIFEST.write_text(
        json.dumps(sections, **DUMP_JSON_KWARGS),
        encoding='utf-8',
    )
    logger.info('📝 Wrote %s', short_path(TERSE_DATA_MANIFEST))


if __name__ == '__main__':
    main()
