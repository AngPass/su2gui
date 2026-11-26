"""Layout of the SU2 .cfg file written by SU2GUI.

Every SU2 option (catalog core/su2_options.json) belongs to a node of the menu
on the left of the GUI (Mesh, Physics, Materials, ...) and to a section of that
node. The .cfg is written node by node, in the order of the menu, with a
commented header for each node and each section, so that the file follows the
workflow of the GUI.

The membership of an option is decided, in this order, by:
  1. the explicit ``keys`` of a section;
  2. the section of config_template.cfg the option is documented in (``template``);
  3. the CONFIG_CATEGORY of CConfig.cpp the option is registered in (``categories``).
Options that are not in the catalog (unknown to SU2) are written last.
Inside a section the options follow the order of config_template.cfg.

This module also converts values between the text typed in the GUI and the
json configuration (``parse_value`` / ``format_value``).

No trame dependency.
"""

import re

from core import su2_options

# Menu nodes, in the order of the menu (and of the .cfg file).
NODES = (
    "Mesh",
    "Physics",
    "Materials",
    "Flow Conditions",
    "Numerics",
    "Time Domain",
    "Boundaries",
    "Dynamic Mesh",
    "Initialization",
    "Adjoint & Design",
    "File I/O",
    "Solver",
)

OTHER_NODE = "Other"

# (node, section title, template sections, CConfig categories, explicit keys)
_SECTIONS = (
    # ------------------------------------------------------------------ Mesh
    ("Mesh", "Mesh input and output", (), ("Input/output files and formats",),
     ("MESH_FILENAME", "MESH_FORMAT", "MESH_OUT_FILENAME", "MESH_OUT_FORMAT", "MESH_BOX_SIZE",
      "MESH_BOX_LENGTH", "MESH_BOX_OFFSET", "MESH_BOX_POLY_SOL_FEM", "REORIENT_ELEMENTS",
      "MULTIZONE_MESH", "MULTIZONE_ADAPT_FILENAME")),
    # --------------------------------------------------------------- Physics
    ("Physics", "Problem definition", ("DIRECT, ADJOINT, AND LINEARIZED PROBLEM DEFINITION",),
     ("Problem Definition",),
     ("SOLVER", "MATH_PROBLEM", "KIND_TURB_MODEL", "INC_ENERGY_EQUATION", "WEAKLY_COUPLED_HEAT_EQUATION")),
    ("Physics", "Hybrid RANS/LES and stochastic backscatter",
     ("DES Parameters", "Stochastic Backscatter Model (SBS)"), ("Hybrid_RANSLES Options",), ()),
    ("Physics", "Wall functions and wall roughness",
     ("WALL ROUGHNESS DEFINITION", "WALL FUNCTION DEFINITION"), (), ("MARKER_WALL_FUNCTIONS",)),
    ("Physics", "Turbulence model uncertainty quantification", ("UNCERTAINTY QUANTIFICATION DEFINITION",), (), ()),
    ("Physics", "Multizone and multiphysics coupling",
     ("MULTIZONE DEFINITION", "CONJUGATE HEAT TRANSFER (CHT)"), ("Multizone definition",),
     ("MULTIZONE", "MULTIZONE_SOLVER", "CONFIG_LIST", "NZONES", "CHT_INTERFACE_CONTACT_RESISTANCE",
      "KIND_INTERPOLATION", "CONSERVATIVE_INTERPOLATION", "KIND_RADIAL_BASIS_FUNCTION",
      "RADIAL_BASIS_FUNCTION_PARAMETER", "RADIAL_BASIS_FUNCTION_POLYNOMIAL_TERM",
      "RADIAL_BASIS_FUNCTION_PRUNE_TOLERANCE", "NUM_NEAREST_NEIGHBORS",
      "STAT_RELAX_PARAMETER", "AITKEN_DYN_MAX_INITIAL", "AITKEN_DYN_MIN_INITIAL", "BGS_RELAXATION",
      "RELAXATION", "DYNAMIC_LOAD_TRANSFER", "RAMP_FSI_ITER")),
    ("Physics", "Species transport", ("SPECIES TRANSPORT SIMULATION",), (), ()),
    ("Physics", "Combustion (Cantera, flamelet)", ("DETAILED CHEMISTRY WITH CANTERA", "FLAMELET MODEL"), (), ()),
    ("Physics", "Radiative heat transfer", ("RADIATIVE HEAT TRANSFER SIMULATION",), (), ()),
    ("Physics", "Source terms",
     ("BODY FORCE DEFINITION", "VORTICITY_CONFINEMENT", "STREAMWISE PERIODICITY DEFINITION"), (),
     ("PYTHON_CUSTOM_SOURCE",)),
    ("Physics", "Turbomachinery", ("TURBOMACHINERY SIMULATION",), (), ("RELATIVE_FRAME_SLIDINGPLANE",)),
    ("Physics", "Engines and actuator disks", ("ENGINE SIMULATION",), (), ()),
    ("Physics", "Supersonic simulation (sonic boom)", ("SUPERSONIC SIMULATION",), ("Equivalent Area",), ()),
    ("Physics", "Structural solver (FEA)",
     ("FEA SOLVER FOR FLUID-STRUCTURE INTERACTION", "Dielectric effects", "Prestretch", "Body Forces",
      "Weakly Coupled Heat"), ("FEA solver",), ()),
    # ------------------------------------------------------------- Materials
    ("Materials", "Fluid model",
     ("NONEQUILIBRIUM GAS, IDEAL GAS, POLYTROPIC, VAN DER WAALS AND PENG ROBINSON CONSTANTS, CoolProp library",
      "NEMO NUMERICAL METHOD DEFINITION"),
     ("FluidModel", "Cantera fluid model", "Data-driven fluid model parameters"),
     ("INC_DENSITY_MODEL", "TEMPERATURE_LIMITS")),
    ("Materials", "Viscosity model", ("VISCOSITY MODEL",), (), ()),
    ("Materials", "Thermal conductivity model", ("THERMAL CONDUCTIVITY MODEL",), (),
     ("THERMAL_CONDUCTIVITY_CONSTANT",)),
    ("Materials", "Solid properties", ("SOLID ZONE HEAT VARIABLES",), (), ()),
    # ------------------------------------------------------- Flow conditions
    ("Flow Conditions", "Compressible free-stream conditions", ("COMPRESSIBLE FREE-STREAM DEFINITION",),
     ("Freestream Conditions",), ()),
    ("Flow Conditions", "Incompressible flow conditions", ("INCOMPRESSIBLE FLOW CONDITION DEFINITION",), (), ()),
    ("Flow Conditions", "Reference values", ("REFERENCE VALUE DEFINITION",), ("Reference Conditions",), ()),
    ("Flow Conditions", "Fixed lift coefficient (CL driver)", ("CL DRIVER DEFINITION",), (), ()),
    # -------------------------------------------------------------- Numerics
    ("Numerics", "Gradients and CFL", ("COMMON PARAMETERS DEFINING THE NUMERICAL METHOD",),
     ("Time-marching",), ()),
    ("Numerics", "Flow numerical method", ("FLOW NUMERICAL METHOD DEFINITION",), ("Spatial Discretization",), ()),
    ("Numerics", "Slope limiters and dissipation sensors", ("SLOPE LIMITER AND DISSIPATION SENSOR DEFINITION",), (), ()),
    ("Numerics", "Turbulence numerical method", ("TURBULENT NUMERICAL METHOD DEFINITION",), (), ()),
    ("Numerics", "Species numerical method", (), (),
     ("CONV_NUM_METHOD_SPECIES", "MUSCL_SPECIES", "MUSCL_KAPPA_SPECIES", "SLOPE_LIMITER_SPECIES",
      "TIME_DISCRE_SPECIES", "CFL_REDUCTION_SPECIES")),
    ("Numerics", "Heat numerical method", ("HEAT NUMERICAL METHOD DEFINITION",), (), ("TIMESTEP_HEAT",)),
    ("Numerics", "Incompressible solver", ("PRESSURE-BASED INCOMPRESSIBLE SOLVER DEFINITION",), (),
     ("BETA_FACTOR", "BULK_MODULUS")),
    ("Numerics", "Linear solver", ("LINEAR SOLVER DEFINITION",), ("Linear solver definition",), ()),
    ("Numerics", "Multigrid", ("MULTIGRID PARAMETERS",), ("Multi-grid",), ()),
    ("Numerics", "High-order (DG-FEM) flow solver", ("FEM FLOW NUMERICAL METHOD DEFINITION",),
     ("FEM flow solver definition",), ()),
    # ----------------------------------------------------------- Time domain
    ("Time Domain", "Time-dependent simulation", ("TIME-DEPENDENT SIMULATION",), (),
     ("TIME_ITER", "RESTART_ITER")),
    ("Time Domain", "Harmonic balance", (), (),
     ("TIME_INSTANCES", "HB_PERIOD", "HB_PRECONDITION", "OMEGA_HB")),
    # ------------------------------------------------------------ Boundaries
    ("Boundaries", "Boundary conditions", ("BOUNDARY CONDITION DEFINITION",), ("Boundary Markers",),
     ("INC_INLET_TYPE", "INC_INLET_DAMPING", "INLET_USE_NORMAL", "INC_OUTLET_TYPE", "INC_OUTLET_DAMPING",
      "MARKER_INLET_SPECIES", "MARKER_SPECIES_STRONG_BC", "MARKER_EMISSIVITY")),
    ("Boundaries", "Surface identification (monitoring, plotting, analysis)", ("SURFACES IDENTIFICATION",), (), ()),
    # ---------------------------------------------------------- Dynamic mesh
    ("Dynamic Mesh", "Grid movement", ("DYNAMIC MESH DEFINITION",), ("Dynamic mesh definition",), ()),
    ("Dynamic Mesh", "Mesh deformation",
     ("MESH DEFORMATION PARAMETERS (NEW SOLVER)", "GRID DEFORMATION PARAMETERS"),
     ("Grid deformation", "Deformable mesh"), ("MARKER_DEFORM_MESH_INTERNAL",)),
    ("Dynamic Mesh", "Aeroelastic simulation (typical section model)",
     ("AEROELASTIC SIMULATION (Typical Section Model)",), ("Aeroelastic Simulation (Typical Section Model)",), ()),
    ("Dynamic Mesh", "Gust simulation", ("GUST SIMULATION",), ("Wind Gust",), ()),
    # -------------------------------------------------------- Initialization
    ("Initialization", "Restart and initial solution", (), (),
     ("RESTART_SOL", "SOLUTION_FILENAME", "SOLUTION_ADJ_FILENAME", "READ_BINARY_RESTART",
      "DISCARD_INFILES", "SPECIES_INIT")),
    # ------------------------------------------------------ Adjoint & design
    ("Adjoint & Design", "Objective function", (), (),
     ("OBJECTIVE_FUNCTION", "OBJECTIVE_WEIGHT", "CUSTOM_OBJFUNC")),
    ("Adjoint & Design", "Adjoint numerical method",
     ("ADJOINT-FLOW NUMERICAL METHOD DEFINITION", "ADJOINT-TURBULENT NUMERICAL METHOD DEFINITION"),
     ("Adjoint and Gradient",), ()),
    ("Adjoint & Design", "Automatic differentiation",
     ("AUTOMATIC DIFFERENTIATION", "AUTOMATIC DIFFERENTIATION (TAPE TEST DEBUG MODE)"),
     ("Automatic Differentation options",), ()),
    ("Adjoint & Design", "Design variables", ("DESIGN VARIABLE PARAMETERS",), (), ("DV_VALUE_NEW", "DV_VALUE_OLD")),
    ("Adjoint & Design", "Free-form deformation", ("FREE-FORM DEFORMATION PARAMETERS",), ("FFD point inversion",), ()),
    ("Adjoint & Design", "Geometry evaluation", ("GEOMETRY EVALUATION PARAMETERS",), (), ("GEO_PARAM",)),
    ("Adjoint & Design", "Optimal shape design", ("OPTIMAL SHAPE DESIGN DEFINITION",),
     ("Optimization Problem", "Python Options"), ("GRADIENT_METHOD",)),
    ("Adjoint & Design", "Inverse design", ("INVERSE DESIGN SIMULATION",), ("Inverse design problem",), ()),
    ("Adjoint & Design", "Topology optimization", ("TOPOLOGY OPTIMIZATION",), (), ()),
    ("Adjoint & Design", "Reference geometry", ("REFERENCE GEOMETRY",), (), ()),
    ("Adjoint & Design", "Sobolev gradient smoothing", ("SOBOLEV GRADIENT SMOOTHING OPTIONS",),
     ("Sobolev Gradient Solver Parameters",), ()),
    # --------------------------------------------------------------- File I/O
    ("File I/O", "Input/output files", ("INPUT/OUTPUT FILE INFORMATION",), (), ("WRT_RESTART_COMPACT",)),
    ("File I/O", "Screen, history and volume output", ("SCREEN/HISTORY VOLUME OUTPUT",),
     ("Output Options", "Visualize Control Volumes"), ()),
    ("File I/O", "Buffet sensor", ("BUFFET SENSOR DEFINITION",), (), ()),
    ("File I/O", "Reduced order model (libROM)", ("LIBROM PARAMETERS",), ("libROM options",), ()),
    # ---------------------------------------------------------------- Solver
    ("Solver", "Iterations and convergence", ("SOLVER CONTROL",), ("Convergence",), ()),
    ("Solver", "Parallel execution and partitioning",
     ("HYBRID PARALLEL (MPI+OpenMP) OPTIONS", "PARTITIONING OPTIONS (ParMETIS)", "PASTIX PARAMETERS"), (),
     ("NUMBER_PART", "CONSOLE", "DECOMPOSED")),
)

OTHER_SECTION = "Options not known to SU2"


class Section:
    __slots__ = ("node", "title", "template", "categories", "keys")

    def __init__(self, node, title, template, categories, keys):
        self.node, self.title = node, title
        self.template, self.categories, self.keys = tuple(template), tuple(categories), tuple(keys)

    @property
    def id(self):
        return f"{self.node}/{self.title}"


SECTIONS = tuple(Section(*s) for s in _SECTIONS)
_OTHER = Section(OTHER_NODE, OTHER_SECTION, (), (), ())

_by_key, _by_template, _by_category = {}, {}, {}
for _s in SECTIONS:
    for _k in _s.keys:
        _by_key.setdefault(_k, _s)
    for _t in _s.template:
        _by_template.setdefault(_t, _s)
    for _c in _s.categories:
        _by_category.setdefault(_c, _s)

_section_cache = {}


def section_of(name):
    """Section (node and title) an option is written in."""
    sec = _section_cache.get(name)
    if sec is None:
        entry = su2_options.catalog().get("options", {}).get(name)
        if name in _by_key:
            sec = _by_key[name]
        elif entry is None:
            sec = _OTHER
        else:
            sec = (_by_template.get(entry.get("section"))
                   or _by_category.get(entry.get("category"))
                   or _OTHER)
        _section_cache[name] = sec
    return sec


def node_of(name):
    return section_of(name).node


def option_info(name):
    """Catalog entry of an option ({} if unknown)."""
    return su2_options.catalog().get("options", {}).get(name, {})


def _sort_key(name):
    order = option_info(name).get("order")
    return (0, order, name) if order is not None else (1, 0, name)


_section_index = {s.id: i for i, s in enumerate(SECTIONS)}
_section_index[_OTHER.id] = len(SECTIONS)


def options_of_node(node):
    """All the catalog options of a node: [(section, [names...]), ...] in .cfg order."""
    groups = {}
    for name in su2_options.catalog().get("options", {}):
        sec = section_of(name)
        if sec.node == node:
            groups.setdefault(sec.id, (sec, []))[1].append(name)
    out = []
    for sec_id in sorted(groups, key=lambda i: _section_index[i]):
        sec, names = groups[sec_id]
        out.append((sec, sorted(names, key=_sort_key)))
    return out


def grouped(config):
    """Options of ``config`` grouped for the .cfg: [(node, [(section, [(key, value), ...]), ...]), ...]."""
    buckets = {}
    for key, value in config.items():
        buckets.setdefault(section_of(key).id, []).append(key)
    nodes = []
    for node in NODES + (OTHER_NODE,):
        sections = []
        for sec in SECTIONS + (_OTHER,):
            if sec.node != node or sec.id not in buckets:
                continue
            keys = sorted(buckets[sec.id], key=_sort_key)
            sections.append((sec, [(k, config[k]) for k in keys]))
        if sections:
            nodes.append((node, sections))
    return nodes


# --------------------------------------------------------------------------- #
# .cfg text
# --------------------------------------------------------------------------- #
WIDTH = 80


def node_header(number, node):
    title = f"{number}. {node.upper()}" if number else node.upper()
    bar = "%" * WIDTH
    return [bar, f"% {title}".ljust(WIDTH - 1) + "%", bar]


def section_header(title):
    text = f" {title} "
    left = (WIDTH - 2 - len(text)) // 2
    right = WIDTH - 2 - len(text) - left
    if left < 3:
        return [f"% --- {title} --- %"]
    return ["%" + "-" * left + text + "-" * right + "%"]


def build_cfg_lines(config, value_text):
    """Lines of the options of ``config`` grouped by menu node and section.

    ``value_text(value)`` gives the .cfg text of a value (None: not written).
    """
    lines = []
    for node, sections in grouped(config):
        written = [(sec, [(k, value_text(v)) for k, v in items]) for sec, items in sections]
        written = [(sec, [(k, t) for k, t in items if t is not None]) for sec, items in written]
        written = [(sec, items) for sec, items in written if items]
        if not written:
            continue
        number = NODES.index(node) + 1 if node in NODES else None
        if lines:
            lines.append("")
        lines.extend(node_header(number, node))
        for sec, items in written:
            lines.append("")
            lines.extend(section_header(sec.title))
            lines.extend(f"{k}= {t}" for k, t in items)
    return lines


# --------------------------------------------------------------------------- #
# values typed in the GUI <-> json configuration
# --------------------------------------------------------------------------- #
ENUM_KINDS = ("Enum", "Convect", "MathProblem")
NUMBER_KINDS = ("Double", "UnsignedLong", "UnsignedShort", "Long")
INTEGER_KINDS = ("UnsignedLong", "UnsignedShort", "Long")


def editor_kind(name):
    """Widget used to edit an option: 'bool', 'enum', 'enumlist', 'markers' or 'text'."""
    info = option_info(name)
    kind = info.get("kind")
    if kind == "Bool":
        return "bool"
    if kind in ENUM_KINDS and info.get("values"):
        return "enum"
    if kind == "EnumList" and info.get("values"):
        return "enumlist"
    if kind == "StringList" and name.startswith("MARKER_"):
        return "markers"
    return "text"


def _scalar(text):
    """Number if the token is a number, else the string."""
    t = text.strip()
    if re.fullmatch(r"[-+]?\d+", t):
        return int(t)
    try:
        return float(t)
    except ValueError:
        return t


def _split_list(text):
    t = text.strip()
    if len(t) >= 2 and t[0] in "([{" and t[-1] in ")]}":
        t = t[1:-1]
    parts = t.split(",") if "," in t else t.split()
    return [p.strip() for p in parts if p.strip()]


def tokens(value):
    """Items of a list value (lists, or a string separated by spaces/commas)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(tokens(v))
        return out
    if isinstance(value, bool):
        return ["YES" if value else "NO"]
    return [t for t in re.split(r"[\s,()]+", str(value)) if t]


def parse_value(name, value):
    """Json value of an option from what the GUI widget gives.

    Returns None when the option must be removed (empty input)."""
    kind = option_info(name).get("kind")
    widget = editor_kind(name)
    if value is None:
        return None
    if widget in ("enumlist", "markers"):
        items = tokens(value) if not isinstance(value, (list, tuple)) else [str(v).strip() for v in value]
        items = [i for i in items if i]
        return items or None
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if text == "":
        return None
    if widget == "bool":
        up = text.upper()
        if up in ("YES", "TRUE", "1"):
            return True
        if up in ("NO", "FALSE", "0"):
            return False
        return text
    if widget == "enum" or kind == "String":
        return text
    if kind in NUMBER_KINDS:
        try:
            return int(text) if kind in INTEGER_KINDS else float(text)
        except ValueError:
            return _scalar(text)   # e.g. a user variable, substituted when the .cfg is written
    # lists and composite options (markers, arrays, ...)
    items = _split_list(text)
    if len(items) == 1 and not (text.startswith("(") or "," in text):
        # a single value: keep the scalar for scalar-like kinds
        if kind in (None, "Generic"):
            return _scalar(items[0])
    return [_scalar(i) for i in items]


def format_value(name, value):
    """Value shown in the GUI widget for a json value."""
    widget = editor_kind(name)
    if widget in ("enumlist", "markers"):
        return [str(t) for t in tokens(value)]
    if value is None:
        return "" if widget == "text" else None
    if widget == "bool":
        if isinstance(value, bool):
            return "YES" if value else "NO"
        return str(value).upper()
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in _flatten(value))
    return str(value)


def _flatten(value):
    for item in value:
        if isinstance(item, (list, tuple)):
            yield from _flatten(item)
        else:
            yield item


def same_value(a, b):
    """True if two json values give the same option for SU2.

    Lists and strings of space/comma separated items are compared item by item
    ("A B" == ["A", "B"]), numbers by value, booleans as YES/NO."""
    def scalar(v):
        if isinstance(v, bool):
            return "YES" if v else "NO"
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        try:
            return float(s)
        except ValueError:
            return s.upper() if s.upper() in ("YES", "NO", "TRUE", "FALSE") and len(s) > 1 else s

    def norm(v):
        items = [scalar(x) for x in tokens(v)]
        items = ["YES" if i == "TRUE" else "NO" if i == "FALSE" else i for i in items]
        return tuple(items)
    return norm(a) == norm(b)
