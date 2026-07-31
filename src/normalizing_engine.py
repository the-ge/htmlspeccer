import json
import logging
import re
import string
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slugify import slugify

from config import DUMP_JSON_KWARGS
from emending_engine import Emender
from filtering_engine import (
    AriaRoleTerseData,
    AttributeTerseData,
    ContentCategoryTerseData,
    ElementKindTerseData,
    ElementTerseData,
    EventHandlerTerseData,
    GlobalAttributeTerseData,
    InputTypeTerseData,
)
from util import dictify, make_serializable, parse_section, sort_top_level

logger = logging.getLogger(__name__)

# ---- Typed, merged entities (normalize-stage output shape) ----


@dataclass(frozen=True, slots=True)
class AriaRoleData:
    name: str
    url: str = ''
    deprecated_since_version: str = ''


@dataclass(frozen=True, slots=True)
class AttributeData:
    name: str
    tag_scope: set[str] = field(default_factory=set)
    description: str = ''
    value_type: str = 'string'
    value_enum: set[str] = field(default_factory=set)
    value_info: str = ''
    separator: str = ''
    urls: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ContentCategoryData:
    name: str
    elements: set[str] = field(default_factory=set)
    elements_maybe: list[str] = field(default_factory=list)
    exceptions: str = ''
    url: str = ''


@dataclass(frozen=True, slots=True)
class ElementData:
    name: str
    description: str = ''
    categories: set[str] = field(default_factory=set)
    attributes: set[str] = field(default_factory=set)
    children: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ElementKindData:
    name: str
    tags: set[str] = field(default_factory=set)
    info: str = ''


@dataclass(frozen=True, slots=True)
class EventHandlerData:
    name: str
    applies_to: str = ''
    urls: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class GlobalAttributeData:
    name: str
    url: str = ''


@dataclass(frozen=True, slots=True)
class InputTypeData:
    name: str
    value_type: str = ''
    control_type: str = ''
    url: str = ''


# Match a list of one-or-more keywords such as `"foo"; "bar"; "the empty string"`
KEYWORDS_PATTERN = re.compile(r'^(?:"[a-zA-Z0-9/-]*"|the empty string)(?:; (?:"[a-zA-Z0-9/-]*"|the empty string))*$')

# Match element exceptions like "element (if ...)"
EXCEPTION_PATTERN = re.compile(r'([a-zA-Z0-9-]+) \(if [a-zA-Z0-9\' -]+\)')

# Special cases: phrase -> list of yielded tokens (empty list yields nothing)
SPECIAL_ELEMENTS = {
    'autonomous custom elements': [],
    'HTML elements': [],
    'form-associated custom elements': ['custom'],
    'MathML math': ['math'],
    'SVG svg': ['svg'],
}

RECOVERABLE_ERRORS = (AttributeError, ValueError, FileNotFoundError)

ATTRIBUTE_TYPE_IF_EQUALS = {
    'Boolean attribute':                    'bool',
    'Valid integer':                        'int',
    'Valid date string with optional time': 'datetime',
}

ATTRIBUTE_TYPE_IF_STARTSWITH = {
    'Valid non-negative integer':  'int',
    'Valid floating-point number': 'float',
}

ATTRIBUTE_SEPARATOR_IF_EQUALS = {
    'Valid list of floating-point numbers': ',',
    'Valid source size list':               ',',
}

ATTRIBUTE_SEPARATOR_IF_CONTAINS = {
    'space-separated tokens':                       ' ',
    'ordered set of unique space-separated tokens': ' ',
    'comma-separated list of':                      ',',
    'set of comma-separated tokens':                ',',
}


# ---- Generators for splitting spec strings ----


def gen_attributes(attributes: str) -> Iterator[str]:
    for attribute in attributes.strip(string.whitespace + ';').split(';'):
        yield attribute.strip('*').strip()


def gen_content_categories(categories: str) -> Iterator[str]:
    for category in categories.strip(string.whitespace + ';').split(';'):
        cat = category.strip().strip('*')
        if cat != 'empty':
            yield cat


def gen_elements(elements: str) -> Iterator[str]:
    elements = elements.strip()
    if not elements:
        return

    # 1) Handle known special phrases
    if elements in SPECIAL_ELEMENTS:
        yield from SPECIAL_ELEMENTS[elements]
        return

    if ';' in elements:
        for e in re.split(r'\s*;\s*', elements.strip(string.whitespace + ';')):
            yield from gen_elements(e.strip())
    elif ',' in elements:
        for e in re.split(r'\s*,\s*', elements.strip(string.whitespace + ',')):
            yield from gen_elements(e)
    else:
        yield elements


def gen_element_exceptions(xs: str) -> Iterator[str]:
    if not xs:
        return
    parts = xs.split(';') if ';' in xs else [xs]
    for x in parts:
        matches = EXCEPTION_PATTERN.fullmatch(x.strip())
        if matches:
            yield matches.group(1)


def gen_enum(keywords: str) -> Iterator[str]:
    if KEYWORDS_PATTERN.fullmatch(keywords):

        def process_keyword(keyword: str) -> str:
            keyword = keyword.strip()
            return '' if keyword == 'the empty string' else keyword.strip('"')

        yield from map(process_keyword, keywords.split(';'))


_ADJACENT_TOKENS_PATTERN = re.compile(r'\b([a-zA-Z][a-zA-Z0-9-]*)\b[ \t]*\n[ \t]*\b([a-zA-Z][a-zA-Z0-9-]*)\b')


def split_splittables(text: str, context: str) -> str:
    """Detect and repair words missing a separator in the whitespace. Returns the words in a semicolon-separated string.
    First issue of this kind: `controls` "Element(s)" cell has no semicolon between 'video' and 'img' <code> elements in
    https://html.spec.whatwg.org/multipage/indices.html#attributes-3:attr-media-controls (still active on 2026-07-22).
    """

    def repair(match: re.Match) -> str:
        word_a, word_b = match.group(1), match.group(2)
        logger.warning("⚠️ %s: missing separator between '%s' and '%s'.", context, word_a, word_b)
        return f'{word_a};{word_b}'

    return _ADJACENT_TOKENS_PATTERN.sub(repair, text)


# ---- Parsers for each section ----
# Each function takes the terse data rows for its section (read from TERSE_DATA_DIR by Normalizer).


def parse_aria_roles(rows: Iterator[AriaRoleTerseData]) -> Iterator[AriaRoleData]:
    for row in rows:
        yield AriaRoleData(
            name=row.name,
            url=row.url,
            deprecated_since_version=row.deprecated_since_version,
        )


def _parse_attribute_info(elements_info: str, value_info: str) -> tuple[set[str], str, str, str, bool]:
    """Return (tag_scope, tag_notes, value_type, value_info, is_complicated)."""
    is_complicated = value_info.endswith('*')
    if is_complicated:
        value_info = value_info[:-1]
    value_type = ' '.join(x.strip().strip('*') for x in value_info.split('\n')).strip()
    value_info = value_type

    elements_set: set[str] = set()
    elements_notes: list[str] = []
    for token in gen_elements(elements_info):
        tmp = token.strip()
        idx = tmp.find('(')
        if idx != -1:
            is_complicated = True
            elements_set.add(tmp[:idx].strip())
            elements_notes.append(token)
        else:
            elements_set.add(tmp)
    elements_notes = '' if not elements_notes else f'Special tag scope: {", ".join(elements_notes)}'
    return elements_set, elements_notes, value_type, value_info, is_complicated


def parse_attributes(rows: Iterator[AttributeTerseData]) -> Iterator[AttributeData]:
    for row in rows:
        name, elements_info, description, value_info, urls = (
            row.attribute,
            row.elements,
            row.description,
            row.value,
            row.urls,
        )

        elements_info = split_splittables(elements_info, f'Attribute {row.attribute!r} tag scope')

        tag_scope, tag_notes, value_type, value_info, is_complicated = _parse_attribute_info(elements_info, value_info)

        value_enum = set(gen_enum(value_type))
        if value_enum:
            value_type, value_info, separator = 'enum', '', ''
        else:
            t = ATTRIBUTE_TYPE_IF_EQUALS.get(value_type)
            if t is None:
                for prefix, mapped_type in ATTRIBUTE_TYPE_IF_STARTSWITH.items():
                    if value_type.startswith(prefix):
                        t = mapped_type
                        break
                else:
                    t = 'string'

            s = ATTRIBUTE_SEPARATOR_IF_EQUALS.get(value_type)
            if s is None:
                value_type_lower = value_type.lower()
                for substring, sep in ATTRIBUTE_SEPARATOR_IF_CONTAINS.items():
                    if substring in value_type_lower:
                        s = sep
                        break
            if s is None:
                s = ''

            value_type, separator = t, s

        value_info = '. '.join([
            v
            for v in [
                value_info,
                tag_notes,
                '*Incomplete description. See the full specification.' if is_complicated else '',
            ]
            if v
        ])

        yield AttributeData(
            name=name,
            tag_scope=tag_scope,
            description=description,
            value_type=value_type,
            value_enum=value_enum,
            value_info=value_info,
            separator=separator,
            urls=urls,
        )


def parse_content_categories(rows: Iterator[ContentCategoryTerseData]) -> Iterator[ContentCategoryData]:
    for row in rows:
        category = ' '.join(row.category.split())

        exceptions = '; '.join(x.strip() for x in row.exceptions.split(';'))
        if exceptions == '—':
            exceptions = ''
        if category.endswith('*'):
            exceptions += '; The tabindex attribute can also make any element into interactive content.'
        category = category.rstrip('*').strip()

        elements_set = set(gen_elements(row.elements))
        elements_maybe = list(gen_element_exceptions(exceptions))

        yield ContentCategoryData(
            name=category,
            url=row.url,
            elements=elements_set,
            elements_maybe=elements_maybe,
            exceptions=exceptions,
        )


def parse_elements(rows: Iterator[ElementTerseData]) -> Iterator[ElementData]:
    for row in rows:
        elements = gen_elements(row.element)
        categories = set(gen_content_categories(row.categories))
        attributes = set(gen_attributes(row.attributes))
        children = set(gen_content_categories(row.children))

        for e in sorted(elements):
            yield ElementData(
                name=e,
                description=row.description.strip(),
                categories=categories,
                attributes=attributes,
                children=children,
            )


def parse_element_kinds(rows: Iterator[ElementKindTerseData]) -> Iterator[ElementKindData]:
    for row in rows:
        yield ElementKindData(
            name=slugify(row.name),
            tags=set(row.tags),
            info=row.info,
        )


def parse_event_handlers(rows: Iterator[EventHandlerTerseData]) -> Iterator[EventHandlerData]:
    for row in rows:
        yield EventHandlerData(
            name=row.attribute,
            applies_to=row.elements,
            urls=row.urls,
        )


def parse_global_attributes(rows: Iterator[GlobalAttributeTerseData]) -> Iterator[GlobalAttributeData]:
    for name in ('class', 'id', 'role', 'slot'):
        yield GlobalAttributeData(name=name)
    for row in rows:
        yield GlobalAttributeData(name=row.name, url=row.url)


def parse_input_types(rows: Iterator[InputTypeTerseData]) -> Iterator[InputTypeData]:
    for row in rows:
        yield InputTypeData(
            name=row.keyword,
            value_type=row.data_type,
            control_type=row.control_type,
            url=row.url,
        )


class Normalizer:
    """Normalizing stage engine: terse data NDJSON -> typed, merged entities, with validation and fallback cache."""

    def __init__(
        self,
        terse_data_dir: Path,
        cache_dir: Path,
        emender: Emender | None = None,
    ) -> None:
        self.terse_data_dir = terse_data_dir
        self.cache_dir = cache_dir
        self.emender = emender if emender is not None else Emender(domain='normalize')
        self._manifest: dict[str, dict] = {}  # populated by _validate(), collected by get_all()

    # ---- internal helpers ----

    def _save_cache(self, key: str, data: dict | set) -> None:
        """Save a Python object to the cache directory as JSON."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        serialized = make_serializable(data)
        if isinstance(serialized, dict):
            serialized = sort_top_level(serialized)
        (self.cache_dir / f'{key}.json').write_text(
            json.dumps(serialized, **DUMP_JSON_KWARGS),
            encoding='utf-8',
        )

    def _load_cache(self, key: str) -> dict | list | None:
        """Load a Python object from the cache directory; return None if missing."""
        path = self.cache_dir / f'{key}.json'
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def _build_cached(self, key: str, builder: Callable[[], dict | set]) -> dict | set:
        """Run `builder`, validate and cache its result under `key`; on a recoverable error, fall back to the cache."""
        try:
            result = builder()
            self._validate(key, len(result))
        except RECOVERABLE_ERRORS as e:
            return self._log_parse_error_and_fallback(e, key)
        else:
            self._save_cache(key, result)
            logger.info('🏗️ Built and cached %s %s', len(result), key)
            return result

    def _log_parse_error_and_fallback(self, e: Exception, cache_key: str) -> dict | list | None:
        logger.error('❌ Terse data missing or unexpected shape: %s', e)
        cached = self._load_cache(cache_key)
        if cached is None:
            msg = f'No cache available for {cache_key}'
            raise RuntimeError(msg) from e
        logger.info('📂 Loaded %s from cache', cache_key)
        return cached

    def _validate(self, key: str, count: int) -> dict:
        """Compare `count` against the previous cached run for `key` (if any) and decide pass/warn/raise. No fixed floor:
        a category may legitimately grow or shrink a little as the spec evolves, but a bigger jump either way is more
        likely a broken filter/parser than a real change upstream.

        delta ==  0 or no previous run -> pass, silent
        abs(delta) == 1                -> pass, warn
        abs(delta) >= 2                -> raise

        Stores and returns the manifest entry for `key`: {status, row_count} plus delta, omitted when 0 (nothing changed)
        or unavailable (first run).
        """
        delta_warn = 1
        delta_fatal = 2
        previous = self._load_cache(key)
        previous_count = len(previous) if previous is not None else None
        delta = 0 if previous_count is None else count - previous_count

        if abs(delta) >= delta_fatal:
            msg = f'{key}: count changed by {delta:+d} since last run ({previous_count} -> {count})'
            raise ValueError(msg)
        if abs(delta) == delta_warn:
            logger.warning('⚠️ %s: count changed by %d since last run (%d -> %d)', key, delta, previous_count, count)

        entry = {'status': 'ok', 'row_count': count, 'delta': delta}
        self._manifest[key] = entry
        return entry

    def _get_dictified(
        self, page: str, section: str, cls: type, *, merge: bool = True
    ) -> dict[str, Any]:
        def builder() -> dict[str, Any]:
            parser = getattr(sys.modules[__name__], f'parse_{section}')
            entries = list(parse_section(self.terse_data_dir, page, section, cls, parser))
            self.emender.emend_normalizing_section(section, entries)
            return dictify(entries, merge=merge)

        return self._build_cached(section, builder)

    # ---- public builders ----

    def get_aria_roles(self) -> dict[str, Any]:
        """Build ARIA roles with caching and validation."""
        return self._get_dictified(
            'aria',
            'aria_roles',
            AriaRoleTerseData,
        )

    def get_attributes(self) -> dict[str, Any]:
        """Build attributes with caching and validation."""
        return self._get_dictified(
            'indices',
            'attributes',
            AttributeTerseData,
        )

    def get_content_categories(self) -> dict[str, Any]:
        """Build content categories with caching and validation."""
        return self._get_dictified(
            'indices',
            'content_categories',
            ContentCategoryTerseData,
        )

    def get_elements(self) -> dict[str, Any]:
        """Build elements with caching and validation."""
        return self._get_dictified(
            'indices',
            'elements',
            ElementTerseData,
        )

    def get_element_kinds(self) -> dict[str, Any]:
        """Build element types with caching and validation."""
        return self._get_dictified(
            'syntax',
            'element_kinds',
            ElementKindTerseData,
        )

    def get_event_handlers(self) -> dict[str, Any]:
        """Build event handlers with caching and validation."""
        return self._get_dictified(
            'indices',
            'event_handlers',
            EventHandlerTerseData,
        )

    def get_global_attributes(self) -> dict[str, Any]:
        """Build global attributes with caching and validation."""
        return self._get_dictified(
            'dom',
            'global_attributes',
            GlobalAttributeTerseData,
        )

    def get_input_types(self) -> dict[str, Any]:
        """Build input types with caching and validation."""
        return self._get_dictified(
            'input',
            'input_types',
            InputTypeTerseData,
        )

    def get_all(self) -> dict[str, Any]:
        """Run all builders and return a dict of results."""
        results = {
            'aria_roles': self.get_aria_roles(),
            'attributes': self.get_attributes(),
            'content_categories': self.get_content_categories(),
            'elements': self.get_elements(),
            'element_kinds': self.get_element_kinds(),
            'event_handlers': self.get_event_handlers(),
            'input_types': self.get_input_types(),
            # Plain list, not the {name: {}} dict convention the other domains use.
            'global_attributes': self.get_global_attributes(),
        }
        return results, dict(self._manifest)
