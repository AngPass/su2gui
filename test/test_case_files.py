"""Tests of the case location (core/paths.py) and of the .cfg/.json writer (core/su2_io.py).

Run with:  python -m unittest discover -s test -p "test_*.py"
"""

import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import paths  # noqa: E402
from core import su2_io  # noqa: E402


class TestCasePaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "scratch" / "su2gui_cases"
        self._saved = paths._cases_root

    def tearDown(self):
        paths._cases_root = self._saved
        self.tmp.cleanup()

    def _no_remembered_dir(self, value=None):
        from core import user_config
        saved = user_config.get_cases_dir
        user_config.get_cases_dir = lambda: value
        self.addCleanup(setattr, user_config, "get_cases_dir", saved)

    def test_default_is_installation_user_dir(self):
        self._no_remembered_dir()
        paths._cases_root = None
        old = os.environ.pop(paths.ENV_VAR, None)
        try:
            self.assertEqual(paths.cases_root(), paths.APP_USER_DIR)
        finally:
            if old is not None:
                os.environ[paths.ENV_VAR] = old

    def test_remembered_dir_is_used_at_start(self):
        self.root.mkdir(parents=True)
        self._no_remembered_dir(str(self.root))
        paths._cases_root = None
        old = os.environ.pop(paths.ENV_VAR, None)
        try:
            self.assertEqual(paths.cases_root(), self.root)
        finally:
            if old is not None:
                os.environ[paths.ENV_VAR] = old

    def test_active_case_stays_in_its_folder(self):
        first = self.root / "first"
        paths.set_cases_root(first)
        paths.mark_case_dir(first / "naca")
        paths.set_active_case("naca", first / "naca")
        self.addCleanup(paths.set_active_case, None)
        # the user shows the cases of another folder: the open case does not move
        paths.set_cases_root(self.root / "second")
        self.assertEqual(paths.case_dir("naca"), first / "naca")
        self.assertEqual(paths.case_dir("other"), self.root / "second" / "other")

    def test_env_var_and_cli(self):
        paths._cases_root = None
        os.environ[paths.ENV_VAR] = str(self.root)
        try:
            self.assertEqual(paths.cases_root(), self.root)
        finally:
            del os.environ[paths.ENV_VAR]
        other = self.root.parent / "other"
        self.assertEqual(paths.set_cases_root(other), other)   # --cases-dir wins
        self.assertTrue(other.is_dir())                        # created
        self.assertEqual(paths.case_dir("naca"), other / "naca")
        self.assertEqual(paths.case_dir(""), other)

    def test_only_marked_dirs_are_cases_in_custom_root(self):
        paths.set_cases_root(self.root)
        paths.mark_case_dir(self.root / "naca")
        (self.root / "my_data").mkdir()          # unrelated data in the same folder
        (self.root / "file.txt").write_text("x")
        self.assertEqual(paths.list_cases(), ["naca"])
        self.assertTrue(paths.is_case_dir(self.root / "naca"))
        self.assertFalse(paths.is_case_dir(self.root / "my_data"))

    def test_case_names(self):
        for good in ("naca", "naca_0012", "run-1"):
            self.assertTrue(paths.is_valid_case_name(good), good)
        for bad in ("", ".", "..", "../x", "a/b", "a\\b", ".hidden", None):
            self.assertFalse(paths.is_valid_case_name(bad), bad)


class TestCfgWriter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved_root = paths._cases_root
        paths.set_cases_root(Path(self.tmp.name) / "cases")
        self.bc = [
            {"bcName": "wall", "bc_subtype": "Temperature", "bc_temperature": 300.0},
            {"bcName": "farfield", "bc_subtype": "Far-field"},
            {"bcName": "in1", "bc_subtype": "Total Conditions", "bc_temperature": 288.15,
             "bc_pressure": 101325.0, "bc_velocity_normal": [1.0, 0.0, 0.0]},
        ]
        self.state = types.SimpleNamespace(
            case_name="naca", jsonData={"SOLVER": "RANS", "RESTART_SOL": False, "ITER": 100,
                                        "MARKER_MONITORING": ["wall"], "OLD_EMPTY": []},
            BCDictList=self.bc, wall_function=False, config_desc="% test case\n")
        su2_io.state = self.state

    def tearDown(self):
        paths._cases_root = self._saved_root
        self.tmp.cleanup()

    def test_deprecated_option_is_renamed_in_cfg(self):
        self.state.jsonData["INC_INLET_USENORMAL"] = True
        su2_io.write_case_configuration("c.json", "c.cfg", update_state=False, variables={})
        text = (paths.case_dir("naca") / "c.cfg").read_text()
        self.assertIn("INLET_USE_NORMAL= YES", text)
        self.assertNotIn("INC_INLET_USENORMAL", text)

    def test_case_configuration_is_pure(self):
        before = dict(self.state.jsonData)
        cfg = su2_io.case_configuration(self.state.jsonData, self.bc, False)
        self.assertEqual(self.state.jsonData, before)          # state not modified
        self.assertEqual(cfg["MARKER_ISOTHERMAL"], [["wall", 300.0]])
        self.assertEqual(cfg["MARKER_FAR"], [["farfield"]])
        self.assertEqual(cfg["INLET_TYPE"], "TOTAL_CONDITIONS")  # single enum in SU2
        self.assertNotIn("OLD_EMPTY", cfg)
        self.assertNotIn("MARKER_WALL_FUNCTIONS", cfg)

    def test_cfg_text(self):
        cfg = {"A": True, "B": False, "M": [("wall", 300.0)], "L": [["a", 1], ["b", 2]], "N": None, "S": "x"}
        text = su2_io.build_cfg_text(cfg)
        self.assertIn("A= YES\n", text)
        self.assertIn("B= NO\n", text)
        self.assertIn("M= (wall, 300.0)\n", text)       # tuples are flattened too
        self.assertIn("L= (a, 1, b, 2)\n", text)
        self.assertNotIn("N=", text)

    def test_variables_are_substituted_in_cfg_only(self):
        self.state.jsonData["DEFORM"] = ["__AMP__", 2]
        written = su2_io.write_case_configuration("c.json", "c.cfg", update_state=False,
                                                  variables={"__AMP__": 0.045})
        case = paths.case_dir("naca")
        self.assertIn("DEFORM= (0.045, 2)", (case / "c.cfg").read_text())
        self.assertIn('"__AMP__"', (case / "c.json").read_text())
        self.assertEqual(len(written), 2)

    def test_written_only_when_changed(self):
        case = paths.case_dir("naca")
        w1 = su2_io.write_case_configuration("c.json", "c.cfg", update_state=False, variables={})
        self.assertEqual({p.name for p in w1}, {"c.json", "c.cfg"})
        mtime = (case / "c.cfg").stat().st_mtime_ns
        time.sleep(0.01)
        self.assertEqual(su2_io.write_case_configuration("c.json", "c.cfg", update_state=False, variables={}), [])
        self.assertEqual((case / "c.cfg").stat().st_mtime_ns, mtime)

        # a change in the GUI (here: a boundary condition) is written at the next check
        self.bc[0]["bc_temperature"] = 350.0
        w2 = su2_io.write_case_configuration("c.json", "c.cfg", update_state=False, variables={})
        self.assertEqual({p.name for p in w2}, {"c.json", "c.cfg"})
        self.assertIn("MARKER_ISOTHERMAL= (wall, 350.0)", (case / "c.cfg").read_text())
        self.assertFalse((case / "c.cfg.tmp").exists())

    def test_no_case_no_write(self):
        self.state.case_name = ""
        self.assertEqual(su2_io.write_case_configuration("c.json", "c.cfg", update_state=False), [])


if __name__ == "__main__":
    unittest.main()
