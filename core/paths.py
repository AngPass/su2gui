"""Location of the SU2GUI cases.

Every case is a directory ``<cases root>/<case name>`` that holds the mesh, the
.cfg/.json configuration, the SU2 output (history, restart, volume files) and
the logs. The cases root is, in order of precedence:

1. the folder chosen in the GUI or with the ``--cases-dir`` option (set_cases_root),
2. the ``SU2GUI_CASES_DIR`` environment variable,
3. the folder chosen the last time (remembered in the user configuration file),
4. ``<SU2GUI installation>/user`` (historical default).

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
    try:
        from core.user_config import get_cases_dir
        last = get_cases_dir()
        if last and Path(last).is_dir():
            return Path(last).resolve()
    except Exception:
        pass
    return APP_USER_DIR


def set_cases_root(path, remember=False):
    """Use ``path`` as the directory containing the cases (created if needed).

    With remember=True the folder is also used at the next start.
    """
    global _cases_root
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    _cases_root = root
    if remember:
        try:
            from core.user_config import set_cases_dir
            set_cases_dir(root)
        except Exception:
            pass
    return root


def cases_root():
    """Directory containing all cases."""
    return _cases_root if _cases_root is not None else _default_root()


# (name, directory) of the active case: it stays where it was created/loaded also
# when the cases folder is changed afterwards
_active_case = None


def set_active_case(case_name, directory=None):
    """Record the directory of the active case (default: <cases root>/<name>)."""
    global _active_case
    if not case_name:
        _active_case = None
        return None
    directory = Path(directory).expanduser().resolve() if directory else cases_root() / str(case_name)
    _active_case = (str(case_name), directory)
    return directory


def case_dir(case_name):
    """Directory of the case ``case_name`` (the cases root if the name is empty)."""
    if not case_name:
        return cases_root()
    if _active_case is not None and _active_case[0] == str(case_name):
        return _active_case[1]
    return cases_root() / str(case_name)


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
