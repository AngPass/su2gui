import sys
import os
import re
import json
from pathlib import Path

# Try to import VTK (optional for validation functions)
try:
    import vtk
    VTK_AVAILABLE = True
except ImportError:
    VTK_AVAILABLE = False

# Add parent directory to path to allow importing from sibling directories
parent_dir = str(Path(__file__).parent.parent.absolute())
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
from core.paths import case_dir, cases_root

try:
    from core.su2_json import *
except ImportError:
    pass

try:
    from core.logger import log
except ImportError:
    # Fallback logging function
    def log(level, message):
        print(f"[{level.upper()}] {message}")

try:
    from core.su2_py_wrapper import save_json_cfg_py_file
except ImportError:
    pass

# Import validation functions
try:
    from core.json_validation import cfg_to_json_dict, validate_cfg_with_schema, apply_su2_fixes, apply_schema_fixes
    VALIDATION_AVAILABLE = True
except ImportError:
    log("warning", "Validation functions not available")
    VALIDATION_AVAILABLE = False

BASE = Path(__file__).parent.parent

# catalog of the SU2 options (names, enum values, deprecated names)
from core import su2_options

# remove empty lists from dictlist object
def remove_empty_lists(d):
  final_dict = {}
  for a, b in d.items():
     if b:
       if isinstance(b, dict):
         final_dict[a] = remove_empty_lists(b)
       elif isinstance(b, list):
         final_dict[a] = list(filter(None, [remove_empty_lists(i) for i in b]))
       else:
         final_dict[a] = b
  return final_dict

########################################################################################
# create the json entries for the boundaries using BCDictList
########################################################################################
# Options generated from the boundary conditions. Empty lists are not written.
MARKER_OPTION_KEYS = (
  'MARKER_ISOTHERMAL', 'MARKER_HEATFLUX', 'MARKER_HEATTRANSFER', 'MARKER_EULER',
  'MARKER_WALL_FUNCTIONS', 'MARKER_OUTLET', 'INC_OUTLET_TYPE', 'MARKER_SYM', 'MARKER_FAR',
  'MARKER_INLET', 'INC_INLET_TYPE', 'INLET_TYPE', 'MARKER_SUPERSONIC_INLET',
  'MARKER_SUPERSONIC_OUTLET',
)


def build_marker_options(bc_list, wall_function, warn=True):
  """Marker options for the boundary conditions in ``bc_list`` (BCDictList).

  Returns a dict {option: value}; a value of None means that the option must be
  removed from the configuration. Pure function: the state is not modified.
  """
  marker_inlet=[]
  marker_isothermal=[]
  marker_heatflux=[]
  marker_heattransfer=[]
  marker_euler=[]
  marker_symmetry=[]
  marker_farfield=[]
  marker_outlet=[]
  marker_supersonic_inlet=[]
  marker_supersonic_outlet=[]
  marker_wall_functions = []

  # PRESSURE_OUTLET or MASS_FLOW_OUTLET
  marker_inc_outlet_type=[]
  # PRESSURE_INLET or VELOCITY_INLET
  marker_inc_inlet_type=[]
  # TOTAL_CONDITIONS or MASS_FLOW
  marker_inlet_type=[]

  # loop over the boundaries and construct the markers
  for bcdict in (bc_list or []):
    subtype = bcdict.get('bc_subtype')
    name = bcdict.get('bcName')
    # ##### WALL BOUNDARY CONDITIONS #####
    if subtype=="Temperature":
        marker_isothermal.append( [name, bcdict['bc_temperature']] )
        marker_wall_functions.append( [name, "STANDARD_WALL_FUNCTION"] )
    elif subtype=="Heat flux":
        marker_heatflux.append( [name, bcdict['bc_heatflux']] )
        marker_wall_functions.append( [name, "STANDARD_WALL_FUNCTION"] )
    elif subtype=="Heat transfer":
        marker = [name]
        marker.extend(bcdict['bc_heattransfer'])
        marker_heattransfer.append( marker )
        marker_wall_functions.append( [name, "STANDARD_WALL_FUNCTION"] )
    elif subtype=="Euler":
        # inviscid (slip) wall: no wall function, MARKER_WALL_FUNCTIONS is for viscous walls only
        marker_euler.append([name])
    # ##### OUTLET BOUNDARY CONDITIONS #####
    elif subtype=="Target mass flow rate":
        marker_outlet.append( [name, bcdict['bc_massflow']] )
        marker_inc_outlet_type.append("MASS_FLOW_OUTLET")
    elif subtype=="Pressure outlet":
        marker_outlet.append( [name, bcdict['bc_pressure']] )
        marker_inc_outlet_type.append("PRESSURE_OUTLET")
    # ##### INLET BOUNDARY CONDITIONS #####
    elif subtype=="Velocity inlet":
        # note that temperature is always saved.
        marker = [name, bcdict['bc_temperature'], bcdict['bc_velocity_magnitude']]
        marker.extend(bcdict['bc_velocity_normal'])
        marker_inlet.append( marker )
        marker_inc_inlet_type.append("VELOCITY_INLET")
    elif subtype=="Pressure inlet":
        marker = [name, bcdict['bc_temperature'], bcdict['bc_pressure']]
        marker.extend(bcdict['bc_velocity_normal'])
        marker_inlet.append( marker )
        marker_inc_inlet_type.append("PRESSURE_INLET")
    elif subtype=="Total Conditions":
        marker = [name, bcdict['bc_temperature'], bcdict['bc_pressure']]
        marker.extend(bcdict['bc_velocity_normal'])
        marker_inlet.append( marker )
        marker_inlet_type.append("TOTAL_CONDITIONS")
    elif subtype=="Mass Flow":
        marker = [name, bcdict['bc_density'], bcdict['bc_velocity_magnitude']]
        marker.extend(bcdict['bc_velocity_normal'])
        marker_inlet.append( marker )
        marker_inlet_type.append("MASS_FLOW")
    # ##### SYMMETRY BOUNDARY CONDITIONS #####
    elif subtype=="Symmetry":
        marker_symmetry.append( [name] )
    # ##### FARFIELD BOUNDARY CONDITIONS #####
    elif subtype=="Far-field":
        marker_farfield.append( [name] )
    # ##### SUPERSONIC INLET BOUNDARY CONDITIONS #####
    elif subtype=="Supersonic Inlet":
        marker = [name, bcdict['bc_temperature'], bcdict['bc_pressure']]
        marker.extend(bcdict['bc_velocity_normal'])
        marker_supersonic_inlet.append( marker )
    # ##### SUPERSONIC OUTLET BOUNDARY CONDITIONS #####
    elif subtype=="Supersonic Outlet":
        marker_supersonic_outlet.append( [name] )

  options = {
    'MARKER_ISOTHERMAL': marker_isothermal,
    'MARKER_HEATFLUX': marker_heatflux,
    'MARKER_HEATTRANSFER': marker_heattransfer,
    'MARKER_EULER': marker_euler,
    # do not keep wall functions of a previous setting
    'MARKER_WALL_FUNCTIONS': marker_wall_functions if wall_function else None,
    'MARKER_OUTLET': marker_outlet,
    'INC_OUTLET_TYPE': marker_inc_outlet_type,
    'MARKER_SYM': marker_symmetry,
    'MARKER_FAR': marker_farfield,
    'MARKER_INLET': marker_inlet,
    'INC_INLET_TYPE': marker_inc_inlet_type,
    'MARKER_SUPERSONIC_INLET': marker_supersonic_inlet,
    'MARKER_SUPERSONIC_OUTLET': marker_supersonic_outlet,
  }

  # INLET_TYPE (compressible) is a single enum in SU2 (addEnumOption): one type for all
  # inlet markers, unlike INC_INLET_TYPE which is a list with one entry per marker.
  if marker_inlet_type:
    if warn and len(set(marker_inlet_type)) > 1:
      log("error", f"SU2 supports a single INLET_TYPE for all compressible inlets, found {sorted(set(marker_inlet_type))}. "
                   f"Using {marker_inlet_type[0]} for all inlets.")
    options['INLET_TYPE'] = marker_inlet_type[0]
  else:
    options['INLET_TYPE'] = None
  return options


def case_configuration(json_data, bc_list, wall_function, warn=True):
  """The configuration written to the case: json_data with the boundary markers
  of bc_list, deprecated SU2 options renamed, without empty lists.
  Pure function: the state is not modified."""
  cfg = dict(json_data or {})
  for key, value in build_marker_options(bc_list, wall_function, warn=warn).items():
    if value is None:
      cfg.pop(key, None)
    else:
      cfg[key] = value
  # options renamed/removed in SU2 (SU2 stops on deprecated names)
  cfg, messages = su2_options.migrate(cfg)
  report_option_issues([(None, m) for m in messages], level="warn")
  # all empty markers will be removed for writing
  return {key: val for key, val in cfg.items() if val != []}


# messages already shown in this session (the autosave checks every few seconds)
_reported_issues = set()


def report_option_issues(issues, prefix="", level="error"):
  """Log the problems found by su2_options.check()/migrate() once per session."""
  for _key, message in issues:
    text = f"{prefix}{message}"
    if text in _reported_issues:
      continue
    _reported_issues.add(text)
    log(level, f"{text}  \n(checked against the options of {su2_options.source()}; "
               "SU2 stops on unknown options and invalid values)" if level == "error" else text)


def createjsonMarkers():
  """Update state.jsonData with the markers of the boundary conditions."""
  state.jsonData = case_configuration(state.jsonData, state.BCDictList, state.wall_function)


def _flatten(value):
  for item in value:
    if isinstance(item, (list, tuple)):
      yield from _flatten(item)
    else:
      yield item


_VARIABLE_PATTERN = re.compile(r"\b([A-Za-z_]\w*)\b")


def _substitute(text, variables):
  """Replace the user variables (Variables tab) by their value in a cfg value."""
  if not variables:
    return text
  return _VARIABLE_PATTERN.sub(lambda m: str(variables.get(m.group(1), m.group(1))), text)


def current_variables():
  """User variables defined in the Variables tab ({name: value})."""
  try:
    from core.variables import get_variables_dict
    return get_variables_dict() or {}
  except Exception:
    return {}


def _scalar_cfg(value, variables):
  if value is True:
    return "YES"
  if value is False:
    return "NO"
  return _substitute(str(value), variables)


def cfg_value(value, variables=None):
  """SU2 .cfg representation of a json value (None: option not written)."""
  if value is None or (isinstance(value, str) and value.lower() == 'none'):
    return None
  # lists (and lists of lists/tuples) are flattened between round brackets
  if isinstance(value, (list, tuple)):
    return "(" + ", ".join(_scalar_cfg(v, variables) for v in _flatten(value)) + ")"
  return _scalar_cfg(value, variables)


def build_cfg_text(config, description="", variables=None):
  """Text of the SU2 .cfg file for the configuration dict ``config``."""
  lines = [f"{description}  "] if description else []
  for attribute, value in config.items():
    text = cfg_value(value, variables)
    if text is None:
      continue
    lines.append(f"{attribute}= {text}")
  return "\n".join(lines) + "\n"


def build_json_text(config):
  return json.dumps(config, sort_keys=True, indent=4, ensure_ascii=False) + "\n"


# last text written to each file, so that the periodic autosave does not re-read the files
_last_written = {}


def _write_if_changed(path, text):
  """Write ``text`` to ``path`` atomically, only if the content is different.

  Returns True if the file was written.
  """
  path = Path(path)
  key = str(path.resolve())
  if _last_written.get(key) == text and path.is_file():
    return False
  try:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
      _last_written[key] = text
      return False
  except (OSError, UnicodeDecodeError):
    pass
  tmp = path.with_name(path.name + ".tmp")
  with open(tmp, 'w', encoding="utf-8") as f:
    f.write(text)
  os.replace(tmp, path)
  _last_written[key] = text
  return True


def write_case_configuration(filename_json_export, filename_cfg_export, update_state=True,
                             variables=None):
  """Write the .json and .cfg files of the active case if their content changed.

  With update_state=False the state (state.jsonData) is not modified, which is
  what the periodic autosave uses. The user variables are substituted in the
  .cfg (SU2 cannot read them); the .json keeps them. Returns the written files.
  """
  if not state.case_name:
    return []
  if variables is None:
    variables = current_variables()
  config = case_configuration(state.jsonData, state.BCDictList, state.wall_function,
                              warn=update_state)
  if update_state:
    state.jsonData = config
  # names/values that SU2 would reject (reported, the file is written anyway)
  report_option_issues(su2_options.check(config), prefix=f"{filename_cfg_export}: ")

  directory = case_dir(state.case_name)
  directory.mkdir(parents=True, exist_ok=True)
  written = []
  if _write_if_changed(directory / filename_json_export, build_json_text(config)):
    written.append(directory / filename_json_export)
  if _write_if_changed(directory / filename_cfg_export,
                       build_cfg_text(config, state.config_desc or "", variables)):
    written.append(directory / filename_cfg_export)
  return written


########################################################################################
# Export the new json configuration file as .json and as .cfg #
########################################################################################
def save_json_cfg_file(filename_json_export,filename_cfg_export):
    if state.case_name == None or state.case_name == "":
        log("info", "Case name is not defined, did not export the configuration file")
        return
    written = write_case_configuration(filename_json_export, filename_cfg_export)
    for path in written:
        log("info", f"Saved {path}")

########################################################################################
# ##### export internal vtk multiblock mesh to an su2 file
# ##### exports single zone .su2 mesh with boundary conditions only
########################################################################################
def _cell_connectivity(dataset, cell_id, id_list):
    """Point ids of a cell, as a space separated string."""
    dataset.GetCellPoints(cell_id, id_list)
    return " ".join(str(id_list.GetId(j)) for j in range(id_list.GetNumberOfIds()))


def save_su2mesh(multiblock,su2_export_filename):
    """Write the mesh as a single-zone native SU2 ASCII mesh (.su2).

    Layout read by SU2 (CSU2ASCIIMeshReaderFVM):
      NDIME= n
      NELEM= n, then one line per element: <VTK cell type> <point ids> <element index>
      NPOIN= n, then one line per point: <x> <y> [<z>] <point index>
      NMARK= n, then per marker MARKER_TAG= name, MARKER_ELEMS= n and
      one line per boundary element: <VTK cell type> <point ids>
    SU2 uses the VTK cell type identifiers. The boundary grids share the point set
    of the interior grid, so their point ids are global.
    """
    internalBlock = multiblock.GetBlock(0) if multiblock is not None else None
    if internalBlock is None or internalBlock.GetNumberOfBlocks() == 0:
        log("info", "no internal block, mesh not saved")
        return

    if internalBlock.GetNumberOfBlocks() > 1:
        # a .su2 file with several zones needs NZONE/IZONE sections and per-zone numbering
        log("error", f"The mesh has {internalBlock.GetNumberOfBlocks()} interior blocks: "
                     "only single-zone .su2 meshes can be exported, mesh not saved")
        return

    data = internalBlock.GetBlock(0)
    if data is None or data.GetNumberOfPoints() == 0:
        log("info", "internal block is empty, mesh not saved")
        return

    boundaryBlock = multiblock.GetBlock(1)

    NDIME = int(state.nDim)
    NELEM = data.GetNumberOfCells()
    NPOINT = data.GetNumberOfPoints()
    ids = vtk.vtkIdList()

    log("info", f"saving su2 mesh file {su2_export_filename}: {NDIME}D, {NELEM} elements, {NPOINT} points")

    out = [f"NDIME= {NDIME}", f"NELEM= {NELEM}"]

    # element connectivity
    for i in range(NELEM):
        out.append(f"{data.GetCellType(i)} {_cell_connectivity(data, i, ids)} {i}")

    # point coordinates (full precision)
    out.append(f"NPOIN= {NPOINT}")
    for i in range(NPOINT):
        p = data.GetPoint(i)
        coords = p[:3] if NDIME == 3 else p[:2]
        out.append(" ".join(f"{c:.17g}" for c in coords) + f" {i}")

    # boundary markers
    NMARK = boundaryBlock.GetNumberOfBlocks() if boundaryBlock is not None else 0
    out.append(f"NMARK= {NMARK}")
    for m in range(NMARK):
        marker = boundaryBlock.GetBlock(m)
        name = boundaryBlock.GetMetaData(m).Get(vtk.vtkCompositeDataSet.NAME())
        ncells = marker.GetNumberOfCells() if marker is not None else 0
        out.append(f"MARKER_TAG= {name}")
        out.append(f"MARKER_ELEMS= {ncells}")
        for i in range(ncells):
            out.append(f"{marker.GetCellType(i)} {_cell_connectivity(marker, i, ids)}")

    with open(case_dir(state.case_name) / su2_export_filename, 'w') as f:
        f.write("\n".join(out))
        f.write("\n")

########################################################################################
# Convert config file to JSON and validate with schema using predefined functions
########################################################################################
def convert_and_validate_config(cfg_file_path: str, schema_path: str = None, output_json_path: str = None):
    """
    Convert SU2 config file to JSON and validate it against a schema using predefined functions.
    
    Args:
        cfg_file_path (str): Path to the SU2 configuration file (.cfg)
        schema_path (str, optional): Path to the JSON schema file. Defaults to JsonSchema.json
        output_json_path (str, optional): Path to save the converted JSON file
    
    Returns:
        tuple: (is_valid, config_dict, errors)
    """
    
    if not VALIDATION_AVAILABLE:
        log("error", "Validation functions are not available")
        return False, {}, ["Validation functions not imported"]
    
    try:
        # Set default schema path if not provided
        if not schema_path:
            schema_path = str(BASE / "JsonSchema.json")
        
        log("info", f"Converting config file: {cfg_file_path}")
        log("info", f"Using schema: {schema_path}")
        
        config_dict = cfg_to_json_dict(cfg_file_path)
        log("info", f"Successfully parsed {len(config_dict)} configuration parameters")
        
        config_dict = apply_su2_fixes(config_dict)
        log("info", "Applied SU2 compatibility fixes")
        
        if output_json_path:
            try:
                with open(output_json_path, "w", encoding="utf-8") as json_file:
                    json.dump(config_dict, json_file, indent=2, ensure_ascii=False)
                log("info", f"JSON file saved to: {output_json_path}")
            except Exception as e:
                log("error", f"Error saving JSON file: {e}")
        
        # Validate using predefined function
        is_valid, validated_config, errors = validate_cfg_with_schema(cfg_file_path, schema_path)
        
        if is_valid:
            log("info", "Configuration is valid against schema!")
        else:
            log("error", f"Configuration validation failed with {len(errors)} errors")
            for i, error in enumerate(errors, 1):
                if hasattr(error, 'message'):
                    log("error", f"  {i}. {error.message}")
                else:
                    log("error", f"  {i}. {str(error)}")
        
        return is_valid, config_dict, errors
        
    except FileNotFoundError as e:
        log("error", f"File not found: {e}")
        return False, {}, [str(e)]
    except Exception as e:
        log("error", f"Unexpected error in convert_and_validate_config: {e}")
        return False, {}, [str(e)]

########################################################################################
# Simple wrapper function for easy use
########################################################################################
def load_and_validate_config(cfg_file_path: str, schema_file: str = "JsonSchema.json"):
    """
    Simple wrapper to load a config file and validate it.
    
    Args:
        cfg_file_path (str): Path to the SU2 configuration file
        schema_file (str): Name of schema file (defaults to JsonSchema.json)
    
    Returns:
        tuple: (is_valid, config_dict, errors)
    """
    schema_path = str(BASE / schema_file)
    return convert_and_validate_config(cfg_file_path, schema_path)
