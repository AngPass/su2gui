"""Location of the SU2GUI cases.

Every case is a directory ``<cases root>/<case name>`` that holds the mesh, the
.cfg/.json configuration, the SU2 output (history, restart, volume files) and
the logs. The cases root is, in order of precedence:

1. the ``--cases-dir`` command line option (set_cases_root),
2. the ``SU2GUI_CASES_DIR`` environment variable,
3. ``<SU2GUI installation>/user`` (historical default).

Application files that are not part of a case (the default config template
``user/config.json``, the JSON schema in ``user/start``, the global
``su2gui.log``) stay in the installation directory: see ``APP_USER_DIR``.

This module has no trame dependency so it can be imported everywhere.
"""

import os
from pathlib import Path

# SU2GUI installation directory
BASE = Path(__file__).resolve().parent.parent

# application data shipped with SU2GUI (templates, schema, global log)
APP_USER_DIR = BASE / "user"

ENV_VAR = "SU2GUI_CASES_DIR"

_cases_root = None


def _default_root():
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    return APP_USER_DIR


def set_cases_root(path):
    """Use ``path`` as the directory containing the cases (created if needed)."""
    global _cases_root
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    _cases_root = root
    return root


def cases_root():
    """Directory containing all cases."""
    return _cases_root if _cases_root is not None else _default_root()


def case_dir(case_name):
    """Directory of the case ``case_name`` (the cases root if the name is empty)."""
    root = cases_root()
    if not case_name:
        return root
    return root / str(case_name)


# File created in every case directory. With a custom cases root (which may be
# e.g. a scratch directory with other data) only directories holding this marker
# are listed and can be deleted by the GUI.
CASE_MARKER = ".su2gui_case"


def is_valid_case_name(name):
    """A case name must be a plain directory name (no path separators, not . or ..)."""
    if not name or not isinstance(name, str):
        return False
    if name in (".", "..") or name.startswith("."):
        return False
    return not any(sep in name for sep in ("/", "\\", os.sep)) and "\0" not in name


def mark_case_dir(path):
    """Mark ``path`` as an SU2GUI case directory."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / CASE_MARKER).touch(exist_ok=True)


def is_case_dir(path):
    """True for directories created by SU2GUI.

    In the historical root (``<installation>/user``) every subdirectory is a
    case, also the ones created before the marker existed.
    """
    path = Path(path)
    if not path.is_dir():
        return False
    if (path / CASE_MARKER).is_file():
        return True
    return path.resolve().parent == APP_USER_DIR.resolve() and cases_root().resolve() == APP_USER_DIR.resolve()


def list_cases():
    """Names of the cases in the cases root."""
    root = cases_root()
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [n for n in names if is_case_dir(root / n)]
