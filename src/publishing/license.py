from config import (
    DIST_ROOT_DIR,
    PROJECT_ROOT,
)

# ---- Licenses (single consumer: this driver) ----
LICENSES_DIR = PROJECT_ROOT / 'licenses'
COPYRIGHT_FILE = LICENSES_DIR / 'COPYRIGHT'  # static, copied verbatim to DIST_ROOT_DIR/COPYRIGHT
DIST_COPYRIGHT_FILE = DIST_ROOT_DIR / 'COPYRIGHT'
W3C_LICENSE_FILE = LICENSES_DIR / 'W3C-Document-License.html'  # static, copied verbatim alongside COPYRIGHT
DIST_W3C_LICENSE_FILE = DIST_ROOT_DIR / 'W3C-Document-License.html'


def copy_licenses() -> None:
    """Copy the static licenses/NOTICE file to dist/NOTICE, unmodified."""
    DIST_ROOT_DIR.mkdir(parents=True, exist_ok=True)
    DIST_COPYRIGHT_FILE.write_text(COPYRIGHT_FILE.read_text(encoding='utf-8'), encoding='utf-8')
    DIST_W3C_LICENSE_FILE.write_text(W3C_LICENSE_FILE.read_text(encoding='utf-8'), encoding='utf-8')
