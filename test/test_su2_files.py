"""Unit tests for core/su2_files.py.

The test files are written with the same layout as the SU2 (develop) writers:
CSU2BinaryFileWriter (binary restart) and CSU2FileWriter (ASCII restart).

Run with:  python -m unittest discover -s test -p "test_*.py"
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import su2_files as sf  # noqa: E402


def write_su2_binary(path, names, data, precision_field=0, legacy_trailer=False):
    """Mimic CSU2BinaryFileWriter::WriteData."""
    n_points, n_vars = data.shape
    scalar = 4 if precision_field == 4 else 8
    header = np.array([sf.SU2_RESTART_MAGIC_NUMBER, n_vars, n_points, precision_field, 0], dtype="<i4")
    if legacy_trailer:
        header[3], header[4] = 1, 5
    with open(path, "wb") as f:
        f.write(header.tobytes())
        for name in names:
            buf = name.encode("ascii")[: sf.CGNS_STRING_SIZE]
            f.write(buf + b"\x00" * (sf.CGNS_STRING_SIZE - len(buf)))
        f.write(data.astype("<f8" if scalar == 8 else "<f4").tobytes())
        if legacy_trailer:
            f.write(np.array([10], dtype="<i4").tobytes())
            f.write(np.zeros(5, dtype="<f8").tobytes())


def write_su2_csv(path, names, data):
    """Mimic CSU2FileWriter: quoted header starting with PointID, one line per point."""
    with open(path, "w") as f:
        f.write('"PointID"' + "".join(f',"{n}"' for n in names) + "\n")
        for i, row in enumerate(data):
            f.write(str(i) + "".join(f", {v:.15e}" for v in row) + "\n")


class TestRestartFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.names = ["x", "y", "Pressure", "Velocity_x", "Velocity_y"]
        rng = np.random.default_rng(0)
        self.data = rng.normal(size=(7, len(self.names)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_binary_double(self):
        p = self.dir / "restart.dat"
        write_su2_binary(p, self.names, self.data)
        self.assertTrue(sf.is_su2_binary_restart(p))
        df = sf.read_su2_restart(p)
        self.assertEqual(list(df.columns), self.names)
        np.testing.assert_array_equal(df.to_numpy(), self.data)
        self.assertEqual(sf.solution_fields(df), ["Pressure", "Velocity_x", "Velocity_y"])

    def test_binary_single_precision(self):
        p = self.dir / "restart.dat"
        write_su2_binary(p, self.names, self.data, precision_field=4)
        df = sf.read_su2_restart(p)
        np.testing.assert_allclose(df.to_numpy(), self.data.astype(np.float32), rtol=0)

    def test_binary_legacy_trailer_is_ignored(self):
        p = self.dir / "restart.dat"
        write_su2_binary(p, self.names, self.data, legacy_trailer=True)
        df = sf.read_su2_restart(p)
        np.testing.assert_array_equal(df.to_numpy(), self.data)

    def test_binary_truncated_raises(self):
        p = self.dir / "restart.dat"
        write_su2_binary(p, self.names, self.data)
        raw = p.read_bytes()
        p.write_bytes(raw[:-16])  # SU2 still writing
        with self.assertRaises(ValueError):
            sf.read_su2_binary_restart(p)

    def test_ascii_csv(self):
        p = self.dir / "restart.csv"
        write_su2_csv(p, self.names, self.data)
        self.assertFalse(sf.is_su2_binary_restart(p))
        df = sf.read_su2_restart(p)
        self.assertEqual(list(df.columns), ["PointID"] + self.names)
        np.testing.assert_allclose(df[self.names].to_numpy(), self.data, rtol=1e-14)
        self.assertEqual(sf.solution_fields(df), ["Pressure", "Velocity_x", "Velocity_y"])

    def test_ascii_csv_3d_drops_z(self):
        names = ["x", "y", "z", "Density"]
        data = np.ones((3, 4))
        p = self.dir / "restart.csv"
        write_su2_csv(p, names, data)
        self.assertEqual(sf.solution_fields(sf.read_su2_restart(p)), ["Density"])

    def test_bytes_magic(self):
        p = self.dir / "restart.dat"
        write_su2_binary(p, self.names, self.data)
        self.assertTrue(sf.bytes_are_su2_binary_restart(p.read_bytes()))
        self.assertFalse(sf.bytes_are_su2_binary_restart(b'"PointID","x"\n'))


class TestFileNames(unittest.TestCase):
    def test_trim_extension_only_at_end(self):
        self.assertEqual(sf.trim_extension("restart.dat", ".dat"), "restart")
        self.assertEqual(sf.trim_extension("restart.dat.bak", ".dat"), "restart.dat.bak")
        self.assertEqual(sf.trim_extension("restart", ".dat"), "restart")

    def test_history_filename(self):
        self.assertEqual(sf.history_filename({}), "history.csv")
        self.assertEqual(sf.history_filename({"CONV_FILENAME": "hist.csv"}), "hist.csv")
        self.assertEqual(sf.history_filename({"CONV_FILENAME": "hist", "TABULAR_FORMAT": "TECPLOT"}), "hist.dat")
        cfg = {"CONV_FILENAME": "history", "TIME_DOMAIN": "YES", "RESTART_SOL": True, "RESTART_ITER": 42}
        self.assertEqual(sf.history_filename(cfg), "history_00042.csv")
        # steady restart: no suffix
        self.assertEqual(sf.history_filename({"RESTART_SOL": True, "RESTART_ITER": 42}), "history.csv")

    def test_restart_filename(self):
        self.assertEqual(sf.restart_filename({}), "restart.dat")
        self.assertEqual(sf.restart_filename({"RESTART_FILENAME": "flow.csv",
                                              "OUTPUT_FILES": ["RESTART_ASCII", "PARAVIEW"]}), "flow.csv")
        self.assertEqual(sf.restart_filename({"RESTART_FILENAME": "flow.csv",
                                              "OUTPUT_FILES": ["RESTART", "PARAVIEW"]}), "flow.dat")

    def test_latest_unsteady_restart(self):
        with tempfile.TemporaryDirectory() as d:
            for it in (8, 9, 10):
                Path(d, f"restart_{it:05d}.dat").write_bytes(b"x")
            cfg = {"TIME_DOMAIN": True}
            self.assertEqual(sf.latest_restart_path(d, cfg).name, "restart_00010.dat")
            self.assertEqual(sf.latest_restart_path(d, {}).name, "restart.dat")

    def test_solution_filename_for(self):
        self.assertEqual(sf.solution_filename_for("sol.txt", binary=False), "sol.csv")
        self.assertEqual(sf.solution_filename_for("sol.dat", binary=False), "sol.csv")
        self.assertEqual(sf.solution_filename_for("sol.csv", binary=True), "sol.dat")
        self.assertEqual(sf.solution_filename_for("../evil/sol.dat", binary=True), "sol.dat")


class TestOutputFrequencies(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(sf.volume_output_frequencies({}), [250, 250, 250])
        self.assertEqual(sf.volume_output_frequencies({"TIME_DOMAIN": "YES"}), [1, 1, 1])

    def test_repeat_last(self):
        cfg = {"OUTPUT_FILES": ["PARAVIEW", "SURFACE_PARAVIEW", "RESTART"], "OUTPUT_WRT_FREQ": [100]}
        self.assertEqual(sf.volume_output_frequencies(cfg), [100, 100, 100])
        self.assertEqual(sf.restart_output_frequency(cfg), 100)

    def test_index_aligned(self):
        # restart is the LAST file: its frequency is the last entry, not [0]
        cfg = {"OUTPUT_FILES": ["PARAVIEW", "SURFACE_PARAVIEW", "RESTART"], "OUTPUT_WRT_FREQ": [50, 50, 500]}
        self.assertEqual(sf.restart_output_frequency(cfg), 500)
        sf.set_output_frequency(cfg, ("RESTART", "RESTART_ASCII"), 1000)
        self.assertEqual(cfg["OUTPUT_WRT_FREQ"], [50, 50, 1000])

    def test_scalar_frequency(self):
        cfg = {"OUTPUT_FILES": ["RESTART", "PARAVIEW"], "OUTPUT_WRT_FREQ": 20}
        self.assertEqual(sf.volume_output_frequencies(cfg), [20, 20])


class TestResidualFields(unittest.TestCase):
    def test_compressible(self):
        self.assertEqual(sf.residual_history_fields({"SOLVER": "EULER"}, 2),
                         ["RMS_DENSITY", "RMS_MOMENTUM-X", "RMS_MOMENTUM-Y", "RMS_ENERGY"])
        self.assertIn("RMS_MOMENTUM-Z", sf.residual_history_fields({"SOLVER": "NAVIER_STOKES"}, 3))

    def test_incompressible_energy_is_enthalpy(self):
        fields = sf.residual_history_fields({"SOLVER": "INC_NAVIER_STOKES", "INC_ENERGY_EQUATION": "YES"}, 2)
        self.assertEqual(fields[-1], "RMS_ENTHALPY")
        self.assertNotIn("RMS_TEMPERATURE", fields)
        fields = sf.residual_history_fields({"SOLVER": "INC_NAVIER_STOKES", "WEAKLY_COUPLED_HEAT_EQUATION": True}, 2)
        self.assertIn("RMS_TEMPERATURE", fields)

    def test_turbulence(self):
        self.assertEqual(sf.residual_history_fields({"SOLVER": "RANS", "KIND_TURB_MODEL": "SA"}, 2)[-1], "RMS_NU_TILDE")
        self.assertEqual(sf.residual_history_fields({"SOLVER": "INC_RANS", "KIND_TURB_MODEL": "SST"}, 2)[-2:],
                         ["RMS_TKE", "RMS_DISSIPATION"])


if __name__ == "__main__":
    unittest.main()
