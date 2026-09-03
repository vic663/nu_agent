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
from nuagent.backends.openfoam.mesh import size_pipe_mesh, size_ribbed_mesh
from nuagent.backends.openfoam.postprocess import extract_heated_pipe_qois, extract_ribbed_tube_qois
from nuagent.spec import (
    HeatedPipeCase,
    NumericsSpec,
    RibbedTubeCase,
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


def ribbed_blockmesh_context(case: RibbedTubeCase, mesh, theta: float) -> dict[str, Any]:
    """Vertices, blocks and patch faces of the multi-block ribbed-tube wedge.

    Vertex ids per station i: A=5i (axis), Bm/Bp=5i+1/5i+2 (rib-tip radius at -/+theta),
    Cm/Cp=5i+3/5i+4 (wall radius at -/+theta).  Face vertex lists follow the local hex
    face convention used by blockMesh for the two block types.
    """
    r1 = mesh.rib_tip_radius
    stations = mesh.stations
    segs = mesh.segments
    blocks, inlet, outlet, wall, front, back, axis = [], [], [], [], [], [], []

    def ids(i):
        b = 5 * i
        return b, b + 1, b + 2, b + 3, b + 4  # A, Bm, Bp, Cm, Cp

    for i, seg in enumerate(segs):
        A0, Bm0, Bp0, Cm0, Cp0 = ids(i)
        A1, Bm1, Bp1, Cm1, Cp1 = ids(i + 1)
        gx = seg.axial_grading
        # core block: axis -> rib tip radius (collapsed at the axis)
        blocks.append(
            {
                "segment": i,
                "kind": seg.kind,
                "layer": "core",
                "v": [A0, A1, Bm1, Bm0, A0, A1, Bp1, Bp0],
                "nx": seg.n_axial,
                "ny": mesh.n_core,
                "gx": gx,
                "gy": f"{mesh.core_grading:.6g}",
            }
        )
        axis.append([A0, A1, A1, A0])
        front.append([A0, Bm0, Bm1, A1])
        back.append([A0, A1, Bp1, Bp0])
        if seg.kind == "rib":
            wall.append([Bm0, Bp0, Bp1, Bm1])  # rib top (core block outer face)
        else:
            # rib-layer block: rib tip radius -> wall
            blocks.append(
                {
                    "segment": i,
                    "kind": seg.kind,
                    "layer": "rib layer",
                    "v": [Bm0, Bm1, Cm1, Cm0, Bp0, Bp1, Cp1, Cp0],
                    "nx": seg.n_axial,
                    "ny": mesh.n_rib_layer,
                    "gx": gx,
                    "gy": mesh.rib_layer_grading,
                }
            )
            wall.append([Cm0, Cp0, Cp1, Cm1])  # tube wall
            front.append([Bm0, Cm0, Cm1, Bm1])
            back.append([Bp0, Bp1, Cp1, Cp0])
            prev_rib = i > 0 and segs[i - 1].kind == "rib"
            next_rib = i + 1 < len(segs) and segs[i + 1].kind == "rib"
            if prev_rib:
                wall.append([Bm0, Bp0, Cp0, Cm0])  # downstream face of the previous rib
            if next_rib:
                wall.append([Bm1, Cm1, Cp1, Bp1])  # upstream face of the next rib
        if i == 0:
            inlet.append([A0, A0, Bp0, Bm0])
            if seg.kind != "rib":
                inlet.append([Bm0, Bp0, Cp0, Cm0])
        if i == len(segs) - 1:
            outlet.append([A1, Bm1, Bp1, A1])
            if seg.kind != "rib":
                outlet.append([Bm1, Cm1, Cp1, Bp1])

    return {
        "station_vertices": [{"x": f"{x:.10g}"} for x in stations],
        "r1y": f"{r1 * math.cos(theta):.10g}",
        "r1z_pos": f"{r1 * math.sin(theta):.10g}",
        "r1z_neg": f"{-r1 * math.sin(theta):.10g}",
        "blocks": blocks,
        "n_blocks": len(blocks),
        "n_cells": mesh.n_cells,
        "inlet_faces": inlet,
        "outlet_faces": outlet,
        "wall_faces": wall,
        "front_faces": front,
        "back_faces": back,
        "axis_faces": axis,
        "n_ribs": case.n_ribs,
        "e_over_D": case.rib_height_over_diameter,
        "p_over_e": case.rib_pitch_over_height,
        "w_over_e": case.rib_width_over_height,
        "inlet_length": case.inlet_length_over_diameter * case.diameter,
        "ribbed_length": case.ribbed_length,
        "outlet_length": case.outlet_length_over_diameter * case.diameter,
    }


class OpenFOAMBackend:
    name = "openfoam"

    def __init__(self) -> None:
        # one loader over the template root: field/numerics templates are shared ("heated_pipe/..."),
        # only the blockMeshDict differs between the smooth pipe and the ribbed tube
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_ROOT)),
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
        ribbed = isinstance(case, RibbedTubeCase)
        mesh = size_ribbed_mesh(case, refinement) if ribbed else size_pipe_mesh(case, refinement)
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
        ctx: dict[str, Any] = {
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
            "n_axial": getattr(mesh, "n_axial", None),
            "n_radial": getattr(mesh, "n_radial", None),
            "radial_grading": f"{mesh.radial_grading:.6g}"
            if hasattr(mesh, "radial_grading")
            else None,
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
            "_ribbed": ribbed,
        }
        if ribbed:
            ctx.update(ribbed_blockmesh_context(case, mesh, theta))
        return ctx

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

        blockmesh_set = "ribbed_tube" if ctx["_ribbed"] else "heated_pipe"
        files = [
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
            files.append("0/epsilon" if case.turbulence_model.uses_epsilon else "0/omega")

        for rel in files:
            out = workdir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                self.env.get_template(f"heated_pipe/{rel}.j2").render(**ctx), newline="\n"
            )
        (workdir / "system/blockMeshDict").write_text(
            self.env.get_template(f"{blockmesh_set}/system/blockMeshDict.j2").render(**ctx),
            newline="\n",
        )
        allrun = workdir / "Allrun"
        allrun.write_text(
            self.env.get_template("heated_pipe/Allrun.j2").render(**ctx), newline="\n"
        )
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

    def extend_case(
        self, spec: SimulationSpec, case: CaseHandle, adjustments: dict[str, Any] | None
    ) -> CaseHandle:
        """Re-render the numerics dictionaries of an existing case and restart from the latest time.

        Used when a run completed without diverging but did not meet the residual target: the
        iteration budget (and optionally relaxation factors / schemes) change, the mesh and the
        fields are kept, so no work is thrown away.  ``Allrun --continue`` skips meshing.
        """
        ctx = self.render_context(spec, case.refinement, adjustments)
        ctx["start_from"] = "latestTime"
        for rel in ("system/controlDict", "system/fvSchemes", "system/fvSolution"):
            (case.path / rel).write_text(
                self.env.get_template(f"heated_pipe/{rel}.j2").render(**ctx), newline="\n"
            )
        case.metadata["numerics"] = ctx["_numerics"].model_dump()
        case.metadata["adjustments"] = adjustments or {}
        case.metadata["continued"] = case.metadata.get("continued", 0) + 1
        case.spec_hash = spec_hash(
            spec, {"refinement": case.refinement, "adjustments": adjustments or {}}
        )
        write_case_metadata(case, spec)
        return case

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
        if isinstance(spec.case, RibbedTubeCase):
            return extract_ribbed_tube_qois(case.path, spec.case, case.metadata["stations"])
        return extract_heated_pipe_qois(case.path, spec.case, case.metadata["stations"])
