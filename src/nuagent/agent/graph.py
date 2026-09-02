"""The NuAgent workflow graph (LangGraph).

::

    plan -> review -> build -> approve -> run -> monitor --(converged)--> postprocess -> verify
              |         ^                          |                                        |
        (blocking)      |                  (diverged / stalled)                             v
              |         +--------------- diagnose  (bounded retries)                  model_form
              |                                                                             |
              v                                                                             v
            report <---- critique <---- uq <---- calibrate <---- validate <-----------------+
              |
             END          (any hard failure routes straight to report)

Routing decisions are made from the state written by deterministic nodes;
the only LLM-influenced nodes are ``plan``, ``review`` (may add warnings), ``diagnose`` and
``critique`` (see :mod:`nuagent.agent.policy`).  ``review`` is an independent *verifier* of the
plan (generator–verifier separation); ``model_form`` fans identical solver jobs out over
alternative turbulence closures (orchestrator–workers) and reduces them deterministically.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from nuagent.agent.nodes import Runtime, make_nodes
from nuagent.agent.state import AgentState


def _after_plan(state: AgentState) -> str:
    return "report" if state.get("status") == "failed" else "review"


def _after_review(state: AgentState) -> str:
    return "report" if state.get("status") == "failed" else "build"


def _after_build(state: AgentState) -> str:
    return "report" if state.get("status") == "failed" else "approve"


def _after_approve(state: AgentState) -> str:
    spec = state.get("spec", {})
    if spec.get("execution", {}).get("require_approval") and not state.get("approved"):
        return "report"
    return "run"


def _after_monitor(state: AgentState) -> str:
    conv = state.get("convergence", {})
    if conv.get("converged"):
        return "postprocess"
    return "diagnose"


def _after_diagnose(state: AgentState) -> str:
    return "report" if state.get("status") == "failed" else "build"


def _after_postprocess(state: AgentState) -> str:
    return "report" if state.get("status") == "failed" else "verify"


def build_graph(runtime: Runtime, checkpointer: Any | None = None, with_checkpointer: bool = False):
    nodes = make_nodes(runtime)
    g = StateGraph(AgentState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", _after_plan, {"review": "review", "report": "report"})
    g.add_conditional_edges("review", _after_review, {"build": "build", "report": "report"})
    g.add_conditional_edges("build", _after_build, {"approve": "approve", "report": "report"})
    g.add_conditional_edges("approve", _after_approve, {"run": "run", "report": "report"})
    g.add_edge("run", "monitor")
    g.add_conditional_edges(
        "monitor", _after_monitor, {"postprocess": "postprocess", "diagnose": "diagnose"}
    )
    g.add_conditional_edges("diagnose", _after_diagnose, {"build": "build", "report": "report"})
    g.add_conditional_edges(
        "postprocess", _after_postprocess, {"verify": "verify", "report": "report"}
    )
    g.add_edge("verify", "model_form")
    g.add_edge("model_form", "validate")
    g.add_edge("validate", "calibrate")
    g.add_edge("calibrate", "uq")
    g.add_edge("uq", "critique")
    g.add_edge("critique", "report")
    g.add_edge("report", END)
    if checkpointer is None and with_checkpointer:
        checkpointer = InMemorySaver()
    return g.compile(checkpointer=checkpointer)


def run_workflow(
    runtime: Runtime,
    spec: dict[str, Any] | None = None,
    task: str | None = None,
    workdir: str | None = None,
    thread_id: str = "nuagent",
    auto_approve: bool = False,
) -> AgentState:
    """Convenience wrapper: run the graph to completion (resuming through approvals if ``auto_approve``)."""
    from langgraph.types import Command

    needs_ckpt = bool(spec and spec.get("execution", {}).get("require_approval"))
    graph = build_graph(runtime, with_checkpointer=needs_ckpt)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    inputs: dict[str, Any] = {"decisions": []}
    if spec is not None:
        inputs["spec"] = spec
    if task:
        inputs["task"] = task
    if workdir:
        inputs["workdir"] = workdir
    result = graph.invoke(inputs, config=config)
    while "__interrupt__" in result:
        if not auto_approve:
            result["status"] = "needs_human"
            return result
        result = graph.invoke(Command(resume="yes"), config=config)
    return result
