"""Command-line interface.

Examples
--------
::

    # deterministic (no LLM): run a specification end to end
    nuagent run examples/heated_pipe/laminar_verification.yaml --backend openfoam

    # natural-language planning with an LLM, then the same deterministic pipeline
    nuagent ask "Turbulent water flow in a 20 mm pipe at Re=20000 with 50 kW/m2 wall heating; validate Nu and f"

    # dry run: generate the case files only
    nuagent build examples/heated_pipe/turbulent_validation.yaml --out runs/turb

    # agent qualification suite
    nuagent eval evals/tasks --backend mock --policy rules
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from nuagent import __version__

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="NuAgent — agentic V&V workflow for convective heat-transfer and transport simulations",
)
console = Console()


LLM_HELP = (
    "No usable LLM configured. The deterministic workflow needs none (default --policy rules). "
    "For --policy llm / `nuagent ask`, set one of:\n"
    "  ANTHROPIC_API_KEY=...                       (default model anthropic:claude-sonnet-4-5)\n"
    "  OPENAI_API_KEY=...  --model openai:gpt-4o\n"
    "  OPENAI_BASE_URL=http://localhost:11434/v1 --model openai:<local model>   (Ollama / vLLM, no key)\n"
    "and install the provider extra, e.g. pip install 'nuagent[anthropic]' or 'nuagent[openai]'."
)


def _runtime(backend: str, executor: str, policy: str, model: str | None):
    from nuagent.agent import Runtime, get_policy
    from nuagent.backends import get_backend
    from nuagent.executors import get_executor

    if model:  # must be set before the LLM policy builds its chat model
        os.environ["NUAGENT_LLM_MODEL"] = model
    try:
        pol = get_policy(policy, model=None)
    except Exception as exc:  # noqa: BLE001 - missing provider package / credentials
        console.print(f"[red]{type(exc).__name__}: {exc}[/]\n")
        console.print(LLM_HELP, markup=False)
        raise typer.Exit(2) from None
    return Runtime(backend=get_backend(backend), executor=get_executor(executor), policy=pol)


def _print_summary(result: Mapping[str, Any]) -> None:
    status = result.get("status", "?")
    color = {
        "success": "green",
        "completed_with_issues": "yellow",
        "failed": "red",
        "needs_human": "magenta",
    }.get(status, "white")
    console.print(f"\n[bold {color}]Status: {status}[/]")
    if result.get("error"):
        console.print(f"[red]{result['error']}[/]")
    qois = result.get("qois", {}).get("values", {})
    if qois:
        t = Table(title="Quantities of interest")
        t.add_column("QoI")
        t.add_column("value", justify="right")
        for k, v in qois.items():
            t.add_row(k, f"{v:.5g}" if isinstance(v, float) else str(v))
        console.print(t)
    val = result.get("validation", {}).get("results", {})
    if val:
        t = Table(title="Validation")
        for c in ("QoI", "computed", "reference", "source", "deviation", "result"):
            t.add_column(c)
        for q, r in val.items():
            if "relative_error" in r:
                t.add_row(
                    q,
                    f"{r['value']:.4g}",
                    f"{r['reference']:.4g}",
                    r["source"],
                    f"{100 * r['relative_error']:+.1f} %",
                    "[green]PASS[/]" if r["passed"] else "[red]FAIL[/]",
                )
            else:
                t.add_row(q, "-", "-", "-", "-", f"[red]{r.get('error')}[/]")
        console.print(t)
    gci = result.get("verification", {}).get("gci", {})
    if gci:
        t = Table(title="Grid convergence (GCI)")
        for c in ("QoI", "observed order", "extrapolated", "GCI fine", "convergence"):
            t.add_column(c)
        for q, g in gci.items():
            t.add_row(
                q,
                f"{g['observed_order']:.2f}" if g["observed_order"] else "-",
                f"{g['extrapolated']:.5g}" if g["extrapolated"] else "-",
                f"{100 * g['gci_fine']:.2f} %" if g["gci_fine"] is not None else "-",
                g["convergence"],
            )
        console.print(t)
    crit = result.get("critique", {})
    if crit:
        console.print(
            f"Review: [bold]{crit.get('verdict')}[/] — " + "; ".join(crit.get("warnings", [])[:5])
        )
    if result.get("report_path"):
        console.print(f"Report: [cyan]{result['report_path']}[/]")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"nuagent {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", help="Show version and exit", callback=_version_callback, is_eager=True
    ),
):
    """NuAgent command-line interface."""


@app.command()
def run(
    spec: Path = typer.Argument(..., exists=True, help="Simulation spec (YAML/JSON)"),
    backend: str | None = typer.Option(None, help="Override backend: openfoam | festim | mock"),
    executor: str | None = typer.Option(None, help="Override executor: local | docker | slurm"),
    policy: str = typer.Option("rules", help="Decision policy: rules | llm"),
    model: str | None = typer.Option(
        None, help="LLM (provider:model), e.g. anthropic:claude-sonnet-4-5"
    ),
    workdir: Path | None = typer.Option(None, help="Run directory (default runs/<name>)"),
    auto_approve: bool = typer.Option(False, help="Approve HPC submissions without pausing"),
):
    """Run the full workflow (plan → build → run → monitor → verify → validate → report) on a spec."""
    import yaml

    from nuagent.agent import run_workflow
    from nuagent.spec import SimulationSpec

    raw = yaml.safe_load(Path(spec).read_text())
    if isinstance(raw, dict) and "spec" in raw and "case" not in raw:
        raw = raw["spec"]  # an eval task file: run its reference specification
    if backend:
        raw["backend"] = backend
    if executor:
        raw.setdefault("execution", {})["executor"] = executor
    s = SimulationSpec.model_validate(raw)
    rt = _runtime(s.backend.value, s.execution.executor.value, policy, model)
    console.print(
        f"[bold]NuAgent {__version__}[/] — {s.name} | backend={s.backend.value} executor={s.execution.executor.value} policy={policy}"
    )
    result = run_workflow(
        rt,
        spec=s.model_dump(mode="json"),
        workdir=str(workdir) if workdir else None,
        auto_approve=auto_approve,
    )
    _print_summary(result)
    # 0 only for a validated result; 2 distinguishes "ran, but V&V did not clear it" from a hard
    # failure, so a CI job or a shell script cannot treat an unvalidated run as a good one.
    raise typer.Exit({"success": 0, "completed_with_issues": 2}.get(result.get("status"), 1))


@app.command()
def ask(
    task: str = typer.Argument(..., help="Engineering question in natural language"),
    backend: str = typer.Option("openfoam", help="openfoam | festim | mock"),
    executor: str = typer.Option("local"),
    model: str | None = typer.Option(None, help="LLM (provider:model)"),
    workdir: Path | None = typer.Option(None),
    plan_only: bool = typer.Option(False, help="Only produce the specification, do not run"),
):
    """Plan a simulation from natural language with an LLM, then run the deterministic pipeline."""
    from nuagent.agent import run_workflow

    rt = _runtime(backend, executor, "llm", model)
    try:
        if plan_only:
            spec = rt.policy.plan(task)
            console.print_json(spec.model_dump_json(indent=2))
            raise typer.Exit()
        result = run_workflow(rt, task=task, workdir=str(workdir) if workdir else None)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - authentication / network errors from the provider
        console.print(f"[red]{type(exc).__name__}: {str(exc)[:400]}[/]\n")
        console.print(LLM_HELP, markup=False)
        raise typer.Exit(2) from None
    _print_summary(result)


@app.command()
def build(
    spec: Path = typer.Argument(..., exists=True),
    out: Path = typer.Option(Path("case"), help="Output case directory"),
    backend: str | None = typer.Option(None),
    refinement: float = typer.Option(1.0, help="Mesh refinement factor"),
):
    """Generate the solver input files for a spec without running (dry run / inspection)."""
    from nuagent.backends import get_backend
    from nuagent.spec import SimulationSpec

    s = SimulationSpec.from_yaml(spec)
    b = get_backend(backend or s.backend.value)
    handle = b.build(s, out, refinement=refinement)
    console.print(
        f"case written to [cyan]{handle.path}[/] ({handle.n_cells} cells, h={handle.representative_h:.3e} m)"
    )
    for f in sorted(p for p in handle.path.rglob("*") if p.is_file()):
        console.print(f"  {f.relative_to(handle.path)}")


@app.command()
def calibrate(
    spec: Path = typer.Argument(..., exists=True),
    out: Path = typer.Option(Path("runs/calibration")),
):
    """Run only the Bayesian-calibration block of a spec."""
    from nuagent.calibration.workflow import run_calibration_for_spec
    from nuagent.spec import SimulationSpec

    s = SimulationSpec.from_yaml(spec)
    if s.calibration is None:
        console.print("[red]spec has no 'calibration' section[/]")
        raise typer.Exit(2)
    res = run_calibration_for_spec(s, out)
    console.print(res["summary_markdown"])


@app.command()
def uq(spec: Path = typer.Argument(..., exists=True), out: Path = typer.Option(Path("runs/uq"))):
    """Run only the UQ / sensitivity block of a spec."""
    from nuagent.spec import SimulationSpec
    from nuagent.uq.workflow import run_uq_for_spec

    s = SimulationSpec.from_yaml(spec)
    if s.uq is None:
        console.print("[red]spec has no 'uq' section[/]")
        raise typer.Exit(2)
    res = run_uq_for_spec(s, out)
    console.print(res["summary_markdown"])


@app.command("eval")
def eval_cmd(
    tasks: Path = typer.Argument(Path("evals/tasks"), help="Directory of task YAML files"),
    backend: str = typer.Option("mock"),
    policy: str = typer.Option("rules"),
    model: str | None = typer.Option(None),
    out: Path = typer.Option(Path("runs/evals")),
    repeats: int = typer.Option(
        1, min=1, help="Independent trials per task; reports pass^k reliability (τ-bench)"
    ),
):
    """Agent qualification: run the task suite and score success, retries, V&V outcomes, pass^k."""
    from nuagent.evals.harness import run_suite

    rt = _runtime(backend, "local", policy, model)
    scoreboard = run_suite(tasks, rt, out, repeats=repeats)
    t = Table(title=f"Eval suite — backend={backend} policy={policy} repeats={repeats}")
    for c in (
        "task",
        "kind",
        "rep",
        "status",
        "attempts",
        "validated",
        "GCI ok",
        "review",
        "ok?",
        "wall [s]",
    ):
        t.add_column(c)
    n_neg = 0
    for r in scoreboard["tasks"]:
        neg = r.get("negative_control")
        n_neg += bool(neg)
        t.add_row(
            r["task"],
            "[yellow]neg. control[/]" if neg else "normal",
            str(r["repeat"]),
            r["status"],
            str(r["attempts"]),
            "yes" if r["validated"] else "no",
            "yes" if r["gci_ok"] else "no",
            str(r.get("critique_verdict") or "-"),
            "[green]PASS[/]" if r.get("success") else "[red]FAIL[/]",
            f"{r['wall_time_s']:.1f}",
        )
    console.print(t)
    console.print(
        f"agent behaved correctly on: [bold]{scoreboard['success_rate']:.0%}[/] of tasks  "
        f"(validated: {scoreboard['validation_rate']:.0%}  mean attempts: {scoreboard['mean_attempts']:.2f})"
    )
    if n_neg:
        console.print(
            f"[dim]{n_neg} of {len(scoreboard['tasks'])} task(s) are negative controls: a defective "
            "set-up that the workflow is required to refuse. For those, 'failed'/'not validated' is "
            "the correct outcome, and the 'ok?' column is the grade.[/]"
        )
    else:
        console.print(
            "[yellow]no negative controls in this suite: a success rate measured only on tasks that "
            "are supposed to succeed cannot detect a wrong answer.[/]"
        )
    if repeats > 1:
        console.print(
            "pass^k: " + "  ".join(f"k={k}: {v:.2f}" for k, v in scoreboard["pass_hat_k"].items())
        )
    console.print(f"scoreboard: {out / 'scoreboard.json'}")


@app.command()
def report(run_dir: Path = typer.Argument(..., exists=True)):
    """Re-render the Markdown report from a finished run directory."""
    from nuagent.reporting.report import write_report
    from nuagent.spec import SimulationSpec

    state = json.loads((run_dir / "result.json").read_text())
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    state["decisions"] = decisions
    spec = SimulationSpec.from_yaml(run_dir / "spec.yaml")
    path = write_report(spec, state, run_dir, status=state.get("status", "unknown"))
    console.print(f"report written to [cyan]{path}[/]")


@app.command()
def doctor():
    """Check which solvers, executors and LLM providers are available on this machine."""
    import shutil

    from nuagent.backends import get_backend
    from nuagent.backends.openfoam.backend import find_foam_bashrc

    t = Table(title="NuAgent environment")
    t.add_column("component")
    t.add_column("status")
    t.add_row(
        "OpenFOAM",
        f"[green]{find_foam_bashrc()}[/]"
        if get_backend("openfoam").available()
        else "[red]not found[/] (set NUAGENT_FOAM_BASHRC or use --executor docker)",
    )
    t.add_row(
        "FESTIM",
        "[green]importable[/]"
        if get_backend("festim").available()
        else "[yellow]not importable[/] (use conda env / docker image nuagent-festim)",
    )
    t.add_row("Docker", "[green]found[/]" if shutil.which("docker") else "[yellow]not found[/]")
    t.add_row(
        "SLURM", "[green]sbatch found[/]" if shutil.which("sbatch") else "[yellow]not found[/]"
    )
    t.add_row("mpirun", "[green]found[/]" if shutil.which("mpirun") else "[yellow]not found[/]")
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "NUAGENT_LLM_MODEL"):
        t.add_row(var, "[green]set[/]" if os.environ.get(var) else "[dim]unset[/]")
    console.print(t)


if __name__ == "__main__":  # pragma: no cover
    app()
