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
"""

from __future__ import annotations

import json
import time
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


def run_task(task: dict[str, Any], rt: Runtime, outdir: Path) -> dict[str, Any]:
    ref_spec = SimulationSpec.model_validate({**task["spec"], "backend": rt.backend.name})
    workdir = outdir / ref_spec.name
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
    return {
        "task": task["_file"],
        "status": result.get("status"),
        "attempts": result.get("attempt", 0),
        "validated": bool(result.get("validation", {}).get("passed")),
        "expected_ranges_ok": expected_ok,
        "gci_ok": gci_ok,
        "max_attempts_expected": expect.get("max_attempts"),
        "attempts_ok": (result.get("attempt", 0) <= expect["max_attempts"])
        if expect.get("max_attempts")
        else True,
        "plan_grade": plan_grade,
        "wall_time_s": wall,
        "error": result.get("error"),
        "report": result.get("report_path"),
    }


def run_suite(tasks_dir: Path, rt: Runtime, outdir: Path) -> dict[str, Any]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    rows = [run_task(t, rt, outdir) for t in load_tasks(tasks_dir)]
    n = len(rows) or 1
    success = [
        r["status"] in ("success", "completed_with_issues")
        and r["expected_ranges_ok"]
        and r["attempts_ok"]
        for r in rows
    ]
    scoreboard = {
        "backend": rt.backend.name,
        "policy": rt.policy.name,
        "n_tasks": len(rows),
        "success_rate": sum(success) / n,
        "validation_rate": sum(r["validated"] for r in rows) / n,
        "gci_rate": sum(r["gci_ok"] for r in rows) / n,
        "mean_attempts": sum(r["attempts"] for r in rows) / n,
        "mean_plan_score": (
            sum(r["plan_grade"]["score"] for r in rows if r["plan_grade"])
            / max(1, sum(1 for r in rows if r["plan_grade"]))
        )
        if any(r["plan_grade"] for r in rows)
        else None,
        "tasks": rows,
    }
    (outdir / "scoreboard.json").write_text(json.dumps(scoreboard, indent=2, default=str))
    return scoreboard
