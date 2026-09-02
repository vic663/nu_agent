"""Render the Markdown report and provenance record for a workflow run."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from nuagent.reporting import plots
from nuagent.reporting.provenance import collect_provenance
from nuagent.spec import SimulationSpec

TEMPLATES = Path(__file__).parent / "templates"


def fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return "nan"
        if v == 0:
            return "0"
        if abs(v) >= 1e5 or abs(v) < 1e-3:
            return f"{v:.4e}"
        return f"{v:.5g}"
    return str(v)


def pct(v: Any) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{100 * v:.2f} %"


def case_table(spec: SimulationSpec) -> list[tuple[str, str]]:
    case = spec.case
    rows: list[tuple[str, str]] = []
    if case.kind == "heated_pipe":
        rows += [
            (
                "Fluid",
                f"{case.fluid.name} (ρ={case.fluid.rho} kg/m³, μ={case.fluid.mu} Pa·s, Pr={case.fluid.pr:.3g})",
            ),
            (
                "Diameter / length",
                f"{case.diameter} m / {case.length:.4g} m (L/D = {case.length_over_diameter})",
            ),
            (
                "Reynolds number",
                f"{case.reynolds:.4g} ({case.regime.value}); U_in = {case.inlet_velocity:.4g} m/s",
            ),
            (
                "Wall heat flux",
                f"{case.wall_heat_flux:.4g} W/m²; T_in = {case.inlet_temperature} K",
            ),
            (
                "Turbulence model",
                f"{case.turbulence_model.value}, wall treatment: {case.wall_treatment.value}, Pr_t = {case.turbulent_prandtl}",
            ),
            (
                "Base mesh",
                f"{case.mesh.n_radial} radial × {case.mesh.cells_per_diameter} cells/D, target y+ = {case.mesh.target_yplus}",
            ),
            (
                "Numerics",
                f"{case.numerics.div_scheme}, relax U/p/h = {case.numerics.relax_U}/{case.numerics.relax_p}/{case.numerics.relax_h}, target residual {case.numerics.residual_target:g}",
            ),
        ]
    elif case.kind == "permeation":
        rows += [
            (
                "Material",
                f"{case.material.name}: D₀={case.material.D_0:.3g} m²/s, E_D={case.material.E_D} eV",
            ),
            ("Thickness / temperature", f"{case.thickness:.3g} m / {case.temperature} K"),
            ("Upstream concentration", f"{case.upstream_concentration:.3g} m⁻³"),
            (
                "Traps",
                ", ".join(f"{t.name}: E_p={t.E_p} eV, n={t.n:.2g} m⁻³" for t in case.traps)
                or "none",
            ),
            ("Discretisation", f"{case.n_cells} cells, {case.n_steps} steps"),
        ]
    elif case.kind == "tds":
        rows += [
            ("Material", f"{case.material.name}"),
            (
                "Implantation",
                f"{case.implantation_flux:.3g} m⁻²s⁻¹ for {case.implantation_time} s at {case.implantation_temperature} K",
            ),
            (
                "Ramp",
                f"{case.ramp_rate} K/s to {case.final_temperature} K after {case.rest_time} s rest",
            ),
            ("Traps", ", ".join(f"{t.name}: E_p={t.E_p} eV, n={t.n:.2g} m⁻³" for t in case.traps)),
        ]
    rows.append(
        (
            "Execution",
            f"{spec.execution.executor.value}, {spec.execution.n_procs} proc(s), max {spec.execution.max_attempts} attempt(s)",
        )
    )
    return rows


def write_report(spec: SimulationSpec, state: dict[str, Any], workdir: Path, status: str) -> Path:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    figdir = workdir / "figures"
    figdir.mkdir(exist_ok=True)

    convergence = state.get("convergence", {}) or {}
    qois = state.get("qois", {}) or {}
    verification = state.get("verification", {}) or {}
    validation = state.get("validation", {}) or {}
    spec_dict = spec.model_dump(mode="json")

    residual_plot = plots.plot_residuals(
        convergence.get("residual_history", {}), figdir / "residuals.png"
    )
    profile_plot = plots.plot_profiles(
        spec_dict, qois.get("profiles", {}), validation, figdir / "profiles.png"
    )
    gci_plot = plots.plot_gci(verification, figdir / "gci.png")

    provenance = collect_provenance(workdir, spec_dict, state)
    (workdir / "provenance.json").write_text(json.dumps(provenance, indent=2))
    with open(workdir / "decisions.jsonl", "w") as fh:
        for d in state.get("decisions", []):
            fh.write(json.dumps(d, default=str) + "\n")
    (workdir / "result.json").write_text(
        json.dumps(
            {
                "status": status,
                **{
                    k: state.get(k)
                    for k in (
                        "error",
                        "qois",
                        "verification",
                        "validation",
                        "calibration",
                        "uq",
                        "critique",
                        "convergence",
                        "run",
                        "attempt",
                        "adjustments",
                    )
                },
            },
            indent=2,
            default=str,
        )
    )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)), trim_blocks=False, lstrip_blocks=False
    )
    env.filters["fmt"] = fmt
    text = env.get_template("report.md.j2").render(
        spec=spec_dict,
        state=state,
        status=status,
        case_table=case_table(spec),
        convergence=convergence,
        run=state.get("run", {}) or {},
        qois=qois,
        verification=verification,
        validation=validation,
        calibration=state.get("calibration") or {},
        uq=state.get("uq") or {},
        critique=state.get("critique", {}) or {},
        provenance=provenance,
        provenance_json=json.dumps(
            {k: v for k, v in provenance.items() if k != "input_digests"}, indent=2
        ),
        residual_plot=residual_plot.relative_to(workdir).as_posix() if residual_plot else None,
        profile_plot=profile_plot.relative_to(workdir).as_posix() if profile_plot else None,
        gci_plot=gci_plot.relative_to(workdir).as_posix() if gci_plot else None,
        workdir=str(workdir),
        fmt=fmt,
        pct=pct,
    )
    if state.get("error"):
        text = text.replace(
            "## 1. Problem definition",
            f"> **Error:** {state['error']}\n\n## 1. Problem definition",
            1,
        )
    path = workdir / "report.md"
    path.write_text(text)
    return path
