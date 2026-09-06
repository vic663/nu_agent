"""Decision policies: what the *agent* decides, separated from what the workflow *does*.

Four decisions in the workflow are judgement calls:

1. **plan**      — turn an engineering question into a :class:`SimulationSpec`
2. **review**    — independent pre-flight check of the plan before solver time is spent
3. **diagnose**  — given a failed/non-converged run, propose bounded numerics changes
4. **critique**  — review the final results for physical plausibility

Everything else (meshing, running, parsing, GCI, validation arithmetic) is
deterministic code.  A :class:`RulesPolicy` implements all decisions with
explicit heuristics so the entire workflow is reproducible without an LLM;
:class:`LLMPolicy` layers a language model on top *but always passes the
LLM's proposal through the same validators*, so a hallucinated parameter can
never reach the solver.  This separation is also what makes the agent
"qualifiable": the evals compare both policies on the same tasks.
"""

from __future__ import annotations

import json
import math
from typing import Any, Protocol

from pydantic import BaseModel, Field

from nuagent.backends.base import ConvergenceReport
from nuagent.spec import HeatedPipeCase, SimulationSpec

# --------------------------------------------------------------------------- #
# Shared schemas
# --------------------------------------------------------------------------- #


class Adjustments(BaseModel):
    """Bounded numerics changes the diagnostician may propose (validated again by the backend)."""

    relax_U: float | None = Field(None, ge=0.1, le=0.9)
    relax_p: float | None = Field(None, ge=0.05, le=0.7)
    relax_h: float | None = Field(None, ge=0.1, le=0.95)
    relax_turbulence: float | None = Field(None, ge=0.1, le=0.9)
    div_scheme: str | None = Field(None, pattern="^(upwind|linearUpwind|limitedLinear)$")
    max_iterations: int | None = Field(None, ge=100, le=100_000)
    n_non_orthogonal_correctors: int | None = Field(None, ge=0, le=3)
    n_steps: int | None = Field(None, ge=10, le=1_000_000)
    rationale: str = Field("", description="One or two sentences explaining the change")
    give_up: bool = Field(
        False, description="True if no numerics change can plausibly fix the problem"
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in self.model_dump().items()
            if v is not None and k not in ("rationale", "give_up")
        }


class Critique(BaseModel):
    verdict: str = Field(..., pattern="^(accept|accept_with_warnings|reject)$")
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""


class ReviewFindings(BaseModel):
    """Additional pre-flight concerns an LLM reviewer may raise (it cannot remove rule findings)."""

    warnings: list[str] = Field(
        default_factory=list,
        description="Specific, actionable concerns about the specification not already listed",
    )


class Policy(Protocol):
    name: str

    def plan(self, task: str, hints: dict[str, Any] | None = None) -> SimulationSpec: ...

    def review(self, spec: SimulationSpec, findings: Any) -> list[str]: ...

    def diagnose(
        self,
        spec: SimulationSpec,
        report: ConvergenceReport,
        log_tail: str,
        current: dict[str, Any],
        attempt: int,
    ) -> Adjustments: ...

    def critique(self, spec: SimulationSpec, results: dict[str, Any]) -> Critique: ...


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #


def rules_diagnose(
    spec: SimulationSpec, report: ConvergenceReport, current: dict[str, Any], attempt: int
) -> Adjustments:
    """Deterministic diagnosis table (the fallback and the baseline for evals)."""
    if isinstance(spec.case, HeatedPipeCase):
        num = spec.case.numerics.model_dump()
        num.update(current)
        if report.diverged:
            if num["div_scheme"] != "upwind":
                return Adjustments(
                    div_scheme="upwind",
                    relax_U=round(min(num["relax_U"], 0.5), 3),
                    relax_p=round(min(num["relax_p"], 0.2), 3),
                    rationale="Divergence: switch convection to bounded upwind and tighten under-relaxation for the first stable solution.",
                )
            if num["relax_U"] > 0.15:
                return Adjustments(
                    relax_U=round(max(0.1, num["relax_U"] * 0.6), 3),
                    relax_p=round(max(0.05, num["relax_p"] * 0.6), 3),
                    relax_turbulence=round(max(0.1, num["relax_turbulence"] * 0.7), 3),
                    max_iterations=min(100_000, int(num["max_iterations"] * 1.5)),
                    rationale="Still diverging with upwind: reduce all under-relaxation factors and allow more iterations.",
                )
            return Adjustments(
                give_up=True,
                rationale="Divergence persists at minimum relaxation; likely a setup/mesh problem rather than numerics.",
            )
        if report.completed and not report.converged:
            adj = Adjustments(
                max_iterations=min(100_000, int(num["max_iterations"] * 2)),
                rationale="Run stalled above the residual target: double the iteration budget",
            )
            if report.bounding_events > 0:
                adj.relax_turbulence = round(max(0.1, num["relax_turbulence"] * 0.7), 3)
                adj.rationale += " and relax turbulence equations harder (bounding events seen)."
            return adj
        return Adjustments(
            give_up=True, rationale=f"Run failed before producing residuals: {report.reason}"
        )
    # FESTIM / other transient solvers: refine time stepping
    if report.diverged or not report.converged:
        n_steps = int(current.get("n_steps", getattr(spec.case, "n_steps", 400)))
        return Adjustments(
            n_steps=min(1_000_000, n_steps * 2),
            rationale="Non-linear solver trouble: halve the time step.",
        )
    return Adjustments(give_up=True, rationale=report.reason)


def rules_critique(spec: SimulationSpec, results: dict[str, Any]) -> Critique:
    """Physics sanity checks on the assembled results (the 'Fermi check')."""
    warnings: list[str] = []
    checks = results.get("qois", {}).get("checks", {})
    values = results.get("qois", {}).get("values", {})
    if abs(checks.get("energy_balance_error", 0.0)) > 0.02:
        warnings.append(
            f"energy balance error {checks['energy_balance_error'] * 100:.1f} % exceeds 2 %"
        )
    if abs(checks.get("mass_balance_error", 0.0)) > 0.01:
        warnings.append(
            f"mass balance error {checks['mass_balance_error'] * 100:.2f} % exceeds 1 %"
        )
    if "friction_factor_consistency" in checks and abs(checks["friction_factor_consistency"]) > 0.1:
        warnings.append("friction factor from dp/dx and from wall shear differ by more than 10 %")
    if isinstance(spec.case, HeatedPipeCase):
        yp = checks.get("yplus_avg", checks.get("yplus_avg_estimate"))
        if yp is not None and spec.case.turbulence_model.value != "laminar":
            if spec.case.wall_treatment.value == "resolved" and yp > 5:
                warnings.append(f"wall-resolved setup but average y+ = {yp:.1f} > 5")
            if spec.case.wall_treatment.value == "wall_function" and not (20 <= yp <= 300):
                warnings.append(f"wall-function setup but average y+ = {yp:.1f} outside 20-300")
        nu = values.get("Nu")
        if nu is not None and (not math.isfinite(nu) or nu <= 0):
            warnings.append("non-physical Nusselt number")
    if spec.case.kind == "ribbed_tube":
        frac = checks.get("reversed_flow_fraction_of_gap")
        reattach = checks.get("reattachment_x_over_e")
        if frac is not None and frac > 0.8 and spec.case.rib_pitch_over_height >= 6:
            warnings.append(
                f"no reattachment between ribs (reversed flow over {frac * 100:.0f} % of the gap): "
                f"p/e = {spec.case.rib_pitch_over_height:g} should give k-type roughness with reattachment at "
                f"~4-5 e; the closure ({spec.case.turbulence_model.value}) is probably over-predicting the "
                "separation bubble — compare with a k-epsilon family model"
            )
        elif reattach is not None and math.isfinite(reattach) and reattach > 0:
            pass  # attached region present: consistent with k-type roughness
    for q, v in results.get("verification", {}).get("gci", {}).items():
        if v.get("convergence") in ("oscillatory", "divergent"):
            warnings.append(f"grid convergence for {q} is {v['convergence']}")
        elif v.get("gci_fine") is not None and v["gci_fine"] > 0.05:
            warnings.append(
                f"numerical uncertainty (GCI) for {q} is {v['gci_fine'] * 100:.1f} % > 5 %"
            )
    if results.get("model_form"):
        from nuagent.agent.model_form import ensemble_warnings

        warnings.extend(ensemble_warnings(spec, results["model_form"]))
    failed = [
        q
        for q, r in results.get("validation", {}).get("results", {}).items()
        if not r.get("passed", True)
    ]
    if failed:
        warnings.append(f"validation failed for: {', '.join(failed)}")
    # A PASS against a correlation evaluated outside its stated validity range is not a validation.
    out_of_range = [
        f"{q} vs {r.get('source', '?')}"
        for q, r in results.get("validation", {}).get("results", {}).items()
        if "relative_error" in r and not r.get("reference_valid", True)
    ]
    if out_of_range:
        warnings.append(
            "reference correlation used outside its stated validity range for: "
            + ", ".join(out_of_range)
        )
    verdict = "accept" if not warnings else ("reject" if failed else "accept_with_warnings")
    return Critique(
        verdict=verdict,
        warnings=warnings,
        summary=f"{len(warnings)} warning(s) from rule-based review",
    )


class RulesPolicy:
    name = "rules"

    def plan(self, task: str, hints: dict[str, Any] | None = None) -> SimulationSpec:
        if hints and "spec" in hints:
            return SimulationSpec.model_validate(hints["spec"])
        raise ValueError(
            "RulesPolicy cannot plan from natural language; provide a spec (YAML/JSON) or use an LLM policy"
        )

    def review(self, spec, findings) -> list[str]:
        return []  # the deterministic findings are computed by nuagent.agent.preflight

    def diagnose(self, spec, report, log_tail, current, attempt) -> Adjustments:
        return rules_diagnose(spec, report, current, attempt)

    def critique(self, spec, results) -> Critique:
        return rules_critique(spec, results)


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #

PLAN_SYSTEM = """You are a senior nuclear thermal-hydraulics and fusion materials engineer configuring
simulations.  Convert the user's request into a SimulationSpec.  Rules:
- Choose physically consistent settings: Re < 2300 -> turbulence_model 'laminar'; Re > 4000 -> 'kOmegaSST'.
- Use the fluid presets when the user names a fluid (water_300K, air_300K, sodium_700K, PbLi_600K, unit_prandtl_liquid).
- Always request verification (mesh_study true) and at least one validation reference:
  laminar -> Nu 'laminar' and f 'laminar' (tolerance 0.02); turbulent -> Nu 'gnielinski' (0.15) and f 'petukhov' (0.10).
- For tritium permeation use backend 'festim' with references permeation_flux_ss/time_lag source 'analytical'.
- Names must be short identifiers (letters, digits, '-' or '_').
Do not invent data; if something is unspecified, use conservative engineering defaults and say so in 'description'."""

DIAGNOSE_SYSTEM = """You are debugging a steady RANS / diffusion simulation that did not converge.
Propose the smallest bounded change to the numerics (under-relaxation, convection scheme, iteration budget,
time steps).  Never change the physics.  Use the rule-based suggestion as a baseline and only deviate with a reason."""

CRITIQUE_SYSTEM = """You are reviewing a simulation report for physical plausibility (energy/mass balance, regime,
comparison against correlations within their uncertainty bands, mesh convergence, and — if a closure
ensemble was run — whether model-form or numerical uncertainty dominates).  Be concise and specific."""

REVIEW_SYSTEM = """You are an independent senior reviewer checking a thermal-fluids / hydrogen-transport simulation
specification BEFORE it is run (generator-verifier separation: you did not write this plan).  List additional,
specific concerns that the rule-based findings do not already cover: physical consistency (regime vs closure,
wall treatment vs target y+, boundary conditions), sufficiency of the domain (entry length, number of rib pitches),
validity of the chosen validation references, and whether the execution budget is plausible.  Return an empty
list if you have nothing to add.  Do not repeat the rule-based findings and do not invent data."""


class LLMPolicy:
    """LLM-backed decisions with rule-based fallbacks and schema validation."""

    name = "llm"

    def __init__(self, model=None, fallback: Policy | None = None):
        if model is None:
            from nuagent.agent.llm import get_chat_model

            model = get_chat_model()
        self.model = model
        self.fallback = fallback or RulesPolicy()

    def plan(self, task: str, hints: dict[str, Any] | None = None) -> SimulationSpec:
        if hints and "spec" in hints:
            return SimulationSpec.model_validate(hints["spec"])
        structured = self.model.with_structured_output(SimulationSpec)
        msg = task if not hints else f"{task}\n\nHints (JSON): {json.dumps(hints)}"
        spec = structured.invoke([("system", PLAN_SYSTEM), ("human", msg)])
        return SimulationSpec.model_validate(spec if isinstance(spec, dict) else spec.model_dump())

    def review(self, spec, findings) -> list[str]:
        """Add concerns to the deterministic pre-flight findings; failures fall back to none."""
        try:
            structured = self.model.with_structured_output(ReviewFindings)
            known = getattr(findings, "to_dict", lambda: findings)()
            out = structured.invoke(
                [
                    ("system", REVIEW_SYSTEM),
                    (
                        "human",
                        f"Specification: {spec.model_dump_json()}\n"
                        f"Rule-based findings: {json.dumps(known, default=str)}",
                    ),
                ]
            )
            out = out if isinstance(out, ReviewFindings) else ReviewFindings.model_validate(out)
            return [f"[llm] {w}" for w in out.warnings if w.strip()]
        except Exception:  # noqa: BLE001 - review must never break the workflow
            return []

    def diagnose(self, spec, report, log_tail, current, attempt) -> Adjustments:
        baseline = self.fallback.diagnose(spec, report, log_tail, current, attempt)
        try:
            structured = self.model.with_structured_output(Adjustments)
            prompt = (
                f"Case: {spec.case.model_dump_json()}\n"
                f"Current adjustments: {json.dumps(current)}\nAttempt: {attempt}\n"
                f"Convergence report: {json.dumps({k: v for k, v in report.to_dict().items() if k != 'residual_history'})}\n"
                f"Log tail:\n{log_tail[-3000:]}\n\nRule-based baseline: {baseline.model_dump_json()}"
            )
            out = structured.invoke([("system", DIAGNOSE_SYSTEM), ("human", prompt)])
            return out if isinstance(out, Adjustments) else Adjustments.model_validate(out)
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail the workflow
            baseline.rationale += (
                f" (LLM diagnosis unavailable: {type(exc).__name__}; rules applied)"
            )
            return baseline

    def critique(self, spec, results) -> Critique:
        rules = self.fallback.critique(spec, results)
        try:
            structured = self.model.with_structured_output(Critique)
            slim = {
                k: v
                for k, v in results.items()
                if k in ("qois", "verification", "validation", "convergence", "model_form")
            }
            if isinstance(slim.get("model_form"), dict):  # keep the prompt small: drop raw members
                slim["model_form"] = {k: v for k, v in slim["model_form"].items() if k != "members"}
            out = structured.invoke(
                [
                    ("system", CRITIQUE_SYSTEM),
                    (
                        "human",
                        f"Spec: {spec.model_dump_json()}\nResults: {json.dumps(slim, default=str)[:12000]}\n"
                        f"Rule-based warnings: {rules.warnings}",
                    ),
                ]
            )
            out = out if isinstance(out, Critique) else Critique.model_validate(out)
            # rules warnings are authoritative; the LLM may only add
            out.warnings = list(dict.fromkeys(rules.warnings + out.warnings))
            if rules.verdict == "reject":
                out.verdict = "reject"
            return out
        except Exception as exc:  # noqa: BLE001
            rules.summary += f" (LLM review unavailable: {type(exc).__name__})"
            return rules


def get_policy(name: str, model=None) -> Policy:
    if name == "rules":
        return RulesPolicy()
    if name == "llm":
        return LLMPolicy(model=model)
    raise ValueError(f"unknown policy {name!r}")
