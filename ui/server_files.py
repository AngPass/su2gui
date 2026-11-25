"""Server-side file browser.

The VFileInput widgets use the file picker of the *browser*, so they show the
files of the machine running the browser (e.g. the user's PC when SU2GUI runs
on a cluster node behind an SSH tunnel). This dialog lists the filesystem of
the machine running the SU2GUI server instead, and passes the selected file to
the same loader used by the upload widget. The file is read on the server and
never travels through the browser.

Usage (su2gui.py):
    register_server_file_target("mesh", "Load .su2 mesh", [".su2"], load_file_su2)
    server_browser_dialog()               # once, inside the layout
    server_file_button("mesh", "...")     # next to the upload widget
"""

import mimetypes
import os
import sys
from pathlib import Path

parent_dir = str(Path(__file__).parent.parent.absolute())
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from trame.widgets import vuetify, html

from ui.uicard import server
from core.logger import log

state, ctrl = server.state, server.controller

# maximum number of entries sent to the browser for one directory
MAX_ENTRIES = 2000

# target name -> {"title", "extensions", "handler", "last_dir"}
_targets = {}

# optional directories outside of which browsing is not allowed (empty: no restriction)
_roots = []
# quick-access directories shown in the dialog (the roots, or home when unrestricted)
_places = []

state.server_browser_visible = False
state.server_browser_title = ""
state.server_browser_target = ""
state.server_browser_dir = ""
state.server_browser_path = ""
state.server_browser_entries = []
state.server_browser_error = ""
state.server_browser_info = ""
state.server_browser_show_all = False
state.server_browser_places = []
state.server_browser_pick_dir = False


def _update_places(extra=()):
    """Quick-access buttons: the roots if restricted, otherwise home plus ``extra``."""
    places = list(_roots) if _roots else [Path.home()] + [Path(p).expanduser().resolve() for p in extra]
    seen, unique = set(), []
    for p in places:
        if str(p) not in seen:
            seen.add(str(p))
            unique.append(p)
    _places[:] = unique
    state.server_browser_places = [{"label": str(p), "path": str(p)} for p in unique]


def set_server_browser_root(paths):
    """Restrict browsing to ``paths`` (a path or a list of paths) and their subdirectories.

    None or an empty list removes the restriction.
    """
    if paths is None:
        paths = []
    elif isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    _roots[:] = [Path(p).expanduser().resolve() for p in paths]
    _update_places()
    if _roots:
        log("info", f"Server file browser restricted to {', '.join(str(r) for r in _roots)}")


def add_server_browser_places(paths):
    """Extra quick-access directories when browsing is not restricted."""
    if not _roots:
        _update_places(paths)


_update_places()


def register_server_file_target(name, title, extensions, handler):
    """Register a loader that receives the selected file.

    ``handler`` is called with the same dictionary the upload widget produces:
    {"name", "size", "type", "content"} with ``content`` as bytes.
    """
    _targets[name] = {
        "title": title,
        "extensions": tuple(e.lower() for e in extensions),
        "handler": handler,
        "last_dir": None,
        "dirs_only": False,
    }


def register_server_dir_target(name, title, handler):
    """Register a target that selects a directory: ``handler(Path)`` is called with the
    directory shown in the path field (it may not exist yet, the handler creates it)."""
    _targets[name] = {
        "title": title,
        "extensions": (),
        "handler": handler,
        "last_dir": None,
        "dirs_only": True,
    }


def _start_dir():
    if _roots:
        return _roots[0]
    return Path.home()


def _allowed(path):
    if not _roots:
        return True
    for root in _roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def is_allowed_path(path):
    """True if ``path`` is inside the folders allowed by --browse-root (or no restriction)."""
    return _allowed(Path(path).expanduser().resolve())


def _outside_message(path):
    return f"{path} is outside of the allowed directories ({', '.join(str(r) for r in _roots)})"


def _format_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0


def _list_dir(directory, target):
    """Directories first, then the files matching the target extensions."""
    show_all = bool(state.server_browser_show_all)
    extensions = target["extensions"]
    dirs, files = [], []
    with os.scandir(directory) as it:
        for entry in it:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": entry.path, "is_dir": True, "size": ""})
                elif entry.is_file():
                    if target.get("dirs_only") and not show_all:
                        continue
                    if not show_all and extensions and not entry.name.lower().endswith(extensions):
                        continue
                    files.append({"name": entry.name, "path": entry.path, "is_dir": False,
                                  "size": _format_size(entry.stat().st_size)})
            except OSError:
                continue  # broken link or no permission
    dirs.sort(key=lambda e: e["name"].lower())
    files.sort(key=lambda e: e["name"].lower())
    return dirs + files


def _show_dir(directory):
    target = _targets.get(state.server_browser_target)
    if target is None:
        return
    directory = Path(directory).expanduser()
    try:
        directory = directory.resolve()
        if not directory.is_dir():
            raise NotADirectoryError(f"{directory} is not a directory")
        if not _allowed(directory):
            raise PermissionError(_outside_message(directory))
        entries = _list_dir(directory, target)
    except OSError as e:
        state.server_browser_error = str(e)
        return

    state.server_browser_error = ""
    state.server_browser_info = ""
    if len(entries) > MAX_ENTRIES:
        state.server_browser_info = f"Showing the first {MAX_ENTRIES} of {len(entries)} entries"
        entries = entries[:MAX_ENTRIES]
    state.server_browser_dir = str(directory)
    state.server_browser_path = str(directory)
    state.server_browser_entries = entries
    target["last_dir"] = directory


def open_server_browser(target_name, start_dir=None):
    target = _targets.get(target_name)
    if target is None:
        log("error", f"Unknown server file target: {target_name}")
        return
    state.server_browser_target = target_name
    state.server_browser_title = target["title"]
    state.server_browser_show_all = False
    state.server_browser_pick_dir = bool(target.get("dirs_only"))
    start = (Path(start_dir) if start_dir and Path(start_dir).expanduser().is_dir() else None) \
        or target["last_dir"] or (Path(state.server_browser_dir) if state.server_browser_dir else _start_dir())
    _show_dir(start)
    if state.server_browser_error:
        _show_dir(_start_dir())
    state.server_browser_visible = True


def server_browser_go(path):
    """Go to the directory typed in the path field (a file path loads the file)."""
    if not path:
        return
    p = Path(str(path).strip()).expanduser()
    if p.is_file():
        server_browser_open_entry(str(p), False)
    else:
        _show_dir(p)


def server_browser_up():
    current = Path(state.server_browser_dir or _start_dir())
    if current.parent != current:
        _show_dir(current.parent)


def server_browser_home():
    _show_dir(_start_dir())


def server_browser_close():
    state.server_browser_visible = False


def server_browser_use_dir(path=None):
    """Directory targets: use the folder typed in the path field (or the current one)."""
    target = _targets.get(state.server_browser_target)
    if target is None or not target.get("dirs_only"):
        return
    p = Path(str(path or state.server_browser_dir or _start_dir()).strip()).expanduser()
    if not p.is_absolute():
        p = Path(state.server_browser_dir or _start_dir()) / p
    p = p.resolve()
    if p.exists() and not p.is_dir():
        state.server_browser_error = f"{p} is a file, not a folder"
        return
    if not _allowed(p):
        state.server_browser_error = _outside_message(p)
        return
    target["last_dir"] = p if p.is_dir() else p.parent
    state.server_browser_visible = False
    try:
        target["handler"](p)
    except Exception as e:
        import traceback
        log("error", f"Could not use the folder {p}: {e}", detail=traceback.format_exc())


def server_browser_open_entry(path, is_dir):
    if is_dir:
        _show_dir(path)
        return

    target = _targets.get(state.server_browser_target)
    if target is None:
        return
    p = Path(path).expanduser().resolve()
    if not _allowed(p):
        state.server_browser_error = _outside_message(p)
        return
    try:
        content = p.read_bytes()
    except OSError as e:
        state.server_browser_error = f"Could not read {p}: {e}"
        return

    file_dict = {
        "name": p.name,
        "size": len(content),
        "type": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
        "content": content,
    }
    target["last_dir"] = p.parent
    state.server_browser_visible = False
    log("info", f"Loading {p} from the server filesystem")
    try:
        target["handler"](file_dict)
    except Exception as e:
        import traceback
        log("error", f"Could not load {p}: {e}", detail=traceback.format_exc())


@state.change("server_browser_show_all")
def _update_show_all(server_browser_show_all, **kwargs):
    if state.server_browser_visible and state.server_browser_dir:
        _show_dir(state.server_browser_dir)


def server_file_button(target_name, tooltip):
    """Small button that opens the server browser for ``target_name``."""
    with vuetify.VBtn(
        icon=True,
        small=True,
        click=(open_server_browser, f"['{target_name}']"),
        title=tooltip,
        __properties=["title"],
    ):
        vuetify.VIcon("mdi-server")


def server_browser_dialog():
    """The dialog; create it once inside the layout."""
    with vuetify.VDialog(v_model=("server_browser_visible", False), width=750, scrollable=True):
        with vuetify.VCard():
            vuetify.VCardTitle("{{ server_browser_title }} (server files)",
                               classes="grey lighten-1 py-1 grey--text text--darken-3")

            with vuetify.VCardText(classes="pt-3", style="max-height: 70vh;"):
                with vuetify.VRow(classes="align-center", dense=True):
                    with vuetify.VBtn(icon=True, small=True, click=server_browser_up,
                                      title="Parent directory", __properties=["title"]):
                        vuetify.VIcon("mdi-arrow-up")
                    with vuetify.VBtn(icon=True, small=True, click=server_browser_home,
                                      title="Home directory", __properties=["title"]):
                        vuetify.VIcon("mdi-home")
                    vuetify.VTextField(
                        v_model=("server_browser_path", ""),
                        label="Directory or file on the server",
                        dense=True,
                        hide_details=True,
                        outlined=True,
                        classes="mx-2",
                    )
                    vuetify.VBtn("Go", small=True, click=(server_browser_go, "[server_browser_path]"))

                # quick access: allowed directories (or home + --browse-place directories)
                with vuetify.VRow(dense=True, classes="mt-2"):
                    with vuetify.VChip(
                        v_for="(place, j) in server_browser_places",
                        key="place.path",
                        small=True,
                        outlined=True,
                        classes="mr-1 mb-1",
                        click=(server_browser_go, "[place.path]"),
                    ):
                        vuetify.VIcon("mdi-folder-star-outline", left=True, small=True)
                        html.Span("{{ place.label }}")

                vuetify.VCheckbox(
                    v_model=("server_browser_show_all", False),
                    label="Show all files",
                    dense=True,
                    hide_details=True,
                    classes="mt-1",
                )
                vuetify.VAlert("{{ server_browser_error }}", v_show=("server_browser_error",),
                               type="error", dense=True, outlined=True, classes="mt-2")
                vuetify.VAlert("{{ server_browser_info }}", v_show=("server_browser_info",),
                               type="info", dense=True, outlined=True, classes="mt-2")

                with vuetify.VList(dense=True):
                    with vuetify.VListItem(
                        v_for="(entry, i) in server_browser_entries",
                        key="entry.path",
                        click=(server_browser_open_entry, "[entry.path, entry.is_dir]"),
                    ):
                        with vuetify.VListItemIcon(classes="mr-2"):
                            vuetify.VIcon("{{ entry.is_dir ? 'mdi-folder' : 'mdi-file-outline' }}",
                                          small=True)
                        with vuetify.VListItemContent():
                            vuetify.VListItemTitle("{{ entry.name }}")
                        vuetify.VListItemActionText("{{ entry.size }}")
                    with vuetify.VListItem(v_if="server_browser_entries.length === 0"):
                        vuetify.VListItemTitle("{{ server_browser_pick_dir ? 'No subfolders' : 'No matching files in this directory' }}",
                                               classes="grey--text")

            with vuetify.VCardActions():
                vuetify.VSpacer()
                # folder selection: the folder in the path field (it can be a new one)
                vuetify.VBtn("Use this folder", v_if="server_browser_pick_dir", color="primary",
                             click=(server_browser_use_dir, "[server_browser_path]"))
                vuetify.VBtn("Close", click=server_browser_close)
