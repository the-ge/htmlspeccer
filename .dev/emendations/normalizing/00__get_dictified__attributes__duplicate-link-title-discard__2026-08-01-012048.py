import logging

logger = logging.getLogger(__name__)


def emend(section: str, data: list) -> bool:
    """Resolve two attribute data rows yielding a title/link entry; keep first, drop the redundant second.

    Issue location: https://html.spec.whatwg.org/multipage/indices.html#attributes-3:attr-link-title.
    Explanation: the next row also containing a `link` tag for the `title` attribute will be dropped.
    """
    if section != 'attributes':
        return False

    entries = [e for e in data if e.name == 'title' and e.tag == 'link']
    if len(entries) <= 1:
        return False

    for entry in entries[1:]:
        data.remove(entry)
        logger.info('🩹 Emended duplicate %r/%r pair: dropped redundant entries', 'title', 'link')

    return True
