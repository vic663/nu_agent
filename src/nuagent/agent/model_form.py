"""Closure-ensemble study: model-form uncertainty next to numerical uncertainty.

For separated internal flows (rib turbulators, backward-facing steps, impinging jets) the choice of
RANS closure changes integral quantities by tens of percent — far more than the discretisation error
that a grid-refinement study quantifies.  A validation statement that quotes only the GCI band is
therefore incomplete.  This module re-runs the converged case with alternative closures — same
numerics, boundary conditions and core grid family; the near-wall treatment follows each closure's
formulation — and reports the spread of the quantities of interest as a model-form uncertainty, together
with the per-closure physics diagnostics (reattachment, y+) and the deviation of every member from the
validation reference.

Architecturally this is the *orchestrator–workers* pattern from the agent literature: the workflow
fans out identical, independent solver jobs (optionally concurrently) and reduces their results with
deterministic code.  No language model is involved; the LLM (if any) only sees the reduced table in
the critique step.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from nuagent.agent.cases import reusable_case
from nuagent.agent.vv import default_references, reference_for
from nuagent.spec import HeatedPipeCase, SimulationSpec, TurbulenceModel, WallTreatment

# High-Reynolds-number closures need log-law wall functions; Launder-Sharma integrates to the wall.
# k-omega SST is formulated for both and keeps whatever the primary case uses.
PREFERRED_WALL_TREATMENT: dict[TurbulenceModel, WallTreatment] = {
    TurbulenceModel.K_EPSILON: WallTreatment.WALL_FUNCTION,
    TurbulenceModel.REALIZABLE_KE: WallTreatment.WALL_FUNCTION,
    TurbulenceModel.LAUNDER_SHARMA_KE: WallTreatment.RESOLVED,
}


def closure_variant(
    spec: SimulationSpec, closure: TurbulenceModel, adapt_wall_treatment: bool | None = None
) -> SimulationSpec:
    """The same problem with a different turbulence closure (re-validated through the schema).

    With ``adapt_wall_treatment`` (default: the spec's ``model_form.adapt_wall_treatment``) the member
    gets the wall treatment its closure is formulated for, which changes the near-wall mesh (y+ target)
    but keeps the core grid family, the numerics and the boundary conditions.
    """
    closure = TurbulenceModel(closure)
    if adapt_wall_treatment is None:
        adapt_wall_treatment = spec.model_form.adapt_wall_treatment if spec.model_form else True
    d = spec.model_dump(mode="json")
    d["case"]["turbulence_model"] = closure.value
    if adapt_wall_treatment and closure in PREFERRED_WALL_TREATMENT:
        d["case"]["wall_treatment"] = PREFERRED_WALL_TREATMENT[closure].value
    d["name"] = f"{spec.name}-{closure.value}"
    d["model_form"] = None  # members do not spawn ensembles of their own
    return SimulationSpec.model_validate(d)


def _member_result(rt: Any, spec_k: SimulationSpec, case_dir: Path, adjustments: dict) -> dict:
    closure = spec_k.case.turbulence_model.value
    member: dict[str, Any] = {
        "closure": closure,
        "wall_treatment": spec_k.case.wall_treatment.value,
        "path": str(case_dir),
        "converged": False,
    }
    try:
        existing = reusable_case(case_dir, spec_k, adjustments)
        if existing is not None:
            case, member["reused"] = existing, True
        else:
            case = rt.backend.build(spec_k, case_dir, refinement=1.0, adjustments=adjustments)
            res = rt.run_case(spec_k, case)
            member["returncode"] = res.returncode
            member["wall_time_s"] = res.wall_time_s
        rep = rt.backend.parse_log(case)
        member.update(
            n_cells=case.n_cells,
            converged=rep.converged,
            iterations=rep.iterations,
            reason=rep.reason,
        )
        if rep.converged:
            q = rt.backend.extract_qois(case, spec_k)
            member["values"] = q.values
            member["checks"] = q.checks
    except Exception as exc:  # noqa: BLE001 - one bad member must not sink the ensemble
        member["reason"] = f"{type(exc).__name__}: {exc}"
    return member


def summarise_ensemble(
    spec: SimulationSpec,
    members: list[dict[str, Any]],
    quantities: list[str],
    gci: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reduce member results to spreads, deviations from the primary closure and from references."""
    gci = gci or {}
    primary = spec.case.turbulence_model.value
    converged = [m for m in members if m.get("converged") and m.get("values")]
    refs: dict[str, Any] = {}
    for r in default_references(spec):
        refs.setdefault(r.quantity, r)  # the first reference of a quantity is the primary one
    out: dict[str, Any] = {
        "primary": primary,
        "closures": [m["closure"] for m in members],
        "members": members,
        "n_converged": len(converged),
        "quantities": quantities,
        "spread": {},
    }
    for q in quantities:
        vals = {
            m["closure"]: float(m["values"][q])
            for m in converged
            if q in m["values"] and math.isfinite(float(m["values"][q]))
        }
        if len(vals) < 2:
            continue
        p = vals.get(primary)
        arr = list(vals.values())
        vmin, vmax, mean = min(arr), max(arr), sum(arr) / len(arr)
        scale = abs(p) if p else abs(mean)
        spread = (vmax - vmin) / scale if scale else math.inf
        g = gci.get(q, {}).get("gci_fine")
        entry: dict[str, Any] = {
            "min": vmin,
            "max": vmax,
            "mean": mean,
            "primary_value": p,
            "range_over_primary": spread,
            "model_form_uncertainty": 0.5 * spread,  # half range, relative to the primary value
            "gci_fine": g,
            "dominant": (
                None if g is None else ("model_form" if 0.5 * spread > g else "numerical")
            ),
            "deviation_from_primary": ({c: (v - p) / p for c, v in vals.items()} if p else {}),
        }
        ref = refs.get(q)
        if ref is not None:
            try:
                r = reference_for(spec, ref)
                dev = {c: (v - r["value"]) / r["value"] for c, v in vals.items()}
                entry["reference"] = {
                    "value": r["value"],
                    "source": r["source"],
                    "uncertainty": r.get("uncertainty", 0.0),
                    "tolerance": ref.tolerance,
                    "deviation": dev,
                    "within_tolerance": [c for c, d in dev.items() if abs(d) <= ref.tolerance],
                }
            except KeyError:
                pass
        out["spread"][q] = entry
    # per-closure physics diagnostics worth showing side by side
    diag_keys = (
        "reattachment_x_over_e",
        "reversed_flow_fraction_of_gap",
        "yplus_avg",
        "yplus_avg_estimate",
        "energy_balance_error",
    )
    out["diagnostics"] = {
        m["closure"]: {k: m["checks"][k] for k in diag_keys if k in m.get("checks", {})}
        for m in converged
    }
    return out


def run_closure_ensemble(rt: Any, spec: SimulationSpec, state: dict[str, Any]) -> dict[str, Any]:
    """Run every alternative closure of ``spec.model_form`` on the base grid and reduce the results."""
    mf = spec.model_form
    workdir = Path(state["workdir"])
    adjustments = dict(state.get("adjustments", {}))
    primary = spec.case.turbulence_model
    skipped: list[str] = []
    variants: list[SimulationSpec] = []
    for closure in dict.fromkeys(mf.closures):
        if closure is primary:
            continue
        try:
            variants.append(closure_variant(spec, closure))
        except Exception as exc:  # noqa: BLE001 - e.g. laminar closure for a turbulent Re
            skipped.append(f"{closure.value}: {exc}")

    primary_member = {
        "closure": primary.value,
        "wall_treatment": spec.case.wall_treatment.value,
        "path": state.get("case", {}).get("path"),
        "n_cells": state.get("case", {}).get("n_cells"),
        "converged": True,
        "iterations": state.get("convergence", {}).get("iterations"),
        "reason": "primary run",
        "values": state.get("qois", {}).get("values", {}),
        "checks": state.get("qois", {}).get("checks", {}),
    }
    jobs = [(v, workdir / f"model_form_{v.case.turbulence_model.value}") for v in variants]
    if mf.parallel > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=min(mf.parallel, len(jobs))) as pool:
            members = list(pool.map(lambda j: _member_result(rt, j[0], j[1], adjustments), jobs))
    else:
        members = [_member_result(rt, v, d, adjustments) for v, d in jobs]

    quantities = [q for q in ("Nu", "f") if q in primary_member["values"]]
    if not quantities:
        quantities = [
            q for q, v in primary_member["values"].items() if isinstance(v, (int, float))
        ][:4]
    summary = summarise_ensemble(
        spec,
        [primary_member, *members],
        quantities,
        gci=state.get("verification", {}).get("gci", {}),
    )
    summary["skipped"] = skipped
    return summary


def ensemble_warnings(spec: SimulationSpec, model_form: dict[str, Any]) -> list[str]:
    """Rule-based reading of an ensemble: what a turbulence modeller would flag."""
    warnings: list[str] = []
    if not model_form or not isinstance(spec.case, HeatedPipeCase):
        return warnings
    primary = model_form.get("primary")
    for q, s in model_form.get("spread", {}).items():
        ref = s.get("reference", {})
        tol = ref.get("tolerance", 0.10)
        rng = s.get("range_over_primary", 0.0)
        g = s.get("gci_fine")
        if rng > tol:
            msg = (
                f"turbulence closures disagree on {q} by {rng * 100:.0f} % of the {primary} value "
                f"(model-form uncertainty ±{s['model_form_uncertainty'] * 100:.0f} %"
            )
            msg += f" vs numerical GCI {g * 100:.1f} %)" if g is not None else ")"
            warnings.append(msg)
        if ref:
            ok = ref.get("within_tolerance", [])
            if primary not in ok and ok:
                warnings.append(
                    f"{q}: the primary closure {primary} is outside the {ref['source']} tolerance "
                    f"while {', '.join(ok)} agree with it — the discrepancy is model form, not "
                    "discretisation"
                )
            elif not ok:
                warnings.append(
                    f"{q}: no closure in the ensemble reproduces {ref['source']} within "
                    f"±{tol * 100:.0f} % (spread {s['min']:.4g}–{s['max']:.4g} vs {ref['value']:.4g})"
                )
    for m in model_form.get("members", []):
        if not m.get("converged"):
            warnings.append(
                f"closure {m['closure']} did not converge on the base grid ({m.get('reason')})"
            )
    treatments = {m["closure"]: m.get("wall_treatment") for m in model_form.get("members", [])}
    for closure, d in model_form.get("diagnostics", {}).items():
        yp = d.get("yplus_avg", d.get("yplus_avg_estimate"))
        wt = treatments.get(closure)
        if yp is not None and wt == "wall_function" and not (20 <= yp <= 300):
            warnings.append(
                f"closure {closure} uses wall functions but its average y+ = {yp:.1f} is outside "
                "20-300: not a valid wall-function solution"
            )
        if yp is not None and wt == "resolved" and yp > 5:
            warnings.append(f"closure {closure} is wall-resolved but its average y+ = {yp:.1f} > 5")
        frac = d.get("reversed_flow_fraction_of_gap")
        if frac is not None and frac > 0.8 and getattr(spec.case, "rib_pitch_over_height", 0) >= 6:
            warnings.append(
                f"closure {closure} predicts no reattachment between ribs (reversed flow over "
                f"{frac * 100:.0f} % of the gap) — d-type cavity flow where k-type is expected"
            )
    return warnings
