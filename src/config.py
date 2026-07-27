import os
from pathlib import Path

# ---- Project root ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---- Directories ----
RAW_DATA_DIR = PROJECT_ROOT / '.dev/data/raw'  # raw spec HTML files
TERSE_DATA_DIR = PROJECT_ROOT / '.dev/data/terse'  # NDJSON records, one file per (page, section)
ATOMIC_DATA_CACHE_DIR = PROJECT_ROOT / '.dev/data/cache'  # normalize-stage fallback cache
ATOMIC_DATA_DIR = PROJECT_ROOT / '.dev/data/atomic'  # typed+merged entities, one JSON file per category
DIST_DATA_DIR = Path(os.environ['HTMLSPEC_DIST_DIR']) if 'HTMLSPEC_DIST_DIR' in os.environ else PROJECT_ROOT / 'dist'
DIST_JSON_DATA_DIR = DIST_DATA_DIR / 'json'  # final JSON output
DIST_YAML_DATA_DIR = DIST_DATA_DIR / 'yaml'  # final YAML output
EMENDATIONS_DIR = PROJECT_ROOT / '.dev/emendations'  # hand-authored emendation rules (plain Python)

# ---- Filtering (stage 1: HTML -> TERSE_DATA_DIR/*.ndjson) ----
# Maps each raw source page to the section names extracted from it. Keys match RAW_DATA_DIR/{page}.html;
# each (page, section) pair has exactly one NDJSON file at TERSE_DATA_DIR/{page}.{section}.ndjson
# and one entry in TERSE_DATA_MANIFEST.
PAGE_SECTIONS = {
    'indices': ('elements', 'content_categories', 'attributes', 'event_handlers'),
    'dom': ('global_attributes',),  # NOTE! to create a tuple with one element, it needs the trailing comma.
    'input': ('input_types',),
    'syntax': ('element_types',),
    'aria': ('aria_roles',),
}

# ---- Manifest ----
RAW_DATA_MANIFEST = RAW_DATA_DIR / 'manifest.json'  # raw per-source fetch timestamps
TERSE_DATA_MANIFEST = TERSE_DATA_DIR / 'manifest.json'  # per (page, section) extraction status
ATOMIC_DATA_MANIFEST = ATOMIC_DATA_DIR / 'manifest.json'  # per-category normalization status
DIST_DATA_MANIFEST = DIST_DATA_DIR / 'manifest.json'

# ---- Logging ----
LOG_LEVEL = 'DEBUG'  # DEBUG INFO WARNING ERROR CRITICAL

# ---- Formatting ----
DUMP_NDJSON_KWARGS = {'sort_keys': False, 'ensure_ascii': False}
DUMP_JSON_KWARGS = {**DUMP_NDJSON_KWARGS, 'indent': 2}
DUMP_YAML_KWARGS = {'sort_keys': False, 'indent': 2, 'allow_unicode': True, 'width': float('inf')}
