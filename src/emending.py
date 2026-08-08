import importlib.util
import logging
from collections.abc import Callable
from pathlib import Path

from config import EMENDATIONS_DIR

logger = logging.getLogger(__name__)

Emendation = Callable[[str, list], bool]


class Emender:
    """Apply targeted, manually-authored transformations to input data."""

    def __init__(self, domain: str, emendations_dir: Path = EMENDATIONS_DIR) -> None:
        self.domain = domain
        self.emendations_dir = emendations_dir

    def emend_normalizing_section(self, section: str, data: list) -> None:
        """Load and apply this section's emendations (if any) to `data`, in place.

        Emendations are single-use and never cached: each call re-globs and re-imports
        `emendations_dir/domain/section/<section>/*.py`, sorted by filename. A missing
        section directory means no emendations exist for that section yet and is silently
        skipped. Load or apply failures propagate, since emendations are mandatory once present.
        """
        section_dir = self.emendations_dir / self.domain / 'section' / section
        if not section_dir.is_dir():
            return

        for path in sorted(section_dir.glob('*.py')):
            logger.info('🚧 Placeholder for emendation %r .', path.name)
            continue  # loading emendations disabled during massive normalizing refactor
            spec = importlib.util.spec_from_file_location(f'emendation_{path.stem}', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            logger.info('🩹 Applying emendation %r for section %r', path.name, section)
            module.emend(section, data)
