import importlib.util
import logging
from collections.abc import Callable
from pathlib import Path

from config import EMENDATIONS_DIR

logger = logging.getLogger(__name__)

Emendation = Callable[[str, Any], bool]


class Emender:
    """Apply targeted, manually-authored transformations to input data."""

    def __init__(self, domain: str, emendations_dir: Path = EMENDATIONS_DIR) -> None:
        self.domain = domain
        self.emendations_dir = emendations_dir
        self._emendations: list[tuple[str, Emendation]] = self._load_emendations()

    def _load_emendations(self) -> list[tuple[str, Emendation]]:
        domain_dir = self.emendations_dir / self.domain
        if not domain_dir.is_dir():
            msg = f'Emendations directory not found for domain {self.domain!r}: {domain_dir}'
            raise FileNotFoundError(msg)

        emendations = []
        for path in sorted(domain_dir.glob('*.py')):
            spec = importlib.util.spec_from_file_location(f'emendation_{path.stem}', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            emendations.append((path.stem, module.emend))
        return emendations

    def emend_normalizing_section(self, section: str, data: Any) -> None:
        """Mutate `entries` in place."""
        for name, emend in self._emendations:
            if emend(section, data):
                logger.info('🩹 Applied emendation %r.', name)
