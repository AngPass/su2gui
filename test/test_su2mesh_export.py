"""Round-trip test of core.su2_io.save_su2mesh on a native SU2 mesh.

A .su2 mesh is loaded into the same VTK multiblock layout that su2gui.py builds
(block 0: interior with one unstructured grid, block 1: one grid per marker,
all sharing the same points), exported with save_su2mesh and compared with
the original. The SU2 QuickStart mesh is used when an SU2 checkout is found
(SU2_HOME or a sibling "SU2" directory), otherwise a small built-in mesh.

Run with:  python -m unittest discover -s test -p "test_*.py"
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import vtk
except ImportError:  # pragma: no cover
    vtk = None

SMALL_MESH = """NDIME= 2
NELEM= 2
5 0 1 2 0
9 1 3 4 2 1
NPOIN= 5
0.0 0.0 0
1.0 0.0 1
0.0 1.0 2
2.0 0.0 3
2.0 1.0 4
NMARK= 2
MARKER_TAG= lower
MARKER_ELEMS= 2
3 0 1
3 1 3
MARKER_TAG= upper
MARKER_ELEMS= 1
3 2 4
"""


def find_su2_mesh():
    candidates = []
    if os.environ.get("SU2_HOME"):
        candidates.append(Path(os.environ["SU2_HOME"]))
    candidates.append(ROOT.parent / "SU2")
    for base in candidates:
        mesh = base / "QuickStart" / "mesh_NACA0012_inv.su2"
        if mesh.is_file():
            return mesh.read_text()
    return SMALL_MESH


def parse_su2(text):
    """Minimal native .su2 parser (single zone) returning plain python structures."""
    lines = [l.split("%")[0].strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    out = {"markers": {}}
    i = 0
    while i < len(lines):
        key, _, val = lines[i].partition("=")
        key, val = key.strip(), val.strip()
        if key == "NDIME":
            out["ndim"] = int(val)
        elif key == "NELEM":
            n = int(val)
            # the last value is the element index; keep type + connectivity only
            out["elems"] = [[int(v) for v in lines[i + 1 + k].split()][:-1] for k in range(n)]
            i += n
        elif key == "NPOIN":
            n = int(val.split()[0])
            pts = []
            for k in range(n):
                vals = [float(v) for v in lines[i + 1 + k].split()]
                pts.append(vals[: out["ndim"]])
            out["points"] = np.array(pts)
            i += n
        elif key == "MARKER_TAG":
            tag = val
            n = int(lines[i + 1].partition("=")[2])
            out["markers"][tag] = [[int(v) for v in lines[i + 2 + k].split()] for k in range(n)]
            i += 1 + n
        i += 1
    return out


def build_multiblock(parsed):
    pts = vtk.vtkPoints()
    pts.SetDataTypeToDouble()  # as in su2gui.load_file_su2
    for p in parsed["points"]:
        pts.InsertNextPoint(p[0], p[1], p[2] if len(p) > 2 else 0.0)
    grid = vtk.vtkUnstructuredGrid()
    grid.SetPoints(pts)
    for e in parsed["elems"]:
        grid.InsertNextCell(e[0], len(e) - 1, e[1:])
    interior = vtk.vtkMultiBlockDataSet()
    interior.SetBlock(0, grid)
    boundary = vtk.vtkMultiBlockDataSet()
    for m, (tag, elems) in enumerate(parsed["markers"].items()):
        mg = vtk.vtkUnstructuredGrid()
        mg.SetPoints(pts)
        for e in elems:
            mg.InsertNextCell(e[0], len(e) - 1, e[1:])
        boundary.SetBlock(m, mg)
        boundary.GetMetaData(m).Set(vtk.vtkCompositeDataSet.NAME(), tag)
    root = vtk.vtkMultiBlockDataSet()
    root.SetBlock(0, interior)
    root.SetBlock(1, boundary)
    return root


@unittest.skipIf(vtk is None, "VTK not available")
class TestSaveSu2Mesh(unittest.TestCase):
    def setUp(self):
        from core import paths
        self._saved_root = paths._cases_root

    def tearDown(self):
        from core import paths
        paths._cases_root = self._saved_root

    def test_round_trip(self):
        from core import su2_io, paths

        original = parse_su2(find_su2_mesh())
        root = build_multiblock(original)

        with tempfile.TemporaryDirectory() as tmp:
            paths.set_cases_root(Path(tmp) / "user")
            (Path(tmp) / "user" / "case").mkdir(parents=True)
            su2_io.state = types.SimpleNamespace(nDim=original["ndim"], case_name="case")
            su2_io.save_su2mesh(root, "mesh_out.su2")
            exported = parse_su2((Path(tmp) / "user" / "case" / "mesh_out.su2").read_text())

        self.assertEqual(exported["ndim"], original["ndim"])
        self.assertEqual(exported["elems"], original["elems"])
        np.testing.assert_array_equal(exported["points"], original["points"])
        self.assertEqual(exported["markers"], original["markers"])

    def test_multiple_interior_blocks_are_refused(self):
        from core import su2_io, paths

        root = build_multiblock(parse_su2(SMALL_MESH))
        root.GetBlock(0).SetBlock(1, vtk.vtkUnstructuredGrid())
        with tempfile.TemporaryDirectory() as tmp:
            paths.set_cases_root(Path(tmp) / "user")
            (Path(tmp) / "user" / "case").mkdir(parents=True)
            su2_io.state = types.SimpleNamespace(nDim=2, case_name="case")
            su2_io.save_su2mesh(root, "mesh_out.su2")
            self.assertFalse((Path(tmp) / "user" / "case" / "mesh_out.su2").exists())


if __name__ == "__main__":
    unittest.main()
