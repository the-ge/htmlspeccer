import logging
from collections.abc import Iterable
from pathlib import Path

from slugify import slugify

from config import PROJECT_ROOT

logger = logging.getLogger(__name__)


def deduplicate(items: Iterable[str]) -> list[str]:
    """Deduplicate items, preserving first-seen order.

    Returns:
        Deduplicated input Iterable
    """
    return list(dict.fromkeys(items))


def normalize_url(url: str, base: str) -> str:
    """Prefix relative spec URLs with the multipage base.

    Returns:
        Full URL
    """
    return url if url.startswith('https://') else base + url


def short_path(path: Path) -> str:
    """Format a path relative to PROJECT_ROOT for logging, or as an absolute path if outside it.

    Returns:
        Path relative to PROJECT_ROOT
    """
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def slugify_by_vocabulary(text: str, slugified: dict[str, str]) -> str:
    """Slugify text, first by looking into the provided vocabulary, then via the slugify module.

    Returns:
        The slugified text
    """
    if text in slugified:
        return slugified[text]

    logger.warning("⚠️ not found in vocabulary: '%s'", text)
    return slugify(text)


def sort_top_level(d: dict) -> dict:
    """Sort the input dict by the top-level keys (inner key order is left untouched).

    Returns:
        New dict with the top-level keys sorted
    """
    return dict(sorted(d.items()))
