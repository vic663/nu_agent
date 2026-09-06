"""Parse OpenFOAM solver logs into a :class:`ConvergenceReport`.

Works for the SIMPLE-family solvers (``simpleFoam``, ``buoyantSimpleFoam``,
``rhoSimpleFoam``...) and, for the fields it recognises, PIMPLE solvers.  The
parser is regex-based and streaming so it can be run on partial logs while a
job is still executing.

The residual criterion is met in either of two ways:

1. the solver's own ``residualControl`` message ("SIMPLE solution converged");
2. NuAgent's criterion — the initial residuals of the *physically meaningful*
   fields (``ignore_fields`` excludes e.g. the azimuthal ``Uz`` component of an
   axisymmetric wedge, whose normalised residual is round-off noise) are below
   ``residual_target`` at the end of the log.

Meeting that criterion sets ``criterion_met``, which is the signal the live
monitor uses to ask a still-running solver to stop cleanly.  It is **not** the
verdict: ``converged`` additionally requires ``completed`` (an ``End`` marker or
a clean ``residualControl`` stop) and the absence of any fatal condition, and
the run node further requires a zero exit status.  A job killed by the OOM
killer or the scheduler can leave a log whose last written residuals sit under
target; without the ``completed`` term that is indistinguishable from success.
"""

from __future__ import annotations

import re
from pathlib import Path

from nuagent.backends.base import ConvergenceReport

_TIME_RE = re.compile(r"^Time = ([0-9.eE+-]+)\s*$")
_SOLVE_RE = re.compile(
    r"^(?P<solver>[\w:]+):\s+Solving for (?P<field>[\w.]+), Initial residual = (?P<init>[0-9.eE+-]+|nan|-nan|inf),"
    r" Final residual = (?P<final>[0-9.eE+-]+|nan|-nan|inf), No Iterations (?P<n>\d+)"
)
_CONT_RE = re.compile(
    r"time step continuity errors : sum local = (?P<local>[0-9.eE+-]+|nan|-nan|inf), global = (?P<global>[0-9.eE+-]+|nan|-nan)"
)
_BOUND_RE = re.compile(r"^bounding (?P<field>\w+),")
_CONVERGED_RE = re.compile(r"SIMPLE solution converged in ([0-9.eE+-]+) iterations")
_END_RE = re.compile(r"^End\s*$")
_FATAL_RE = re.compile(
    r"FOAM FATAL (IO )?ERROR|^Floating point exception|sigFpe::sigHandler|sigSegv::sigHandler"
    r"|Segmentation fault|^Aborted"
    # Out-of-band deaths: an MPI abort, an OOM kill or a scheduler kill leaves a log that ends
    # mid-run.  Without these the last residuals may sit below target and the run would be read
    # as converged.
    r"|MPI_ABORT|MPI_Abort|APPLICATION TERMINATED WITH THE EXIT STRING"
    r"|^Killed|Out of memory|std::bad_alloc|slurmstepd: error|DUE TO TIME LIMIT"
)

DEFAULT_IGNORE = ("Uz",)


def _to_float(s: str) -> float:
    try:
        return float(s)
    except ValueError:  # pragma: no cover
        return float("nan")


def parse_openfoam_log(
    text: str,
    residual_target: float | None = None,
    ignore_fields: tuple[str, ...] = DEFAULT_IGNORE,
    max_history: int = 400,
) -> ConvergenceReport:
    iterations = 0
    last_initial: dict[str, float] = {}
    history: dict[str, list[float]] = {}
    continuity: float | None = None
    bounding = 0
    solver_converged = False
    completed = False
    diverged = False
    reason = ""
    seen_this_iter: set[str] = set()

    for line in text.splitlines():
        m = _TIME_RE.match(line)
        if m:
            iterations = int(float(m.group(1)))
            seen_this_iter.clear()
            continue
        m = _SOLVE_RE.match(line)
        if m:
            field = m.group("field")
            init = _to_float(m.group("init"))
            if init != init or init == float("inf"):  # NaN / inf
                diverged, reason = (
                    True,
                    f"non-finite residual for {field} at iteration {iterations}",
                )
            if (
                field not in seen_this_iter
            ):  # first solve per iteration (e.g. before non-orthogonal correctors)
                seen_this_iter.add(field)
                last_initial[field] = init
                history.setdefault(field, []).append(init)
            continue
        m = _CONT_RE.search(line)
        if m:
            continuity = _to_float(m.group("local"))
            if continuity != continuity:
                diverged, reason = True, f"non-finite continuity error at iteration {iterations}"
            continue
        if _BOUND_RE.match(line):
            bounding += 1
            continue
        m = _CONVERGED_RE.search(line)
        if m:
            solver_converged = True
            iterations = int(float(m.group(1)))
            continue
        if _END_RE.match(line):
            completed = True
            continue
        if _FATAL_RE.search(line):
            diverged = True
            reason = reason or f"fatal error in log: {line.strip()[:120]}"

    # Residual explosion counts as divergence even without NaN
    for field, hist in history.items():
        if field in ignore_fields:
            continue
        if len(hist) > 20 and hist[-1] > 1e3 * max(min(hist), 1e-30) and hist[-1] > 1.0:
            diverged = True
            reason = reason or f"residual of {field} grew by >1e3 to {hist[-1]:.2e}"

    tracked = {k: v for k, v in last_initial.items() if k not in ignore_fields}
    residual_target_met = (
        bool(tracked)
        and residual_target is not None
        and all(v < residual_target for v in tracked.values())
    )
    if solver_converged and not completed:
        completed = True  # residualControl stops the run cleanly before 'End' in some versions
    # `criterion_met` is the live-stop signal; `converged` is the verdict and additionally
    # requires that the solver actually finished.  Without the `completed` term a run killed by
    # the scheduler or the OOM killer, whose last written residuals happen to sit under target,
    # is indistinguishable from a converged one.
    criterion_met = solver_converged or residual_target_met
    converged = criterion_met and completed and not diverged

    if not reason:
        if solver_converged:
            reason = f"solver residualControl satisfied after {iterations} iterations"
        elif criterion_met and not completed:
            reason = (
                f"residual target reached at iteration {iterations}, but the log has no End "
                "marker: the run was truncated (killed, timed out, or still running)"
            )
        elif criterion_met:
            worst = max(tracked.items(), key=lambda kv: kv[1])
            reason = (
                f"all tracked residuals below {residual_target:g} at iteration {iterations} "
                f"(worst {worst[0]}={worst[1]:.2e}; ignored: {', '.join(ignore_fields) or 'none'})"
            )
        elif completed:
            worst = max(tracked.items(), key=lambda kv: kv[1]) if tracked else ("?", float("nan"))
            reason = f"reached endTime after {iterations} iterations; worst residual {worst[0]}={worst[1]:.2e}"
        else:
            reason = f"log ends at iteration {iterations} without End marker (running or crashed)"

    decimated = {}
    for field, hist in history.items():
        step = max(1, len(hist) // max_history)
        decimated[field] = hist[::step]

    return ConvergenceReport(
        converged=converged,
        diverged=diverged,
        completed=completed,
        criterion_met=criterion_met,
        iterations=iterations,
        final_residuals=dict(last_initial),
        continuity_error=continuity,
        bounding_events=bounding,
        reason=reason,
        residual_history=decimated,
    )


def parse_log_file(path: Path, residual_target: float | None = None, **kwargs) -> ConvergenceReport:
    if not path.exists():
        return ConvergenceReport(False, False, False, 0, reason=f"log file {path.name} not found")
    return parse_openfoam_log(
        path.read_text(errors="replace"), residual_target=residual_target, **kwargs
    )


_SERIOUS_CHECKS = (
    "non-orthogonality",
    "skewness",
    "negative",
    "face pyramids",
    "concave",
    "closedness",
)


def parse_checkmesh(path: Path) -> dict:
    """Summarise ``checkMesh`` output: cell count, quality metrics and failed checks."""
    if not Path(path).exists():
        return {"available": False}
    text = Path(path).read_text(errors="replace")
    out: dict = {
        "available": True,
        "ok": "Mesh OK" in text,
        "failed_checks": [],
        "serious_failures": [],
    }
    m = re.search(r"cells:\s+(\d+)", text)
    if m:
        out["n_cells"] = int(m.group(1))
    m = re.search(r"Mesh non-orthogonality Max: ([0-9.eE+-]+) average: ([0-9.eE+-]+)", text)
    if m:
        out["max_non_orthogonality"] = float(m.group(1))
        out["avg_non_orthogonality"] = float(m.group(2))
    m = re.search(r"Max skewness = ([0-9.eE+-]+)", text)
    if m:
        out["max_skewness"] = float(m.group(1))
    m = re.search(r"Max aspect ratio = ([0-9.eE+-]+)", text)
    if m:
        out["max_aspect_ratio"] = float(m.group(1))
    for line in text.splitlines():
        if line.strip().startswith("***"):
            msg = line.strip().lstrip("*").strip()
            out["failed_checks"].append(msg)
            if any(k in msg.lower() for k in _SERIOUS_CHECKS):
                out["serious_failures"].append(msg)
    return out
