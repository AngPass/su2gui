"""Tests of the server-side file browser logic (ui/server_files.py).

trame is replaced by minimal stubs, so only the navigation/loading logic is
tested, not the rendered dialog.

Run with:  python -m unittest discover -s test -p "test_*.py"
"""

import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _State:
    """Attribute-style state returning None for unknown keys, like trame."""

    def __init__(self):
        object.__setattr__(self, "_data", {})

    def __getattr__(self, name):
        return self._data.get(name)

    def __setattr__(self, name, value):
        self._data[name] = value

    def __getitem__(self, name):
        return self._data.get(name)

    def __setitem__(self, name, value):
        self._data[name] = value

    def dirty(self, *names):
        pass

    def change(self, *names):
        def decorator(func):
            return func
        return decorator


def _import_server_files():
    """Import ui.server_files with trame, ui.uicard and core.logger stubbed."""
    stubs = {}
    trame = types.ModuleType("trame")
    widgets = types.ModuleType("trame.widgets")
    widgets.vuetify = types.ModuleType("trame.widgets.vuetify")
    stubs["trame"], stubs["trame.widgets"], stubs["trame.widgets.vuetify"] = trame, widgets, widgets.vuetify

    uicard = types.ModuleType("ui.uicard")
    uicard.server = types.SimpleNamespace(state=_State(), controller=types.SimpleNamespace())
    stubs["ui.uicard"] = uicard

    logger = types.ModuleType("core.logger")
    logger.messages = []
    logger.log = lambda level, msg, **kw: logger.messages.append((level, msg))
    stubs["core.logger"] = logger

    saved = {k: sys.modules.get(k) for k in list(stubs) + ["ui.server_files"]}
    sys.modules.update(stubs)
    sys.modules.pop("ui.server_files", None)
    try:
        module = importlib.import_module("ui.server_files")
    finally:
        for k, v in saved.items():
            if k == "ui.server_files":
                continue
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return module


class TestServerFileBrowser(unittest.TestCase):
    def setUp(self):
        self.sf = _import_server_files()
        self.state = self.sf.state
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name).resolve()
        (self.dir / "cases").mkdir()
        (self.dir / ".hidden").mkdir()
        (self.dir / "b_mesh.su2").write_bytes(b"NDIME= 2\n")
        (self.dir / "A_mesh.SU2").write_bytes(b"NDIME= 3\n")
        (self.dir / "notes.txt").write_bytes(b"x")
        self.loaded = []
        self.sf.register_server_file_target("mesh", "Load mesh", [".su2"], self.loaded.append)
        self.sf.set_server_browser_root(None)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self):
        return [e["name"] for e in self.state.server_browser_entries]

    def test_listing_dirs_first_filtered_and_no_hidden(self):
        self.state.server_browser_target = "mesh"
        self.sf.server_browser_go(str(self.dir))
        self.assertEqual(self.names(), ["cases", "A_mesh.SU2", "b_mesh.su2"])
        self.state.server_browser_show_all = True
        self.sf.server_browser_go(str(self.dir))
        self.assertIn("notes.txt", self.names())

    def test_open_file_calls_loader_with_bytes(self):
        self.sf.open_server_browser("mesh")
        self.assertTrue(self.state.server_browser_visible)
        self.sf.server_browser_open_entry(str(self.dir / "b_mesh.su2"), False)
        self.assertEqual(len(self.loaded), 1)
        f = self.loaded[0]
        self.assertEqual(f["name"], "b_mesh.su2")
        self.assertEqual(f["content"], b"NDIME= 2\n")
        self.assertEqual(f["size"], len(b"NDIME= 2\n"))
        self.assertFalse(self.state.server_browser_visible)
        # the next opening starts in the directory of the last file
        self.sf.open_server_browser("mesh")
        self.assertEqual(self.state.server_browser_dir, str(self.dir))

    def test_navigation_up_and_into_dir(self):
        self.state.server_browser_target = "mesh"
        self.sf.server_browser_go(str(self.dir / "cases"))
        self.assertEqual(self.state.server_browser_dir, str(self.dir / "cases"))
        self.sf.server_browser_up()
        self.assertEqual(self.state.server_browser_dir, str(self.dir))
        self.sf.server_browser_open_entry(str(self.dir / "cases"), True)
        self.assertEqual(self.state.server_browser_dir, str(self.dir / "cases"))

    def test_typed_file_path_loads_file(self):
        self.state.server_browser_target = "mesh"
        self.sf.server_browser_go(str(self.dir / "A_mesh.SU2"))
        self.assertEqual(self.loaded[0]["name"], "A_mesh.SU2")

    def test_invalid_dir_reports_error(self):
        self.state.server_browser_target = "mesh"
        self.sf.server_browser_go(str(self.dir))
        self.sf.server_browser_go(str(self.dir / "missing"))
        self.assertTrue(self.state.server_browser_error)
        self.assertEqual(self.state.server_browser_dir, str(self.dir))

    def test_root_restriction(self):
        self.sf.set_server_browser_root(self.dir / "cases")
        self.state.server_browser_target = "mesh"
        self.sf.server_browser_go(str(self.dir))
        self.assertIn("outside", self.state.server_browser_error)
        self.sf.server_browser_open_entry(str(self.dir / "b_mesh.su2"), False)
        self.assertEqual(self.loaded, [])
        # going up from the root is refused too
        self.sf.server_browser_home()
        self.assertEqual(self.state.server_browser_dir, str(self.dir / "cases"))
        self.sf.server_browser_up()
        self.assertEqual(self.state.server_browser_dir, str(self.dir / "cases"))


if __name__ == "__main__":
    unittest.main()
