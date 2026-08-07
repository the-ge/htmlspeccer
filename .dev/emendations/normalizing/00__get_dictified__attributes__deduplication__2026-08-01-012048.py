import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def emend(section: str, data: list) -> bool:
    """Log each occurrence of a duplicate attribute name (by description and tags). No mutation yet."""
    if section != 'attributes':
        return False

    by_name = defaultdict(list)
    for entry in data:
        by_name[entry.name].append(entry)

    has_fired = False
    for name, entries in by_name.items():
        if len(entries) <= 1:
            continue
        total = len(entries)
        has_fired = True
        for i, entry in enumerate(entries, start=1):
            logger.info(
                '🩹 Duplicate attribute %r (%d/%d): description=%r, tag=%r',
                name, i, total, entry.description, entry.tag,
            )

    return has_fired
