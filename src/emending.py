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

    def emend_normalizing_section_input(self, section: str, data: list) -> None:
        """Load and apply this section's input emendations (if any) to `data`, in place.

        Input emendations correct only `section`'s own extracted data. Run from normalize pass 1,
        before validation, so `_validate()`'s row count reflects corrected data.
        """
        self._apply(section, data, 'input')

    def emend_normalizing_section_external(self, section: str, data: list) -> None:
        """Load and apply this section's external emendations (if any) to `data`, in place.

        External emendations pull in another section's already-parsed data. Run from normalize pass 2,
        after every section has been built and snapshotted to PRE_EMENDATION_DATA_DIR, so cross-section
        reads always see this run's data regardless of SECTION_SOURCES order.
        """
        self._apply(section, data, 'external')

    def _apply(self, section: str, data: list, kind: str) -> None:
        """Load and apply `section`'s `kind` ('input' or 'external') emendations to `data`, in place.

        Emendations are single-use and never cached: each call re-globs and re-imports
        `emendations_dir/domain/section/<section>/<kind>/*.py`, sorted by filename. A missing
        directory means no emendations exist for that section/kind yet and is silently
        skipped. Load or apply failures propagate, since emendations are mandatory once present.
        """
        section_dir = self.emendations_dir / self.domain / 'section' / section / kind
        if not section_dir.is_dir():
            return

        for path in sorted(section_dir.glob('*.py')):
            spec = importlib.util.spec_from_file_location(f'emendation_{path.stem}', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.emend(section, data)
