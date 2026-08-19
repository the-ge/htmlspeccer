import json
import logging
import sys
from inspect import currentframe
from pathlib import Path

from bs4 import BeautifulSoup

from config import DUMP_JSON_KWARGS, NORMALIZED_DATA_DIR, RECOVERABLE_ERRORS
from curating.aria_roles import parse_aria_roles  # noqa: F401 (dynmically called; @todo annotate)
from curating.attributes import parse_attributes  # noqa: F401 (dynmically called; @todo annotate)
from curating.content_categories import parse_content_categories  # noqa: F401 (dynmically called; @todo annotate)
from curating.element_kinds import parse_element_kinds  # noqa: F401 (dynmically called; @todo annotate)
from curating.elements import parse_elements  # noqa: F401 (dynmically called; @todo annotate)
from curating.event_handlers import parse_event_handlers  # noqa: F401 (dynmically called; @todo annotate)
from curating.global_attributes import parse_global_attributes  # noqa: F401 (dynmically called; @todo annotate)
from curating.input_types import parse_input_types  # noqa: F401 (dynmically called; @todo annotate)
from emending import Emender
from schema import CURATION_MAP
from util.serializing import dataclass_to_dict, dict_to_dataclass, write_ndjson

logger = logging.getLogger(__name__)


class Curator:
    """Converts raw spec HTML to typed entities, with validation and fallback cache."""

    def __init__(
        self,
        raw_data_dir: Path,
        cache_dir: Path,
        emender: Emender | None = None,
    ) -> None:
        self.raw_data_dir = raw_data_dir
        self.cache_dir = cache_dir
        self.emender = emender if emender is not None else Emender()
        self._soup_cache: dict[str, BeautifulSoup | None] = {}
        self._manifest: dict[str, dict] = {}
        self._fallback_sections: set[str] = set()

    # ---- public builders ----

    def get_all(self) -> tuple[dict[str, list], dict]:
        """Run all section builders, apply external emendations, then finalize the manifest and cache.

        Non-fallback sections get their normalized-data write, external emendation, and cache save;
        fallback sections already hold final (post-emendation) cached data, so all three are skipped for
        them. `output_row_count` and `delta` are recorded for every section once all entries are final.

        Returns:
            {section: [entities]} and the manifest
        """
        results = {section: self._get_parsed_section(section) for section in CURATION_MAP}

        NORMALIZED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        for section, entries in results.items():
            if section not in self._fallback_sections:
                write_ndjson(NORMALIZED_DATA_DIR / f'{section}.ndjson', entries)

        for section, entries in results.items():
            if section not in self._fallback_sections:
                self.emender.emend(currentframe().f_code.co_name, section, entries)

        for section, entries in results.items():
            count = len(entries)
            previous = self._load_cached_raw(section)
            previous_count = len(previous) if previous is not None else None
            delta = 0 if previous_count is None else count - previous_count
            self._manifest[section]['output_row_count'] = count
            if delta:
                logger.warning(
                    '⚠️ %s: count changed by %d since last run (%d -> %d)', section, delta, previous_count, count
                )
                self._manifest[section]['delta'] = delta

        for section, entries in results.items():
            if section not in self._fallback_sections:
                self._save_cache(section, entries)

        return results, dict(self._manifest)

    # ---- internal helpers ----

    def _get_parsed_section(self, section: str) -> list:
        """Parse `section` from its page's soup and apply its input emendations.

        Records `input_row_count` (the row count straight out of parse_X(), before any emendation) in the
        manifest. On a recoverable parse/extraction error, falls back to the previous cached run for
        `section` instead (see `_log_parse_error_and_fallback`).

        Returns:
            List of data JSON objects

        Raises:
            FileNotFoundError: if section raw source not found
        """
        page, cls = CURATION_MAP[section]
        soup = self._load_soup(page)

        try:
            if soup is None:
                msg = f'No raw HTML available for page {CURATION_MAP[section][0]!r}'
                raise FileNotFoundError(msg)

            parser = getattr(sys.modules[__name__], f'parse_{section}')
            parsed = list(parser(soup))
            input_row_count = len(parsed)
            self.emender.emend(currentframe().f_code.co_name, section, parsed)
        except RECOVERABLE_ERRORS as e:
            return self._log_parse_error_and_fallback(e, section, cls)

        self._manifest[section] = {'input_row_count': input_row_count}
        logger.info('🏗️ Built %s %s', len(parsed), section)
        return parsed

    def _load_soup(self, page: str) -> BeautifulSoup | None:
        """Load and cache the soup for `page` (shared across every section of that page).

        Returns:
            - A BeautifulSoup object or
            - None if the raw HTML is missing or unreadable (also logs)
        """
        if page not in self._soup_cache:
            try:
                with (self.raw_data_dir / f'{page}.html').open('r') as fp:
                    soup = BeautifulSoup(fp, 'lxml')
                self.emender.emend(currentframe().f_code.co_name, page, soup)
                self._soup_cache[page] = soup
            except OSError:
                logger.exception('❌ Could not read %s.html', page)
                self._soup_cache[page] = None
        return self._soup_cache[page]

    def _save_cache(self, key: str, entries: list) -> None:
        """Save a list of entity dataclass instances to the cache directory as JSON."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        serialized = [dataclass_to_dict(e) for e in entries]
        (self.cache_dir / f'{key}.json').write_text(
            json.dumps(serialized, **DUMP_JSON_KWARGS),
            encoding='utf-8',
        )

    def _load_cached_raw(self, key: str) -> list | None:
        """Load the raw (still plain-dict) cached entries for `key`; return None if missing.

        Returns:
            The cached list of dicts or None if not found in cache
        """
        path = self.cache_dir / f'{key}.json'
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def _load_cached_dataclass(self, key: str, cls: type) -> list | None:
        """Load the cached entries for `key`, reconstructed as `cls` instances.

        Returns:
            The cached list of dataclass objects or None if not found in cache
        """
        raw = self._load_cached_raw(key)
        return None if raw is None else [dict_to_dataclass(cls, d) for d in raw]

    def _validate(self, key: str, count: int) -> dict:
        """Compare `count` against the previous cached run for `key` (if any) and decide pass/warn/raise.

        No fixed floor: a category may legitimately grow or shrink a little as the spec evolves,
        but a bigger jump either way is more likely a broken extraction/parse than a real change upstream.
        Stores the manifest entry. Warns if the source row count changes.

        Returns:
            The manifest entry for `key`: {status, row_count} plus delta
        """
        previous = self._load_cached_raw(key)
        previous_count = len(previous) if previous is not None else None
        delta = 0 if previous_count is None else count - previous_count

        if abs(delta) >= 1:
            logger.warning('⚠️ %s: count changed by %d since last run (%d -> %d)', key, delta, previous_count, count)

        entry = {'status': 'ok', 'row_count': count, 'delta': delta}
        self._output_manifest[key] = entry
        return entry

    def _log_parse_error_and_fallback(self, e: Exception, section: str, cls: type) -> list:
        """Load `section`'s previously cached (already fully emended) data after a recoverable parse error.

        Records a manifest entry with `input_row_count: None`, and marks `section` as a fallback so
        `get_all()` skips re-running emendations and re-caching over data that's already final.

        Returns:
            The cached list of dataclass objects

        Raises:
            RuntimeError: if no cache is available for `section`
        """
        logger.error('❌ Parsing failed: %s', e)

        cached = self._load_cached_dataclass(section, cls)

        if cached is None:
            msg = f'No cache available for {section}'
            raise RuntimeError(msg) from e

        logger.info('📂 Loaded %s from cache', section)
        self._manifest[section] = {'input_row_count': None}
        self._fallback_sections.add(section)
        return cached
