# solver gittree menu

# note that in the main menu, we need to call add the following:
# 1) from core.solver import *
# 2) call solver_card() in SinglePageWithDrawerLayout
# 3) define a node in the gittree (pipeline)
# 4) define any global state variables that might be needed

import sys
import os
import shutil
import numpy as np
import pandas as pd
import subprocess
import asyncio
import matplotlib
import warnings
import matplotlib.pyplot as plt
import vtk
from pathlib import Path

BASE = Path(__file__).parent.parent

parent_dir = str(Path(__file__).parent.parent.absolute())
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from ui.uicard import ui_card, ui_subcard, server
from trame.widgets import vuetify
from core.su2_json import *
from core.su2_io import save_su2mesh, save_json_cfg_file
from core.config_validator import SU2ConfigValidator

# check if a file is opened by another process
#import psutil
from base64 import b64decode
import io, struct

# real-time update, asynchronous io
from trame.app import get_server, asynchronous

from trame.app.file_upload import ClientFile

from vtkmodules.vtkCommonDataModel import vtkDataObject
from vtkmodules.util.numpy_support import numpy_to_vtk

# SU2 (develop) file conventions: file names, restart formats, history fields
from core import su2_files
# location of the cases (--cases-dir / SU2GUI_CASES_DIR)
from core import paths

# import the grid from the mesh module
from ui.mesh import *
from ui.vtk_helper import *

# Logging function
from core.logger import log, update_su2_logs

# matplotlib
matplotlib.use("agg")
from trame.widgets import matplotlib as tramematplotlib

# Suppress noisy mpld3 deprecation warnings with Matplotlib 3.10+
try:
    from matplotlib import MatplotlibDeprecationWarning
    warnings.filterwarnings(
        "ignore",
        category=MatplotlibDeprecationWarning,
        module=r"mpld3.*",
    )
except Exception:
    pass

# line 'i' has fixed color so the color does not change if a line is deselected
mplColorList=['blue','orange','red','green','purple','brown','pink','gray','olive','cyan',
              'black','gold','yellow','springgreen','thistle','beige','coral','navy','salmon','lightsteelblue']



state, ctrl = server.state, server.controller
############################################################################
# Solver models - list options #
############################################################################

# the main su2 solver process
proc_SU2 = None

# list of fields that we could check for convergence
state.convergence_fields=[]
state.convergence_fields_range=[]
# list of booleans stating which of the fields need to be
# included in the convergence criteria
state.convergence_fields_visibility=[]

# global iteration number while running a case
state.global_iter = -1

# Initialize solver state variables.
# Note: trame's state returns None for unknown keys, so hasattr() is always True
# and cannot be used to detect uninitialized variables.
def _init_state(name, value):
    if getattr(state, name, None) is None:
        setattr(state, name, value)

_init_state('solver_running', False)
_init_state('solver_icon', "mdi-play-circle")
_init_state('keep_updating', False)
# The validation panel is currently hidden, so the user cannot see or disable the
# auto-fixes: keep them off by default and only report the issues in the log.
_init_state('apply_auto_fixes', False)
_init_state('validation_issues', [])
_init_state('validation_fixes', [])
_init_state('validation_summary', "")

# initialize from json file
def set_json_solver():
    if 'ITER' in state.jsonData:
        state.iter_idx = state.jsonData['ITER']
        state.dirty('iter_idx')
    if 'CONV_RESIDUAL_MINVAL' in state.jsonData:
        state.convergence_val = state.jsonData['CONV_RESIDUAL_MINVAL']
        state.dirty('convergence_val')
    if 'CONV_FIELD' in state.jsonData:
        state.convergence_fields = state.jsonData['CONV_FIELD']
        log("info", f"state convergence fields =  = {state.convergence_fields} {type(state.convergence_fields)}")


# matplotlib
state.active_figure="mpl_plot_history"
state.graph_update=True
@state.change("active_figure", "figure_size", "countdown", "monitorLinesVisibility", "x", "ylist", "monitorLinesNames")
def update_chart(active_figure, **kwargs):
    log("info", "updating figure 1")
    try:
        if hasattr(ctrl, 'update_figure') and callable(ctrl.update_figure):
            ctrl.update_figure(globals()[active_figure]())
        else:
            log("debug", "ctrl.update_figure not available yet (normal during initialization)")
    except Exception as e:
        import traceback
        log("error", f"Error updating figure: {e}", detail=traceback.format_exc())
    #ctrl.update_figure2(globals()[active_figure]())

#matplotlib
def update_visibility(index, visibility):
    log("info", f"monitorLinesVisibility =  = {state.monitorLinesVisibility}")
    state.monitorLinesVisibility[index] = visibility
    log("info", f"monitorLinesVisibility =  = {state.monitorLinesVisibility}")
    state.dirty("monitorLinesVisibility")
    log("info", f"Toggle {index} to {visibility}")
    log("info", f"monitorLinesVisibility =  = {state.monitorLinesVisibility}")

#matplotlib
def dialog_card():
    log("info", f"dialog card, lines= = {state.monitorLinesNames}")
    # show_dialog2 determines if the entire dialog is shown or not
    with vuetify.VDialog(width=200,position='{X:10,Y:10}',transition="dialog-top-transition",v_model=("show_dialog",False)):
      #with vuetify.VCard(color="light-gray"):
      with vuetify.VCard():
        vuetify.VCardTitle("Line visibility", classes="grey lighten-1 grey--text text--darken-3")

        #with vuetify.VListGroup(value=("true",), sub_group=True):
        #    with vuetify.Template(v_slot_activator=True):
        #            vuetify.VListItemTitle("Bars")
        #    with vuetify.VListItemContent():
        #            #with vuetify.VListItem(v_for="id in monitorLinesRange", key="id"):
        vuetify.VCheckbox(
                              # loop over list monitorLinesRange
                              v_for="id in monitorLinesRange",
                              key="id",
                              # checkbox changes the state of monitorLinesVisibility[id]
                              v_model=("monitorLinesVisibility[id]",),
                              # name of the checkbox
                              label=("`label= ${ monitorLinesNames[id] }`",),
                              # on each change, immediately go to update_visibility
                              change=(update_visibility,"[id, $event]"),
                              classes="mt-1 pt-1",
                              hide_details=True,
                              dense=True,
        )


        # close dialog window button
        # right-align the button
        with vuetify.VCol(classes="text-right"):
          vuetify.VBtn("Close", classes="mt-5",click=update_dialog)


def active_case_dir():
    """Directory of the active case."""
    return paths.case_dir(state.case_name)


def history_path():
    """History file written by SU2 for the current configuration."""
    return active_case_dir() / su2_files.history_filename(state.jsonData)


def restart_path():
    """Most recent restart file written by SU2 for the current configuration."""
    return su2_files.latest_restart_path(active_case_dir(), state.jsonData)


def _file_signature(path):
    """(mtime, size) of a file, or None if it does not exist."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _set_solver_stopped():
    state.keep_updating = False
    state.solver_running = False
    state.solver_icon = "mdi-play-circle"


# real-time update every xx seconds
@asynchronous.task
async def start_countdown(result):
    global proc_SU2

    # Only re-read the restart file when SU2 has rewritten it: SU2 writes it every
    # OUTPUT_WRT_FREQ iterations, not every polling interval.
    last_restart_signature = None
    try:
        while state.keep_updating:
            await asyncio.sleep(2.0)
            with state:
                try:
                    readHistory(history_path())

                    current_restart = restart_path()
                    signature = _file_signature(current_restart)
                    if signature is not None and signature != last_restart_signature:
                        if readRestart(current_restart, False):
                            last_restart_signature = signature

                    # flip-flop to trigger the redraw of the history plot
                    state.countdown = not state.countdown
                except Exception as e:
                    import traceback
                    log("error", f"Error while updating the solver monitor: {e}", detail=traceback.format_exc())

                # check that the job is still running
                if proc_SU2 is None or proc_SU2.poll() is not None:
                    returncode = None if proc_SU2 is None else proc_SU2.returncode
                    log("info", f"SU2 job has stopped (return code {returncode})")
                    _set_solver_stopped()
                    # final update with the last files written by SU2
                    try:
                        readHistory(history_path())
                        readRestart(restart_path(), False)
                    except Exception as e:
                        log("warn", f"Could not read the final solver output: {e}")
                update_su2_logs()
    finally:
        # never leave the GUI in the "running" state if the task dies
        if proc_SU2 is None or proc_SU2.poll() is not None:
            with state:
                _set_solver_stopped()


###############################################################
# PIPELINE CARD : Solver
###############################################################
def solver_card():
    with ui_card(title="Solver", ui_name="Solver"):
        log("debug", "## Solver Selection ##")
      # 1 row of option lists
        with vuetify.VRow(classes="pt-2"):
          with vuetify.VCol(cols="8"):

            vuetify.VTextField(
                # What to do when something is selected
                v_model=("convergence_val", -12),
                # the name of the list box
                label="Residual convergence value",
            )
          with vuetify.VCol(cols="4", classes="py-0 my-0"):
            with vuetify.VBtn(classes="mx-0 py-0 mt-2 mb-0",elevation=1,variant="text",color="white", click=update_solver_dialog_card_convergence, icon="mdi-dots-vertical"):
              vuetify.VIcon("mdi-dots-vertical",density="compact",color="green")

        # 1 row of option lists
        with vuetify.VRow(classes="pt-2"):
          with vuetify.VCol(cols="10"):

            vuetify.VTextField(
                # What to do when something is selected
                v_model=("iter_idx", 100),
                # the name of the list box
                label="Iterations",
            )

        with vuetify.VBtn("Solve",click=su2_play):
            vuetify.VIcon("{{solver_icon}}",color="purple")

        # Validation panel (nijso temporarily removed, will be added back in a future update)
        # with vuetify.VExpansionPanels():
        #     with vuetify.VExpansionPanel():
        #         vuetify.VExpansionPanelHeader("Validation & Preflight")
        #         with vuetify.VExpansionPanelContent():
        #             with vuetify.VRow(classes="pt-2"):
        #                 with vuetify.VCol(cols="6"):
        #                     vuetify.VCheckbox(
        #                         v_model=("apply_auto_fixes", True),
        #                         label="Apply auto-fixes before run",
        #                         hide_details=True,
        #                         dense=True,
        #                     )
        #                 with vuetify.VCol(cols="6", classes="text-right"):
        #                     vuetify.VBtn("Run preflight", color="primary", click=run_preflight_validation)
        #             # Summary
        #             vuetify.VAlert(
        #                 v_show=("validation_summary",),
        #                 type_="info",
        #                 text=("validation_summary", ""),
        #                 dense=True,
        #                 outlined=True,
        #             )
        #             # Issues list
        #             vuetify.VSubheader("Issues")
        #             with vuetify.VList(two_line=True, dense=True):
        #                 with vuetify.Template(v_slot_item=True):
        #                     pass
        #             with vuetify.VList(dense=True):
        #                 # Render up to 20 issues (robust guard when list may be undefined)
        #                 with vuetify.VListItem(v_for="(item,idx) in ((typeof validation_issues !== 'undefined' && validation_issues) ? validation_issues : []).slice(0,20)", key="idx"):
        #                     with vuetify.VListItemContent():
        #                         vuetify.VListItemTitle("`$${item.path || 'root'}`")
        #                         vuetify.VListItemSubtitle("`$${item.message}`")
        #             # Fixes list
        #             vuetify.VSubheader("Applied Fixes (preview)")
        #             with vuetify.VList(dense=True):
        #                 with vuetify.VListItem(v_for="(fix,i) in ((typeof validation_fixes !== 'undefined' && validation_fixes) ? validation_fixes : []).slice(0,20)", key="i"):
        #                     vuetify.VListItemTitle("`$${fix.message}`")

########################################################################################
# Checks/Corrects some json entries before starting the Solver
########################################################################################
# def checkjsonData():
#    if 'RESTART_FILENAME' in state.jsonData:
#        state.jsonData['RESTART_FILENAME' ] = 'restart'
#        state.restart_filename = 'restart'
#    if 'SOLUTION_FILENAME' in state.jsonData:
#        state.jsonData['SOLUTION_FILENAME' ] = 'solution_flow'

def checkCaseName():
    if state.case_name is None or state.case_name == "":
        log("error", "Case name is empty, create a new case.  \n Otherwise your data will not be saved!")
        return False
    return True

def check_solver_requirements():
    """Check if all requirements are met to run the solver"""
    issues = []

    su2_path = getattr(state, "su2_cfd_path", None)
    if not su2_path:
        try:
            from core.user_config import get_su2_path
            su2_path = get_su2_path()
        except:
            pass

    if not su2_path:
        issues.append("SU2_CFD executable path not configured")
    elif not os.path.exists(su2_path):
        issues.append(f"SU2_CFD executable not found at: {su2_path}")

    # Check case name
    if not hasattr(state, 'case_name') or not state.case_name:
        issues.append("No case name specified")

    # Check configuration
    if not hasattr(state, 'jsonData') or not state.jsonData:
        issues.append("No configuration data loaded")

    return issues
###############################################################
# Solver - state changes
###############################################################
@state.change("iter_idx")
def update_material(iter_idx, **kwargs):
    #
    log("debug", f"ITER value:  = {state.iter_idx}")
    #
    # we want to call a submenu
    #state.active_sub_ui = "submaterials_fluid"
    #
    # update config option value
    try:
      state.jsonData['ITER'] = int(state.iter_idx)
    except ValueError:
      log("error", "Invalid value for ITER")

@state.change("convergence_val")
def update_material(convergence_val, **kwargs):
    #
    # update config option value
    # CONV_RESIDUAL_MINVAL is a double option in SU2 (log10 of the residual)
    try:
      state.jsonData['CONV_RESIDUAL_MINVAL'] = float(state.convergence_val)
    except (TypeError, ValueError):
      log("error", "Invalid value for CONV_RESIDUAL_MINVAL in solver")


# start SU2 solver
def su2_play():
    global proc_SU2

    log("info", "=== SOLVE BUTTON CLICKED ===")

    # Use stored SU2_CFD path or fallback to "SU2_CFD" if not set
    su2_cfd_path = getattr(state, "su2_cfd_path", None)
    log("info", f"Initial SU2 path: {su2_cfd_path}")

    if not su2_cfd_path:
        # Try to get from config as fallback
        try:
            from core.user_config import get_su2_path
            su2_cfd_path = get_su2_path()
            log("info", f"Config SU2 path: {su2_cfd_path}")
        except Exception as e:
            log("error", f"Failed to import user_config: {e}")
            su2_cfd_path = None

        if not su2_cfd_path:
            log("error", " SU2_CFD path not configured!")
            log("error", "Please restart SU2GUI and configure the SU2_CFD executable path.")
            log("error", "Cannot start solver without SU2_CFD executable path.")
            # Reset the button state
            state.solver_running = False
            state.solver_icon = "mdi-play-circle"
            return

    # Check if SU2_CFD executable exists
    if not os.path.exists(su2_cfd_path):
        log("error", f" SU2_CFD executable not found at: {su2_cfd_path}")
        log("error", "Please check the SU2_CFD path configuration.")
        state.solver_running = False
        state.solver_icon = "mdi-play-circle"
        return

    # every time we press the button we switch the state
    state.solver_running = not state.solver_running
    if state.solver_running:
        log("info", f"### SU2 solver started using {su2_cfd_path}!")
        # change the solver button icon
        state.solver_icon="mdi-stop-circle"

        # reset monitorLinesNames for the history plot
        state.monitorLinesNames = []

        # check if the case name is set
        if not checkCaseName():
            log("error", " Cannot start solver: No case name specified.")
            log("error", "Please create a case in the CASES tab first.")
            # Reset the solver state
            state.solver_running = False
            state.solver_icon = "mdi-play-circle"
            return

        log("info", f" Using case: {state.case_name}")

        if not state.jsonData:
            log("error", " No configuration data available.")
            log("error", "Please load a mesh file or configuration.")
            state.solver_running = False
            state.solver_icon = "mdi-play-circle"
            return

        # Check if required files exist
        mesh_filename = state.jsonData.get('MESH_FILENAME', 'unknown')
        log("info", f"Expected mesh file: {mesh_filename}")

        # save the cfg file
        try:
            save_json_cfg_file(state.filename_json_export,state.filename_cfg_export)
            log("info", f"Saved config file: {state.filename_cfg_export}")
        except Exception as e:
            log("error", f"Failed to save config file: {e}")
            state.solver_running = False
            state.solver_icon = "mdi-play-circle"
            return

        # Preflight validation of the saved cfg (custom cross-option checks)
        try:
            _run_validation(log_issues=True)
        except Exception as e:
            import traceback
            log("warn", f"Preflight validation could not be completed: {e}", detail=traceback.format_exc())

        # Continue with mesh save and solver launch
        # save the mesh file
        try:
            global root
            save_su2mesh(root, state.jsonData['MESH_FILENAME'])
            log("info", f"Saved mesh file: {state.jsonData['MESH_FILENAME']}")
        except Exception as e:
            log("error", f"Failed to save mesh file: {e}")
            state.solver_running = False
            state.solver_icon = "mdi-play-circle"
            return

        # clear old su2 log and set new one
        state.last_modified_su2_log_len = 0
        state.su2_logs = ""

        # run SU2_CFD with config.cfg
        try:
            with open(active_case_dir() / "su2.out", "w") as outfile:
                with open(active_case_dir() / "su2.err", "w") as errfile:
                    proc_SU2 = subprocess.Popen([su2_cfd_path, state.filename_cfg_export],
                                                cwd=active_case_dir(),
                                                text=True,
                                                stdout=outfile,
                                                stderr=errfile
                                                )
        except OSError as e:
            log("error", f"Could not start SU2_CFD: {e}")
            proc_SU2 = None
            _set_solver_stopped()
            return
        # at this point we have started the simulation
        # we can now start updating the real-time plots
        state.keep_updating = True
        log("debug", f"start polling, poll =  = {proc_SU2.poll()}")

        # Wait until process terminates
        # while result.poll() is None:
        #   time.sleep(1.0)
        log("debug", f"result =  = {proc_SU2}")
        log("debug", f"result poll=  = {proc_SU2.poll()}")

        # periodic update of the monitor and volume result
        start_countdown(proc_SU2)

    else:
        # Stop solver
        state.solver_icon = "mdi-play-circle"
        log("info", "### SU2 solver stopped!")
        log("debug", f"process= = {type(proc_SU2)}")
        if proc_SU2 is not None:
            proc_SU2.terminate()
        else:
            log("warning", "No SU2 process to terminate")

# Options that are regenerated from the boundary conditions (state.BCDictList) by
# createjsonMarkers() at every save: a fix written to jsonData would be overwritten,
# so these have to be corrected in the Boundaries tab instead.
_BC_GENERATED_PREFIXES = ("MARKER_",)
_BC_GENERATED_KEYS = {"INC_INLET_TYPE", "INC_OUTLET_TYPE", "INLET_TYPE"}


def _is_bc_generated(key):
    return key in _BC_GENERATED_KEYS or str(key).startswith(_BC_GENERATED_PREFIXES)


def _coerce_like(original, new):
    """Keep the json type of an option when taking a value parsed from the cfg file."""
    if isinstance(original, bool):
        return su2_files.as_bool(new, original)
    return new


def _apply_validation_fixes(result):
    """Apply only the options changed by the auto-fixes, keeping the json types.

    The validator re-parses the written .cfg, where lists are flattened and
    booleans are YES/NO strings, so its full config must never replace jsonData.
    Returns the number of fixes applied to jsonData.
    """
    fixed_cfg = result.get('config_data') or {}
    applied = 0
    for fix in result.get('applied_fixes', []):
        path = fix.get('path') or []
        if not path:
            continue
        key = str(path[0])
        if _is_bc_generated(key):
            log("error", f"Boundary condition issue ({key}): {fix.get('message', '')}. "
                         "Please correct it in the Boundaries tab.")
            continue
        if key in fixed_cfg:
            state.jsonData[key] = _coerce_like(state.jsonData.get(key), fixed_cfg[key])
        else:
            state.jsonData.pop(key, None)
        log("warn", f"Auto-fix applied: {fix.get('message', '')}")
        applied += 1
    return applied


def _run_validation(log_issues):
    """Validate the saved cfg, update the validation panel and apply auto-fixes if enabled."""
    cfg_path = str(active_case_dir() / state.filename_cfg_export)
    auto_fix = bool(state.apply_auto_fixes)
    validator = SU2ConfigValidator()
    result = validator.validate_config_file(cfg_path, auto_fix=auto_fix)

    errors = result.get('errors', [])
    if log_issues and not result.get('valid', False):
        log("error", f"Configuration preflight found {len(errors)} issues")
        # Show up to 10 issues for readability
        for i, err in enumerate(errors[:10], start=1):
            path = "/".join([str(p) for p in err.get('path', [])]) if isinstance(err, dict) else ''
            msg = err.get('message', str(err)) if isinstance(err, dict) else str(err)
            log("error", f"  {i}. {path}: {msg}")
        if len(errors) > 10:
            log("error", f"  ... and {len(errors) - 10} more")

    fixes = result.get('applied_fixes', [])
    state.validation_issues = [
        {
            'path': '/'.join([str(p) for p in (e.get('path') or [])]) if isinstance(e, dict) else '',
            'message': (e.get('message') if isinstance(e, dict) else str(e))
        }
        for e in errors
    ]
    state.validation_fixes = fixes
    state.validation_summary = (
        f"Issues: {len(state.validation_issues)} | Fixes: {len(fixes)} | Auto-fix: {'ON' if auto_fix else 'OFF'}"
    )
    state.dirty('validation_issues'); state.dirty('validation_fixes'); state.dirty('validation_summary'); state.dirty('apply_auto_fixes')

    if auto_fix and fixes and _apply_validation_fixes(result) > 0:
        # Persist the corrected options so SU2 uses them
        save_json_cfg_file(state.filename_json_export, state.filename_cfg_export)
    return result


def run_preflight_validation():
    """Run preflight validation and update the validation panel, without starting SU2."""
    try:
        # Persist current JSON/CFG so validation checks the latest config
        try:
            save_json_cfg_file(state.filename_json_export, state.filename_cfg_export)
        except Exception as e:
            log('warn', f'Could not save config before preflight: {e}')
        _run_validation(log_issues=True)
        log('info', 'Preflight validation complete')
    except Exception as e:
        import traceback
        log('warn', f'Preflight validation failed: {e}', detail=traceback.format_exc())

# matplotlib history
def update_convergence_fields_visibility(index, visibility):
    log("debug", f"index= = {index}")
    log("debug", f"visible= = {state.convergence_fields_visibility}")
    state.convergence_fields_visibility[index] = visibility
    log("debug", f"visible= = {state.convergence_fields_visibility}")
    state.dirty("convergence_fields_visibility")
    log("debug", f"Toggle {index} to {visibility}")


# matplotlib history
# select which variables to use for convergence. Currently: only residual values of the solver
def solver_dialog_card_convergence():
    with vuetify.VDialog(width=300,position='{X:10,Y:10}',transition="dialog-top-transition",v_model=("show_solver_dialog_card_convergence",False)):
      with vuetify.VCard():


        vuetify.VCardTitle("Convergence Criteria",
                           classes="grey lighten-1 py-1 grey--text text--darken-3")
        with vuetify.VContainer(fluid=True):

          # ####################################################### #
          with vuetify.VRow(classes="py-0 my-0"):
            with vuetify.VCol(cols="8", classes="py-1 my-1 pr-0 mr-0"):
              vuetify.VCheckbox(
                              # loop over list of convergence fields
                              v_for="id in convergence_fields_range",
                              key="id",
                              # checkbox changes the state of monitorLinesVisibility[id]
                              v_model=("convergence_fields_visibility[id]",),
                              # name of the checkbox
                              label=("`${ convergence_fields[id] }`",),
                              # on each change, immediately go to update_convergence_fields_visibility
                              change=(update_convergence_fields_visibility,"[id, $event]"),
                              classes="mt-1 pt-1",
                              hide_details=True,
                              dense=True,
              )

        with vuetify.VCardText():
          vuetify.VBtn("close", click=update_solver_dialog_card_convergence)



###############################################################################
def update_solver_dialog_card_convergence():
    log("debug", f"changing state of solver_dialog_Card_convergence to: = {state.show_solver_dialog_card_convergence}")
    state.show_solver_dialog_card_convergence = not state.show_solver_dialog_card_convergence    # if we show the card, then also update the fields that we need to show
    if state.show_solver_dialog_card_convergence==True:
      # RMS residual history fields defined by SU2 for this setup
      # (compressible: RMS_DENSITY..., incompressible: RMS_PRESSURE..., energy: RMS_ENTHALPY,
      #  weakly coupled heat: RMS_TEMPERATURE, SA: RMS_NU_TILDE, SST: RMS_TKE/RMS_DISSIPATION)
      state.convergence_fields = su2_files.residual_history_fields(state.jsonData, state.nDim)
      state.convergence_fields_range = list(range(len(state.convergence_fields)))

      # get the checkbox states from the jsondata
      selected = [str(f) for f in su2_files.as_list(state.jsonData.get('CONV_FIELD'))]
      state.convergence_fields_visibility = [f in selected for f in state.convergence_fields]

      log("debug", f"convergence fields: = {state.convergence_fields}")
      state.dirty('convergence_fields')
      state.dirty('convergence_fields_range')
      state.dirty('convergence_fields_visibility')
    else:
      # the dialog is closed again: update CONV_FIELD in jsonData. Keep the fields that
      # are not RMS residuals (e.g. coefficients used for Cauchy convergence).
      offered = list(state.convergence_fields or [])
      visibility = list(state.convergence_fields_visibility or [])
      kept = [str(f) for f in su2_files.as_list(state.jsonData.get('CONV_FIELD')) if str(f) not in offered]
      chosen = [f for f, v in zip(offered, visibility) if v]
      state.jsonData['CONV_FIELD'] = chosen + kept






###############################################################################
# matplotlib
def update_dialog():
    state.show_dialog = not state.show_dialog
    state.dirty('monitorLinesVisibility')
    state.dirty('monitorLinesNames')
    state.dirty('monitorLinesRange')



###############################################################################
# Iteration counters written by SU2 in the history file (in order of preference)
ITERATION_COLUMNS = ('Inner_Iter', 'Outer_Iter', 'Time_Iter')

# Read the history file
# set the names and visibility
def readHistory(filename):
    log("debug", f"read_history, filename={filename}")

    # Initialize state variables if they don't exist
    _init_state('monitorLinesNames', [])
    _init_state('monitorLinesRange', [])
    _init_state('monitorLinesVisibility', [])
    _init_state('x', [])
    _init_state('ylist', [])
    _init_state('global_iter', 0)

    # Check if file exists. Do not create it: SU2 creates it at the start of the run,
    # and a placeholder written by the GUI could race with SU2.
    filename = str(filename)
    if not os.path.exists(filename):
        log("debug", f"History file does not exist (yet): {filename}")
        state.x = []
        state.ylist = []
        state.global_iter = 0
        return [state.x, state.ylist]

    try:
        # read the history file (SU2 writes quoted, space-padded column names)
        dataframe = su2_files.clean_history_columns(pd.read_csv(filename, skipinitialspace=True))
        # the last line can be incomplete while SU2 is writing it
        dataframe = dataframe.apply(pd.to_numeric, errors="coerce").dropna(how="all")

        # Check if dataframe is empty
        if dataframe.empty:
            # First-run or freshly created file; keep noise low
            log("info", f"History file is empty: {filename}")
            state.x = []
            state.ylist = []
            state.global_iter = 0
            return [state.x, state.ylist]

        # limit the columns to the residuals: rms[...] (and max[...], bgs[...] if requested)
        dfrms = dataframe.filter(regex=r'^(rms|max|bgs)\[')

        # If no columns match the filter, use all numeric columns except the iteration counters
        if dfrms.empty:
            log("info", "No residual columns found, using all numeric columns")
            dfrms = dataframe.drop(columns=[c for c in ITERATION_COLUMNS if c in dataframe.columns])
            dfrms = dfrms.select_dtypes(include=['number'])

            # If still no numeric columns, log warning and return empty
            if dfrms.empty:
                log("warn", "No numeric columns found in history file")
                state.x = []
                state.ylist = []
                state.global_iter = 0
                return [state.x, state.ylist]

        # (re)initialize the line names/visibility when the set of columns changes
        columns = list(dfrms.columns)
        if list(state.monitorLinesNames or []) != columns:
            state.monitorLinesNames = columns
            state.monitorLinesRange = list(range(len(columns)))
            state.monitorLinesVisibility = [True] * len(columns)
            state.dirty('monitorLinesNames')
            state.dirty('monitorLinesVisibility')
            state.dirty('monitorLinesRange')
            log("info", f"Initialized monitor lines: {state.monitorLinesNames}")

        # x axis: the iteration counter written by SU2 (Inner_Iter for steady runs,
        # Time_Iter for unsteady ones); fall back to the row number.
        iter_col = next((c for c in ITERATION_COLUMNS if c in dataframe.columns), None)
        if su2_files.is_time_domain(state.jsonData) and 'Time_Iter' in dataframe.columns:
            iter_col = 'Time_Iter'
        if iter_col is not None:
            state.x = [int(v) for v in dataframe[iter_col].fillna(0).tolist()]
        else:
            state.x = list(range(len(dfrms.index)))
        state.global_iter = state.x[-1] if state.x else 0

        state.ylist = [dfrms.iloc[:, c].tolist() for c in range(len(dfrms.columns))]

        # Update state
        state.dirty('x')
        state.dirty('ylist')
        state.dirty('global_iter')

        log("debug", f"Loaded history data: {len(state.x)} iterations, {len(dfrms.columns)} variables")
        return [state.x, state.ylist]

    except pd.errors.EmptyDataError:
        log("warn", f"History file is empty or has no data: {filename}")
        state.x = []
        state.ylist = []
        state.global_iter = 0
        return [state.x, state.ylist]

    except Exception as e:
        import traceback
        log("error", f"Error reading history file {filename}: {e}", detail=traceback.format_exc())
        state.x = []
        state.ylist = []
        state.global_iter = 0
        return [state.x, state.ylist]


###############################################################################
# read restart file (binary or ASCII)
def Read_SU2_Restart(val_filename):
    """Read an SU2 restart/solution file into a DataFrame.

    The format is detected like SU2 does (CSolver::Read_SU2_Restart_ASCII/Binary):
    a binary file starts with the magic number 535532, otherwise it is the CSV
    written by RESTART_ASCII. Returns an empty DataFrame on failure.
    """
    val_filename = str(val_filename)
    if not os.path.exists(val_filename):
        log("debug", f"Restart file does not exist (yet): {val_filename}")
        return pd.DataFrame()
    try:
        df = su2_files.read_su2_restart(val_filename)
        log("debug", f"Read restart file {val_filename}: {len(df)} points, {len(df.columns)} columns")
        return df
    except Exception as e:
        # typically the file is being rewritten by SU2 while we read it
        log("info", f"Could not read restart file {val_filename}: {e}")
        return pd.DataFrame()


# ##### upload restart/solution file #####
@state.change("restartFile")
def uploadRestart(restartFile, **kwargs):
  log("debug", "Updating restart file")
  if restartFile is None:
    state.jsonData["RESTART_SOL"] = False
    log("debug", "removed file")
    return

  # check if the case name is set
  if not checkCaseName():
    state.restartFile = None
    return

  filename = restartFile['name']
  file = ClientFile(restartFile)

  # raw bytes of the uploaded file
  content = file.content
  if isinstance(content, str):
    if filename.endswith(".dat"):
      try:
        content = b64decode(content, validate=True)
      except Exception:
        content = content.encode('utf-8')
    else:
      content = content.encode('utf-8')

  # SU2 decides the format from READ_BINARY_RESTART and the magic number
  binary = su2_files.bytes_are_su2_binary_restart(content)

  # SU2 reads GetFilename(SOLUTION_FILENAME, ".dat"/".csv"): the file on disk must
  # carry the extension that matches the format.
  stored_name = su2_files.solution_filename_for(filename, binary)
  active_case_dir().mkdir(parents=True, exist_ok=True)
  file_path = active_case_dir() / stored_name

  try:
    with open(file_path, 'wb') as f:
      f.write(content)

    state.jsonData["READ_BINARY_RESTART"] = binary
    state.jsonData["SOLUTION_FILENAME"] = stored_name
    state.jsonData["RESTART_SOL"] = True
    if stored_name != filename:
      log("info", f"Solution file '{filename}' stored as '{stored_name}' (SU2 expects the {'.dat' if binary else '.csv'} extension)")
    if su2_files.is_time_domain(state.jsonData):
      log("warn", "Unsteady restart: SU2 reads SOLUTION_FILENAME with the RESTART_ITER suffix "
                  "(e.g. solution_00009.dat), rename the file accordingly.")

    # Read and process the restart file
    if readRestart(file_path, True, initialization='.auto'):
      log("info", f"Restart file '{filename}' loaded successfully")
  except Exception as e:
    import traceback
    log("error", f"Error uploading restart file: {e}", detail=traceback.format_exc())
    return


# read the restart file and attach its fields to the grid
# reset_active_field is used to show the active field
# returns True when the fields were updated
def readRestart(restartFile, reset_active_field, **kwargs):

  restartFile = str(restartFile)
  log("debug", f"read_restart, filename= = {restartFile}")

  if 'initialization' in kwargs:
    df = Read_SU2_Restart(restartFile)
  else:
    # copy the file first, to reduce the time window in which SU2 can rewrite it
    # while we read it; a partially written binary file is detected by the reader
    lock_file = restartFile + ".lock"
    try:
      shutil.copy2(restartFile, lock_file)
      df = Read_SU2_Restart(lock_file)
    except OSError as e:
      log("debug", f"Restart file not available yet: {e}")
      df = pd.DataFrame()
    finally:
      try:
        os.remove(lock_file)
      except OSError:
        pass

  if df.empty:
    return False

  # check if the points match, if not then the restart does not belong to this mesh
  # (or we were reading while SU2 was writing it) and we skip this update
  points = grid.GetPoints()
  n_points = 0 if points is None else points.GetNumberOfPoints()
  if len(df) != n_points:
    log("info", f"Restart file has {len(df)} points, the mesh has {n_points}: skipping update")
    return False

  field_names = su2_files.solution_fields(df)
  if not field_names:
    log("warn", "Restart file contains no solution fields")
    return False

  # remove the arrays of the previous restart that are not in this one
  point_data = grid.GetPointData()
  previous = [a.get('text') for a in (state.dataset_arrays or [])]
  for name in previous:
    if name not in field_names:
      point_data.RemoveArray(name)

  # construct the dataset_arrays
  datasetArrays = []
  for counter, name in enumerate(field_names):
    values = np.ascontiguousarray(df[name].to_numpy(dtype=np.float64))
    array = numpy_to_vtk(values, deep=1)
    array.SetName(name)
    point_data.AddArray(array)

    datasetArray = {
        "text": name,
        "value": counter,
        "type": vtkDataObject.FIELD_ASSOCIATION_POINTS,
        "range": [float(np.nanmin(values)), float(np.nanmax(values))] if values.size else [0.0, 1.0],
    }
    datasetArrays.append(datasetArray)

  state.dataset_arrays = datasetArrays

  mesh_mapper.SetInputData(grid)
  mesh_actor.SetMapper(mesh_mapper)
  renderer.AddActor(mesh_actor)

  # we should now have the scalars available. If we update the field from an active run, do not reset the
  # active scalar field
  if reset_active_field==True:
    defaultArray = datasetArrays[0]

    mesh_mapper.SelectColorArray(defaultArray.get('text'))
    mesh_mapper.GetLookupTable().SetRange(defaultArray.get('range'))
    mesh_mapper.SetScalarVisibility(True)
    mesh_mapper.SetUseLookupTableScalarRange(True)

    # Mesh: Setup default representation to surface
    mesh_actor.GetProperty().SetRepresentationToSurface()
    mesh_actor.GetProperty().SetPointSize(1)
    #do not show the edges
    mesh_actor.GetProperty().EdgeVisibilityOff()

    # We have loaded a mesh, so enable the exporting of files
    state.export_disabled = False

  ctrl.view_update()
  return True


###############################################################################
def figure_size():
    if state.figure_size is None:
        return {}

    dpi = state.figure_size.get("dpi")
    rect = state.figure_size.get("size")
    w_inch = rect.get("width") / dpi
    h_inch = rect.get("height") / dpi

    if ((w_inch<=0) or (h_inch<=0)):
       return {}

    return {
        "figsize": (w_inch, h_inch),
        "dpi": dpi,
    }




###############################################################################
def mpl_plot_history():
    plt.close('all')
    fig, ax = plt.subplots(1, 1, **figure_size(), facecolor='blue')
    ax.set_facecolor('#eafff5')
    fig.set_facecolor('blue')
    fig.patch.set_facecolor('blue')
    fig.subplots_adjust(top=0.98, bottom=0.15, left=0.05, right=0.99, hspace=0.0, wspace=0.0)

    has_lines = False

    try:
        # Check if state variables are properly initialized
        if not hasattr(state, 'monitorLinesRange') or not hasattr(state, 'monitorLinesVisibility'):
            log("info", "Monitor line state variables not initialized")
            ax.text(0.5, 0.5, 'No history data available\nRun a simulation to generate data',
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes, fontsize=12)
            return fig

        if not hasattr(state, 'x') or not hasattr(state, 'ylist'):
            log("info", "History data not available")
            ax.text(0.5, 0.5, 'No history data available\nRun a simulation to generate data',
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes, fontsize=12)
            return fig

        # Check if we have data to plot
        if not state.x or not state.ylist:
            log("info", "No history data to plot")
            ax.text(0.5, 0.5, 'No history data available\nRun a simulation to generate data',
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes, fontsize=12)
            return fig

        # Ensure all arrays have the same length
        if len(state.monitorLinesRange) != len(state.monitorLinesVisibility):
            log("warn", f"Mismatch in monitor line arrays: range={len(state.monitorLinesRange)}, visibility={len(state.monitorLinesVisibility)}")
            # Fix the arrays
            max_len = max(len(state.monitorLinesRange), len(state.monitorLinesVisibility))
            while len(state.monitorLinesRange) < max_len:
                state.monitorLinesRange.append(len(state.monitorLinesRange))
            while len(state.monitorLinesVisibility) < max_len:
                state.monitorLinesVisibility.append(True)

        # Plot the data
        for idx in state.monitorLinesRange:
            if idx < len(state.monitorLinesVisibility) and state.monitorLinesVisibility[idx]:
                if idx < len(state.ylist):
                    label = state.monitorLinesNames[idx] if (hasattr(state, 'monitorLinesNames') and idx < len(state.monitorLinesNames)) else f'Variable {idx}'
                    color = mplColorList[idx % len(mplColorList)]
                    ax.plot(state.x, state.ylist[idx], label=label, linewidth=2, color=color)
                    has_lines = True

        ax.set_xlabel('Iterations', labelpad=10)
        ax.set_ylabel('Residuals', labelpad=10)
        ax.grid(True, color="lightgray", linestyle="solid")

        if has_lines:
            ax.legend(framealpha=1, facecolor='white')
        else:
            ax.text(0.5, 0.5, 'No visible data lines\nCheck line visibility settings',
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes, fontsize=12)

        ax.autoscale(enable=True, axis="x")
        ax.autoscale(enable=True, axis="y")

    except IndexError as e:
        log("error", f"IndexError in plot history: {e}")
        if hasattr(state, 'x'):
            log("error", f"state.x length: {len(state.x)}")
        if hasattr(state, 'ylist'):
            log("error", f"state.ylist length: {len(state.ylist)}")
        if hasattr(state, 'monitorLinesNames'):
            log("error", f"state.monitorLinesNames length: {len(state.monitorLinesNames)}")
        if hasattr(state, 'monitorLinesVisibility'):
            log("error", f"state.monitorLinesVisibility length: {len(state.monitorLinesVisibility)}")

        # Show error message on plot
        ax.text(0.5, 0.5, f'Error plotting data: {str(e)}\nCheck logs for details',
               horizontalalignment='center', verticalalignment='center',
               transform=ax.transAxes, fontsize=10, color='red')

    except Exception as e:
        log("error", f"Unexpected error in plot history: {e}")
        ax.text(0.5, 0.5, f'Error plotting data: {str(e)}\nCheck logs for details',
               horizontalalignment='center', verticalalignment='center',
               transform=ax.transAxes, fontsize=10, color='red')

    return fig
