# fileio gittree menu

# note that in the main menu, we need to call add the following:
# 1) from ui.fileio import *
# 2) call fileio_card() in SinglePageWithDrawerLayout
# 3) define a node in the gittree (pipeline), note that name in gittree node should be
#    the same as name in ui_card() in fileio_card definition
# 4) define any global state variables that might be needed

# 5) to initialize all fields from the config file, createfunction set_json_fileio()
#    and set all state variables using the json file
# 6) call set_json_fileio() from the main su2gui

# 7) write the results to file in su2_ui.py. Here, we need to construct any 'special' config options
#    that are not simply the output of the json options.

import sys
import os
from pathlib import Path

# Add parent directory to path to allow importing from sibling directories
parent_dir = str(Path(__file__).parent.parent.absolute())
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# definition of ui_card
from ui.uicard import ui_card, ui_subcard, server
from trame.widgets import vuetify
from core.su2_json import *
from core import su2_files

state, ctrl = server.state, server.controller

# [SOLUTION_FILENAME - text string]
# RESTART_FILENAME - text string
# VOLUME_FILENAME - text string
# [READ_BINARY_RESTART -boolean]
# OUTPUT_WRT_FREQ - integer
# VOLUME_OUTPUT - list of strings
# OUTPUT_FILES - list of strings
# HISTORY_OUTPUT - text string
# HISTORY_WRT_FREQ_INNER integer
# CONV_FILENAME - text string
#
# CONV_FIELD - string
# CONV_RESIDUAL_MINVAL - negative integer
# CONV_STARTITER - integer

# ### READ CONFIG FILE ### #
# set the state variables using the json data from the config file
def set_json_fileio():
  # OUTPUT_WRT_FREQ has one entry per OUTPUT_FILES entry (SU2 repeats the last one
  # and uses 250/1 when unset), so the frequencies are looked up by file type.
  restart_freq = su2_files.restart_output_frequency(state.jsonData)
  volume_freq = su2_files.output_frequency(state.jsonData, _volume_kinds())

  try:
    state.restart_filename = state.jsonData['RESTART_FILENAME']
  except KeyError as e:
    log("warn", f"Key '{e.args[0]}' not found in state.jsonData")
  if restart_freq is not None:
    state.fileio_restart_frequency = restart_freq
  state.fileio_restart_binary = not su2_files.restart_is_ascii(state.jsonData)
  state.fileio_restart_overwrite = su2_files.as_bool(state.jsonData.get('WRT_RESTART_OVERWRITE'), True)

  try:
    state.fileio_volume_name = state.jsonData['VOLUME_FILENAME']
  except KeyError as e:
    log("warn", f"Key '{e.args[0]}' not found in state.jsonData")
  if volume_freq is not None:
    state.fileio_volume_frequency = volume_freq
  state.fileio_volume_overwrite = su2_files.as_bool(state.jsonData.get('WRT_VOLUME_OVERWRITE'), True)
    
  try:
    state.fileio_history_name = state.jsonData['CONV_FILENAME']
    state.fileio_history_frequency = state.jsonData['HISTORY_WRT_FREQ_INNER']
  except KeyError as e:
    log("warn", f"Key '{e.args[0]}' not found in state.jsonData")
    

  state.dirty('restart_filename')
  state.dirty('fileio_restart_frequency')
  state.dirty('fileio_restart_binary')
  state.dirty('fileio_restart_overwrite')
  state.dirty('fileio_volume_name')
  state.dirty('fileio_volume_frequency')
  state.dirty('fileio_volume_overwrite')
  state.dirty('fileio_history_name')
  state.dirty('fileio_history_frequency')

# for the main card, we need to define variables in the UI elements and then create
# a state.change for them
#
###############################################################
# PIPELINE CARD : PHYSICS
###############################################################
def fileio_card():
    with ui_card(title="File I/O", ui_name="File I/O"):
        log("info", "     ## File I/O Selection ##")

        with vuetify.VContainer(fluid=True, classes="pa-1 ma-1"):
          # ####################################################### #
          with vuetify.VRow():
            with vuetify.VCol(cols="4", classes="py-1 pl-0 pr-1"):
               vuetify.VSheet("filename",classes="grey pl-1",rounded=True)
            with vuetify.VCol(cols="3", classes="py-1 px-0"):
               vuetify.VSheet("frequency",classes="grey pl-1",rounded=True)
            with vuetify.VCol(cols="2", classes="py-1 pl-3 pr-1"):
               vuetify.VSheet("binary", classes="grey pl-1",rounded=True)
            with vuetify.VCol(cols="2", classes="py-1 pl-0 pr-0"):
               vuetify.VSheet("overwrite",classes="grey pl-1",rounded=True)

          with vuetify.VRow():
            with vuetify.VCol(cols="4", classes="py-1 pl-0 pr-1"):
              vuetify.VTextField(
                label="Restart",
                v_model=("restart_filename", state.restart_filename),
                outlined=True,
                dense=True,
                hide_details=True,
              )
            with vuetify.VCol(cols="3",classes="py-1 px-0"):
              vuetify.VTextField(
                v_model=("fileio_restart_frequency", 200),
                label="Frequency",
                outlined=True,
                dense=True,
                hide_details=True,
              )
            with vuetify.VCol(cols="2",classes="py-1 pl-4 pr-0"):
              vuetify.VCheckbox(
                v_model=("fileio_restart_binary", False),
                #label="binary",
                outlined=True,
                hide_details=True,
                dense=True,
            )
            with vuetify.VCol(cols="2",classes="py-1 pl-4 pr-0"):
              vuetify.VCheckbox(
                v_model=("fileio_restart_overwrite", False),
                #label="overwrite",
                outlined=True,
                hide_details=True,
                dense=True,
            )


          with vuetify.VRow():
            with vuetify.VCol(cols="4",classes="py-1 pl-0 pr-1"):
              vuetify.VTextField(
                v_model=("fileio_volume_name", "flow"),
                label="Volume output",
                outlined=True,
                dense=True,
                hide_details=True,
              )
            with vuetify.VCol(cols="3",classes="py-1 px-0"):
              vuetify.VTextField(
                v_model=("fileio_volume_frequency", 100),
                label="Frequency",
                outlined=True,
                dense=True,
                hide_details=True,
              )
            #with vuetify.VCol(cols="2",classes="py-1 pl-4 pr-0"):
            #  vuetify.VCheckbox(
            #    v_model=("fileio_volume_binary_idx", False),
            #    #label="binary",
            #    outlined=True,
            #    hide_details=True,
            #    dense=True,
            #)
            with vuetify.VCol(cols="2",offset="2",classes="py-1 pl-4 pr-0"):
              vuetify.VCheckbox(
                v_model=("fileio_volume_overwrite", False),
                #label="overwrite",
                outlined=True,
                hide_details=True,
                dense=True,
            )

          with vuetify.VRow():
            with vuetify.VCol(cols="4",classes="py-1 pl-0 pr-1"):
              vuetify.VTextField(
                v_model=("fileio_history_name", "history"),
                label="History",
                outlined=True,
                dense=True,
                hide_details=True,
              )
            with vuetify.VCol(cols="3",classes="py-1 px-0"):
              vuetify.VTextField(
                v_model=("fileio_history_frequency", 1),
                label="Frequency",
                outlined=True,
                dense=True,
                hide_details=True,
              )
#
@state.change("restart_filename")
def update_material(restart_filename, **kwargs):
    state.jsonData['RESTART_FILENAME']= restart_filename
    state.dirty('fileio_restart_binary')
    state.dirty('jsonData')

_RESTART_KINDS = ("RESTART", "RESTART_ASCII")

def _volume_kinds():
    """OUTPUT_FILES entries that are not restart files (volume/surface visualization files)."""
    return tuple(f for f in su2_files.output_files(state.jsonData) if f not in _RESTART_KINDS)

# OUTPUT_WRT_FREQ is index-aligned with OUTPUT_FILES (one frequency per file type)
@state.change("fileio_restart_frequency")
def update_material(fileio_restart_frequency, **kwargs):
    try:
      su2_files.set_output_frequency(state.jsonData, _RESTART_KINDS, int(fileio_restart_frequency))
      state.dirty('jsonData')
    except (TypeError, ValueError) as e:
      log("error", f"Invalid restart output frequency in FileIO Tab: {e}")

# if binary, change the file type
@state.change("fileio_restart_binary")
def update_material(fileio_restart_binary, **kwargs):
    # expand OUTPUT_FILES / OUTPUT_WRT_FREQ first, so that replacing or appending
    # the restart entry keeps the frequencies aligned with the files
    files = su2_files.output_files(state.jsonData)
    freqs = su2_files.volume_output_frequencies(state.jsonData)
    wanted, other = ("RESTART", "RESTART_ASCII") if bool(fileio_restart_binary) else ("RESTART_ASCII", "RESTART")

    # SU2 appends the extension itself (and trims it if present)
    base = su2_files.restart_basename({'RESTART_FILENAME': state.restart_filename or 'restart'})
    state.restart_filename = base + (".dat" if wanted == "RESTART" else ".csv")

    if other in files:
      idx = files.index(other)
      files[idx] = wanted
    elif wanted not in files:
      files.append(wanted)
      freqs.append(freqs[-1] if freqs else su2_files.DEFAULT_WRT_FREQ_STEADY)
    # remove duplicates of the restart entry, keeping the frequencies aligned
    seen = set()
    new_files, new_freqs = [], []
    for f, fr in zip(files, freqs):
      if f in _RESTART_KINDS:
        if f != wanted or f in seen:
          continue
        seen.add(f)
      new_files.append(f)
      new_freqs.append(fr)
    state.jsonData['OUTPUT_FILES'] = new_files
    state.jsonData['OUTPUT_WRT_FREQ'] = new_freqs
    state.dirty('jsonData')

@state.change("fileio_restart_overwrite")
def update_material(fileio_restart_overwrite, **kwargs):
    try:
        state.jsonData['WRT_RESTART_OVERWRITE']= bool(fileio_restart_overwrite)
        state.dirty('jsonData')
    except Exception as e:
      log("error", f"An error occurred in FileIO Tab: \n {str(e)}")

#
@state.change("fileio_volume_name")
def update_material(fileio_volume_name, **kwargs):
    state.jsonData['VOLUME_FILENAME']= fileio_volume_name
    state.dirty('jsonData')

@state.change("fileio_volume_frequency")
def update_material(fileio_volume_frequency, **kwargs):
    try:
        su2_files.set_output_frequency(state.jsonData, _volume_kinds(), int(fileio_volume_frequency))
        state.dirty('jsonData')
    except (TypeError, ValueError) as e:
      log("error", f"Invalid volume output frequency in FileIO Tab: {e}")

@state.change("fileio_volume_overwrite")
def update_material(fileio_volume_overwrite, **kwargs):
    try:
        state.jsonData['WRT_VOLUME_OVERWRITE']= bool(fileio_volume_overwrite)
        state.dirty('jsonData')
    except Exception as e:
      log("error", f"An error occurred in FileIO Tab: \n {str(e)}")
# if binary, change the file type
#@state.change("fileio_volume_binary")
#def update_material(fileio_restart_binary, **kwargs):
#    if bool(fileio_restart_binary)==True:
#      state.jsonData['OUTPUT_FILES'][0]= "RESTART"
#    else:
#      state.jsonData['OUTPUT_FILES'][0]= "RESTART_ASCII"
#    state.dirty('jsonData')


#
@state.change("fileio_history_name")
def update_material(fileio_history_name, **kwargs):
    state.jsonData['CONV_FILENAME']= fileio_history_name
    state.dirty('jsonData')

@state.change("fileio_history_frequency")
def update_material(fileio_history_frequency, **kwargs):
    try:
        state.jsonData['HISTORY_WRT_FREQ_INNER']= int(fileio_history_frequency) 
        state.dirty('jsonData')
    except Exception as e:
      log("error", f"An error occurred in FileIO Tab: \n{str(e)}")

