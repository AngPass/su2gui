"""Helpers that mirror the file conventions of SU2 (develop branch).

Every rule implemented here is taken from the SU2 sources, so that the GUI
reads and writes exactly what SU2_CFD expects:

* file names: ``CConfig::GetFilename``, ``CConfig::GetHistory_FileName``,
  ``CConfig::GetUnsteady_FileName`` and ``PrintingToolbox::TrimExtension``
  (Common/src/CConfig.cpp, Common/include/CConfig.hpp);
* native binary restart format: ``CSU2BinaryFileWriter::WriteData`` and
  ``CSolver::Read_SU2_Restart_Binary`` (header of ``SU2_RESTART_HEADER_SIZE``
  ints, field names of ``CGNS_STRING_SIZE`` chars, row-major point data);
* ASCII restart format: ``CSU2FileWriter`` (CSV with a quoted header that
  starts with ``PointID``);
* volume output frequencies: ``CConfig::SetPostprocessing`` (defaults and the
  "repeat the last frequency" rule for OUTPUT_WRT_FREQ);
* residual history fields: ``CFlowCompOutput``, ``CFlowIncOutput`` and
  ``CFlowOutput::AddHistoryOutputFields_ScalarRMS_RES``.

The module has no dependency on trame/VTK so it can be unit tested.
"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

# --- constants from Common/include/option_structure.hpp ---------------------
SU2_RESTART_MAGIC_NUMBER = 535532
SU2_RESTART_HEADER_SIZE = 5
SU2_RESTART_PRECISION_IDX = 3
CGNS_STRING_SIZE = 33

# Coordinates and point index that are not solution fields.
COORDINATE_FIELDS = ("PointID", "Point_ID", "x", "y", "z")

# Default steady/unsteady volume output frequency (CConfig::SetPostprocessing).
DEFAULT_WRT_FREQ_STEADY = 250
DEFAULT_WRT_FREQ_UNSTEADY = 1


# --- generic option parsing ---------------------------------------------------
def as_bool(value: Any, default: bool = False) -> bool:
    """Interpret an SU2 boolean option (bool, YES/NO, TRUE/FALSE, 1/0)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().upper()
    if text in ("YES", "TRUE", "1"):
        return True
    if text in ("NO", "FALSE", "0"):
        return False
    return default


def as_list(value: Any) -> List[Any]:
    """Return an SU2 list option as a python list (scalars become 1-item lists)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# --- file names -----------------------------------------------------------------
def trim_extension(name: str, ext: str) -> str:
    """PrintingToolbox::TrimExtension: drop ``ext`` only if ``name`` ends with it."""
    name = str(name)
    if ext and name.endswith(ext):
        return name[: -len(ext)]
    return name


def unsteady_suffix(iteration: int) -> str:
    """CConfig::GetUnsteady_FileName always uses 5 digits: ``_00042``."""
    return f"_{int(iteration):05d}"


def is_time_domain(cfg: Dict[str, Any]) -> bool:
    return as_bool(cfg.get("TIME_DOMAIN"), False)


def history_filename(cfg: Dict[str, Any]) -> str:
    """Name of the history file written by SU2 (CConfig::GetHistory_FileName)."""
    name = str(cfg.get("CONV_FILENAME", "history") or "history")
    name = trim_extension(name, ".dat")
    name = trim_extension(name, ".csv")
    if is_time_domain(cfg) and as_bool(cfg.get("RESTART_SOL"), False):
        name += unsteady_suffix(int(cfg.get("RESTART_ITER", 1) or 1))
    tab = str(cfg.get("TABULAR_FORMAT", "CSV") or "CSV").upper()
    return name + (".dat" if tab == "TECPLOT" else ".csv")


def output_files(cfg: Dict[str, Any]) -> List[str]:
    """OUTPUT_FILES with the SU2 default when it is not set."""
    files = [str(f).upper() for f in as_list(cfg.get("OUTPUT_FILES"))]
    if not files:
        files = ["RESTART", "PARAVIEW", "SURFACE_PARAVIEW"]
    return files


def restart_is_ascii(cfg: Dict[str, Any]) -> bool:
    """True when SU2 writes the restart as CSV (RESTART_ASCII in OUTPUT_FILES)."""
    files = output_files(cfg)
    return "RESTART_ASCII" in files and "RESTART" not in files


def restart_extension(cfg: Dict[str, Any]) -> str:
    return ".csv" if restart_is_ascii(cfg) else ".dat"


def restart_basename(cfg: Dict[str, Any]) -> str:
    """RESTART_FILENAME without the extension SU2 appends itself."""
    name = str(cfg.get("RESTART_FILENAME", "restart") or "restart")
    name = trim_extension(name, ".dat")
    name = trim_extension(name, ".csv")
    return name


def restart_filename(cfg: Dict[str, Any]) -> str:
    """Name of the (steady) restart file SU2 writes (CConfig::GetFilename)."""
    return restart_basename(cfg) + restart_extension(cfg)


def latest_restart_path(case_dir: os.PathLike, cfg: Dict[str, Any]) -> Path:
    """Path of the most recent restart file in ``case_dir``.

    For steady problems this is simply RESTART_FILENAME + extension. For
    unsteady problems SU2 appends ``_<iter:05d>`` (and does not overwrite), so
    we pick the highest iteration that exists on disk.
    """
    case_dir = Path(case_dir)
    ext = restart_extension(cfg)
    base = restart_basename(cfg)
    if not is_time_domain(cfg):
        return case_dir / (base + ext)

    pattern = re.compile(re.escape(base) + r"_(\d{5,})" + re.escape(ext) + "$")
    best: Optional[Path] = None
    best_iter = -1
    for candidate in glob.glob(str(case_dir / (glob.escape(base) + "_*" + ext))):
        match = pattern.search(os.path.basename(candidate))
        if match and int(match.group(1)) > best_iter:
            best_iter = int(match.group(1))
            best = Path(candidate)
    return best if best is not None else case_dir / (base + ext)


def solution_filename_for(uploaded_name: str, binary: bool) -> str:
    """File name under which an uploaded solution must be stored.

    SU2 reads ``GetFilename(SOLUTION_FILENAME, ".dat"|".csv")``: it trims the
    matching extension and appends it again, so the file on disk must end in
    ``.dat`` (binary) or ``.csv`` (ASCII), whatever the uploaded name was.
    """
    stem = os.path.basename(str(uploaded_name))
    for ext in (".dat", ".csv", ".txt"):
        stem = trim_extension(stem, ext)
    return stem + (".dat" if binary else ".csv")


# --- volume output frequency ------------------------------------------------------
def volume_output_frequencies(cfg: Dict[str, Any]) -> List[int]:
    """OUTPUT_WRT_FREQ expanded to one entry per OUTPUT_FILES entry.

    Same rules as CConfig::SetPostprocessing: if not set, 250 (steady) or 1
    (unsteady) for every file; if shorter than OUTPUT_FILES, the last value is
    repeated.
    """
    files = output_files(cfg)
    freqs: List[int] = []
    for value in as_list(cfg.get("OUTPUT_WRT_FREQ")):
        try:
            freqs.append(int(value))
        except (TypeError, ValueError):
            continue
    if not freqs:
        default = DEFAULT_WRT_FREQ_UNSTEADY if is_time_domain(cfg) else DEFAULT_WRT_FREQ_STEADY
        return [default] * len(files)
    while len(freqs) < len(files):
        freqs.append(freqs[-1])
    return freqs


def output_frequency(cfg: Dict[str, Any], kinds: Sequence[str]) -> Optional[int]:
    """Writing frequency of the first OUTPUT_FILES entry whose name is in ``kinds``."""
    files = output_files(cfg)
    freqs = volume_output_frequencies(cfg)
    for i, name in enumerate(files):
        if name in kinds:
            return freqs[i]
    return None


def restart_output_frequency(cfg: Dict[str, Any]) -> Optional[int]:
    return output_frequency(cfg, ("RESTART", "RESTART_ASCII"))


def set_output_frequency(cfg: Dict[str, Any], kinds: Sequence[str], value: int) -> None:
    """Set the frequency of the OUTPUT_FILES entry in ``kinds`` (index-consistent)."""
    files = output_files(cfg)
    freqs = volume_output_frequencies(cfg)
    for i, name in enumerate(files):
        if name in kinds:
            freqs[i] = int(value)
    cfg["OUTPUT_FILES"] = files
    cfg["OUTPUT_WRT_FREQ"] = freqs


# --- restart files -------------------------------------------------------------------
def is_su2_binary_restart(path: os.PathLike) -> bool:
    """Same check SU2 does: the first int of a binary restart is the magic number."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return False
    if len(head) < 4:
        return False
    return int(np.frombuffer(head, dtype="<i4")[0]) == SU2_RESTART_MAGIC_NUMBER


def bytes_are_su2_binary_restart(data: bytes) -> bool:
    if not isinstance(data, (bytes, bytearray)) or len(data) < 4:
        return False
    return int(np.frombuffer(bytes(data[:4]), dtype="<i4")[0]) == SU2_RESTART_MAGIC_NUMBER


def _scalar_size(precision_field: int) -> int:
    """GetSU2BinaryScalarSize: 0 and 1 (legacy files) mean double precision."""
    if precision_field in (0, 1):
        return 8
    if precision_field in (4, 8):
        return precision_field
    raise ValueError(f"Invalid floating point precision {precision_field} in SU2 binary header")


def read_su2_binary_restart(path: os.PathLike) -> pd.DataFrame:
    """Read a native SU2 binary restart (.dat) into a DataFrame.

    Layout (CSU2BinaryFileWriter): 5 int32 header
    [magic, nFields, nPoints, scalar size, spare], nFields names of 33 chars,
    then nPoints*nFields scalars stored point by point. A legacy metadata
    trailer, if present, is ignored. The PointID column is not stored in
    binary files.
    """
    with open(path, "rb") as f:
        raw = f.read()

    header_bytes = SU2_RESTART_HEADER_SIZE * 4
    if len(raw) < header_bytes:
        raise ValueError("File too short to be an SU2 binary restart")

    header = np.frombuffer(raw[:header_bytes], dtype="<i4")
    if int(header[0]) != SU2_RESTART_MAGIC_NUMBER:
        raise ValueError("Not an SU2 binary restart file (wrong magic number)")

    n_fields = int(header[1])
    n_points = int(header[2])
    scalar = _scalar_size(int(header[SU2_RESTART_PRECISION_IDX]))

    offset = header_bytes
    names = []
    for _ in range(n_fields):
        chunk = raw[offset: offset + CGNS_STRING_SIZE]
        if len(chunk) < CGNS_STRING_SIZE:
            raise ValueError("Truncated field names in SU2 binary restart")
        names.append(chunk.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip())
        offset += CGNS_STRING_SIZE

    count = n_fields * n_points
    nbytes = count * scalar
    if len(raw) - offset < nbytes:
        raise ValueError("Truncated data in SU2 binary restart (file still being written?)")

    dtype = "<f8" if scalar == 8 else "<f4"
    data = np.frombuffer(raw[offset: offset + nbytes], dtype=dtype).reshape(n_points, n_fields)
    return pd.DataFrame(data.astype(np.float64, copy=False), columns=names)


def read_su2_ascii_restart(path: os.PathLike) -> pd.DataFrame:
    """Read an SU2 CSV restart: quoted header starting with PointID."""
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [str(c).strip().strip('"').strip() for c in df.columns]
    # Coerce everything to numbers and drop non-numeric (e.g. legacy metadata) rows.
    df = df.apply(pd.to_numeric, errors="coerce").dropna(how="any").reset_index(drop=True)
    return df


def read_su2_restart(path: os.PathLike) -> pd.DataFrame:
    """Read an SU2 restart in either format, detected like SU2 (magic number)."""
    if is_su2_binary_restart(path):
        return read_su2_binary_restart(path)
    return read_su2_ascii_restart(path)


def solution_fields(df: pd.DataFrame) -> List[str]:
    """Columns of a restart DataFrame that are solution fields (not coordinates)."""
    return [c for c in df.columns if c not in COORDINATE_FIELDS]


# --- history / convergence fields ------------------------------------------------------
def residual_history_fields(cfg: Dict[str, Any], n_dim: int) -> List[str]:
    """RMS residual history fields SU2 defines for the current setup.

    These are the names accepted by CONV_FIELD (CFlowCompOutput,
    CFlowIncOutput, CFlowOutput::AddHistoryOutputFields_ScalarRMS_RES).
    """
    solver = str(cfg.get("SOLVER", "EULER") or "EULER").upper()
    incompressible = solver.startswith("INC_")
    fields: List[str] = []

    if incompressible:
        fields += ["RMS_PRESSURE", "RMS_VELOCITY-X", "RMS_VELOCITY-Y"]
        if n_dim == 3:
            fields.append("RMS_VELOCITY-Z")
        if as_bool(cfg.get("WEAKLY_COUPLED_HEAT_EQUATION"), False):
            fields.append("RMS_TEMPERATURE")
        if as_bool(cfg.get("INC_ENERGY_EQUATION"), False):
            fields.append("RMS_ENTHALPY")
    else:
        fields += ["RMS_DENSITY", "RMS_MOMENTUM-X", "RMS_MOMENTUM-Y"]
        if n_dim == 3:
            fields.append("RMS_MOMENTUM-Z")
        fields.append("RMS_ENERGY")

    if solver in ("RANS", "INC_RANS"):
        turb = str(cfg.get("KIND_TURB_MODEL", "NONE") or "NONE").upper()
        if turb == "SA":
            fields.append("RMS_NU_TILDE")
        elif turb == "SST":
            fields += ["RMS_TKE", "RMS_DISSIPATION"]

    return fields


def clean_history_columns(df: pd.DataFrame) -> pd.DataFrame:
    """SU2 writes quoted, space-padded column names in the history CSV."""
    df.columns = [str(c).replace('"', "").strip() for c in df.columns]
    return df
