"""OpenFOAM backend: template-driven case generation for the heated pipe.

Design notes
------------
* Every dictionary is rendered from a Jinja2 template with *validated* numbers
  from the :class:`~nuagent.spec.HeatedPipeCase`.  The LLM never edits
  OpenFOAM syntax; it only proposes changes to whitelisted numerics that are
  re-validated through :class:`~nuagent.spec.NumericsSpec`.
* Templates target the ESI branch (``buoyantSimpleFoam``); tested on v1912 and
  written to be compatible with v2312-v2512 (``opencfd/openfoam-default``).
* The generated ``Allrun`` is self-contained so Docker and SLURM executors
  only need to invoke it.
"""

from __future__ import annotations

import math
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from nuagent import __version__
from nuagent.backends.base import (
    CaseHandle,
    ConvergenceReport,
    QoIResult,
    spec_hash,
    write_case_metadata,
)
from nuagent.backends.openfoam.logparse import parse_checkmesh, parse_log_file
from nuagent.backends.openfoam.mesh import size_pipe_mesh
from nuagent.backends.openfoam.postprocess import extract_heated_pipe_qois
from nuagent.spec import (
    HeatedPipeCase,
    NumericsSpec,
    SimulationSpec,
    TurbulenceModel,
    WallTreatment,
)

TEMPLATE_ROOT = Path(__file__).parent / "templates"
APPLICATION = "buoyantSimpleFoam"

# Numerics the diagnostician is allowed to change, with hard bounds
ADJUSTABLE_NUMERICS = {
    "relax_U": (0.1, 0.9),
    "relax_p": (0.05, 0.7),
    "relax_h": (0.1, 0.95),
    "relax_turbulence": (0.1, 0.9),
    "div_scheme": ("upwind", "linearUpwind", "limitedLinear"),
    "max_iterations": (100, 100_000),
    "n_non_orthogonal_correctors": (0, 3),
    "residual_target": (1e-8, 1e-3),
}


def default_stations(length: float, n: int = 19) -> list[float]:
    return [float(v) for v in np.linspace(0.05, 0.95, n) * length]


def find_foam_bashrc() -> Path | None:
    candidates = [os.environ.get("NUAGENT_FOAM_BASHRC", "")]
    if os.environ.get("WM_PROJECT_DIR"):
        candidates.append(os.path.join(os.environ["WM_PROJECT_DIR"], "etc", "bashrc"))
    import glob

    candidates += sorted(glob.glob("/usr/lib/openfoam/openfoam*/etc/bashrc"), reverse=True)
    candidates += sorted(glob.glob("/opt/openfoam*/etc/bashrc"), reverse=True)
    candidates += ["/usr/share/openfoam/etc/bashrc", "/openfoam/bash.rc"]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


class OpenFOAMBackend:
    name = "openfoam"

    def __init__(self, template_set: str = "heated_pipe") -> None:
        self.template_set = template_set
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_ROOT / template_set)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # ------------------------------------------------------------------ #
    def available(self) -> bool:
        return shutil.which("blockMesh") is not None or find_foam_bashrc() is not None

    # ------------------------------------------------------------------ #
    def apply_adjustments(
        self, numerics: NumericsSpec, adjustments: dict[str, Any] | None
    ) -> NumericsSpec:
        """Return a new NumericsSpec with whitelisted, bounded adjustments applied."""
        if not adjustments:
            return numerics
        data = numerics.model_dump()
        for key, value in adjustments.items():
            if key not in ADJUSTABLE_NUMERICS:
                raise ValueError(
                    f"adjustment {key!r} is not allowed; permitted: {sorted(ADJUSTABLE_NUMERICS)}"
                )
            bounds = ADJUSTABLE_NUMERICS[key]
            if isinstance(bounds[0], str):
                if value not in bounds:
                    raise ValueError(f"{key} must be one of {bounds}")
            else:
                value = min(max(value, bounds[0]), bounds[1])
            data[key] = value
        return NumericsSpec.model_validate(data)

    def render_context(
        self, spec: SimulationSpec, refinement: float, adjustments: dict[str, Any] | None
    ) -> dict[str, Any]:
        case = spec.case
        if not isinstance(case, HeatedPipeCase):
            raise TypeError("OpenFOAM backend currently supports HeatedPipeCase only")
        numerics = self.apply_adjustments(case.numerics, adjustments)
        mesh = size_pipe_mesh(case, refinement)
        fluid = case.fluid
        turbulent = case.turbulence_model is not TurbulenceModel.LAMINAR
        radius = 0.5 * case.diameter
        theta = math.radians(case.mesh.wedge_angle_deg)
        u_in = case.inlet_velocity
        k_in = 1.5 * (case.inlet_turbulence_intensity * u_in) ** 2
        mixing_length = 0.07 * case.diameter
        c_mu = 0.09
        omega_in = math.sqrt(k_in) / (c_mu**0.25 * mixing_length)
        epsilon_in = c_mu**0.75 * k_in**1.5 / mixing_length
        stations = default_stations(case.length)
        return {
            "nuagent_version": __version__,
            "case_name": spec.name,
            "application": APPLICATION,
            "n_procs": spec.execution.n_procs,
            # geometry / mesh
            "diameter": case.diameter,
            "radius": radius,
            "length": case.length,
            "wedge_angle_deg": case.mesh.wedge_angle_deg,
            "ry": radius * math.cos(theta),
            "rz_pos": radius * math.sin(theta),
            "rz_neg": -radius * math.sin(theta),
            "n_axial": mesh.n_axial,
            "n_radial": mesh.n_radial,
            "radial_grading": f"{mesh.radial_grading:.6g}",
            # fluid
            "fluid_name": fluid.name,
            "rho": fluid.rho,
            "mu": fluid.mu,
            "cp": fluid.cp,
            "k": fluid.k,
            "pr": f"{fluid.pr:.6g}",
            "mol_weight": fluid.mol_weight,
            # flow / BCs
            "u_in": f"{u_in:.8g}",
            "t_in": case.inlet_temperature,
            "q_wall": case.wall_heat_flux,
            "p_ref": 0.0,  # rhoConst EOS: absolute level irrelevant; p~0 keeps GAMG residuals well-scaled
            "turbulent": turbulent,
            "turbulence_model": case.turbulence_model.value,
            "resolved": case.wall_treatment is WallTreatment.RESOLVED,
            "prt": case.turbulent_prandtl,
            "intensity": case.inlet_turbulence_intensity,
            "k_in": f"{k_in:.6g}",
            "omega_in": f"{omega_in:.6g}",
            "epsilon_in": f"{epsilon_in:.6g}",
            "mixing_length": f"{mixing_length:.6g}",
            # numerics
            "max_iterations": numerics.max_iterations,
            "write_interval": numerics.write_interval,
            "use_function_objects": False,
            "residual_target": f"{numerics.residual_target:.3g}",
            "residual_target_turb": f"{10 * numerics.residual_target:.3g}",
            "relax_U": numerics.relax_U,
            "relax_p": numerics.relax_p,
            "relax_h": numerics.relax_h,
            "relax_turbulence": numerics.relax_turbulence,
            "div_scheme": numerics.div_scheme,
            "n_non_orthogonal_correctors": numerics.n_non_orthogonal_correctors,
            # post-processing
            "_mesh": mesh,
            "_numerics": numerics,
            "_stations": stations,
        }

    def build(
        self,
        spec: SimulationSpec,
        workdir: Path,
        refinement: float = 1.0,
        adjustments: dict[str, Any] | None = None,
    ) -> CaseHandle:
        ctx = self.render_context(spec, refinement, adjustments)
        case = spec.case
        assert isinstance(case, HeatedPipeCase)
        turbulent = ctx["turbulent"]
        workdir = Path(workdir)
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)

        files = [
            "system/blockMeshDict",
            "system/controlDict",
            "system/fvSchemes",
            "system/fvSolution",
            "system/decomposeParDict",
            "constant/g",
            "constant/thermophysicalProperties",
            "constant/turbulenceProperties",
            "0/U",
            "0/T",
            "0/p",
            "0/p_rgh",
            "0/alphat",
        ]
        if turbulent:
            files += ["0/nut", "0/k"]
            files.append(
                "0/omega" if case.turbulence_model is TurbulenceModel.K_OMEGA_SST else "0/epsilon"
            )

        for rel in files:
            out = workdir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(self.env.get_template(rel + ".j2").render(**ctx))
        allrun = workdir / "Allrun"
        allrun.write_text(self.env.get_template("Allrun.j2").render(**ctx))
        allrun.chmod(0o755)

        mesh = ctx["_mesh"]
        handle = CaseHandle(
            path=workdir,
            backend=self.name,
            spec_hash=spec_hash(spec, {"refinement": refinement, "adjustments": adjustments or {}}),
            refinement=refinement,
            representative_h=mesh.representative_h,
            n_cells=mesh.n_cells,
            metadata={
                "application": APPLICATION,
                "mesh": mesh.to_dict(),
                "numerics": ctx["_numerics"].model_dump(),
                "stations": ctx["_stations"],
                "adjustments": adjustments or {},
                "log": f"log.{APPLICATION}",
            },
        )
        write_case_metadata(handle, spec)
        return handle

    # ------------------------------------------------------------------ #
    def parse_log(self, case: CaseHandle) -> ConvergenceReport:
        target = case.metadata.get("numerics", {}).get("residual_target")
        report = parse_log_file(case.path / f"log.{APPLICATION}", residual_target=target)
        # Mesh quality: only *serious* checkMesh failures are surfaced in the convergence reason;
        # cosmetic warnings (e.g. small determinant of high-aspect boundary-layer cells) are kept as notes.
        quality = parse_checkmesh(case.path / "log.checkMesh")
        case.metadata["mesh_quality"] = quality
        if quality.get("serious_failures"):
            report.reason = f"checkMesh: {', '.join(quality['serious_failures'])}; {report.reason}"
        return report

    def extract_qois(self, case: CaseHandle, spec: SimulationSpec) -> QoIResult:
        assert isinstance(spec.case, HeatedPipeCase)
        return extract_heated_pipe_qois(case.path, spec.case, case.metadata["stations"])
