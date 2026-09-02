"""Entry point of the mock "solver": ``python -m nuagent.backends.mock.simulate <case_dir>``.

Writes an OpenFOAM-style log (so the shared log parser is exercised) and a
``results.json`` with synthetic QoIs.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from nuagent.backends.mock.backend import _mock_values
from nuagent.spec import HeatedPipeCase, SimulationSpec


def _write_log(path: Path, n_iter: int, diverge: bool, converge: bool, fields: list[str]) -> None:
    lines = ["Starting time loop", ""]
    for it in range(1, n_iter + 1):
        lines.append(f"Time = {it}")
        lines.append("")
        for f in fields:
            if diverge and it > 40:
                res = "nan"
            else:
                res = f"{1.0 * math.exp(-it / 60.0):.6e}"
            lines.append(
                f"DILUPBiCGStab:  Solving for {f}, Initial residual = {res}, Final residual = {res}, No Iterations 1"
            )
        cont = "nan" if (diverge and it > 40) else f"{1e-3 * math.exp(-it / 60.0):.6e}"
        lines.append(
            f"time step continuity errors : sum local = {cont}, global = {cont}, cumulative = 0"
        )
        lines.append(f"ExecutionTime = {0.01 * it:.2f} s  ClockTime = {it // 100} s")
        lines.append("")
        if diverge and it > 45:
            lines.append(
                "--> FOAM FATAL ERROR: (mock) floating point exception — solution diverged"
            )
            break
        if converge and it >= 300:
            lines.append(f"\nSIMPLE solution converged in {it} iterations\n")
            break
    lines.append("End")
    path.write_text("\n".join(lines) + "\n")


def main(case_dir: Path) -> int:
    params = json.loads((case_dir / "params.json").read_text())
    spec = SimulationSpec.model_validate(params["spec"])
    h = params["h"]
    meta = params["meta"]
    case = spec.case

    diverge = False
    converge = True
    n_iter = 300
    fields = ["Ux", "Uy", "Uz", "h", "p_rgh"]
    if isinstance(case, HeatedPipeCase):
        numerics = meta["numerics"]
        turbulent = case.turbulence_model.value != "laminar"
        if turbulent:
            fields += ["k", "omega"]
        if turbulent and numerics["relax_U"] > 0.8:
            diverge = True
        if numerics["max_iterations"] < 500:
            converge = False
            n_iter = numerics["max_iterations"]
    _write_log(case_dir / "log.mock", n_iter, diverge, converge, fields)
    if diverge:
        return 1
    (case_dir / "results.json").write_text(json.dumps(_mock_values(spec, h, meta), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()))
