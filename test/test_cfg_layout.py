"""Tests of the layout of the .cfg file (core/cfg_layout.py) and of the option catalog metadata.

Run with:  python -m unittest discover -s test -p "test_*.py"
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import cfg_layout as L  # noqa: E402
from core import su2_options  # noqa: E402
from core import su2_io  # noqa: E402


class TestLayout(unittest.TestCase):
    def test_every_su2_option_has_a_menu_node(self):
        names = su2_options.option_names()
        orphans = [n for n in names if L.node_of(n) not in L.NODES]
        self.assertEqual(orphans, [])
        for sec in L.SECTIONS:
            self.assertIn(sec.node, L.NODES)
            for key in sec.keys:
                self.assertIn(key, names, f"{sec.id}: {key}")

    def test_known_options(self):
        self.assertEqual(L.node_of("SOLVER"), "Physics")
        self.assertEqual(L.node_of("MESH_FILENAME"), "Mesh")
        self.assertEqual(L.node_of("MACH_NUMBER"), "Flow Conditions")
        self.assertEqual(L.node_of("CONV_NUM_METHOD_FLOW"), "Numerics")
        self.assertEqual(L.node_of("TIME_STEP"), "Time Domain")
        self.assertEqual(L.node_of("MARKER_FAR"), "Boundaries")
        self.assertEqual(L.node_of("GRID_MOVEMENT"), "Dynamic Mesh")
        self.assertEqual(L.node_of("RESTART_SOL"), "Initialization")
        self.assertEqual(L.node_of("DV_KIND"), "Adjoint & Design")
        self.assertEqual(L.node_of("VOLUME_OUTPUT"), "File I/O")
        self.assertEqual(L.node_of("ITER"), "Solver")
        self.assertEqual(L.node_of("NOT_AN_OPTION"), L.OTHER_NODE)

    def test_cfg_follows_the_menu(self):
        cfg = {"ITER": 10, "MARKER_FAR": ["far"], "SOLVER": "EULER", "MESH_FILENAME": "m.su2",
               "MACH_NUMBER": 0.8, "KIND_TURB_MODEL": "NONE", "MY_OPTION": 1}
        text = su2_io.build_cfg_text(cfg, "% header\n")
        lines = text.splitlines()
        self.assertEqual(lines[0], "% header")
        order = [l.split("=")[0] for l in lines if "=" in l and not l.startswith("%")]
        # (values "NONE" are not written, see su2_io.cfg_value)
        self.assertEqual(order, ["MESH_FILENAME", "SOLVER", "MACH_NUMBER",
                                 "MARKER_FAR", "ITER", "MY_OPTION"])
        self.assertIn("% 2. PHYSICS", text)
        self.assertIn(" Problem definition ", text)
        self.assertIn("OTHER", text)
        # every non-option line is a comment or empty: SU2 and the GUI read it back
        for line in lines:
            self.assertTrue(line == "" or line.startswith("%") or "= " in line, line)
        self.assertTrue(all(len(l) <= 80 for l in lines if l.startswith("%")))


class TestValues(unittest.TestCase):
    def test_editor_kind(self):
        self.assertEqual(L.editor_kind("SOLVER"), "enum")
        self.assertEqual(L.editor_kind("RESTART_SOL"), "bool")
        self.assertEqual(L.editor_kind("OUTPUT_FILES"), "enumlist")
        self.assertEqual(L.editor_kind("MARKER_PLOTTING"), "markers")
        self.assertEqual(L.editor_kind("MACH_NUMBER"), "text")
        self.assertEqual(L.editor_kind("CONV_NUM_METHOD_FLOW"), "enum")

    def test_parse(self):
        self.assertEqual(L.parse_value("MACH_NUMBER", "0.8"), 0.8)
        self.assertEqual(L.parse_value("ITER", "100"), 100)
        self.assertEqual(L.parse_value("MACH_NUMBER", "__M__"), "__M__")    # user variable
        self.assertEqual(L.parse_value("MACH_NUMBER", ""), None)            # removed
        self.assertIs(L.parse_value("RESTART_SOL", "YES"), True)
        self.assertEqual(L.parse_value("SOLVER", "RANS"), "RANS")
        self.assertEqual(L.parse_value("FREESTREAM_VELOCITY", "(1, 0.0, 0)"), [1, 0.0, 0])
        self.assertEqual(L.parse_value("MARKER_PLOTTING", ["wall", "flap"]), ["wall", "flap"])
        self.assertEqual(L.parse_value("MARKER_PLOTTING", []), None)
        self.assertEqual(L.parse_value("SCREEN_OUTPUT", "INNER_ITER, RMS_RES"), ["INNER_ITER", "RMS_RES"])

    def test_format_and_compare(self):
        self.assertEqual(L.format_value("RESTART_SOL", False), "NO")
        self.assertEqual(L.format_value("SA_OPTIONS", "WITHFT2 NEGATIVE "), ["WITHFT2", "NEGATIVE"])
        self.assertEqual(L.format_value("FREESTREAM_VELOCITY", [1.0, 0.0, 0.0]), "1.0, 0.0, 0.0")
        self.assertTrue(L.same_value("WITHFT2 NEGATIVE ", ["WITHFT2", "NEGATIVE"]))
        self.assertTrue(L.same_value(1, "1.0"))
        self.assertTrue(L.same_value(True, "YES"))
        self.assertFalse(L.same_value(0.8, 0.9))

    def test_catalog_metadata(self):
        info = L.option_info("MACH_NUMBER")
        self.assertEqual(info["default"], "0.0")
        self.assertIn("Mach", info["description"])
        self.assertEqual(L.option_info("SOLVER")["default"], "NONE")
        self.assertIn("ROE", L.option_info("CONV_NUM_METHOD_FLOW")["values"])


if __name__ == "__main__":
    unittest.main()
