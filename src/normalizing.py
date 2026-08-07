import dataclasses
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
from emending import Emender
from filtering import (
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


# ---- Typed entities (normalize-stage output shape) ----


@dataclass(frozen=True, slots=True)
class AriaRoleData:
    name: str
    url: str = ''
    deprecated_since_version: str = ''


@dataclass(frozen=True, slots=True)
class AttributeData:
    name: str
    tag: str | None = None
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


RECOVERABLE_ERRORS = (AttributeError, ValueError, FileNotFoundError)

# Match a list of one-or-more keywords such as `"foo"; "bar"; "the empty string"`
ATTRIBUTE_VALUE_REGEX = re.compile(r'^(?:"[a-zA-Z0-9/-]*"|the empty string)(?:; (?:"[a-zA-Z0-9/-]*"|the empty string))*$')

# Match element exceptions like "element (if ...)"
TAG_IF_REGEX = re.compile(r'([a-zA-Z0-9-]+) \(if [a-zA-Z0-9\' -]+\)')

_SPLITTABLE_REGEX = re.compile(r'\b([a-zA-Z][a-zA-Z0-9-]*)\b[ \t]*\n[ \t]*\b([a-zA-Z][a-zA-Z0-9-]*)\b')

# Sentinel used as the dict key (in place of `tag`) for attributes with no tag restriction.
ALL_TAGS = 'all'

SEPARATOR_BY_STRING = {
    'Valid list of floating-point numbers': ',',
    'Valid source size list':               ',',
}

SEPARATOR_BY_SUBSTRING = {
    'space-separated tokens':                       ' ',
    'ordered set of unique space-separated tokens': ' ',
    'comma-separated list of':                      ',',
    'set of comma-separated tokens':                ',',
}

# Special cases: phrase -> list of yielded tokens (empty list yields nothing)
TAGS_BY_STRING = {
    'autonomous custom elements': [],
    'HTML elements': [],
    'form-associated custom elements': ['custom'],
    'MathML math': ['math'],
    'SVG svg': ['svg'],
}

TYPE_BY_STRING = {
    'Boolean attribute':                    'bool',
    'Valid integer':                        'int',
    'Valid date string with optional time': 'datetime',
}

TYPE_BY_PREFIX = {
    'Valid non-negative integer':  'int',
    'Valid floating-point number': 'float',
}

# Fragment keyword to search for when splitting a shared URL list across a row's tags, in addition to
# the tag's own name. Needed only where a URL fragment doesn't literally contain the tag name (e.g. `a`
# and `area` share fragments under "hyperlink"; `audio`/`video` under "media"; `del`/`ins` under "mod").
# Validated against indices.attributes.ndjson on 2026-08-06: every multi-tag row where a generic fragment's
# real audience is a strict subset of the row's tags requires an entry here; rows where the fragment is
# genuinely shared by every tag in the row need no entry (the no-match-shares-to-all-tags fallback covers
# them). Matching is additive: a tag always still matches its own name, this only adds a second candidate.
URL_BY_STRING = {
    'a': 'hyperlink',
    'area': 'hyperlink',
    'audio': 'media',
    'video': 'media',
    'del': 'mod',
    'ins': 'mod',
}


# ---- Generators for splitting spec strings ----


def gen_attribute_names(input_str: str) -> Iterator[str]:
    for attribute in input_str.strip(string.whitespace + ';').split(';'):
        yield attribute.strip('*').strip()


def gen_attribute_value_enums(input_str: str) -> Iterator[str]:
    if ATTRIBUTE_VALUE_REGEX.fullmatch(input_str):

        def process_keyword(keyword: str) -> str:
            keyword = keyword.strip()
            return '' if keyword == 'the empty string' else keyword.strip('"')

        yield from map(process_keyword, input_str.split(';'))


def gen_content_categories(input_str: str) -> Iterator[str]:
    for category in input_str.strip(string.whitespace + ';').split(';'):
        cat = category.strip().strip('*')
        if cat != 'empty':
            yield cat


def gen_tags(input_str: str) -> Iterator[str]:
    input_str = input_str.strip()
    if not input_str:
        return

    # 1) Handle known special phrases
    if input_str in TAGS_BY_STRING:
        yield from TAGS_BY_STRING[input_str]
        return

    if ';' in input_str:
        for e in re.split(r'\s*;\s*', input_str.strip(string.whitespace + ';')):
            yield from gen_tags(e.strip())
    elif ',' in input_str:
        for e in re.split(r'\s*,\s*', input_str.strip(string.whitespace + ',')):
            yield from gen_tags(e)
    else:
        yield input_str


def gen_tag_ifs(input_str: str) -> Iterator[str]:
    if not input_str:
        return
    parts = input_str.split(';') if ';' in input_str else [input_str]
    for x in parts:
        matches = TAG_IF_REGEX.fullmatch(x.strip())
        if matches:
            yield matches.group(1)


def split_splittables(text: str, context: str) -> str:
    """Detect and repair words missing a separator in the whitespace. Returns the words in a semicolon-separated string.
    First issue of this kind: `controls` "Element(s)" cell has no semicolon between 'video' and 'img' <code> elements in
    https://html.spec.whatwg.org/multipage/indices.html#attributes-3:attr-media-controls (still active on 2026-07-22).
    """

    def repair(match: re.Match) -> str:
        word_a, word_b = match.group(1), match.group(2)
        logger.warning("⚠️ %s: missing separator between '%s' and '%s'.", context, word_a, word_b)
        return f'{word_a};{word_b}'

    return _SPLITTABLE_REGEX.sub(repair, text)


# ---- Parsers for each section ----
# Each function takes the terse data rows for its section (read from TERSE_DATA_DIR by Normalizer).


def parse_aria_roles(rows: Iterator[AriaRoleTerseData]) -> Iterator[AriaRoleData]:
    for row in rows:
        yield AriaRoleData(
            name=row.name,
            url=row.url,
            deprecated_since_version=row.deprecated_since_version,
        )


def _parse_attribute(row: AttributeTerseData) -> Iterator[AttributeData]:
    """Parse one attribute terse data into one or more AttributeData entries, split by tag.

    Splits the input data's `elements` text into tags via gen_tags(), tracking a per-tag scope note
    (`tag_notes`) for tags with a `(if ...)`/`(in ...)` qualifier -- siblings from the same input data
    don't inherit that note. Parses the value description into value_type/value_enum/separator,
    and sets value_info_note when the value description carries a trailing '*' (shared across
    every tag split from this input data, since it describes the value, not scope).

    Yields:
        - if the input data has no tag restriction: a single tagless AttributeData;
        - otherwise splits the input data's shared URL list across tags and yields one AttributeData per tag.
    """
    name, elements_info, description, value_info, urls = (
        row.attribute,
        row.elements,
        row.description,
        row.value,
        row.urls,
    )

    elements_info = split_splittables(elements_info, f'Attribute {name!r} element(s)')
    is_complicated = value_info.endswith('*')
    if is_complicated:
        value_info = value_info[:-1]
    value_type = ' '.join(x.strip().strip('*') for x in value_info.split('\n')).strip()
    value_info = value_type

    tag_notes: dict[str, str] = {}
    for token in gen_tags(elements_info):
        tmp = token.strip()
        idx = tmp.find('(')
        if idx != -1:
            tag = tmp[:idx].strip()
            tag_notes[tag] = f'Special tag scope: {token}'
        elif tmp not in tag_notes:
            tag_notes[tmp] = ''

        tags = set(tag_notes)
        value_info_note = '. [!] Online documentation needed for completeness.' if is_complicated else ''

        value_enum = set(gen_attribute_value_enums(value_type))
        if value_enum:
            value_type, value_info, separator = 'enum', '', ''
        else:
            value_type, separator = _parse_attribute_value(value_type)

        if not tags:
            # No tag restriction (e.g. 'HTML elements'): single entry, no URL split needed.
            yield AttributeData(
                name=name,
                tag=None,
                description=description,
                value_type=value_type,
                value_enum=value_enum,
                value_info=value_info + value_info_note,
                separator=separator,
                urls=set(urls),
            )
            continue

        urls = _parse_attribute_urls(urls, tags)
        for tag in sorted(tags):
            yield AttributeData(
                name=name,
                tag=tag,
                description=description,
                value_type=value_type,
                value_enum=value_enum,
                value_info=value_info + value_info_note,
                separator=separator,
                urls=set(urls[tag]),
            )


def _parse_attribute_urls(urls: list[str], tags: set[str]) -> dict[str, list[str]]:
    """Partition a row's shared URL list across its tags. A URL goes to every tag whose keyword (its own
    name, plus an URL_BY_STRING override if one exists) appears as an exact segment of the URL's
    fragment (the part after '#'). A URL matching no tag's keyword is shared by every tag in the row.
    """
    keywords = {tag: {tag, URL_BY_STRING[tag]} if tag in URL_BY_STRING else {tag} for tag in tags}
    result: dict[str, list[str]] = {tag: [] for tag in tags}
    for url in urls:
        fragment = url.split('#', 1)[-1] if '#' in url else ''
        segments = set(re.split(r'[^a-z0-9]+', fragment.lower()))
        matched = {tag for tag, kws in keywords.items() if kws & segments}
        if len(matched) > 1:
            logger.info(' • URL matches multiple tags %r; adding it to all matches (%r).', sorted(matched), url)
        for tag in matched or tags:
            result[tag].append(url)
    return result


def _parse_attribute_value(value_type_str: str) -> tuple[str, str]:
    value_type = TYPE_BY_STRING.get(value_type_str)
    if value_type is None:
        for prefix, mapped_type in TYPE_BY_PREFIX.items():
            if value_type_str.startswith(prefix):
                value_type = mapped_type
                break
        else:
            value_type = 'string'

    value_separator = SEPARATOR_BY_STRING.get(value_type_str)
    if value_separator is None:
        value_type_lower = value_type_str.lower()
        for substring, sep in SEPARATOR_BY_SUBSTRING.items():
            if substring in value_type_lower:
                value_separator = sep
                break
    if value_separator is None:
        value_separator = ''

    return value_type, value_separator


def parse_attributes(rows: Iterator[AttributeTerseData]) -> Iterator[AttributeData]:
    for row in rows:
        yield from _parse_attribute(row)


def dictify_attributes(attribute_list: list[AttributeData]) -> dict[str, dict[str, Any]]:
    """Convert a list of AttributeData into a dict keyed by name, then by tag (ALL_TAGS for `tag is None`).
    Raises ValueError on a genuine (name, tag) collision, since that indicates a parsing bug rather than
    legitimate data -- unlike dictify(), there's no merge path here.
    """
    result: dict[str, dict[str, Any]] = {}
    for attribute in attribute_list:
        r = dataclasses.asdict(attribute)
        del r['name']
        del r['tag']
        tag_key = ALL_TAGS if attribute.tag is None else attribute.tag
        by_tag = result.setdefault(attribute.name, {})
        if tag_key in by_tag:
            logger.warning('⚠️ Duplicate name+tag pair: (%r, %r)', attribute.name, tag_key)
        by_tag[tag_key] = r
    return result


def parse_content_categories(rows: Iterator[ContentCategoryTerseData]) -> Iterator[ContentCategoryData]:
    for row in rows:
        category = ' '.join(row.category.split())

        exceptions = '; '.join(x.strip() for x in row.exceptions.split(';'))
        if exceptions == '—':
            exceptions = ''
        if category.endswith('*'):
            exceptions += '; The tabindex attribute can also make any element into interactive content.'
        category = category.rstrip('*').strip()

        elements_set = set(gen_tags(row.elements))
        elements_maybe = list(gen_tag_ifs(exceptions))

        yield ContentCategoryData(
            name=category,
            url=row.url,
            elements=elements_set,
            elements_maybe=elements_maybe,
            exceptions=exceptions,
        )


def parse_elements(rows: Iterator[ElementTerseData]) -> Iterator[ElementData]:
    for row in rows:
        elements = gen_tags(row.element)
        categories = set(gen_content_categories(row.categories))
        attributes = set(gen_attribute_names(row.attributes))
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


# section name -> (page, terse dataclass); drives Normalizer.get(). Keys match config.PAGE_SECTIONS values.
SECTION_SOURCES: dict[str, tuple[str, type]] = {
    'aria_roles': ('aria', AriaRoleTerseData),
    'attributes': ('indices', AttributeTerseData),
    'content_categories': ('indices', ContentCategoryTerseData),
    'elements': ('indices', ElementTerseData),
    'element_kinds': ('syntax', ElementKindTerseData),
    'event_handlers': ('indices', EventHandlerTerseData),
    'global_attributes': ('dom', GlobalAttributeTerseData),
    'input_types': ('input', InputTypeTerseData),
}


class Normalizer:
    """Normalizing stage engine: terse data NDJSON -> typed entities, with validation and fallback cache."""

    def __init__(
        self,
        terse_data_dir: Path,
        cache_dir: Path,
        emender: Emender | None = None,
    ) -> None:
        self.terse_data_dir = terse_data_dir
        self.cache_dir = cache_dir
        self.emender = emender if emender is not None else Emender(domain='normalizing')
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
        self, page: str, section: str, cls: type, dictifier: Callable[[list], dict[str, Any]] = dictify
    ) -> dict[str, Any]:
        def builder() -> dict[str, Any]:
            parser = getattr(sys.modules[__name__], f'parse_{section}')
            entries = list(parse_section(self.terse_data_dir, page, section, cls, parser))
            self.emender.emend_normalizing_section(section, entries)
            return dictifier(entries)

        return self._build_cached(section, builder)

    # ---- public builders ----

    def get_section_data(self, section: str) -> dict[str, Any]:
        """Build the named section with caching and validation. `section` must be a key in SECTION_SOURCES."""
        page, cls = SECTION_SOURCES[section]
        dictifier = dictify_attributes if section == 'attributes' else dictify
        return self._get_dictified(page, section, cls, dictifier)

    def get_all(self) -> dict[str, Any]:
        """Run all builders and return a dict of results."""
        results = {section: self.get_section_data(section) for section in SECTION_SOURCES}
        return results, dict(self._manifest)
