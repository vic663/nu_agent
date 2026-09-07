#!/usr/bin/env python3
"""Solver-tolerance study for the FESTIM permeation verification case (needs FESTIM + dolfinx).

Runs the 1 mm tungsten / 600 K membrane at a fixed discretisation under three SNES tolerance
settings and reports, per setting, the steady flux and time lag with their errors against the exact
solution, the time lag the old trapezoidal extractor would have reported, and the SNES statistics
recorded by run_festim.py (zero-iteration steps = the solution stopped being updated).

    A  atol=1e10  rtol=1e-10   current runner defaults
    B  atol=1     rtol=1e-10   isolate the absolute tolerance
    C  atol=1     rtol=1e-12   tighten both

Reading the result:  A != B ~ C  -> the absolute tolerance is the culprit
                     A ~ B != C  -> the relative convergence criterion
                     A ~ B ~ C   -> look at SurfaceFlux / post-processing / the steady-flux estimator

Usage: python scripts/festim_tolerance_study.py --out runs/festim_study [--n-cells 200] [--n-steps 400]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from nuagent.backends.festim.backend import FESTIMBackend
from nuagent.physics import analytical
from nuagent.spec import PermeationCase, SimulationSpec

CASES = {
    "A": {"atol": 1e10, "rtol": 1e-10},
    "B": {"atol": 1.0, "rtol": 1e-10},
    "C": {"atol": 1.0, "rtol": 1e-12},
}
REASONS = {
    "2": "FNORM_ABS",
    "3": "FNORM_RELATIVE",
    "4": "SNORM_RELATIVE",
    "5": "ITS",
    "7": "STEP_LENGTH",
}


def run_case(label: str, adjustments: dict, out: Path, n_cells: int, n_steps: int) -> dict:
    spec = SimulationSpec(
        name=f"tolerance-study-{label}",
        backend="festim",
        case=PermeationCase(
            thickness=1e-3,
            temperature=600.0,
            upstream_concentration=1e20,
            n_cells=n_cells,
            n_steps=n_steps,
        ),
    )
    backend = FESTIMBackend()
    h = backend.build(spec, out / label, adjustments=adjustments)
    proc = subprocess.run(["bash", str(h.allrun)], capture_output=True, text=True, timeout=1800)
    row: dict = {"case": label, **adjustments, "returncode": proc.returncode}
    if proc.returncode != 0:
        row["error"] = (h.path / "log.festim").read_text()[-2000:]
        return row
    rep = backend.parse_log(h)
    q = backend.extract_qois(h, spec)
    D = analytical.arrhenius(4.1e-7, 0.39, 600.0)
    j_exact = analytical.permeation_steady_flux(D, 1e20, 1e-3)
    t_exact = analytical.permeation_time_lag(D, 1e-3)
    data = np.genfromtxt(h.path / "results.csv", delimiter=",", names=True)
    J = np.abs(data["flux_downstream"])
    j_ss = float(np.mean(J[int(0.9 * len(J)) :]))
    t_lag_trapezoid = float(np.trapezoid(j_ss - J, data["t"]) / j_ss)  # the pre-fix extractor
    info = json.loads((h.path / "run_info.json").read_text())
    snes = info.get("snes", {"available": False})
    row.update(
        {
            "converged": rep.converged,
            "festim_version": info.get("festim_version"),
            "J_ss": q.values["permeation_flux_ss"],
            "J_ss_error": q.values["permeation_flux_ss"] / j_exact - 1,
            "time_lag": q.values["time_lag"],
            "time_lag_error": q.values["time_lag"] / t_exact - 1,
            "time_lag_trapezoid": t_lag_trapezoid,
            "time_lag_trapezoid_error": t_lag_trapezoid / t_exact - 1,
            "t_lag_exact": t_exact,
            "snes": snes,
        }
    )
    if snes.get("available") and snes.get("first_zero_iteration_time") is not None:
        row["first_zero_iteration_in_time_lags"] = snes["first_zero_iteration_time"] / t_exact
    return row


def markdown(rows: list[dict], n_cells: int, n_steps: int) -> str:
    lines = [
        f"### FESTIM solver-tolerance study - {n_cells} cells / {n_steps} steps",
        "",
        "| case | atol | rtol | J_ss err | t_lag (right-endpoint) | err | t_lag (trapezoid, old) | err "
        "| SNES it. mean | zero-it. steps | first freeze [t_lag] | reasons |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("returncode", 1) != 0:
            lines.append(
                f"| {r['case']} | {r['atol']:g} | {r['rtol']:g} | FAILED (rc={r['returncode']}) |||||||||"
            )
            continue
        s = r["snes"]
        if s.get("available"):
            it = f"{s['iterations_mean']:.2f}"
            zero = str(s["zero_iteration_steps"])
            first = (
                f"{r['first_zero_iteration_in_time_lags']:.2f}"
                if "first_zero_iteration_in_time_lags" in r
                else "-"
            )
            reasons = ", ".join(
                f"{REASONS.get(k, k)}:{v}" for k, v in s["converged_reasons"].items()
            )
        else:
            it = zero = first = reasons = "n/a"
        lines.append(
            f"| {r['case']} | {r['atol']:g} | {r['rtol']:g} | {100 * r['J_ss_error']:+.3f} % "
            f"| {r['time_lag']:.2f} s | {100 * r['time_lag_error']:+.3f} % "
            f"| {r['time_lag_trapezoid']:.2f} s | {100 * r['time_lag_trapezoid_error']:+.3f} % "
            f"| {it} | {zero} | {first} | {reasons} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=Path("runs/festim_study"))
    ap.add_argument("--n-cells", type=int, default=200)
    ap.add_argument("--n-steps", type=int, default=400)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = [
        run_case(label, adj, args.out, args.n_cells, args.n_steps) for label, adj in CASES.items()
    ]
    table = markdown(rows, args.n_cells, args.n_steps)
    print(table)
    (args.out / "summary.md").write_text(table + "\n")
    (args.out / "summary.json").write_text(json.dumps(rows, indent=2))
    return 0 if all(r.get("returncode") == 0 for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
