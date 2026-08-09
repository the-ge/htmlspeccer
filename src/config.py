import os
from pathlib import Path

# ---- Project root ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---- Directories ----
DATA_DIR = PROJECT_ROOT / '.dev/data'
RAW_DATA_DIR = DATA_DIR / 'raw'  # raw spec HTML files
PRE_EMENDATION_DATA_DIR = DATA_DIR / 'pre_emendation'  # typed entities after 1st emending pass, one NDJSON file per section
NORMALIZED_DATA_DIR = DATA_DIR / 'normalized'  # typed entities after 2nd emending pass, one NDJSON file per section
NORMALIZED_DATA_CACHE_DIR = DATA_DIR / 'cache'  # normalize-stage fallback cache
EMENDATIONS_DIR = PROJECT_ROOT / '.dev/emendations'  # hand-authored emendation rules (plain Python)

_dist_env = os.environ.get('DIST_DATA_DIR')
DIST_ROOT_DIR, _dist_subfolder = (Path(_dist_env), 'data') if _dist_env else (DATA_DIR, 'dist')
DIST_DATA_DIR = DIST_ROOT_DIR / _dist_subfolder  # published json/yaml/manifest; NOTICE stays at DIST_ROOT_DIR
DIST_JSON_DATA_DIR = DIST_DATA_DIR / 'json'  # final JSON output
DIST_YAML_DATA_DIR = DIST_DATA_DIR / 'yaml'  # final YAML output

# ---- Normalizing (stage 2: HTML -> NORMALIZED_DATA_DIR/*.ndjson) ----
# Maps each raw source page to the section names extracted from it. Keys match RAW_DATA_DIR/{page}.html;
# each (page, section) pair has exactly one NDJSON file at NORMALIZED_DATA_DIR/{section}.ndjson
# and one entry in the 'input' half of NORMALIZED_DATA_MANIFEST.
PAGE_SECTIONS = {
    'indices': ('elements', 'content_categories', 'attributes', 'event_handlers'),
    'dom': ('global_attributes',),  # NOTE! to create a tuple with one element, it needs the trailing comma.
    'input': ('input_types',),
    'syntax': ('element_kinds',),
    'aria': ('aria_roles',),
}

# ---- Manifest ----
RAW_DATA_MANIFEST = RAW_DATA_DIR / 'manifest.json'  # raw per-source fetch timestamps
NORMALIZED_DATA_MANIFEST = NORMALIZED_DATA_DIR / 'manifest.json'  # {'input': {...}, 'output': {...}}
DIST_DATA_MANIFEST = DIST_DATA_DIR / 'manifest.json'

# ---- Logging ----
LOG_LEVEL = 'DEBUG'  # DEBUG INFO WARNING ERROR CRITICAL

# ---- Formatting ----
DUMP_NDJSON_KWARGS = {'sort_keys': False, 'ensure_ascii': False}
DUMP_JSON_KWARGS = {**DUMP_NDJSON_KWARGS, 'indent': 2}
DUMP_YAML_KWARGS = {'sort_keys': False, 'indent': 2, 'allow_unicode': True, 'width': float('inf')}

# ---- Content hash for published data ----
DIST_HASH_FILE = NORMALIZED_DATA_CACHE_DIR / 'dist_content.sha256'  # detects real data changes across publish runs
