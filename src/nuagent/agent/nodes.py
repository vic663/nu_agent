"""Workflow nodes.  Each node is a pure function ``state -> partial state``.

The nodes are closed over a :class:`Runtime` (backend, executor, policy) so
that the same graph runs with OpenFOAM on SLURM or with the mock backend in
CI.  Nodes never raise for *expected* failures (divergence, validation
failure): they record the outcome in the state and let the graph route.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nuagent.agent.cases import reusable_case
from nuagent.agent.model_form import run_closure_ensemble
from nuagent.agent.policy import Policy, RulesPolicy
from nuagent.agent.preflight import preflight
from nuagent.agent.state import AgentState, decision
from nuagent.agent.vv import analytical_reference, compare, default_references, reference_for
from nuagent.backends.base import CaseHandle, ConvergenceReport, QoIResult, SolverBackend
from nuagent.executors.base import Executor
from nuagent.spec import ExecutorKind, HeatedPipeCase, SimulationSpec
from nuagent.verification import grid_convergence_index

DEFAULT_VV_QUANTITIES = {
    "heated_pipe": ["Nu", "f"],
    "ribbed_tube": ["Nu", "f"],
    "permeation": ["permeation_flux_ss", "time_lag"],
    "tds": ["T_peak"],
}


@dataclass
class Runtime:
    backend: SolverBackend
    executor: Executor
    policy: Policy = field(default_factory=RulesPolicy)
    live_monitor: bool = (
        True  # stop OpenFOAM runs early once NuAgent's convergence criterion is met
    )

    # -- helpers ------------------------------------------------------------
    def _log_tail(self, case: CaseHandle, n: int = 60) -> str:
        log = case.path / case.metadata.get("log", "log.run")
        if not log.exists():
            return ""
        return "\n".join(log.read_text(errors="replace").splitlines()[-n:])

    def _poll(self, case: CaseHandle, elapsed: float) -> str | None:
        """Live monitor: request a clean stop once the run satisfies the residual criterion.

        This deliberately uses ``criterion_met`` rather than ``converged``: a running log has no
        ``End`` marker yet, so ``converged`` is false by construction while the solver is alive.
        The verdict is formed later, in ``monitor``, from the finished log plus the exit status.
        """
        if not self.live_monitor or case.backend != "openfoam":
            return None
        report = self.backend.parse_log(case)
        if report.criterion_met and report.iterations > 50:
            return "stop"
        if report.diverged:
            return "stop"
        return None

    def run_case(self, spec: SimulationSpec, case: CaseHandle, args: tuple[str, ...] = ()):
        executor = self.executor
        if hasattr(executor, "on_poll") and executor.on_poll is None:
            executor.on_poll = self._poll
        return executor.run(case, spec.execution, args=args)


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #


_reusable_case = reusable_case  # backwards-compatible alias


def _grid_family_check(levels: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify the realised meshes form a systematic refinement family.

    Checks, in order of how badly each one invalidates a GCI:
    1. every level is strictly coarser than the previous one (identical levels carry no
       information — the classic failure is a cell-count floor binding on two levels at once);
    2. the directional counts actually change, so refinement is not one-dimensional;
    3. the wall resolution does not change *regime* across the family (a wall-resolved closure at
       y+ = 4 is not the same model as at y+ = 1), and wall functions stay out of the buffer layer.
    """
    issues: list[str] = []
    ordered = sorted(levels, key=lambda lv: -(lv.get("h") or 0.0))  # coarse -> fine
    for a, b in zip(ordered, ordered[1:], strict=False):
        if not (a.get("n_cells") and b.get("n_cells")) or b["n_cells"] <= a["n_cells"]:
            issues.append(
                f"levels r={a.get('refinement')} and r={b.get('refinement')} do not differ in cell "
                f"count ({a.get('n_cells')} vs {b.get('n_cells')})"
            )
            continue
        ma, mb = a.get("mesh") or {}, b.get("mesh") or {}
        for key in ("n_radial", "n_axial", "n_core"):
            if key in ma and key in mb and ma[key] == mb[key]:
                issues.append(
                    f"levels r={a.get('refinement')} and r={b.get('refinement')} share the same "
                    f"{key}={ma[key]}: refinement is not applied in that direction"
                )
    yps = [lv.get("mesh", {}).get("expected_yplus") for lv in ordered]
    yps = [y for y in yps if isinstance(y, (int, float))]
    if yps:
        lo, hi = min(yps), max(yps)
        if hi <= 2.0:
            pass  # every level is comfortably inside the viscous sublayer
        elif lo >= 30.0:
            pass  # every level sits in the log layer, where wall functions are valid
        elif hi <= 5.0:
            # still nominally "wall resolved", but a low-Re closure integrated to y+ = 4 is not
            # resolving the sublayer the way it does at y+ = 1
            issues.append(
                f"first-cell y+ reaches {hi:.3g} on the coarsest level (finest {lo:.3g}): a "
                "low-Re closure is not resolving the viscous sublayer equally on every level; "
                "anchor the y+ target to the coarsest level of the family"
            )
        else:
            issues.append(
                f"first-cell y+ spans {lo:.3g}-{hi:.3g} across the family, crossing the "
                "wall-resolved / buffer / wall-function regimes: the levels do not discretise "
                "the same model"
            )
    notes = [lv.get("mesh", {}).get("yplus_note") for lv in ordered]
    return {
        "systematic": not issues,
        "issues": issues,
        "yplus_range": [min(yps), max(yps)] if yps else None,
        "notes": sorted({n for n in notes if n}),
    }


def planned_job_budget(spec: SimulationSpec) -> dict[str, Any]:
    """Total solver submissions this workflow may make, for disclosure at the approval gate.

    The main solve is one job; a three-level grid study adds two more; a closure ensemble adds one
    per alternative closure and may run them concurrently.  Approving the first submission without
    seeing this number is how a single 'yes' turns into sixteen concurrent cluster jobs.
    """
    parts = [f"{spec.execution.max_attempts} solve attempt(s) max"]
    total = spec.execution.max_attempts
    if spec.verification.mesh_study:
        levels = max(0, spec.verification.n_levels - 1)
        total += levels
        parts.append(f"{levels} grid-refinement level(s)")
    concurrent = 1
    if spec.model_form is not None and spec.model_form.closures:
        members = max(0, len(set(spec.model_form.closures)) - 1)
        total += members
        concurrent = max(concurrent, min(spec.model_form.parallel, members) or 1)
        parts.append(f"{members} closure-ensemble member(s)")
    return {
        "total_jobs": total,
        "breakdown": ", ".join(parts),
        "max_concurrent": concurrent,
        "max_core_minutes": total * spec.execution.n_procs * spec.execution.wallclock_minutes,
    }


def _approval_block(spec: SimulationSpec, state: AgentState, node: str) -> dict | None:
    """Child solver submissions honour the same gate as the main solve."""
    if spec.execution.require_approval and not state.get("approved"):
        return {
            "decisions": [
                decision(
                    node,
                    "skipped: execution requires human approval and none was granted for this "
                    "workflow, so no further solver jobs were submitted",
                )
            ]
        }
    return None


def make_nodes(rt: Runtime) -> dict[str, Any]:
    def plan(state: AgentState) -> dict:
        try:
            if state.get("spec"):
                spec = SimulationSpec.model_validate(state["spec"])
                msg = "using the provided specification"
            else:
                spec = rt.policy.plan(state.get("task", ""))
                msg = f"planned specification from task with policy '{rt.policy.name}'"
            # absolute: executors change directory into the case, so relative paths would break
            workdir = Path(state.get("workdir") or Path("runs") / spec.name).resolve()
            workdir.mkdir(parents=True, exist_ok=True)
            spec.to_yaml(workdir / "spec.yaml")
            return {
                "spec": spec.model_dump(mode="json"),
                "workdir": str(workdir),
                "attempt": 1,
                "adjustments": {},
                "status": "running",
                "decisions": [
                    decision(
                        "plan", msg, name=spec.name, backend=spec.backend.value, case=spec.case.kind
                    )
                ],
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "failed",
                "error": f"planning failed: {exc}",
                "decisions": [decision("plan", str(exc))],
            }

    def review(state: AgentState) -> dict:
        """Independent pre-flight review of the specification before any solver time is spent.

        Deterministic rules (correlation validity, y+ vs wall treatment, entry length, lessons learned
        about closures, FESTIM time scales) are authoritative; an LLM policy may *add* concerns.
        Blocking findings stop the workflow here — the cheapest place to fail.
        """
        spec = SimulationSpec.model_validate(state["spec"])
        pf = preflight(spec)
        if hasattr(rt.policy, "review"):
            try:
                for w in rt.policy.review(spec, pf):
                    if w not in pf.warnings:
                        pf.warnings.append(w)
            except Exception as exc:  # noqa: BLE001 - review must never break the workflow
                pf.notes.append(f"LLM review unavailable: {type(exc).__name__}")
        out = pf.to_dict()
        (Path(state["workdir"]) / "preflight.json").write_text(json.dumps(out, indent=2))
        if not pf.ok:
            return {
                "preflight": out,
                "status": "failed",
                "error": "pre-flight review found blocking problems: " + "; ".join(pf.blocking),
                "decisions": [
                    decision(
                        "review", "blocked before build", blocking=pf.blocking, warnings=pf.warnings
                    )
                ],
            }
        msg = (
            f"{len(pf.warnings)} warning(s), {len(pf.notes)} note(s)"
            if (pf.warnings or pf.notes)
            else "no findings"
        )
        return {
            "preflight": out,
            "decisions": [decision("review", msg, warnings=pf.warnings, notes=pf.notes)],
        }

    def build(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        attempt = state.get("attempt", 1)
        adjustments = state.get("adjustments", {})
        if state.get("continue_case") and state.get("case") and hasattr(rt.backend, "extend_case"):
            # stalled-but-healthy run: keep mesh and fields, extend the budget, restart from latest time
            prev = CaseHandle.from_dict(state["case"])
            try:
                case = rt.backend.extend_case(spec, prev, adjustments)
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "failed",
                    "error": f"could not extend case: {exc}",
                    "decisions": [decision("build", str(exc))],
                }
            return {
                "case": case.to_dict(),
                "decisions": [
                    decision(
                        "build",
                        f"continuing case from its latest time (attempt {attempt}, {case.n_cells} cells)",
                        path=str(case.path),
                        adjustments=adjustments,
                    )
                ],
            }
        case_dir = Path(state["workdir"]) / f"attempt_{attempt}"
        existing = reusable_case(case_dir, spec, adjustments, backend=rt.backend)
        if existing is not None:
            existing.metadata["reused"] = True
            return {
                "case": existing.to_dict(),
                "decisions": [
                    decision(
                        "build",
                        f"reusing existing case with identical specification (attempt {attempt})",
                        path=str(existing.path),
                    )
                ],
            }
        try:
            case = rt.backend.build(spec, case_dir, refinement=1.0, adjustments=adjustments)
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "failed",
                "error": f"case generation failed: {exc}",
                "decisions": [decision("build", str(exc))],
            }
        return {
            "case": case.to_dict(),
            "decisions": [
                decision(
                    "build",
                    f"built {spec.backend.value} case (attempt {attempt}, {case.n_cells} cells)",
                    path=str(case.path),
                    adjustments=adjustments,
                    mesh=case.metadata.get("mesh"),
                )
            ],
        }

    def approve(state: AgentState) -> dict:
        """Human-in-the-loop gate before expensive HPC submissions."""
        spec = SimulationSpec.model_validate(state["spec"])
        if not spec.execution.require_approval or state.get("approved"):
            return {}
        from langgraph.types import interrupt

        case = CaseHandle.from_dict(state["case"])
        budget = planned_job_budget(spec)
        answer = interrupt(
            {
                "question": (
                    f"Submit this workflow for execution? It may submit up to {budget['total_jobs']} "
                    f"job(s) ({budget['breakdown']}), each with {spec.execution.n_procs} task(s) and "
                    f"a {spec.execution.wallclock_minutes} min wall-clock limit."
                ),
                "case": str(case.path),
                "n_cells": case.n_cells,
                "executor": spec.execution.executor.value,
                "n_procs": spec.execution.n_procs,
                "wallclock_minutes": spec.execution.wallclock_minutes,
                # The gate covers the whole workflow, so the reviewer is shown the whole budget:
                # the main solve, every grid-refinement level and every closure-ensemble member.
                "total_jobs": budget["total_jobs"],
                "job_breakdown": budget["breakdown"],
                "max_concurrent": budget["max_concurrent"],
                "max_core_minutes": budget["max_core_minutes"],
                "script": str(case.path / "job.sbatch")
                if spec.execution.executor is ExecutorKind.SLURM
                else None,
            }
        )
        ok = bool(answer) and str(answer).lower() not in ("no", "false", "0", "reject")
        return {
            "approved": ok,
            "decisions": [decision("approve", f"human approval: {ok}", answer=str(answer))],
        }

    def run(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        case = CaseHandle.from_dict(state["case"])
        if spec.execution.require_approval and not state.get("approved"):
            return {
                "status": "failed",
                "error": "execution not approved",
                "decisions": [decision("run", "not approved")],
            }
        if case.metadata.pop("reused", False) and not state.get("continue_case"):
            from nuagent.executors.base import RunResult

            result = RunResult(returncode=0, wall_time_s=0.0, executor="cached", stdout_tail="")
            return {
                "run": result.to_dict(),
                "decisions": [decision("run", "existing results reused; solver not re-run")],
            }
        args = ("--continue",) if state.get("continue_case") else ()
        result = rt.run_case(spec, case, args)
        return {
            "run": result.to_dict(),
            "decisions": [
                decision(
                    "run",
                    f"{result.executor} run finished rc={result.returncode} in {result.wall_time_s:.1f}s",
                    job_id=result.job_id,
                )
            ],
        }

    def monitor(state: AgentState) -> dict:
        case = CaseHandle.from_dict(state["case"])
        report = rt.backend.parse_log(case)
        # The solver's exit status is part of the verdict, not decoration.  A non-zero rc means
        # the run did not finish, whatever the last residuals in the log happen to say.
        rc = state.get("run", {}).get("returncode")
        report.returncode = rc
        if rc not in (None, 0) and report.converged:
            report.converged = False
            report.reason = (
                f"residual criterion met but the solver exited with rc={rc}; "
                f"not accepted as converged ({report.reason})"
            )
        return {
            "convergence": report.to_dict(),
            "decisions": [
                decision(
                    "monitor",
                    f"{report.status}: {report.reason}",
                    iterations=report.iterations,
                    returncode=rc,
                    criterion_met=report.criterion_met,
                    completed=report.completed,
                    residuals={k: f"{v:.2e}" for k, v in report.final_residuals.items()},
                    continuity=report.continuity_error,
                )
            ],
        }

    def diagnose(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        case = CaseHandle.from_dict(state["case"])
        report = ConvergenceReport(**state["convergence"])
        attempt = state.get("attempt", 1)
        current = dict(state.get("adjustments", {}))
        adj = rt.policy.diagnose(spec, report, rt._log_tail(case), current, attempt)
        if adj.give_up or attempt >= spec.execution.max_attempts:
            why = (
                adj.rationale
                if adj.give_up
                else f"attempt budget ({spec.execution.max_attempts}) exhausted"
            )
            return {
                "status": "failed",
                "error": f"could not obtain a converged solution: {why}",
                "decisions": [decision("diagnose", f"giving up: {why}", proposal=adj.as_dict())],
            }
        current.update(adj.as_dict())
        # a run that completed cleanly but stalled can be *continued* (mesh + fields kept) when only
        # numerics change; a diverged run must be rebuilt from scratch
        continue_case = bool(report.completed and not report.diverged)
        return {
            "attempt": attempt + 1,
            "adjustments": current,
            "continue_case": continue_case,
            "decisions": [
                decision(
                    "diagnose",
                    adj.rationale or "adjusting numerics",
                    adjustments=adj.as_dict(),
                    policy=rt.policy.name,
                )
            ],
        }

    def postprocess(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        case = CaseHandle.from_dict(state["case"])
        try:
            qois = rt.backend.extract_qois(case, spec)
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "failed",
                "error": f"post-processing failed: {exc}",
                "decisions": [decision("postprocess", str(exc))],
            }
        (case.path / "qois.json").write_text(json.dumps(qois.to_dict(), indent=2))
        return {
            "qois": qois.to_dict(),
            "decisions": [
                decision(
                    "postprocess",
                    "extracted QoIs",
                    values={k: v for k, v in qois.values.items()},
                    checks=qois.checks,
                )
            ],
        }

    def verify(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        base_case = CaseHandle.from_dict(state["case"])
        qois = QoIResult(**state["qois"])
        quantities = DEFAULT_VV_QUANTITIES.get(spec.case.kind, list(qois.values))
        quantities = [
            q
            for q in dict.fromkeys(quantities + [r.quantity for r in spec.validation.references])
            if q in qois.values
        ]
        out: dict[str, Any] = {"levels": [], "gci": {}, "exact_error": {}}
        decisions = []

        # exact-solution errors (solution verification against analytical results)
        for q in quantities:
            ref = analytical_reference(spec, q)
            if ref is not None and math.isfinite(qois.values[q]):
                out["exact_error"][q] = {
                    "exact": ref[0],
                    "error": (qois.values[q] - ref[0]) / ref[0],
                    "notes": ref[1],
                }

        if not spec.verification.mesh_study:
            decisions.append(
                decision("verify", "mesh study disabled", exact_error=out["exact_error"])
            )
            return {"verification": out, "decisions": decisions}
        blocked = _approval_block(spec, state, "verify")
        if blocked is not None:
            out["skipped"] = "not approved"
            return {"verification": out, "decisions": decisions + blocked["decisions"]}

        # grid-refinement study: the base grid is the finest; coarser levels are cheap
        r = spec.verification.refinement_ratio
        levels = [(1.0, base_case, qois)]
        for k in range(1, spec.verification.n_levels):
            refinement = r ** (-k)
            case_dir = Path(state["workdir"]) / f"verify_r{refinement:.4g}"
            try:
                case = rt.backend.build(
                    spec, case_dir, refinement=refinement, adjustments=state.get("adjustments", {})
                )
                res = rt.run_case(spec, case)
                rep = rt.backend.parse_log(case)
                if not rep.converged:
                    decisions.append(
                        decision(
                            "verify",
                            f"level r={refinement:.3g} not converged ({rep.reason}); skipped",
                        )
                    )
                    continue
                q_k = rt.backend.extract_qois(case, spec)
                levels.append((refinement, case, q_k))
                decisions.append(
                    decision(
                        "verify",
                        f"level r={refinement:.3g}: {case.n_cells} cells, rc={res.returncode}",
                        values=q_k.values,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                decisions.append(decision("verify", f"level r={refinement:.3g} failed: {exc}"))

        out["levels"] = [
            {
                "refinement": lv,
                "h": c.representative_h,
                "n_cells": c.n_cells,
                "mesh": c.metadata.get("mesh", {}),
                "values": qq.values,
                "path": str(c.path),
            }
            for lv, c, qq in levels
        ]
        # A correct GCI computed on a family that is not a systematic refinement is not a
        # discretisation uncertainty.  Celik et al. (2008) require geometrically similar grids that
        # differ significantly in every direction; check the *realised* meshes, not the requested
        # refinement factors, and say so in the report when they do not.
        out["family"] = _grid_family_check(out["levels"])
        if out["family"]["issues"]:
            decisions.append(
                decision(
                    "verify",
                    "grid family is not a systematic refinement: "
                    + "; ".join(out["family"]["issues"]),
                    levels=[
                        {k: lv.get(k) for k in ("refinement", "n_cells", "h")}
                        for lv in out["levels"]
                    ],
                )
            )
        h = [c.representative_h for _, c, _ in levels if c.representative_h is not None]
        if len(levels) >= 2 and len(h) == len(levels):
            for q in quantities:
                raw = [qq.values.get(q) for _, _, qq in levels]
                f = [
                    float(v) for v in raw if isinstance(v, (int, float)) and math.isfinite(float(v))
                ]
                if len(f) == len(raw):
                    exact = out["exact_error"].get(q, {}).get("exact")
                    out["gci"][q] = grid_convergence_index(q, h, f, exact=exact).to_dict()
            decisions.append(
                decision(
                    "verify",
                    "grid convergence index computed",
                    gci={
                        q: {
                            "p": v["observed_order"],
                            "gci_fine": v["gci_fine"],
                            "convergence": v["convergence"],
                        }
                        for q, v in out["gci"].items()
                    },
                )
            )
        else:
            decisions.append(
                decision("verify", "fewer than two converged levels; GCI not available")
            )

        # ``require_asymptotic``: the grid family must actually be in the asymptotic range before
        # its GCI may be quoted as a numerical-uncertainty band.
        not_asymptotic = [
            q
            for q, v in out["gci"].items()
            if v.get("convergence") != "monotonic"
            or v.get("observed_order") is None
            or v["observed_order"] < 0.5
        ]
        out["asymptotic_ok"] = not not_asymptotic and out.get("family", {}).get("systematic", True)
        out["not_asymptotic"] = not_asymptotic
        if not_asymptotic:
            decisions.append(
                decision(
                    "verify",
                    "grid family is not in the asymptotic range for: " + ", ".join(not_asymptotic),
                    require_asymptotic=spec.verification.require_asymptotic,
                )
            )
        if spec.verification.require_asymptotic and out.get("family", {}).get("issues"):
            return {
                "verification": out,
                "status": "failed",
                "error": (
                    "verification.require_asymptotic is set and the grid family is not a "
                    "systematic refinement: " + "; ".join(out["family"]["issues"])
                ),
                "decisions": decisions,
            }
        if spec.verification.require_asymptotic and not_asymptotic:
            return {
                "verification": out,
                "status": "failed",
                "error": (
                    "verification.require_asymptotic is set and the grid family is not asymptotic "
                    f"for: {', '.join(not_asymptotic)}"
                ),
                "decisions": decisions,
            }
        return {"verification": out, "decisions": decisions}

    def model_form(state: AgentState) -> dict:
        """Closure ensemble on the base grid (orchestrator–workers; deterministic reduction)."""
        spec = SimulationSpec.model_validate(state["spec"])
        if spec.model_form is None or not spec.model_form.closures:
            return {}
        if not isinstance(spec.case, HeatedPipeCase) or spec.case.regime.value == "laminar":
            return {
                "decisions": [
                    decision("model_form", "closure ensemble skipped: not a turbulent CFD case")
                ]
            }
        blocked = _approval_block(spec, state, "model_form")
        if blocked is not None:
            return blocked
        try:
            summary = run_closure_ensemble(rt, spec, dict(state))
        except Exception as exc:  # noqa: BLE001
            return {
                "model_form": {"error": str(exc)},
                "decisions": [decision("model_form", f"closure ensemble failed: {exc}")],
            }
        (Path(state["workdir"]) / "model_form.json").write_text(
            json.dumps(summary, indent=2, default=str)
        )
        spread = {
            q: f"±{s['model_form_uncertainty'] * 100:.1f} %" for q, s in summary["spread"].items()
        }
        return {
            "model_form": summary,
            "decisions": [
                decision(
                    "model_form",
                    f"{summary['n_converged']}/{len(summary['members'])} closures converged; "
                    "model-form uncertainty " + ", ".join(f"{q} {v}" for q, v in spread.items()),
                    closures=summary["closures"],
                    spread=spread,
                    skipped=summary.get("skipped", []),
                )
            ],
        }

    def validate(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        qois = QoIResult(**state["qois"])
        gci = state.get("verification", {}).get("gci", {})
        refs = default_references(spec)  # sensible defaults so a run is never "unvalidated"
        results: dict[str, Any] = {}
        for ref in refs:
            # first reference of a quantity is keyed by the bare name (plots look it up); extra ones by source
            key = ref.quantity if ref.quantity not in results else f"{ref.quantity} [{ref.source}]"
            if ref.quantity not in qois.values:
                results[key] = {
                    "quantity": ref.quantity,
                    "passed": False,
                    "error": "quantity not produced by the backend",
                }
                continue
            try:
                reference = reference_for(spec, ref)
            except KeyError as exc:
                results[key] = {"quantity": ref.quantity, "passed": False, "error": str(exc)}
                continue
            g = gci.get(ref.quantity, {}).get("gci_fine")
            results[key] = {
                "quantity": ref.quantity,
                **compare(qois.values[ref.quantity], reference, ref.tolerance, g),
            }
        all_passed = all(r.get("passed", False) for r in results.values()) if results else False
        summary = ", ".join(
            f"{q}: {r['relative_error'] * 100:+.1f}% vs {r['source']} ({'pass' if r['passed'] else 'FAIL'})"
            if "relative_error" in r
            else f"{q}: {r.get('error')}"
            for q, r in results.items()
        )
        return {
            "validation": {"results": results, "passed": all_passed},
            "decisions": [decision("validate", summary or "no references", passed=all_passed)],
        }

    def calibrate(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        if spec.calibration is None:
            return {}
        from nuagent.calibration.workflow import run_calibration_for_spec

        try:
            result = run_calibration_for_spec(spec, Path(state["workdir"]) / "calibration")
            return {
                "calibration": result,
                "decisions": [
                    decision(
                        "calibrate", "Bayesian calibration finished", summary=result.get("summary")
                    )
                ],
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "calibration": {"error": str(exc)},
                "decisions": [decision("calibrate", f"calibration failed: {exc}")],
            }

    def uq(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        if spec.uq is None:
            return {}
        from nuagent.uq.workflow import run_uq_for_spec

        try:
            result = run_uq_for_spec(spec, Path(state["workdir"]) / "uq")
            return {
                "uq": result,
                "decisions": [
                    decision("uq", "sensitivity analysis finished", sobol=result.get("first_order"))
                ],
            }
        except Exception as exc:  # noqa: BLE001
            return {"uq": {"error": str(exc)}, "decisions": [decision("uq", f"UQ failed: {exc}")]}

    def critique(state: AgentState) -> dict:
        spec = SimulationSpec.model_validate(state["spec"])
        results = {
            k: state.get(k, {})
            for k in (
                "qois",
                "verification",
                "validation",
                "convergence",
                "model_form",
                "preflight",
            )
        }
        crit = rt.policy.critique(spec, results)
        return {
            "critique": crit.model_dump(),
            "decisions": [
                decision("critique", f"{crit.verdict}: {crit.summary}", warnings=crit.warnings)
            ],
        }

    def report(state: AgentState) -> dict:
        from nuagent.reporting.report import write_report

        spec = SimulationSpec.model_validate(state["spec"])
        # V&V and the physics critique are *gates*, not advisory annotations.  Previously the
        # verdict was computed and then never consulted, so a run the critique had rejected still
        # printed "Status: success" whenever validation happened to pass, and exited 0 either way.
        verdict = (state.get("critique") or {}).get("verdict")
        validation_passed = bool(state.get("validation", {}).get("passed"))
        if state.get("status") == "failed" or verdict == "reject":
            status = "failed"
        elif validation_passed:
            status = "success"
        else:
            status = "completed_with_issues"
        gate_decisions = []
        if verdict == "reject" and state.get("status") != "failed":
            gate_decisions.append(
                decision(
                    "report",
                    "physics critique rejected the result: reported as failed even though the run "
                    "converged and completed",
                    verdict=verdict,
                    warnings=(state.get("critique") or {}).get("warnings", []),
                )
            )
        # the gate decision has to be in the state *before* the report is rendered, or the reader
        # never sees why a converged, completed run was reported as failed
        state_for_report = {
            **dict(state),
            "decisions": list(state.get("decisions") or []) + gate_decisions,
        }
        try:
            path = write_report(spec, state_for_report, Path(state["workdir"]), status=status)
        except Exception as exc:  # noqa: BLE001
            return {
                "status": status,
                "decisions": [decision("report", f"report generation failed: {exc}")],
            }
        return {
            "report_path": str(path),
            "status": status,
            "decisions": gate_decisions + [decision("report", f"report written to {path}")],
        }

    return {
        "plan": plan,
        "review": review,
        "build": build,
        "approve": approve,
        "run": run,
        "monitor": monitor,
        "diagnose": diagnose,
        "postprocess": postprocess,
        "verify": verify,
        "model_form": model_form,
        "validate": validate,
        "calibrate": calibrate,
        "uq": uq,
        "critique": critique,
        "report": report,
    }


def needs_approval(spec: SimulationSpec) -> bool:
    return spec.execution.require_approval and spec.execution.executor in (
        ExecutorKind.SLURM,
        ExecutorKind.DOCKER,
        ExecutorKind.LOCAL,
    )


__all__ = ["Runtime", "make_nodes", "needs_approval", "time"]
