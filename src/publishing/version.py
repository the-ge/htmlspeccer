import shutil
import subprocess  # noqa: S404


def get_repo_version() -> dict[str, str]:
    """Get repo version information.

    Returns:
        - official_release (nearest repo tag, empty if none exist),
        - current_tag (nearest repo tag plus distance/dirty suffix), and
        - current_commit_id (full HEAD SHA).

    Raises:
        FileNotFoundError: if `git` not found
    """
    git = shutil.which('git')
    if git is None:
        msg = 'git executable not found on PATH'
        raise FileNotFoundError(msg)

    try:
        official_release = subprocess.run(  # noqa: S603
            [git, 'describe', '--tags', '--abbrev=0'],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        official_release = ''

    current_tag = subprocess.run(  # noqa: S603
        [git, 'describe', '--tags', '--always', '--dirty'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    current_commit_id = subprocess.run(  # noqa: S603
        [git, 'rev-parse', 'HEAD'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    return {
        'generator_release': official_release,
        'generator_tag': current_tag,
        'generator_commit_id': current_commit_id,
    }
