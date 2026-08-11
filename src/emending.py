import importlib.util
import logging
from collections.abc import Callable
from pathlib import Path

from config import EMENDATIONS_DIR

logger = logging.getLogger(__name__)

Emendation = Callable[[str, list], bool]


class Emender:
    """Apply targeted, manually-authored transformations to input data."""

    def __init__(self, emendations_dir: Path = EMENDATIONS_DIR) -> None:
        self.emendations_dir = emendations_dir

    def emend(self, hook: str, section: str, data: list) -> None:
        """Load and apply `section`'s `kind` ('input' or 'external') emendations to `data`, in place.

        Emendations are single-use and never cached: each call re-globs and re-imports
        `emendations_dir/section/<section>/<kind>/*.py`, sorted by filename. A missing
        directory means no emendations exist for that section/kind yet and is silently
        skipped. Load or apply failures propagate, since emendations are mandatory once present.
        """
        section_dir = self.emendations_dir / hook

        if not section_dir.is_dir():
            return

        for path in sorted(section_dir.glob('*.py')):
            spec = importlib.util.spec_from_file_location(f'emendation_{path.stem}', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if module.emend(section, data):
                logger.info('🩹 Emendation applied (%s/%s): %s', hook, section, module.description)
