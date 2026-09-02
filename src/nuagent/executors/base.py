from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from nuagent.backends.base import CaseHandle
from nuagent.spec import ExecutionSpec, ExecutorKind


@dataclass
class RunResult:
    returncode: int
    wall_time_s: float
    executor: str
    stdout_tail: str = ""
    job_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Executor(Protocol):
    name: str

    def run(
        self,
        case: CaseHandle,
        execution: ExecutionSpec,
        timeout_s: float | None = None,
        args: tuple[str, ...] = (),
    ) -> RunResult:
        """Run ``case.allrun`` (optionally with arguments such as ``--continue``) and return the result."""
        ...


def get_executor(kind: ExecutorKind | str, **kwargs) -> Executor:
    kind = ExecutorKind(kind)
    if kind is ExecutorKind.LOCAL:
        from nuagent.executors.local import LocalExecutor

        return LocalExecutor(**kwargs)
    if kind is ExecutorKind.DOCKER:
        from nuagent.executors.docker import DockerExecutor

        return DockerExecutor(**kwargs)
    if kind is ExecutorKind.SLURM:
        from nuagent.executors.slurm import SlurmExecutor

        return SlurmExecutor(**kwargs)
    raise ValueError(kind)


def tail(path: Path, n: int = 30) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()
    return "\n".join(lines[-n:])
