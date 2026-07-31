import os
from pathlib import Path

# ---- Project root ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---- Directories ----
DATA_DIR = PROJECT_ROOT / '.dev/tmp'
RAW_DATA_DIR = DATA_DIR / 'raw'  # raw spec HTML files
TERSE_DATA_DIR = DATA_DIR / 'terse'  # NDJSON records, one file per (page, section)
ATOMIC_DATA_CACHE_DIR = DATA_DIR / 'cache'  # normalize-stage fallback cache
ATOMIC_DATA_DIR = DATA_DIR / 'atomic'  # typed+merged entities, one JSON file per category
EMENDATIONS_DIR = PROJECT_ROOT / '.dev/emendations'  # hand-authored emendation rules (plain Python)

_dist_env = os.environ.get('DIST_DATA_DIR')
DIST_ROOT_DIR, _dist_subfolder = (Path(_dist_env), 'data') if _dist_env else (DATA_DIR, 'dist')
DIST_DATA_DIR = DIST_ROOT_DIR / _dist_subfolder  # published json/yaml/manifest; NOTICE stays at DIST_ROOT_DIR
DIST_JSON_DATA_DIR = DIST_DATA_DIR / 'json'  # final JSON output
DIST_YAML_DATA_DIR = DIST_DATA_DIR / 'yaml'  # final YAML output

# ---- Filtering (stage 1: HTML -> TERSE_DATA_DIR/*.ndjson) ----
# Maps each raw source page to the section names extracted from it. Keys match RAW_DATA_DIR/{page}.html;
# each (page, section) pair has exactly one NDJSON file at TERSE_DATA_DIR/{page}.{section}.ndjson
# and one entry in TERSE_DATA_MANIFEST.
PAGE_SECTIONS = {
    'indices': ('elements', 'content_categories', 'attributes', 'event_handlers'),
    'dom': ('global_attributes',),  # NOTE! to create a tuple with one element, it needs the trailing comma.
    'input': ('input_types',),
    'syntax': ('element_kinds',),
    'aria': ('aria_roles',),
}

# ---- Manifest ----
RAW_DATA_MANIFEST = RAW_DATA_DIR / 'manifest.json'  # raw per-source fetch timestamps
TERSE_DATA_MANIFEST = TERSE_DATA_DIR / 'manifest.json'  # per (page, section) filtering status
ATOMIC_DATA_MANIFEST = ATOMIC_DATA_DIR / 'manifest.json'  # per-category normalizing status
DIST_DATA_MANIFEST = DIST_DATA_DIR / 'manifest.json'

# ---- Logging ----
LOG_LEVEL = 'DEBUG'  # DEBUG INFO WARNING ERROR CRITICAL

# ---- Formatting ----
DUMP_NDJSON_KWARGS = {'sort_keys': False, 'ensure_ascii': False}
DUMP_JSON_KWARGS = {**DUMP_NDJSON_KWARGS, 'indent': 2}
DUMP_YAML_KWARGS = {'sort_keys': False, 'indent': 2, 'allow_unicode': True, 'width': float('inf')}

# ---- Content hash for published data ----
DIST_HASH_FILE = ATOMIC_DATA_CACHE_DIR / 'dist_content.sha256'  # detects real data changes across publish runs
