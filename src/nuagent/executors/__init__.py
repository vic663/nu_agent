"""Execution back-ends: run a case's ``Allrun`` locally, in Docker, or under SLURM."""

from nuagent.executors.base import Executor, RunResult, get_executor
from nuagent.executors.docker import DockerExecutor
from nuagent.executors.local import LocalExecutor
from nuagent.executors.slurm import SlurmExecutor

__all__ = [
    "DockerExecutor",
    "Executor",
    "LocalExecutor",
    "RunResult",
    "SlurmExecutor",
    "get_executor",
]
