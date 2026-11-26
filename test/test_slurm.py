"""Tests of the SLURM batch script and job monitor (core/slurm.py).

Run with:  python -m unittest discover -s test -p "test_*.py"
"""

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import slurm  # noqa: E402


class TestScript(unittest.TestCase):
    def test_script(self):
        text = slurm.build_script(
            {"job_name": "naca", "partition": "cpu", "nodes": "2", "ntasks_per_node": "32",
             "time": "02:00:00", "account": "", "setup": "module load su2\n\nsource env.sh",
             "extra_sbatch": "--exclusive\n#SBATCH --mail-type=END"},
            "config_new.cfg", "/opt/su2/bin/SU2_CFD")
        lines = text.splitlines()
        self.assertEqual(lines[0], "#!/bin/bash")
        for expected in ("#SBATCH --job-name=naca", "#SBATCH --partition=cpu", "#SBATCH --nodes=2",
                         "#SBATCH --ntasks-per-node=32", "#SBATCH --time=02:00:00",
                         "#SBATCH --output=su2.out", "#SBATCH --error=su2.err",
                         "#SBATCH --exclusive", "#SBATCH --mail-type=END",
                         "module load su2", "source env.sh",
                         "srun '/opt/su2/bin/SU2_CFD' 'config_new.cfg'"):
            self.assertIn(expected, lines)
        self.assertNotIn("#SBATCH --account=", text)          # empty settings are not written
        # all #SBATCH lines come before the first command
        first_cmd = next(i for i, l in enumerate(lines) if l.startswith("cd "))
        self.assertTrue(all(i < first_cmd for i, l in enumerate(lines) if l.startswith("#SBATCH")))

    def test_launchers_and_executable(self):
        self.assertIn("mpirun -np ${SLURM_NTASKS:-1} 'SU2_CFD' 'c.cfg'",
                      slurm.build_script({"launcher": "mpirun"}, "c.cfg", None))
        text = slurm.build_script({"launcher": "none", "su2_cfd": "/cluster/SU2_CFD"}, "c.cfg", "/local/SU2_CFD")
        self.assertIn("\n'/cluster/SU2_CFD' 'c.cfg'\n", text)

    def test_no_line_break_injection(self):
        text = slurm.build_script({"partition": "cpu\nrm -rf ~"}, "c.cfg", "SU2_CFD")
        self.assertIn("#SBATCH --partition=cpu rm -rf ~", text)
        self.assertNotIn("\nrm -rf", text)

    def test_validate(self):
        self.assertEqual(slurm.validate({"nodes": "2", "ntasks": "64", "time": "1-12:00:00"}), [])
        problems = " ".join(slurm.validate({"nodes": "0", "ntasks": "x", "time": "1h",
                                            "job_name": "a b", "launcher": "none"}))
        for word in ("nodes", "ntasks", "time", "job name"):
            self.assertIn(word, problems)

    def test_parse_job_id(self):
        self.assertEqual(slurm.parse_job_id("12345\n"), "12345")
        self.assertEqual(slurm.parse_job_id("12345;cluster"), "12345")
        self.assertEqual(slurm.parse_job_id("Submitted batch job 77"), "77")
        self.assertIsNone(slurm.parse_job_id("sbatch: error"))


class FakeSlurm:
    """Answers of squeue/sacct/scancel for a job."""

    def __init__(self, squeue, sacct="COMPLETED|0:0"):
        self.squeue = list(squeue)       # successive (rc, stdout, stderr)
        self.sacct = sacct
        self.calls = []

    def __call__(self, args, **kwargs):
        command = Path(args[0]).stem     # the command may be resolved to a full path
        self.calls.append(command)
        if command == "squeue":
            rc, out, err = self.squeue.pop(0) if len(self.squeue) > 1 else self.squeue[0]
        elif command == "sacct":
            rc, out, err = (0, self.sacct, "") if self.sacct is not None else (1, "", "no accounting")
        else:
            rc, out, err = 0, "", ""
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


class TestJob(unittest.TestCase):
    def job(self, fake):
        self.t = 0.0
        return slurm.SlurmJob("42", runner=fake, clock=lambda: self.t)

    def tick(self, job):
        self.t += 100.0
        return job.poll()

    def test_running_then_completed(self):
        fake = FakeSlurm([(0, "PENDING", ""), (0, "RUNNING", ""), (0, "", "")])
        job = self.job(fake)
        self.assertIsNone(self.tick(job))
        self.assertEqual(job.state, "PENDING")
        self.assertIsNone(self.tick(job))
        self.assertEqual(job.state, "RUNNING")
        self.assertEqual(self.tick(job), 0)
        self.assertEqual(job.state, "COMPLETED")

    def test_purged_job_is_finished(self):
        fake = FakeSlurm([(1, "", "slurm_load_jobs error: Invalid job id specified")], sacct="FAILED|1:0")
        job = self.job(fake)
        self.assertEqual(self.tick(job), 1)
        self.assertEqual(job.state, "FAILED")

    def test_temporary_errors_are_retried(self):
        fake = FakeSlurm([(1, "", "Socket timed out")] * 2 + [(0, "RUNNING", "")])
        job = self.job(fake)
        self.assertIsNone(self.tick(job))
        self.assertIsNone(self.tick(job))
        self.assertIsNone(self.tick(job))
        self.assertEqual(job.state, "RUNNING")

    def test_poll_is_throttled(self):
        fake = FakeSlurm([(0, "RUNNING", "")])
        job = self.job(fake)
        self.tick(job)
        job.poll()   # same time: no new squeue call
        self.assertEqual(fake.calls.count("squeue"), 1)

    def test_no_accounting_and_cancel(self):
        fake = FakeSlurm([(0, "", "")], sacct=None)
        job = self.job(fake)
        self.assertEqual(self.tick(job), 0)
        job.terminate()
        self.assertIn("scancel", fake.calls)


if __name__ == "__main__":
    unittest.main()
