import shutil
import zipfile, os
import sys
from io import BytesIO
from pathlib import Path

# Add parent directory to path to allow importing from sibling directories
parent_dir = str(Path(__file__).parent.parent.absolute())
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
from core.paths import (case_dir, cases_root, is_case_dir, is_valid_case_name, list_cases,
                        mark_case_dir, set_cases_root, set_active_case)
from ui.server_files import register_server_dir_target, open_server_browser, is_allowed_path

from trame.widgets import markdown, html
from trame.widgets import vuetify

from ui.fileio import set_json_fileio
from ui.initialization import set_json_initialization
from core.logger import log
from ui.materials import set_json_materials
from ui.numerics import set_json_numerics
from ui.physics import set_json_physics
from core.su2_io import save_json_cfg_file, save_su2mesh
from core.su2_json import updateBCDictListfromJSON
from core import su2_files
from ui.uicard import server
from ui.mesh import root, mesh_actor, mesh_mapper
from ui.vtk_helper import renderer
from core.solver import proc_SU2, set_json_solver
from core.su2_py_wrapper import save_json_cfg_py_file, generate_python_wrapper


from pathlib import Path
BASE = Path(__file__).parent.parent
# the cases are in core.paths.cases_root() (--cases-dir / SU2GUI_CASES_DIR)


state, ctrl = server.state, server.controller


# show the material dialog cards
state.show_manage_case_dialog_card = False
state.case_name = ''
state.case_name_help = ""
state.case_list = []
# full path of the active case and of the cases folder (shown in the GUI)
state.case_path = ""
state.cases_root_path = str(cases_root())


@state.change("case_name")
def update_case_path(case_name, **kwargs):
    state.case_path = str(case_dir(case_name)) if case_name else ""
    state.cases_root_path = str(cases_root())


# folder where a new case is created (asked in the "Start a new case" dialog)
state.new_case_location = str(cases_root())
state.new_case_preview = ""


def _new_case_dir(name, location):
    """Directory of a new case named ``name`` in ``location`` (None if invalid)."""
    name = (name or "").strip().replace(" ", "_")
    location = (location or "").strip() or str(cases_root())
    if not is_valid_case_name(name):
        return None
    return Path(location).expanduser().resolve() / name


@state.change("new_case_name", "new_case_location")
def update_new_case_preview(new_case_name, new_case_location, **kwargs):
    target = _new_case_dir(new_case_name, new_case_location)
    state.new_case_preview = str(target) if target else "(enter a valid case name)"


def _set_new_case_location(path):
    state.new_case_location = str(path)


def change_cases_folder(path):
    """Show/manage the cases of another folder (the active case stays where it is)."""
    if not is_allowed_path(Path(path)):
        log("error", f"{path} is outside of the folders allowed by --browse-root")
        return
    try:
        root = set_cases_root(path, remember=True)
    except OSError as e:
        log("error", f"Cannot use {path} as cases folder: {e}")
        return
    state.cases_root_path = str(root)
    state.new_case_location = str(root)
    set_cases_list()
    log("info", f"Cases folder: {root}")


register_server_dir_target("case_location", "Folder for the new case", _set_new_case_location)
register_server_dir_target("cases_folder", "Cases folder", change_cases_folder)


############# DIALOG CARDS ##############

# Dialog card for managing CASES
def manage_case_dialog_card():
    with vuetify.VDialog(position='{X:10,Y:10}',
                         width = 650,
                         min_height = 300,
                         transition="dialog-top-transition",
                         v_model=("show_manage_case_dialog_card",False),
                         ):
        with vuetify.VCard():
            vuetify.VCardTitle("Manage Cases",
                           classes="grey lighten-1 py-1 grey--text text--darken-3")


            with vuetify.VContainer(fluid=True, style = "padding: 20px;"):
            # ####################################################### #

                with vuetify.VRow():
                    with vuetify.VCol( classes='col-3'):
                        markdown.Markdown(
                                content=('current_case', "Current Case: "),
                                style="color:black; background-color:white;"
                                )
                    with vuetify.VCol():
                        markdown.Markdown(
                                content=("case_name || 'None'", state.case_name),
                                style="color:black; background-color:white; "
                                )

                # where the cases are stored on the server
                with vuetify.VRow(dense=True):
                    with vuetify.VCol(classes='col-3'):
                        html.Div("Case folder:", style="color:black;")
                    with vuetify.VCol():
                        html.Div("{{ case_path || '-' }}",
                                 style="font-family: monospace; word-break: break-all; color:black;")
                with vuetify.VRow(dense=True):
                    with vuetify.VCol(classes='col-3'):
                        html.Div("All cases in:", style="color:black;")
                    with vuetify.VCol():
                        html.Div("{{ cases_root_path }}",
                                 style="font-family: monospace; word-break: break-all; color:black;")
                    with vuetify.VCol(cols="auto"):
                        # show the cases of another folder
                        with vuetify.VBtn("Change", small=True,
                                          click=(open_server_browser, "['cases_folder', cases_root_path]"),
                                          disabled=("solver_running", False)):
                            vuetify.VIcon("mdi-folder-search-outline", right=True, small=True)

                with vuetify.VRow():
                    with vuetify.VCol():
                        vuetify.VSelect(
                            v_model=("selected_case_idx", None),
                            items=("case_list",state.case_list),
                            # the name of the list box
                            label="Cases",
                            hide_details=True,
                            dense=True,
                            outlined=True,
                            classes="m-4",
                        )

                with vuetify.VRow():
                    with vuetify.VCol():
                        vuetify.VCheckbox(
                                    v_model=("select_all_cases", False),
                                    label = "Select all cases",
                                    outlined=True,
                                    hide_details=True,
                                    dense=True,
                                )

                with vuetify.VRow():
                    with vuetify.VCol():
                        with vuetify.VBtn("Download",
                                    click=f"utils.download('output.zip', trigger('download_case'))"
                        ):
                            vuetify.VIcon("mdi-download-box-outline")
                    with vuetify.VCol():
                        with vuetify.VBtn("Delete",
                                    click=(delete_case, '[selected_case_idx]'),
                                    disabled=("selected_case_idx == case_name || solver_running", False)
                        ):
                            vuetify.VIcon("mdi-trash-can-outline")
                    with vuetify.VCol():
                        with vuetify.VBtn("Load Case",
                                    click=(load_case, '[selected_case_idx]'),
                                    disabled=("selected_case_idx == case_name || solver_running", False)
                        ):
                            vuetify.VIcon("mdi-folder-edit-outline")
                    with vuetify.VCol():
                        with vuetify.VBtn("New Case",
                                    disabled=("solver_running",False),
                                    click=open_new_case_dialog
                        ):
                            vuetify.VIcon("mdi-folder-plus-outline")


# Dialog Box for taking case name
def case_name_dialog_card():
    with vuetify.VDialog(position='{X:10,Y:10}',
                         width = 350,
                         transition="dialog-top-transition",
                         v_model=("show_case_name_dialog", True)):
        with vuetify.VCard():
            vuetify.VCardTitle("Start a new case",
                           classes="grey lighten-1 py-1 grey--text text--darken-3")
            with vuetify.VContainer(fluid=True, style = "padding-left: 20px;"):
                    markdown.Markdown(
                        content=("case_name_help", state.case_name_help),
                        style="color:white; background-color:white;"
                        )
                    with vuetify.VCardText():
                        vuetify.VTextField(
                            label="Case Name",
                            v_model=("new_case_name", state.case_name),
                            outlined=True,
                            dense=True,
                            hide_details=True,
                        )
                        # where the case is created (folder on the server, created if needed)
                        with vuetify.VRow(dense=True, classes="mt-3 align-center"):
                            with vuetify.VCol(cols="10", classes="pa-0"):
                                vuetify.VTextField(
                                    label="Folder (on the server)",
                                    v_model=("new_case_location", state.new_case_location),
                                    outlined=True,
                                    dense=True,
                                    hide_details=True,
                                )
                            with vuetify.VCol(cols="2", classes="pa-0 text-right"):
                                with vuetify.VBtn(icon=True, small=True,
                                                  click=(open_server_browser, "['case_location', new_case_location]"),
                                                  title="Choose the folder on the server",
                                                  __properties=["title"]):
                                    vuetify.VIcon("mdi-folder-search-outline")
                        html.Div("The case will be created in: {{ new_case_preview }}",
                                 classes="text-caption mt-2",
                                 style="font-family: monospace; word-break: break-all; color: grey;")
                    vuetify.VCheckbox(
                                    v_model=("delete_all_previous_cases", False),
                                    label = "Delete all previous cases",
                                    outlined=True,
                                    hide_details=True,
                                    dense=True,
                                )

                    with vuetify.VRow(classname= 'pt-4'):
                        with vuetify.VCol():
                            with vuetify.VCardActions():
                                with vuetify.VBtn("Create ", click="trigger('create_new_case')"):
                                    vuetify.VIcon("mdi-folder-plus-outline")
                        with vuetify.VCol():
                            with vuetify.VCardActions():
                                with vuetify.VBtn("Load Case", click=open_manage_case_dialog):
                                    vuetify.VIcon("mdi-folder-edit-outline")



############# BUTTONS ##############

# function to open the new case dialog
def open_new_case_dialog():
    set_cases_list()
    state.new_case_location = str(cases_root())
    state.delete_all_previous_cases = False
    state.show_manage_case_dialog_card = False
    state.case_name_help = ''
    state.show_case_name_dialog = True

# function to open the manage case dialog
def open_manage_case_dialog():
    set_cases_list()
    state.show_case_name_dialog = False
    state.case_name_help = ''
    state.show_manage_case_dialog_card = True


# function to delete the cases
def delete_case(case_name):
    # if select_all_cases is True, delete all cases
    if state.select_all_cases==True:
        state.select_all_cases=False
        set_cases_list()
        for case in state.case_list:
            delete_case(case)
        return
    if case_name is None or case_name == '' or case_name == state.case_name:
        return
    # delete the single case, only if it is a case directory created by SU2GUI
    if not is_valid_case_name(case_name) or not is_case_dir(case_dir(case_name)):
        log("error", f"'{case_name}' is not an SU2GUI case directory, it was not deleted.")
        return
    log('info', f'case name = {case_name}')
    case_path = case_dir(case_name)
    try:
        shutil.rmtree(case_path)
        log("info", f"Case '{case_name}' deleted successfully.")
    except FileNotFoundError:
        log("Warn", f"Case '{case_name}' not found. - {case_path}")
    set_cases_list()


# function to download the cases
@ctrl.trigger("download_case")
def download_case():
    case_name = state.selected_case_idx
    if (case_name is None or case_name == '') and state.select_all_cases==False:
        return

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_ref:

        # if select_all_cases is False, download all files in the case folder
        if state.select_all_cases==False:

            # save the cfg file
            save_json_cfg_file(state.filename_json_export,state.filename_cfg_export)

            case_path = case_dir(case_name)
            if case_name == '':
                log("Error", "No case selected.")
                return

            # check if the case path exists
            if not os.path.isdir(case_path):
                log("Error", f"Case '{case_path}' not found.")
                return

            for root, dirs, files in os.walk(case_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    zip_ref.write(file_path, os.path.relpath(file_path, case_path))

        # if select_all_cases is True, download all cases
        else:
            case_path = cases_root()

            # check if the case path exists
            if not os.path.isdir(case_path):
                log("Error", f"Cases '{case_path}' not found.")
                return

            for root, dirs, files in os.walk(case_path):
                for dir_name in dirs:
                    folder_path = os.path.join(root, dir_name)
                    # Add the directory to the zip file
                    zip_ref.write(folder_path, os.path.relpath(folder_path, case_path))
                    # Add files inside the directory to the zip file
                    for sub_root, sub_dirs, sub_files in os.walk(folder_path):
                        for file_name in sub_files:
                            file_path = os.path.join(sub_root, file_name)
                            zip_ref.write(file_path, os.path.relpath(file_path, case_path))
                        # Stop further walking into subdirectories
                        break

    zip_buffer.seek(0)  # Reset buffer position to the beginning
    log("info", f"Case '{case_name}' downloaded successfully.")
    return zip_buffer.getvalue()



# function to create a new case
@ctrl.trigger("create_new_case")
def create_new_case():
    new_name = (state.new_case_name or "").strip().replace(" ", "_")

    # the folder chosen in the dialog becomes the cases folder (remembered for the next start)
    location = (state.new_case_location or "").strip() or str(cases_root())
    location_path = Path(location).expanduser()
    if not location_path.is_absolute():
        state.case_name_help = "> Please enter an absolute folder path (e.g. /scratch/user/su2gui_cases)."
        return
    if not is_allowed_path(location_path):
        state.case_name_help = f"> '{location}' is outside of the folders allowed by --browse-root."
        return
    if location_path.exists() and not location_path.is_dir():
        state.case_name_help = f"> '{location}' is a file, not a folder."
        return
    try:
        root = set_cases_root(location_path, remember=True)
    except OSError as e:
        state.case_name_help = f"> Cannot create the folder '{location}':  \n{e}"
        return
    state.cases_root_path = str(root)
    state.new_case_location = str(root)

    set_cases_list()

    if state.delete_all_previous_cases == True:
        set_cases_list()
        for case in state.case_list:
            delete_case(case)

    if new_name == "":
        state.case_name_help = "> Please enter a valid case name."

    elif not is_valid_case_name(new_name):
        state.case_name_help = "> The case name cannot contain '/', '\\' or start with '.'."

    elif new_name in state.case_list:
        state.case_name_help = "> Case name already exists.  \nPlease enter a different name."

    elif (root / new_name).exists():
        # a file or folder that is not an SU2GUI case: do not write into it
        state.case_name_help = f"> '{root / new_name}' already exists and is not an SU2GUI case.  \nPlease enter a different name."

    else:

        state.show_case_name_dialog = False
        reset_values()
        # the case stays in this folder also if the cases folder is changed later
        set_active_case(new_name, root / new_name)
        state.case_name = new_name
        try:
            mark_case_dir(case_dir(state.case_name))
            log("info", f"Case '{state.case_name}' created in {case_dir(state.case_name)}")
        except OSError as e:
            log("error", f"Could not create the case directory {case_dir(state.case_name)}:  \n{e}")
            return

        # create history file
        with open(case_dir(state.case_name) / state.history_filename, 'w') as f:
            f.write('"Time_Iter","Outer_Iter","Inner_Iter",     "rms[P]"     ,     "rms[U]"     ,     "rms[V]"     ,     "rms[T]"     ,     "rms[nu]"    ')

        log("info", f"Case name set to {state.case_name}")

        # Create a default Python wrapper (and config/json) for the new case
        try:
            json_name = getattr(state, 'filename_json_export', 'config.json') or 'config.json'
            cfg_name = getattr(state, 'filename_cfg_export', 'config.cfg') or 'config.cfg'
            py_name = getattr(state, 'filename_py_export', 'run_su2.py') or 'run_su2.py'
            save_json_cfg_py_file(json_name, cfg_name, py_name)
            log("info", f"Default Python wrapper '{py_name}' created for case '{state.case_name}'.")
        except Exception as e:
            log("warn", f"Could not create default Python wrapper for case '{state.case_name}': {e}")

        if state.delete_all_previous_cases == True:
            set_cases_list()
            for case in state.case_list:
                if case != state.case_name:
                    delete_case(case)


# function to load existing case
def load_case(case_name):
    # save the cfg file for the previous case
    save_json_cfg_file(state.filename_json_export,state.filename_cfg_export)
    if case_name is None or case_name == '':
        log("Error", "No case selected.")
        return
    # the cases of the list are in the current cases folder
    set_active_case(case_name, cases_root() / case_name)
    state.case_name = case_name
    state.show_manage_case_dialog_card = False
    state.show_case_name_dialog = False
    reset_values()
    case_path = case_dir(case_name)

    # get the list of files in the case path
    root, dirs, filenames = os.walk(case_path).__next__()
    del dirs

    # try to load mesh file first
    for file in filenames:
        if file.endswith(".su2"):
            mesh_path = os.path.join(root, file)
            with open(mesh_path, 'r') as f:
                content = f.read()
                state.su2_file_upload = {
                    "name": os.path.basename(mesh_path),
                    "size" : os.stat(mesh_path).st_size,
                    "content": content,
                    "type": "text/plain",
                }
            state.dirty('su2_file_upload')
            state.flush()
            break

    # try to load config file
    for file in filenames:
        if file.endswith(".cfg"):
            config_path = os.path.join(root, file)
            with open(config_path, 'r') as f:
                content = f.read()

            state.cfg_file_upload = {
                "name": os.path.basename(config_path),
                "size" : os.stat(config_path).st_size,
                "content": content,
                "type": "text/plain",
            }
            # process the config upload now, so that state.jsonData is the loaded configuration
            state.dirty('cfg_file_upload')
            state.flush()

            log("info", f"Config file {state.cfg_file_upload['name']} loaded successfully.")

            # restart file written by SU2 for this configuration: RESTART_FILENAME with the
            # extension implied by OUTPUT_FILES (.dat binary, .csv for RESTART_ASCII) and,
            # for unsteady runs, the _<iter> suffix of the last time step
            state.restart_filename = state.jsonData.get('RESTART_FILENAME', 'restart') or 'restart'
            restart_path = su2_files.latest_restart_path(root, state.jsonData)
            log('info', f"Restart file = {restart_path}")

            if not os.path.isfile(restart_path):
                log("info", f"Restart file '{restart_path}' not found in the case.")
                break

            with open(restart_path, 'rb') as f:
                content = f.read()
            state.restartFile = {
                "name": os.path.basename(restart_path),
                "size" : os.stat(restart_path).st_size,
                "content": content,
                "type": "application/octet-stream",
            }

            log("info", f"Restart file '{restart_path.name}' loaded successfully.")

            break

    # Ensure a default Python wrapper exists for this case
    try:
        py_name = getattr(state, 'filename_py_export', 'run_su2.py') or 'run_su2.py'
        json_name = getattr(state, 'filename_json_export', 'config.json') or 'config.json'
        cfg_name_default = getattr(state, 'filename_cfg_export', 'config.cfg') or 'config.cfg'

        py_path = os.path.join(case_path, os.path.splitext(py_name)[0] + '.py')

        if 'config_path' not in locals():
            # No config found in the case; create default JSON/CFG/PY trio
            save_json_cfg_py_file(json_name, cfg_name_default, py_name)
            log("info", f"Default config and Python wrapper created for case '{state.case_name}'.")
        elif not os.path.isfile(py_path):
            # Config exists; just create wrapper that points to it
            generate_python_wrapper(
                json_data=getattr(state, 'jsonData', {}),
                filename_py_export=py_name,
                output_dir=case_path,
                config_filename=os.path.basename(config_path),
            )
            log("info", f"Default Python wrapper '{py_name}' created for case '{state.case_name}'.")
    except Exception as e:
        log("warn", f"Could not ensure default Python wrapper for case '{state.case_name}': {e}")

    log("info", f"Case '{case_name}' loaded successfully.")


#############################################
# Button to download the specific output files (currently not is use)
@ctrl.trigger("download_output_files")
def download_outputs():
    files_directory = case_dir(state.case_name)

    save_json_cfg_file(state.filename_json_export,state.filename_cfg_export)
    save_su2mesh(root,state.jsonData['MESH_FILENAME'])

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_ref:
        for filename, list in state.output_list.items():
            if list[0]:
                file_path = os.path.join(files_directory, filename)
                if os.path.isfile(file_path):
                    # binary copy: restart (.dat) and VTK outputs are binary files
                    zip_ref.write(file_path, arcname=list[1])
                else:
                    log("Warn", f"{file_path} does not exist and will not be included in the zip file.")

    zip_buffer.seek(0)  # Reset buffer position to the beginning
    update_manage_case_dialog_card()
    log("info", f"Zip file downloaded successfully.")
    return zip_buffer.getvalue()


#############################################

# get the names of the case folders in the cases root and set case names list
def set_cases_list():
    if not cases_root().is_dir():
        log('error', f"Cases folder not found: '{cases_root()}'")
    state.case_list = list_cases()
    log('info', f"Cases list = {state.case_list}")

# function to start case from the terminal
def case_args(case_name):
    set_cases_list()
    state.new_case_name = case_name
    if case_name in state.case_list:
        load_case(case_name)
    else:
        create_new_case()
    state.flush()


# reset the values, when a new case is created
def reset_values():
    # we need to terminate or kill the result process here
    if state.solver_running:
        state.solver_running = False
        state.solver_icon="mdi-play-circle"
        # proc_SU2.kill()


    # reset the input files
    state.restartFile = None
    state.su2_file_upload = None
    state.cfg_file_upload = None


    state.monitorLinesVisibility = []
    state.monitorLinesNames = []
    state.monitorLinesRange = []

    state.initialize=-1
    # number of dimensions of the mesh (2 or 3)
    state.nDim = 2

    # which boundary is selected?
    state.selectedBoundaryName="none"
    state.selectedBoundaryIndex = 0

    state.BCDictList = [{"bcName": "main_wall",
                     "bcType":"Wall",
                     "bc_subtype":"Temperature",
                     "json":"MARKER_ISOTHERMAL",
                     "bc_velocity_magnitude":0.0,
                     "bc_temperature":300.0,
                     "bc_pressure":0,
                     "bc_density":0.0,
                     "bc_massflow":1.0,
                     "bc_velocity_normal":[1,0,0],
                     "bc_heatflux":0.0,
                     "bc_heattransfer":[1000.0,300.0],
                     }]
    # disable the export file button
    state.export_disabled=True

    # (solver.py) disable the solve button
    state.su2_solve_disabled=False

    # solver settings
    # current solver icon
    state.solver_icon = "mdi-play-circle"
    # current running state
    state.solver_running = False

    state.su2_meshfile="mesh_out.su2"

    state.selectedBoundary = 0

    mesh_actor_list = [{"id":0,"name":"internal","mesh":mesh_actor}]

    mesh_actor.SetMapper(mesh_mapper)
    mesh_actor.SetObjectName("initial_square")

    # Mesh: Setup default representation to surface
    mesh_actor.GetProperty().SetRepresentationToSurface()
    mesh_actor.GetProperty().SetPointSize(1)
    # show the edges
    mesh_actor.GetProperty().EdgeVisibilityOn()
    # color is based on field values
    renderer.AddActor(mesh_actor)

    # set su2 logs to empty
    state.su2_logs = ''

    # # reset jsondata
    # with open('./user/config.json', 'r') as f:
    #     state.jsonData = json.load(f)

    # state.dirty('jsonData')

    # # save the cfg file
    # # save_json_cfg_file(state.filename_json_export,state.filename_cfg_export)

    # updateBCDictListfromJSON()
    # # set all physics states from the json file
    # # this is reading the config file (done by read_json_data) and filling it into the GUI menu's
    # set_json_physics()
    # set_json_initialization()
    # set_json_numerics()
    # set_json_solver()
    # set_json_fileio()
    # set_json_materials()

# when the manage case dialog card is opened, update the cases list
def update_manage_case_dialog_card():
    set_cases_list()
    state.show_manage_case_dialog_card = not state.show_manage_case_dialog_card
