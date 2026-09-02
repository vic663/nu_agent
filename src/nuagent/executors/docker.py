"""Run a case inside a Docker container (OpenFOAM or FESTIM image).

The case directory is bind-mounted at ``/case`` and ``Allrun`` is executed
there.  The default images are the official ESI OpenFOAM image
(``opencfd/openfoam-default``) and the NuAgent FESTIM image built from
``docker/Dockerfile.festim`` (``dolfinx/dolfinx:stable`` + ``pip install festim``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from nuagent.backends.base import CaseHandle
from nuagent.executors.base import RunResult, tail
from nuagent.spec import ExecutionSpec

DEFAULT_IMAGES = {
    "openfoam": "opencfd/openfoam-default:2512",
    "festim": "nuagent-festim:latest",
    "mock": "python:3.11-slim",
}


class DockerExecutor:
    name = "docker"

    def __init__(
        self,
        docker_bin: str = "docker",
        images: dict[str, str] | None = None,
        user_mapping: bool = True,
    ):
        self.docker_bin = docker_bin
        self.images = {**DEFAULT_IMAGES, **(images or {})}
        self.user_mapping = user_mapping

    def available(self) -> bool:
        return shutil.which(self.docker_bin) is not None

    def command(
        self, case: CaseHandle, execution: ExecutionSpec, args: tuple[str, ...] = ()
    ) -> list[str]:
        image = execution.docker_image or self.images[case.backend]
        cmd = [self.docker_bin, "run", "--rm", "-v", f"{case.path.resolve()}:/case", "-w", "/case"]
        if self.user_mapping and hasattr(os, "getuid"):
            cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
        if case.backend == "openfoam":
            # the official image's entrypoint sources the OpenFOAM environment before running the command
            cmd += [image, "./Allrun", *args]
        else:
            cmd += [image, "bash", "./Allrun", *args]
        return cmd

    def run(
        self,
        case: CaseHandle,
        execution: ExecutionSpec,
        timeout_s: float | None = None,
        args: tuple[str, ...] = (),
    ) -> RunResult:
        timeout_s = timeout_s or execution.wallclock_minutes * 60.0
        cmd = self.command(case, execution, args)
        out_path = case.path / "allrun.out"
        t0 = time.time()
        timed_out = False
        with open(out_path, "w") as out:
            try:
                proc = subprocess.run(
                    cmd, stdout=out, stderr=subprocess.STDOUT, timeout=timeout_s, check=False
                )
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                rc, timed_out = 124, True
        return RunResult(
            returncode=rc,
            wall_time_s=time.time() - t0,
            executor=self.name,
            stdout_tail=tail(out_path),
            details={"command": cmd, "timed_out": timed_out},
        )
