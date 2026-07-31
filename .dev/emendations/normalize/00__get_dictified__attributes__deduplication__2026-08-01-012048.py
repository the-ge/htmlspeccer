import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def emend(section: str, data: list) -> bool:
    """Log each occurrence of a duplicate attribute name (by description and tag_scope). No mutation yet."""
    if section != 'attributes':
        return True

    by_name = defaultdict(list)
    for entry in data:
        by_name[entry.name].append(entry)

    for name, entries in by_name.items():
        if len(entries) < 2:
            continue
        total = len(entries)
        for i, entry in enumerate(entries, start=1):
            logger.info(
                '🩹 Duplicate attribute %r (%d/%d): description=%r, tag_scope=%r',
                name, i, total, entry.description, entry.tag_scope,
            )

    return True
