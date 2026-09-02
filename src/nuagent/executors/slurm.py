"""Submit a case to SLURM and poll until completion.

Configuration comes from :class:`~nuagent.spec.ExecutionSpec` (partition,
account, n_procs, wall-clock) and from environment variables for site
specifics that do not belong in a simulation spec:

- ``NUAGENT_SLURM_MODULES``      colon-separated modules to load (e.g. ``openfoam/2412:gcc``)
- ``NUAGENT_FOAM_BASHRC``        etc/bashrc to source when no module provides OpenFOAM
- ``NUAGENT_FESTIM_PYTHON``      python interpreter that has FESTIM installed
- ``NUAGENT_SLURM_EXTRA``        extra ``#SBATCH`` directives separated by ``;``
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from nuagent import __version__
from nuagent.backends.base import CaseHandle
from nuagent.executors.base import RunResult, tail
from nuagent.spec import ExecutionSpec

TEMPLATES = Path(__file__).parent / "templates"
TERMINAL_STATES = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "BOOT_FAIL",
    "DEADLINE",
}


def _walltime(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}:00"


class SlurmExecutor:
    name = "slurm"

    def __init__(
        self,
        poll_interval: float = 30.0,
        sbatch: str = "sbatch",
        squeue: str = "squeue",
        sacct: str = "sacct",
        cores_per_node: int = 64,
    ):
        self.poll_interval = poll_interval
        self.sbatch, self.squeue, self.sacct = sbatch, squeue, sacct
        self.cores_per_node = cores_per_node
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)), trim_blocks=True, lstrip_blocks=True
        )

    def available(self) -> bool:
        return shutil.which(self.sbatch) is not None

    # ------------------------------------------------------------------ #
    def render_script(
        self, case: CaseHandle, execution: ExecutionSpec, args: tuple[str, ...] = ()
    ) -> str:
        n_tasks = execution.n_procs
        nodes = max(1, -(-n_tasks // self.cores_per_node))
        modules = [m for m in os.environ.get("NUAGENT_SLURM_MODULES", "").split(":") if m]
        extra = [d for d in os.environ.get("NUAGENT_SLURM_EXTRA", "").split(";") if d.strip()]
        return self.env.get_template("job.sbatch.j2").render(
            job_name=f"nuagent-{case.path.name}"[:64],
            case_dir=str(case.path.resolve()),
            nodes=nodes,
            n_tasks=n_tasks,
            walltime=_walltime(execution.wallclock_minutes),
            partition=execution.slurm_partition,
            account=execution.slurm_account,
            extra_directives=extra,
            modules=modules,
            foam_bashrc=os.environ.get("NUAGENT_FOAM_BASHRC", ""),
            festim_python=os.environ.get("NUAGENT_FESTIM_PYTHON", ""),
            nuagent_version=__version__,
            run_args=" ".join(args),
        )

    def submit(self, case: CaseHandle, execution: ExecutionSpec, args: tuple[str, ...] = ()) -> str:
        script = case.path / "job.sbatch"
        script.write_text(self.render_script(case, execution, args))
        out = subprocess.run(
            [self.sbatch, "--parsable", str(script)], capture_output=True, text=True, check=True
        )
        job_id = out.stdout.strip().split(";")[0]
        if not re.match(r"^\d+", job_id):
            raise RuntimeError(f"unexpected sbatch output: {out.stdout!r} {out.stderr!r}")
        (case.path / ".nuagent_job_id").write_text(job_id)
        return job_id

    def state(self, job_id: str) -> str:
        q = subprocess.run(
            [self.squeue, "-h", "-j", job_id, "-o", "%T"], capture_output=True, text=True
        )
        st = q.stdout.strip()
        if st:
            return st.split()[0]
        a = subprocess.run(
            [self.sacct, "-n", "-X", "-j", job_id, "-o", "State"], capture_output=True, text=True
        )
        st = a.stdout.strip().split()
        return st[0].split("+")[0] if st else "UNKNOWN"

    def wait(self, case: CaseHandle, job_id: str, timeout_s: float) -> str:
        t0 = time.time()
        while True:
            st = self.state(job_id)
            if st in TERMINAL_STATES:
                return st
            if st == "UNKNOWN" and (case.path / ".nuagent_exit_code").exists():
                return "COMPLETED"
            if time.time() - t0 > timeout_s:
                subprocess.run(["scancel", job_id], check=False)
                return "TIMEOUT"
            time.sleep(self.poll_interval)

    def run(
        self,
        case: CaseHandle,
        execution: ExecutionSpec,
        timeout_s: float | None = None,
        args: tuple[str, ...] = (),
    ) -> RunResult:
        # queue wait is not counted in the solver wall-clock budget; allow a generous margin
        timeout_s = timeout_s or (execution.wallclock_minutes * 60.0 * 3 + 3600)
        t0 = time.time()
        job_id = self.submit(case, execution, args)
        state = self.wait(case, job_id, timeout_s)
        rc_file = case.path / ".nuagent_exit_code"
        rc = (
            int(rc_file.read_text().strip())
            if rc_file.exists()
            else (0 if state == "COMPLETED" else 1)
        )
        out = next(iter(sorted(case.path.glob("slurm-*.out"))), None)
        return RunResult(
            returncode=rc,
            wall_time_s=time.time() - t0,
            executor=self.name,
            stdout_tail=tail(out) if out else "",
            job_id=job_id,
            details={"state": state, "script": str(case.path / "job.sbatch")},
        )
