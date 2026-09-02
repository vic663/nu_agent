"""Backend protocol shared by OpenFOAM, FESTIM and the mock solver.

A backend turns a :class:`~nuagent.spec.SimulationSpec` into a self-contained
*case directory* with an ``Allrun`` script, knows how to read the solver log
and how to extract quantities of interest (QoIs).  It never executes anything
itself — execution is delegated to an :mod:`nuagent.executors` implementation so
the same case runs identically on a laptop, in Docker, or under SLURM.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from nuagent.spec import SimulationSpec


@dataclass
class CaseHandle:
    """A built case on disk."""

    path: Path
    backend: str
    spec_hash: str
    refinement: float = 1.0
    representative_h: float | None = None  # representative cell size for GCI
    n_cells: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allrun(self) -> Path:
        return self.path / "Allrun"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CaseHandle:
        d = dict(d)
        d["path"] = Path(d["path"])
        return cls(**d)


@dataclass
class ConvergenceReport:
    """What the log says about the run."""

    converged: bool
    diverged: bool
    completed: bool  # solver reached End / final time without error
    iterations: int
    final_residuals: dict[str, float] = field(default_factory=dict)
    continuity_error: float | None = None
    bounding_events: int = 0
    reason: str = ""
    residual_history: dict[str, list[float]] = field(default_factory=dict)  # decimated for plotting

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def status(self) -> str:
        if self.diverged:
            return "diverged"
        if self.converged:
            return "converged"
        if self.completed:
            return "completed_not_converged"
        return "failed"


@dataclass
class QoIResult:
    """Quantities of interest plus the profiles they were derived from."""

    values: dict[str, float]
    profiles: dict[str, list[float]] = field(default_factory=dict)
    checks: dict[str, float] = field(default_factory=dict)  # e.g. energy balance error
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class SolverBackend(Protocol):
    """Interface every solver backend implements."""

    name: str

    def available(self) -> bool:
        """Whether the solver can run on this machine (binaries / modules found)."""
        ...

    def build(
        self,
        spec: SimulationSpec,
        workdir: Path,
        refinement: float = 1.0,
        adjustments: dict[str, Any] | None = None,
    ) -> CaseHandle:
        """Write a complete case (input files + ``Allrun``) under ``workdir``."""
        ...

    def parse_log(self, case: CaseHandle) -> ConvergenceReport: ...

    def extract_qois(self, case: CaseHandle, spec: SimulationSpec) -> QoIResult: ...


def spec_hash(spec: SimulationSpec, extra: dict[str, Any] | None = None) -> str:
    """Hash of everything that determines the solver input files (case physics/numerics, backend,
    parallel decomposition) — *not* the V&V or reporting settings, so a case can be reused when only
    the verification/validation plan changes."""
    payload = {
        "backend": spec.backend.value,
        "case": spec.case.model_dump(mode="json"),
        "n_procs": spec.execution.n_procs,
    }
    if extra:
        payload["_extra"] = extra
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def write_case_metadata(case: CaseHandle, spec: SimulationSpec) -> None:
    (case.path / "nuagent_case.json").write_text(
        json.dumps({"case": case.to_dict(), "spec": spec.model_dump(mode="json")}, indent=2)
    )


def get_backend(name: str) -> SolverBackend:
    """Factory used by the CLI and the agent."""
    if name == "openfoam":
        from nuagent.backends.openfoam.backend import OpenFOAMBackend

        return OpenFOAMBackend()
    if name == "festim":
        from nuagent.backends.festim.backend import FESTIMBackend

        return FESTIMBackend()
    if name == "mock":
        from nuagent.backends.mock.backend import MockBackend

        return MockBackend()
    raise ValueError(f"unknown backend {name!r}")
