"""Agent qualification suite.

A *task* is a YAML file with a natural-language ``task`` (for LLM planning), a
reference ``spec`` (for the deterministic policy and for grading the plan),
and ``expect`` criteria.  Running the suite produces a scoreboard that
answers the questions a code-qualification reviewer would ask about an agent:

* did it produce a converged solution?  in how many attempts?
* did the result pass validation against the known reference?
* was the grid-convergence study in the asymptotic range?
* (LLM policies) did the plan reproduce the essential physics choices, and
  how many proposals were rejected by the validators?
* **how reliable is it?** — with ``repeats > 1`` every task is run several
  times and the τ-bench ``pass^k`` statistic (Yao et al. 2024, arXiv:2406.12045)
  is reported: the probability that *all* of ``k`` independent trials succeed.
  A stochastic planner that succeeds 80 % of the time has pass^1 = 0.8 but
  pass^5 ≈ 0.33; an engineering workflow needs pass^k to stay flat.
"""

from __future__ import annotations

import json
import statistics
import time
from math import comb
from pathlib import Path
from typing import Any

import yaml

from nuagent.agent.graph import run_workflow
from nuagent.agent.nodes import Runtime
from nuagent.spec import SimulationSpec


def load_tasks(directory: Path) -> list[dict[str, Any]]:
    tasks = []
    for f in sorted(Path(directory).glob("*.yaml")):
        d = yaml.safe_load(f.read_text())
        d["_file"] = f.name
        tasks.append(d)
    return tasks


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Unbiased estimate of pass^k from ``c`` successes in ``n`` i.i.d. trials (τ-bench, eq. 1).

    ``pass^k = C(c, k) / C(n, k)`` — the probability that ``k`` trials drawn without replacement
    from the observed ones are all successes.  pass^1 is the ordinary success rate.
    """
    if not 1 <= k <= n:
        raise ValueError(f"k must be between 1 and n={n}, got {k}")
    return comb(c, k) / comb(n, k)


def grade_plan(planned: SimulationSpec, reference: SimulationSpec) -> dict[str, Any]:
    """Compare essential physics choices of an LLM plan with the reference spec."""
    checks = {
        "backend": planned.backend == reference.backend,
        "case_kind": planned.case.kind == reference.case.kind,
    }
    if planned.case.kind == reference.case.kind and planned.case.kind in (
        "heated_pipe",
        "ribbed_tube",
    ):
        checks["regime"] = planned.case.regime == reference.case.regime
        checks["turbulence_model"] = (
            planned.case.turbulence_model == reference.case.turbulence_model
        )
        checks["reynolds_within_5pct"] = (
            abs(planned.case.reynolds - reference.case.reynolds) / reference.case.reynolds < 0.05
        )
    checks["has_validation_reference"] = bool(planned.validation.references)
    return {"checks": checks, "score": sum(checks.values()) / len(checks)}


def task_success(row: dict[str, Any]) -> bool:
    """Did the agent do the right thing on this task?

    For an ordinary task that means producing a converged, in-range solution.  For a **negative
    control** (``expect.outcome: fail``) it means the opposite: the workflow had to *detect* a
    deliberately defective set-up rather than return a confident answer.  A qualification suite
    whose only possible outcome is "pass" qualifies nothing, so the two are graded together.
    """
    expect = row.get("expect") or {}
    if expect.get("outcome") == "fail":
        if expect.get("blocked_by_preflight") and not row.get("blocked_by_preflight"):
            return False
        if expect.get("validation_passed") is False and row.get("validated"):
            return False
        if (
            expect.get("critique_verdict")
            and row.get("critique_verdict") != expect["critique_verdict"]
        ):
            return False
        # the defect must have been caught somewhere: a block, a failed validation, or a rejection
        return bool(
            row.get("blocked_by_preflight")
            or not row.get("validated")
            or row.get("critique_verdict") == "reject"
            or row["status"] == "failed"
        )
    return bool(
        row["status"] in ("success", "completed_with_issues")
        and row["expected_ranges_ok"]
        and row["attempts_ok"]
    )


def run_task(task: dict[str, Any], rt: Runtime, outdir: Path, repeat: int = 0) -> dict[str, Any]:
    ref_spec = SimulationSpec.model_validate({**task["spec"], "backend": rt.backend.name})
    workdir = outdir / (ref_spec.name if repeat == 0 else f"{ref_spec.name}_rep{repeat}")
    t0 = time.time()
    plan_grade = None
    if rt.policy.name == "llm" and task.get("task"):
        try:
            planned = rt.policy.plan(task["task"], hints={"backend": rt.backend.name})
            plan_grade = grade_plan(planned, ref_spec)
            spec_to_run = SimulationSpec.model_validate(
                {**planned.model_dump(mode="json"), "backend": rt.backend.name}
            )
        except Exception as exc:  # noqa: BLE001
            plan_grade = {"error": str(exc), "score": 0.0}
            spec_to_run = ref_spec
    else:
        spec_to_run = ref_spec
    result = run_workflow(
        rt, spec=spec_to_run.model_dump(mode="json"), workdir=str(workdir), auto_approve=True
    )
    wall = time.time() - t0
    expect = task.get("expect", {})
    qois = result.get("qois", {}).get("values", {})
    expected_ok = (
        all(
            lo <= qois.get(q, float("nan")) <= hi
            for q, (lo, hi) in expect.get("qoi_ranges", {}).items()
        )
        if expect.get("qoi_ranges")
        else True
    )
    gci = result.get("verification", {}).get("gci", {})
    gci_ok = bool(gci) and all(g.get("convergence") == "monotonic" for g in gci.values())
    critique = result.get("critique", {}) or {}
    preflight = result.get("preflight") or {}
    row = {
        "task": task["_file"],
        "repeat": repeat,
        "expect": expect,
        "negative_control": expect.get("outcome") == "fail",
        "blocked_by_preflight": bool(preflight.get("blocking")),
        "status": result.get("status"),
        "attempts": result.get("attempt", 0),
        "validated": bool(result.get("validation", {}).get("passed")),
        "expected_ranges_ok": expected_ok,
        "gci_ok": gci_ok,
        "max_attempts_expected": expect.get("max_attempts"),
        "attempts_ok": (result.get("attempt", 0) <= expect["max_attempts"])
        if expect.get("max_attempts")
        else True,
        "preflight_warnings": len(preflight.get("warnings", [])),
        "preflight_blocking": list(preflight.get("blocking", [])),
        "critique_verdict": critique.get("verdict"),
        "expected_warning_found": (
            any(expect["critique_warning_contains"] in w for w in critique.get("warnings", []))
            if expect.get("critique_warning_contains")
            else None
        ),
        "plan_grade": plan_grade,
        "wall_time_s": wall,
        "error": result.get("error"),
        "report": result.get("report_path"),
    }
    row["success"] = task_success(row) and row["expected_warning_found"] is not False
    return row


def run_suite(tasks_dir: Path, rt: Runtime, outdir: Path, repeats: int = 1) -> dict[str, Any]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    repeats = max(1, int(repeats))
    tasks = load_tasks(tasks_dir)
    rows = [run_task(t, rt, outdir, repeat=i) for t in tasks for i in range(repeats)]
    n = len(rows) or 1
    per_task: list[dict[str, Any]] = []
    for t in tasks:
        trials = [r for r in rows if r["task"] == t["_file"]]
        c = sum(r["success"] for r in trials)
        attempts = [r["attempts"] for r in trials]
        per_task.append(
            {
                "task": t["_file"],
                "n_trials": len(trials),
                "n_success": c,
                "pass_hat_k": {k: pass_hat_k(len(trials), c, k) for k in range(1, len(trials) + 1)},
                "mean_attempts": statistics.fmean(attempts) if attempts else None,
                "attempts_stdev": statistics.pstdev(attempts) if len(attempts) > 1 else 0.0,
                "validated_rate": sum(r["validated"] for r in trials) / max(1, len(trials)),
            }
        )
    pass_k = {
        k: statistics.fmean(pt["pass_hat_k"][k] for pt in per_task) if per_task else 0.0
        for k in range(1, repeats + 1)
    }
    scoreboard = {
        "backend": rt.backend.name,
        "policy": rt.policy.name,
        "n_tasks": len(tasks),
        "repeats": repeats,
        "n_runs": len(rows),
        "success_rate": sum(r["success"] for r in rows) / n,
        "validation_rate": sum(r["validated"] for r in rows) / n,
        "gci_rate": sum(r["gci_ok"] for r in rows) / n,
        "mean_attempts": sum(r["attempts"] for r in rows) / n,
        "pass_hat_k": pass_k,
        "mean_plan_score": (
            sum(r["plan_grade"]["score"] for r in rows if r["plan_grade"])
            / max(1, sum(1 for r in rows if r["plan_grade"]))
        )
        if any(r["plan_grade"] for r in rows)
        else None,
        "per_task": per_task,
        "tasks": rows,
    }
    (outdir / "scoreboard.json").write_text(json.dumps(scoreboard, indent=2, default=str))
    return scoreboard
