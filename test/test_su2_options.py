"""Tests of the SU2 option catalog (core/su2_options.py, core/su2_options.json).

Run with:  python -m unittest discover -s test -p "test_*.py"
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import su2_options as so  # noqa: E402


class TestCatalog(unittest.TestCase):
    def test_catalog_content(self):
        names = so.option_names()
        self.assertGreater(len(names), 700)
        for name in ("SOLVER", "MARKER_INLET", "INLET_USE_NORMAL", "CONV_FIELD", "OUTPUT_WRT_FREQ"):
            self.assertIn(name, names)
        self.assertNotIn("INC_INLET_USENORMAL", names)
        self.assertIn("INC_LES", so.catalog()["options"]["SOLVER"]["values"])

    def test_migrate_deprecated(self):
        cfg, messages = so.migrate({"INC_INLET_USENORMAL": True, "SOLVER": "INC_RANS"})
        self.assertEqual(cfg, {"INLET_USE_NORMAL": True, "SOLVER": "INC_RANS"})
        self.assertEqual(len(messages), 1)
        # the new name wins if both are present
        cfg, _ = so.migrate({"INC_INLET_USENORMAL": True, "INLET_USE_NORMAL": False})
        self.assertEqual(cfg, {"INLET_USE_NORMAL": False})
        # deprecated without replacement: removed
        cfg, messages = so.migrate({"DATADRIVEN_INITIAL_DENSITY": 1.0})
        self.assertEqual(cfg, {})
        self.assertIn("removed", messages[0])

    def test_check(self):
        issues = dict(so.check({
            "SOLVR": "EULER",                          # typo
            "SOLVER": "INC_RAMS",                      # invalid enum
            "INLET_TYPE": ["TOTAL_CONDITIONS", "MASS_FLOW"],   # single enum
            "RESTART_SOL": "MAYBE",                    # bool
            "SA_OPTIONS": "WITHFT2 NEGATIVE",          # valid enum list
            "ITER": 100,
        }))
        self.assertIn("did you mean SOLVER", issues["SOLVR"])
        self.assertIn("INC_RAMS", issues["SOLVER"])
        self.assertIn("single value", issues["INLET_TYPE"])
        self.assertIn("YES or NO", issues["RESTART_SOL"])
        self.assertNotIn("SA_OPTIONS", issues)
        self.assertNotIn("ITER", issues)

    def test_default_template_is_valid(self):
        cfg = json.loads((ROOT / "user" / "config.json").read_text(encoding="utf-8"))
        cfg, messages = so.migrate(cfg)
        self.assertEqual(messages, [])
        self.assertEqual(so.check(cfg), [])
        self.assertFalse(cfg["RESTART_SOL"])   # a new case has no restart file


if __name__ == "__main__":
    unittest.main()
