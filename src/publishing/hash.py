from hashlib import sha256
from pathlib import Path

from config import DIST_HASH_FILE


def hash_update(dirs: list[Path]) -> bool:
    """Compare a fresh content hash of dirs against the stored stamp; rewrite the stamp only if it changed.

    Returns:
        True if the content changed since the last run, False if not.
    """
    new_hash = _hash_compute(dirs)
    old_hash = DIST_HASH_FILE.read_text(encoding='utf-8').strip() if DIST_HASH_FILE.exists() else None
    if new_hash == old_hash:
        return False
    DIST_HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    DIST_HASH_FILE.write_text(new_hash, encoding='utf-8')
    return True


def _hash_compute(dirs: list[Path]) -> str:
    """Hash file paths and contents across dirs, sorted for determinism.

    Used to detect real data changes between publish runs, since DIST_DATA_MANIFEST always changes
    (source timestamps, git version info), even when the actual published data has not.

    Returns:
        Hash computed for the content and file paths in the input path
    """
    digest = sha256()
    for d in dirs:
        for path in sorted(d.rglob('*')):
            if path.is_file():
                digest.update(str(path.relative_to(d)).encode('utf-8'))
                digest.update(path.read_bytes())
    return digest.hexdigest()
