"""Workflow state shared by all nodes (JSON-serialisable for checkpointing)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class Decision(TypedDict, total=False):
    node: str
    message: str
    data: dict[str, Any]
    timestamp: float


class AgentState(TypedDict, total=False):
    # inputs
    task: str  # natural-language request (LLM planning) — optional if spec is given
    spec: dict[str, Any]  # SimulationSpec.model_dump(mode="json")
    workdir: str
    preflight: dict[str, Any]  # PreflightReview.to_dict(): warnings / blocking / notes
    # execution bookkeeping
    attempt: int
    adjustments: dict[str, Any]
    continue_case: bool  # extend the previous case from its latest time instead of rebuilding
    case: dict[str, Any]  # CaseHandle.to_dict()
    run: dict[str, Any]  # RunResult.to_dict()
    convergence: dict[str, Any]  # ConvergenceReport.to_dict()
    qois: dict[str, Any]  # QoIResult.to_dict()
    # V&V, calibration, UQ
    verification: dict[str, Any]
    model_form: dict[str, Any]  # closure-ensemble summary (model-form uncertainty)
    validation: dict[str, Any]
    calibration: dict[str, Any]
    uq: dict[str, Any]
    critique: dict[str, Any]
    # outputs
    report_path: str
    status: str  # planning | running | success | failed | needs_human
    error: str
    decisions: Annotated[list[Decision], operator.add]  # append-only decision log
    approved: bool


def decision(node: str, message: str, **data: Any) -> Decision:
    import time

    return Decision(node=node, message=message, data=data, timestamp=time.time())
