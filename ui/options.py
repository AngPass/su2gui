# Generic editors of SU2 options, driven by the option catalog (core/su2_options.json)
#
# - option_field(name):   a widget (select / multiple select / text field) bound to one
#                         SU2 option of state.jsonData, used in the cards of the menu;
# - cards of the menu nodes that only use such fields (Flow Conditions, Time Domain,
#   Dynamic Mesh, Adjoint & Design);
# - options_panel_card(): below the card of every menu node, the list of the options of
#   that node that are set, and an editor for any SU2 option of the node. With it, any
#   configuration that SU2 accepts can be written from the menu.
#
# The node/section an option belongs to (and its position in the .cfg) is defined in
# core/cfg_layout.py.

import sys
from pathlib import Path

parent_dir = str(Path(__file__).parent.parent.absolute())
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from trame.widgets import vuetify, html

from ui.uicard import ui_card, server
from core.logger import log
from core import cfg_layout as L
from core import su2_options

state, ctrl = server.state, server.controller

# Options generated from the boundary conditions of the Boundaries menu
# (core/su2_io.build_marker_options): they are not edited here.
MANAGED_KEYS = frozenset((
    'MARKER_ISOTHERMAL', 'MARKER_HEATFLUX', 'MARKER_HEATTRANSFER', 'MARKER_EULER',
    'MARKER_WALL_FUNCTIONS', 'MARKER_OUTLET', 'INC_OUTLET_TYPE', 'MARKER_SYM', 'MARKER_FAR',
    'MARKER_INLET', 'INC_INLET_TYPE', 'INLET_TYPE', 'MARKER_SUPERSONIC_INLET',
    'MARKER_SUPERSONIC_OUTLET',
))

# Options that also have a dedicated widget in a card of the menu: when they are changed
# here, the widgets of that card are updated from the configuration (set_json_<card>).
_SYNC = {
    "physics": ("SOLVER", "KIND_TURB_MODEL", "SA_OPTIONS", "SST_OPTIONS", "INC_ENERGY_EQUATION",
                "WALLMODEL_KAPPA", "WALLMODEL_B", "WALLMODEL_MINYPLUS", "WALLMODEL_MAXITER",
                "WALLMODEL_RELFAC"),
    "materials": ("FLUID_MODEL", "GAMMA_VALUE", "GAS_CONSTANT", "INC_DENSITY_INIT", "INC_DENSITY_MODEL",
                  "INC_TEMPERATURE_INIT", "MOLECULAR_WEIGHT", "THERMODYNAMIC_PRESSURE", "SPECIFIC_HEAT_CP",
                  "CP_POLYCOEFFS", "VISCOSITY_MODEL", "MU_CONSTANT", "MU_REF", "MU_T_REF",
                  "SUTHERLAND_CONSTANT", "MU_POLYCOEFFS", "CONDUCTIVITY_MODEL", "PRANDTL_LAM",
                  "KT_POLYCOEFFS", "THERMAL_CONDUCTIVITY_CONSTANT"),
    "numerics": ("CFL_NUMBER", "NUM_METHOD_GRAD", "NUM_METHOD_GRAD_RECON"),
    "initialization": ("RESTART_SOL", "READ_BINARY_RESTART", "SOLUTION_FILENAME"),
    "fileio": ("CONV_FILENAME", "HISTORY_WRT_FREQ_INNER", "OUTPUT_FILES", "OUTPUT_WRT_FREQ",
               "RESTART_FILENAME", "VOLUME_FILENAME", "WRT_RESTART_OVERWRITE", "WRT_VOLUME_OVERWRITE"),
    "solver": ("ITER", "CONV_RESIDUAL_MINVAL", "CONV_FIELD"),
}
SYNC_KEYS = {key: card for card, keys in _SYNC.items() for key in keys}


def sync_gui(keys):
    """Update the dedicated widgets of the menu after a change of the options ``keys``."""
    cards = {SYNC_KEYS[k] for k in keys if k in SYNC_KEYS}
    if not cards:
        return
    # imported here: the card modules import this module
    if "physics" in cards:
        from ui.physics import set_json_physics
        set_json_physics()
    if "materials" in cards:
        from ui.materials import set_json_materials
        set_json_materials()
    if "numerics" in cards:
        from ui.numerics import set_json_numerics
        set_json_numerics()
    if "initialization" in cards:
        from ui.initialization import set_json_initialization
        set_json_initialization()
    if "fileio" in cards:
        from ui.fileio import set_json_fileio
        set_json_fileio()
    if "solver" in cards:
        from core.solver import set_json_solver
        set_json_solver()


def _json():
    data = state.jsonData
    if not isinstance(data, dict):
        data = {}
        state.jsonData = data
    return data


def set_option(name, value, sync=True):
    """Set (value not None) or remove (value None) an option of the configuration.

    Returns True if the configuration changed."""
    data = _json()
    if value is None:
        if name not in data:
            return False
        data.pop(name)
    else:
        if name in data and L.same_value(data[name], value) and type(data[name]) == type(value):
            return False
        data[name] = value
        for _key, message in su2_options.check({name: value}):
            log("warn", f"{message} ({su2_options.source()})")
    if sync:
        sync_gui([name])
    state.dirty("jsonData")
    return True


def _description(name):
    info = L.option_info(name)
    text = info.get("description", "")
    extra = []
    if "default" in info:
        extra.append(f"default: {info['default']}")
    if info.get("example"):
        extra.append(f"example: {info['example']}")
    if extra:
        text = f"{text} ({', '.join(extra)})" if text else ", ".join(extra)
    return f"{name}: {text}" if text else name


# --------------------------------------------------------------------------- #
# Fields bound to one option
# --------------------------------------------------------------------------- #
_fields = {}           # option name -> state variable of its field


def _var(name):
    return f"opt_{name}"


def _make_handler(name):
    var = _var(name)

    def on_change(**kwargs):
        value = L.parse_value(name, state[var])
        current = _json().get(name)
        if value is None and current is None:
            return
        if value is not None and current is not None and L.same_value(value, current):
            return
        set_option(name, value)
    return on_change


def option_field(name, label=None, **props):
    """Widget editing the SU2 option ``name`` of state.jsonData (empty/cleared: option removed)."""
    info = L.option_info(name)
    widget = L.editor_kind(name)
    var = _var(name)
    if name not in _fields:
        _fields[name] = var
        state[var] = L.format_value(name, _json().get(name))
        state.change(var)(_make_handler(name))
    label = label or name
    common = dict(label=label, dense=True, outlined=True, hide_details=True, clearable=True,
                  classes="mt-2", **props)
    with html.Div(title=_description(name)):
        if widget in ("enum", "bool"):
            values = ["YES", "NO"] if widget == "bool" else info.get("values", [])
            vuetify.VSelect(v_model=(var,), items=(f"{var}_items", values), **common)
        elif widget == "enumlist":
            vuetify.VSelect(v_model=(var,), items=(f"{var}_items", info.get("values", [])),
                            multiple=True, small_chips=True, deletable_chips=True, **common)
        elif widget == "markers":
            vuetify.VCombobox(v_model=(var,), items=("adv_marker_names", []),
                              multiple=True, small_chips=True, deletable_chips=True, **common)
        else:
            placeholder = info.get("default") or info.get("example") or ""
            vuetify.VTextField(v_model=(var,), placeholder=str(placeholder), **common)


def option_fields(names, title=None, show=None):
    """Several option fields, with an optional subtitle; ``show``: JS condition for v_show."""
    with html.Div(v_show=show) if show else html.Div():
        if title:
            html.Div(title, classes="text-subtitle-2 mt-3 grey--text text--darken-2")
        for item in names:
            name, label = item if isinstance(item, tuple) else (item, None)
            option_field(name, label)


def refresh_option_fields():
    """Show the values of state.jsonData in the option fields."""
    data = _json()
    for name, var in _fields.items():
        shown = L.parse_value(name, state[var])
        value = data.get(name)
        if value is None and shown is None:
            continue
        if value is not None and shown is not None and L.same_value(value, shown):
            continue
        state[var] = L.format_value(name, value)


# --------------------------------------------------------------------------- #
# Cards of the menu nodes defined by their option fields
# --------------------------------------------------------------------------- #
def flow_conditions_card():
    with ui_card(title="Flow Conditions", ui_name="Flow Conditions"):
        option_fields([
            ("MACH_NUMBER", "Mach number"),
            ("AOA", "Angle of attack [deg]"),
            ("SIDESLIP_ANGLE", "Sideslip angle [deg]"),
            ("FREESTREAM_OPTION", "Free-stream option"),
            ("FREESTREAM_PRESSURE", "Free-stream pressure"),
            ("FREESTREAM_TEMPERATURE", "Free-stream temperature"),
            ("FREESTREAM_DENSITY", "Free-stream density"),
            ("REYNOLDS_NUMBER", "Reynolds number"),
            ("REYNOLDS_LENGTH", "Reynolds length"),
            ("INIT_OPTION", "Initialization option"),
            ("FREESTREAM_TURBULENCEINTENSITY", "Turbulence intensity"),
            ("FREESTREAM_TURB2LAMVISCRATIO", "Turbulent-to-laminar viscosity ratio"),
            ("REF_DIMENSIONALIZATION", "Non-dimensionalization"),
        ], title="Compressible free-stream", show="physics_comp_idx == 1")
        option_fields([
            ("INC_VELOCITY_INIT", "Initial velocity (vx, vy, vz)"),
            ("INC_NONDIM", "Non-dimensionalization"),
            ("INC_DENSITY_REF", "Reference density"),
            ("INC_VELOCITY_REF", "Reference velocity"),
            ("INC_TEMPERATURE_REF", "Reference temperature"),
        ], title="Incompressible flow", show="physics_comp_idx == 0")
        option_fields([
            ("REF_ORIGIN_MOMENT_X", "Moment origin x"),
            ("REF_ORIGIN_MOMENT_Y", "Moment origin y"),
            ("REF_ORIGIN_MOMENT_Z", "Moment origin z"),
            ("REF_LENGTH", "Reference length"),
            ("REF_AREA", "Reference area (0: computed)"),
        ], title="Reference values (forces and moments)")
        option_fields([
            ("FIXED_CL_MODE", "Fixed CL mode"),
            ("TARGET_CL", "Target CL"),
            ("DCL_DALPHA", "dCL/dalpha [1/deg]"),
        ], title="CL driver")


def time_domain_card():
    with ui_card(title="Time Domain", ui_name="Time Domain"):
        option_fields([
            ("TIME_DOMAIN", "Time-dependent simulation"),
            ("TIME_MARCHING", "Time marching"),
            ("TIME_STEP", "Time step [s]"),
            ("MAX_TIME", "Total physical time [s]"),
            ("TIME_ITER", "Number of time iterations"),
            ("INNER_ITER", "Inner iterations per time step"),
            ("UNST_CFL_NUMBER", "Unsteady CFL (0: use TIME_STEP)"),
            ("RESTART_ITER", "Restart from time iteration"),
            ("WINDOW_START_ITER", "Start of time averaging"),
            ("WINDOW_FUNCTION", "Time averaging window"),
        ])


def dynamic_mesh_card():
    with ui_card(title="Dynamic Mesh", ui_name="Dynamic Mesh"):
        option_fields([
            ("GRID_MOVEMENT", "Grid movement"),
            ("MOTION_ORIGIN", "Motion origin (x, y, z)"),
            ("ROTATION_RATE", "Rotation rate (wx, wy, wz) [rad/s]"),
            ("TRANSLATION_RATE", "Translation rate (vx, vy, vz)"),
            ("PITCHING_OMEGA", "Pitching angular frequency"),
            ("PITCHING_AMPL", "Pitching amplitude [deg]"),
            ("PLUNGING_OMEGA", "Plunging angular frequency"),
            ("PLUNGING_AMPL", "Plunging amplitude"),
        ], title="Grid movement")
        option_fields([
            ("SURFACE_MOVEMENT", "Surface movement"),
            ("MARKER_MOVING", "Moving markers"),
        ], title="Surface movement")
        option_fields([
            ("DEFORM_MESH", "Mesh deformation solver"),
            ("MARKER_DEFORM_MESH", "Deforming markers"),
            ("DEFORM_STIFFNESS_TYPE", "Stiffness type"),
            ("DEFORM_LINEAR_SOLVER_ITER", "Linear solver iterations"),
        ], title="Mesh deformation")


def design_card():
    with ui_card(title="Adjoint & Design", ui_name="Adjoint & Design"):
        html.Div("The adjoint solver is selected in Physics (MATH_PROBLEM).",
                 classes="text-caption grey--text")
        option_fields([
            ("OBJECTIVE_FUNCTION", "Objective function(s)"),
            ("OBJECTIVE_WEIGHT", "Objective weights"),
            ("MARKER_MONITORING", "Monitored markers (objective)"),
        ], title="Objective")
        option_fields([
            ("MARKER_DESIGNING", "Design markers"),
            ("DV_KIND", "Design variable kind"),
            ("DV_MARKER", "Design variable markers"),
            ("DV_PARAM", "Design variable parameters"),
            ("DV_VALUE", "Design variable values"),
            ("FFD_DEFINITION", "FFD box definition"),
            ("FFD_DEGREE", "FFD degree (i, j, k)"),
        ], title="Design variables")
        option_fields([
            ("OPT_OBJECTIVE", "Optimization objective"),
            ("OPT_CONSTRAINT", "Optimization constraints"),
            ("OPT_ITERATIONS", "Optimizer iterations"),
            ("OPT_GRADIENT_FACTOR", "Gradient scaling factor"),
            ("DEFINITION_DV", "Design variable definition"),
        ], title="Shape optimization (SU2 python scripts)")


# --------------------------------------------------------------------------- #
# Panel with all the options of the active menu node
# --------------------------------------------------------------------------- #
state.adv_nodes = list(L.NODES)
state.adv_rows = []
state.adv_count = 0
state.adv_items = []
state.adv_all = False
state.adv_key = None
state.adv_widget = "text"
state.adv_values = []
state.adv_value = ""
state.adv_desc = ""
state.adv_meta = ""
state.adv_managed = False
state.adv_marker_names = []
state.adv_panel = None


def _marker_names():
    names = []
    for bc in (state.BCDictList or []):
        name = bc.get("bcName") if isinstance(bc, dict) else None
        if name and name not in names:
            names.append(name)
    return names


def _node_items(node, with_node=False):
    items = []
    for sec, names in L.options_of_node(node):
        items.append({"header": f"{node} / {sec.title}" if with_node else sec.title})
        for name in names:
            desc = L.option_info(name).get("description", "")
            if len(desc) > 70:
                desc = desc[:67] + "..."
            items.append({"text": f"{name}  {desc}".strip(), "value": name})
    return items


def refresh_option_panel():
    """Update the panel for the active node and the configuration."""
    node = state.active_ui
    data = _json()
    rows = []
    count = 0
    if node in L.NODES:
        from core.su2_io import cfg_value
        for node_name, sections in L.grouped(data):
            if node_name != node:
                continue
            for sec, items in sections:
                rows.append({"type": "header", "text": sec.title})
                for key, value in items:
                    text = cfg_value(value)
                    if text is None:
                        continue
                    count += 1
                    rows.append({"type": "option", "key": key, "value": text,
                                 "managed": key in MANAGED_KEYS, "desc": _description(key)})
    state.adv_rows = rows
    state.adv_count = count
    state.adv_marker_names = _marker_names()


_items_cache = {}


@state.change("active_ui", "adv_all")
def _on_active_node(**kwargs):
    node = state.active_ui
    key = "*" if state.adv_all else node
    if key not in _items_cache:
        if state.adv_all:
            items = []
            for n in L.NODES:
                items.extend(_node_items(n, with_node=True))
        else:
            items = _node_items(node) if node in L.NODES else []
        _items_cache[key] = items
    state.adv_items = _items_cache[key]
    refresh_option_panel()


@state.change("jsonData")
def _on_json_data(**kwargs):
    refresh_option_fields()
    refresh_option_panel()
    if state.adv_key:
        _load_editor(state.adv_key, keep_value=True)


def _load_editor(name, keep_value=False):
    info = L.option_info(name)
    widget = L.editor_kind(name)
    state.adv_widget = widget
    state.adv_values = ["YES", "NO"] if widget == "bool" else info.get("values", [])
    if not keep_value:
        state.adv_value = L.format_value(name, _json().get(name))
    sec = L.section_of(name)
    state.adv_desc = info.get("description", "") or ("Not an option of " + su2_options.source()
                                                       if not info else "")
    meta = []
    if info.get("kind"):
        meta.append(f"type: {info['kind']}")
    if "default" in info:
        meta.append(f"default: {info['default']}")
    if info.get("example"):
        meta.append(f"example: {info['example']}")
    meta.append(f"written in: {sec.node} / {sec.title}")
    state.adv_meta = " | ".join(meta)
    state.adv_managed = name in MANAGED_KEYS


@state.change("adv_key")
def _on_adv_key(adv_key, **kwargs):
    if isinstance(adv_key, dict):
        adv_key = adv_key.get("value")
    name = str(adv_key or "").strip().upper()
    if not name:
        state.adv_desc = state.adv_meta = ""
        state.adv_value = ""
        state.adv_managed = False
        return
    _load_editor(name)


def _current_key():
    key = state.adv_key
    if isinstance(key, dict):
        key = key.get("value")
    return str(key or "").strip().upper()


def apply_option():
    name = _current_key()
    if not name:
        return
    if name in MANAGED_KEYS:
        log("warn", f"{name} is generated from the boundary conditions: set it in the Boundaries menu")
        return
    value = L.parse_value(name, state.adv_value)
    if set_option(name, value):
        log("info", f"{name} {'removed' if value is None else 'set'}")


def remove_option(name=None):
    name = (name or _current_key()).strip().upper()
    if not name:
        return
    if name in MANAGED_KEYS:
        log("warn", f"{name} is generated from the boundary conditions: change it in the Boundaries menu")
        return
    if set_option(name, None):
        log("info", f"{name} removed")
    if name == _current_key():
        state.adv_value = L.format_value(name, None)


def edit_option(name):
    state.adv_key = name
    state.adv_panel = 0
    _load_editor(name)


def use_default():
    name = _current_key()
    info = L.option_info(name)
    if "default" in info:
        state.adv_value = L.format_value(name, L.parse_value(name, info["default"]))


def options_panel_card():
    """Card below the card of every menu node: all the SU2 options of that node."""
    with vuetify.VCard(v_show="adv_nodes.includes(active_ui)", classes="mt-2"):
        with vuetify.VExpansionPanels(v_model=("adv_panel", None), accordion=True, flat=True):
            with vuetify.VExpansionPanel():
                with vuetify.VExpansionPanelHeader(classes="grey lighten-2 py-1",
                                                   style="min-height: 36px;"):
                    html.Div("All SU2 options of {{ active_ui }} ({{ adv_count }} set)",
                             classes="text-subtitle-2")
                with vuetify.VExpansionPanelContent(classes="pt-2"):
                    # ---------------- editor of any option of the node
                    vuetify.VAutocomplete(
                        v_model=("adv_key", None),
                        items=("adv_items", []),
                        label="SU2 option",
                        placeholder="type a name or a word of the description",
                        dense=True, outlined=True, hide_details=True, clearable=True,
                        classes="mt-1",
                    )
                    vuetify.VCheckbox(v_model=("adv_all", False), label="Search in all the menus",
                                      dense=True, hide_details=True, classes="mt-1")
                    with html.Div(v_if="adv_key"):
                        html.Div("{{ adv_desc }}", classes="text-caption mt-2")
                        html.Div("{{ adv_meta }}", classes="text-caption grey--text")
                        html.Div("Generated from the boundary conditions (Boundaries menu).",
                                 v_if="adv_managed", classes="text-caption orange--text text--darken-3")
                        with html.Div(v_if="!adv_managed"):
                            vuetify.VSelect(v_if="adv_widget == 'enum' || adv_widget == 'bool'",
                                            v_model=("adv_value",), items=("adv_values", []),
                                            label="Value", dense=True, outlined=True,
                                            hide_details=True, clearable=True, classes="mt-2")
                            vuetify.VSelect(v_if="adv_widget == 'enumlist'",
                                            v_model=("adv_value",), items=("adv_values", []),
                                            label="Values", multiple=True, small_chips=True,
                                            deletable_chips=True, dense=True, outlined=True,
                                            hide_details=True, clearable=True, classes="mt-2")
                            vuetify.VCombobox(v_if="adv_widget == 'markers'",
                                              v_model=("adv_value",), items=("adv_marker_names", []),
                                              label="Markers", multiple=True, small_chips=True,
                                              deletable_chips=True, dense=True, outlined=True,
                                              hide_details=True, clearable=True, classes="mt-2")
                            vuetify.VTextField(v_if="adv_widget == 'text'",
                                               v_model=("adv_value",),
                                               label="Value (lists: a, b, c)",
                                               dense=True, outlined=True, hide_details=True,
                                               clearable=True, classes="mt-2")
                            with html.Div(classes="d-flex mt-2"):
                                vuetify.VBtn("Set", small=True, color="primary", click=apply_option,
                                             classes="mr-2")
                                vuetify.VBtn("Default", small=True, click=use_default, classes="mr-2")
                                vuetify.VBtn("Remove", small=True, click=(remove_option, "[null]"))
                    # ---------------- options of the node in the configuration
                    vuetify.VDivider(classes="my-2")
                    html.Div("No option of this menu is set.", v_if="adv_count == 0",
                             classes="text-caption grey--text")
                    with html.Div(v_for="(row, i) in adv_rows", key="i"):
                        html.Div("{{ row.text }}", v_if="row.type == 'header'",
                                 classes="text-caption font-weight-bold mt-2 grey--text text--darken-2")
                        with html.Div(v_else=True, classes="d-flex align-center",
                                      style="font-size: 12px; line-height: 1.3;", title=("row.desc",)):
                            html.Span("{{ row.key }}",
                                      style="font-family: monospace; width: 48%; overflow-wrap: anywhere;")
                            html.Span("{{ row.value }}",
                                      style="font-family: monospace; width: 40%; overflow-wrap: anywhere;")
                            with vuetify.VBtn(icon=True, x_small=True, click=(edit_option, "[row.key]")):
                                vuetify.VIcon("mdi-pencil", x_small=True)
                            with vuetify.VBtn(icon=True, x_small=True, disabled=("row.managed",),
                                              click=(remove_option, "[row.key]")):
                                vuetify.VIcon("mdi-delete", x_small=True)
