"""Run SU2 through the SLURM batch system.

The GUI writes a batch script in the folder of the case, submits it with
``sbatch`` and follows the job with ``squeue``/``sacct``. ``SlurmJob`` has the
``poll()``/``terminate()``/``returncode`` interface of ``subprocess.Popen``, so
the monitor of core/solver.py (history plot, restart, logs) works unchanged:
SU2 writes su2.out/su2.err and the history file in the folder of the case,
which must be on a filesystem shared by the login and compute nodes.

No trame dependency.
"""

import re
import shutil
import subprocess
import time
from pathlib import Path

SCRIPT_NAME = "su2_job.sbatch"

# settings shown in the GUI, with their default value
DEFAULTS = {
    "job_name": "su2",
    "partition": "",
    "account": "",
    "qos": "",
    "nodes": "1",
    "ntasks": "",
    "ntasks_per_node": "",
    "cpus_per_task": "",
    "time": "01:00:00",
    "mem": "",
    "launcher": "srun",          # srun | mpirun | none
    "su2_cfd": "",               # empty: SU2_CFD path configured in the GUI
    "setup": "",                 # commands before the run (module load ..., source ...)
    "extra_sbatch": "",          # additional '#SBATCH ...' lines (one per line)
}

LAUNCHERS = ("srun", "mpirun", "none")

# (setting, sbatch option)
_SBATCH_OPTIONS = (
    ("job_name", "job-name"),
    ("partition", "partition"),
    ("account", "account"),
    ("qos", "qos"),
    ("nodes", "nodes"),
    ("ntasks", "ntasks"),
    ("ntasks_per_node", "ntasks-per-node"),
    ("cpus_per_task", "cpus-per-task"),
    ("time", "time"),
    ("mem", "mem"),
)
_INTEGER_SETTINGS = ("nodes", "ntasks", "ntasks_per_node", "cpus_per_task")

# job states for which the job is not finished (squeue --format=%T)
_ACTIVE_STATES = {"PENDING", "CONFIGURING", "RUNNING", "COMPLETING", "SUSPENDED",
                  "REQUEUED", "RESIZING", "SIGNALING", "STAGE_OUT", "STOPPED"}


def settings_from(values):
    """Settings with the defaults for the missing ones, as single-line strings."""
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        if values and values.get(key) is not None:
            out[key] = str(values[key])
    for key, value in out.items():
        if key not in ("setup", "extra_sbatch"):
            out[key] = " ".join(value.split())   # no line breaks in an #SBATCH line
    return out


def validate(settings):
    """Problems of the settings that sbatch would reject (list of messages)."""
    s = settings_from(settings)
    problems = []
    for key in _INTEGER_SETTINGS:
        if s[key] and not re.fullmatch(r"[1-9]\d*", s[key]):
            problems.append(f"{key.replace('_', '-')} must be a positive integer, found '{s[key]}'")
    if s["time"] and not re.fullmatch(r"(\d+-)?\d+(:\d{1,2}){0,2}", s["time"]):
        problems.append(f"time must be like 01:30:00 or 2-00:00:00, found '{s['time']}'")
    if s["job_name"] and not re.fullmatch(r"[\w.+-]+", s["job_name"]):
        problems.append("job name may only contain letters, digits and . _ + -")
    if s["launcher"] not in LAUNCHERS:
        problems.append(f"launcher must be one of {', '.join(LAUNCHERS)}")
    if s["launcher"] == "none" and (_int(s["ntasks"]) or 1) > 1:
        problems.append("ntasks > 1 needs an MPI launcher (srun or mpirun)")
    return problems


def _int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _quote(text):
    """Quote a path for bash."""
    return "'" + str(text).replace("'", "'\\''") + "'"


def build_script(settings, cfg_name, su2_cfd, out_name="su2.out", err_name="su2.err"):
    """Text of the batch script running ``su2_cfd cfg_name`` in the submission folder."""
    s = settings_from(settings)
    lines = ["#!/bin/bash", "# SLURM job written by SU2GUI"]
    for key, option in _SBATCH_OPTIONS:
        if s[key]:
            lines.append(f"#SBATCH --{option}={s[key]}")
    lines.append(f"#SBATCH --output={out_name}")
    lines.append(f"#SBATCH --error={err_name}")
    for extra in s["extra_sbatch"].splitlines():
        extra = extra.strip()
        if not extra:
            continue
        lines.append(extra if extra.startswith("#SBATCH") else f"#SBATCH {extra}")
    lines += ["", 'cd "${SLURM_SUBMIT_DIR:-.}"']
    if s["setup"].strip():
        lines += ["", "# environment"] + [l.rstrip() for l in s["setup"].splitlines() if l.strip()]
    executable = s["su2_cfd"] or su2_cfd or "SU2_CFD"
    command = f"{_quote(executable)} {_quote(cfg_name)}"
    if s["launcher"] == "srun":
        command = f"srun {command}"
    elif s["launcher"] == "mpirun":
        command = f"mpirun -np ${{SLURM_NTASKS:-1}} {command}"
    lines += ["", "# SU2", command, ""]
    return "\n".join(lines)


def parse_job_id(output):
    """Job id from the output of ``sbatch --parsable`` ('1234' or '1234;cluster')
    or of plain ``sbatch`` ('Submitted batch job 1234')."""
    text = (output or "").strip()
    m = re.search(r"Submitted batch job (\d+)", text) or re.match(r"(\d+)(;\S+)?$", text)
    return m.group(1) if m else None


def available():
    return shutil.which("sbatch") is not None


def submit(case_dir, script_name=SCRIPT_NAME):
    """Submit the batch script of the case. Returns the job id; raises RuntimeError."""
    sbatch = shutil.which("sbatch")
    if sbatch is None:
        raise RuntimeError("sbatch not found: SU2GUI must run on a machine of the SLURM cluster")
    result = subprocess.run([sbatch, "--parsable", script_name], cwd=str(case_dir),
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"sbatch failed: {(result.stderr or result.stdout).strip()}")
    job_id = parse_job_id(result.stdout)
    if job_id is None:
        raise RuntimeError(f"unexpected sbatch output: {result.stdout.strip()}")
    return job_id


class SlurmJob:
    """A submitted job with the poll()/terminate()/returncode interface of Popen."""

    POLL_INTERVAL = 10.0   # seconds between two squeue calls

    MAX_FAILURES = 6       # consecutive squeue errors before the job is considered finished

    def __init__(self, job_id, runner=subprocess.run, clock=time.monotonic):
        self.job_id = str(job_id)
        self.returncode = None
        self.state = "PENDING"
        self._run = runner
        self._clock = clock
        self._last_check = None
        self._failures = 0

    def _call(self, args):
        """(return code, stdout, stderr) of a SLURM command; return code None if it cannot run."""
        args = [shutil.which(args[0]) or args[0]] + list(args[1:])
        try:
            r = self._run(args, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            return None, "", str(e)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()

    def _final_state(self):
        rc, out, _ = self._call(["sacct", "-j", self.job_id, "-X", "-n", "-P", "--format=State,ExitCode"])
        if rc != 0 or not out:
            return "COMPLETED", 0   # no accounting: the job left the queue
        state, _, code = out.splitlines()[0].partition("|")
        state = state.split()[0] if state else "UNKNOWN"
        exit_code = _int(code.split(":")[0]) if code else None
        if state == "COMPLETED":
            return state, exit_code or 0
        return state, exit_code if exit_code else 1

    def poll(self):
        """None while the job is queued or running, else its return code."""
        if self.returncode is not None:
            return self.returncode
        now = self._clock()
        if self._last_check is not None and now - self._last_check < self.POLL_INTERVAL:
            return None
        self._last_check = now
        rc, out, err = self._call(["squeue", "-h", "-j", self.job_id, "-o", "%T"])
        state = out.splitlines()[0].strip() if out else ""
        if rc == 0 and state in _ACTIVE_STATES:
            self._failures = 0
            self.state = state
            return None
        # rc 0 with no line (or a final state): the job left the queue; squeue also
        # answers "Invalid job id" once a finished job has been purged
        finished = rc == 0 or "invalid job id" in err.lower()
        if not finished:
            # temporary error (e.g. slurmctld not responding): try again later
            self._failures += 1
            if self._failures < self.MAX_FAILURES:
                return None
        self.state, self.returncode = self._final_state()
        return self.returncode

    def terminate(self):
        self._call(["scancel", self.job_id])
