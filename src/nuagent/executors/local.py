"""Run a case in a local subprocess.

The executor streams the run's console output to ``allrun.out`` and enforces
the wall-clock budget from :class:`~nuagent.spec.ExecutionSpec`.  An optional
``on_poll`` callback receives the case every ``poll_interval`` seconds while the
solver is running, which is how the agent's monitor node watches residuals
live and can stop a converged (or clearly diverging) run early by writing
``stopAt writeNow`` into ``controlDict`` (OpenFOAM honours it because the
generated cases set ``runTimeModifiable true``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from nuagent.backends.base import CaseHandle
from nuagent.executors.base import RunResult, tail
from nuagent.spec import ExecutionSpec

PollCallback = Callable[[CaseHandle, float], str | None]  # returns "stop" to request a clean stop


def request_openfoam_stop(case: CaseHandle) -> bool:
    """Ask a running OpenFOAM solver to write and stop at the next iteration."""
    control = case.path / "system" / "controlDict"
    if not control.exists():
        return False
    text = control.read_text()
    if "stopAt          endTime;" in text:
        control.write_text(text.replace("stopAt          endTime;", "stopAt          writeNow;"))
        return True
    return False


def launch_command(case: CaseHandle, args: tuple[str, ...] = ()) -> list[str]:
    """Command that runs a case on this machine.

    Cases are bash scripts (``Allrun``), as OpenFOAM and FESTIM users expect.  On a machine without a
    Unix shell (native Windows without Git Bash or WSL) a case may ship an ``Allrun.py`` twin — the mock
    backend does — which is run with the current interpreter instead, so the agent, the evals and the
    LLM policies can be exercised anywhere; the real solvers still need bash (WSL2, a container or Linux).
    """
    case_dir = Path(case.path).resolve()
    if shutil.which("bash") is not None:
        return ["bash", str(case_dir / case.allrun.name), *args]
    py_twin = case_dir / "Allrun.py"
    if py_twin.exists():
        return [sys.executable, str(py_twin), *args]
    raise RuntimeError(
        "no 'bash' on PATH: install Git for Windows (Git Bash) or run under WSL2/Docker to execute "
        f"{case.allrun}; the mock backend runs natively through Allrun.py"
    )


class LocalExecutor:
    name = "local"

    def __init__(
        self,
        poll_interval: float = 5.0,
        on_poll: PollCallback | None = None,
        env: dict | None = None,
    ):
        self.poll_interval = poll_interval
        self.on_poll = on_poll
        self.env = env

    def run(
        self,
        case: CaseHandle,
        execution: ExecutionSpec,
        timeout_s: float | None = None,
        args: tuple[str, ...] = (),
    ) -> RunResult:
        timeout_s = timeout_s or execution.wallclock_minutes * 60.0
        out_path = case.path / "allrun.out"
        env = {**os.environ, **(self.env or {})}
        env.setdefault("OMP_NUM_THREADS", "1")
        t0 = time.time()
        with open(out_path, "w") as out:
            proc = subprocess.Popen(
                launch_command(case, args),
                cwd=Path(case.path).resolve(),
                stdout=out,
                stderr=subprocess.STDOUT,
                env=env,
            )
            stopped_early = False
            timed_out = False
            while True:
                try:
                    proc.wait(timeout=self.poll_interval)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = time.time() - t0
                    if elapsed > timeout_s:
                        proc.kill()
                        timed_out = True
                        break
                    if self.on_poll is not None and not stopped_early:
                        try:
                            verdict = self.on_poll(case, elapsed)
                        except Exception:  # noqa: BLE001 - monitoring must never kill the run
                            verdict = None
                        if verdict == "stop":
                            stopped_early = request_openfoam_stop(case)
            if timed_out:
                proc.wait()
        wall = time.time() - t0
        rc = proc.returncode if not timed_out else 124
        return RunResult(
            returncode=rc,
            wall_time_s=wall,
            executor=self.name,
            stdout_tail=tail(out_path),
            details={
                "timed_out": timed_out,
                "stopped_early": stopped_early,
                "cwd": str(Path(case.path)),
            },
        )
