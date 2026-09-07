#!/usr/bin/env python3
"""Standalone FESTIM 2.x runner (copied into each case directory by NuAgent).

Reads ``params.json`` written by :class:`nuagent.backends.festim.backend.FESTIMBackend`,
builds the FESTIM model, runs it and writes

* ``results.csv``   — time series of the exported quantities
* ``run_info.json`` — status, timings, solver statistics

The script deliberately depends only on ``festim``, ``numpy`` and the standard
library so that it can run inside the FESTIM conda environment or the
``dolfinx/dolfinx`` container, separate from the agent's Python environment.

Tested against the FESTIM 2.1 API (``festim.HydrogenTransportProblem``).
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

K_B = 8.617333262e-5  # eV/K


def build_permeation(p: dict):
    import festim as F

    L = p["thickness"]
    n = int(p["n_cells"])
    mesh = F.Mesh1D(np.linspace(0.0, L, n + 1))
    mat = F.Material(D_0=p["material"]["D_0"], E_D=p["material"]["E_D"], name=p["material"]["name"])
    vol = F.VolumeSubdomain1D(id=1, borders=[0.0, L], material=mat)
    upstream = F.SurfaceSubdomain1D(id=1, x=0.0)
    downstream = F.SurfaceSubdomain1D(id=2, x=L)
    mobile = F.Species("H")

    model = F.HydrogenTransportProblem(
        mesh=mesh,
        subdomains=[vol, upstream, downstream],
        species=[mobile],
        temperature=float(p["temperature"]),
    )
    model.boundary_conditions = [
        F.FixedConcentrationBC(
            subdomain=upstream, value=float(p["upstream_concentration"]), species=mobile
        ),
        F.FixedConcentrationBC(subdomain=downstream, value=0.0, species=mobile),
    ]
    model.traps = [
        F.Trap(
            name=tr["name"],
            mobile_species=mobile,
            k_0=tr["k_0"],
            E_k=tr["E_k"],
            p_0=tr["p_0"],
            E_p=tr["E_p"],
            n=tr["n"],
            volume=vol,
        )
        for tr in p.get("traps", [])
    ]
    flux_down = F.SurfaceFlux(field=mobile, surface=downstream)
    flux_up = F.SurfaceFlux(field=mobile, surface=upstream)
    inventory = F.TotalVolume(field=mobile, volume=vol)
    model.exports = [flux_down, flux_up, inventory]

    dt = p["final_time"] / p["n_steps"]
    model.settings = F.Settings(
        atol=p.get("atol", 1e10),
        rtol=p.get("rtol", 1e-10),
        max_iterations=30,
        final_time=p["final_time"],
        stepsize=F.Stepsize(initial_value=dt),
    )
    exports = {
        "flux_downstream": flux_down,
        "flux_upstream": flux_up,
        "mobile_inventory": inventory,
    }
    return model, exports


def build_tds(p: dict):
    import festim as F

    L = p["thickness"]
    n = int(p["n_cells"])
    # refine near the implanted surface
    x_fine = np.linspace(0.0, 20.0 * p["implantation_range"], n // 2 + 1)
    x_coarse = np.linspace(20.0 * p["implantation_range"], L, n - n // 2 + 1)
    mesh = F.Mesh1D(np.unique(np.concatenate([x_fine, x_coarse])))
    mat = F.Material(D_0=p["material"]["D_0"], E_D=p["material"]["E_D"], name=p["material"]["name"])
    vol = F.VolumeSubdomain1D(id=1, borders=[0.0, L], material=mat)
    left = F.SurfaceSubdomain1D(id=1, x=0.0)
    right = F.SurfaceSubdomain1D(id=2, x=L)
    mobile = F.Species("H")

    t_imp = float(p["implantation_time"])
    t_rest = float(p["rest_time"])
    t_ramp_start = t_imp + t_rest
    T_imp = float(p["implantation_temperature"])
    beta = float(p["ramp_rate"])
    t_end = t_ramp_start + (float(p["final_temperature"]) - T_imp) / beta

    flux = float(p["implantation_flux"])
    r_imp = float(p["implantation_range"])
    w_imp = float(p["implantation_width"])

    # NOTE: FESTIM inspects the argument names of callables ("x", "t", "T") to detect dependencies.
    def source_value(x, t):
        gauss = flux / (w_imp * np.sqrt(2.0 * np.pi)) * np.exp(-0.5 * ((x[0] - r_imp) / w_imp) ** 2)
        return gauss * (t <= t_imp)

    def temperature(t):
        if t < t_ramp_start:
            return T_imp
        return T_imp + beta * (t - t_ramp_start)

    model = F.HydrogenTransportProblem(
        mesh=mesh,
        subdomains=[vol, left, right],
        species=[mobile],
        temperature=temperature,
    )
    model.sources = [F.ParticleSource(value=source_value, volume=vol, species=mobile)]
    model.boundary_conditions = [
        F.FixedConcentrationBC(subdomain=left, value=0.0, species=mobile),
        F.FixedConcentrationBC(subdomain=right, value=0.0, species=mobile),
    ]
    model.traps = [
        F.Trap(
            name=tr["name"],
            mobile_species=mobile,
            k_0=tr["k_0"],
            E_k=tr["E_k"],
            p_0=tr["p_0"],
            E_p=tr["E_p"],
            n=tr["n"],
            volume=vol,
        )
        for tr in p["traps"]
    ]
    flux_left = F.SurfaceFlux(field=mobile, surface=left)
    flux_right = F.SurfaceFlux(field=mobile, surface=right)
    exports = {"flux_left": flux_left, "flux_right": flux_right}
    for i, trap in enumerate(model.traps):
        # the immobile trapped species is created at initialise(); refer to it by name
        exports[f"trapped_{i}"] = F.TotalVolume(field=trap.name, volume=vol)
    model.exports = list(exports.values())

    model.settings = F.Settings(
        atol=p.get("atol", 1e10),
        rtol=p.get("rtol", 1e-10),
        max_iterations=30,
        final_time=t_end,
        stepsize=F.Stepsize(
            initial_value=0.5,
            growth_factor=1.2,
            cutback_factor=0.8,
            target_nb_iterations=4,
            max_stepsize=lambda t: 5.0 if t < t_ramp_start else 0.5,
            milestones=[t_imp, t_ramp_start],
        ),
    )
    return model, exports


def run_with_snes_stats(model) -> dict:
    """Time-step the model exactly as ``model.run()`` does, recording per step how many Newton
    iterations the PETSc SNES took, why it stopped and the final residual norm.

    FESTIM's convergence test declares CONVERGED_FNORM_ABS as soon as ||F|| < atol -- also at
    iteration 0, before any update -- so a loose absolute tolerance can silently freeze the solution
    while the transient is still evolving.  A run that hits that shows up here as steps with zero
    iterations; ``first_zero_iteration_time`` says when the freeze began.  Diagnostics are
    best-effort: any failure to read the SNES leaves the physics untouched and marks them
    unavailable.
    """
    iterations: list[int] = []
    reasons: list[int] = []
    residuals: list[float] = []
    times: list[float] = []
    available = True
    while model.t.value < model.settings.final_time:
        model.iterate()
        if available:
            try:
                snes = model.solver.solver
                iterations.append(int(snes.getIterationNumber()))
                reasons.append(int(snes.getConvergedReason()))
                residuals.append(float(snes.getFunctionNorm()))
                times.append(float(model.t.value))
            except Exception:  # noqa: BLE001 - diagnostics must never fail a run
                available = False
    if not available or not iterations:
        return {"available": False}
    zero = [i for i, n in enumerate(iterations) if n == 0]
    reason_counts: dict[str, int] = {}
    # PETSc SNESConvergedReason codes: 2 FNORM_ABS, 3 FNORM_RELATIVE, 4 SNORM_RELATIVE
    for r in reasons:
        reason_counts[str(r)] = reason_counts.get(str(r), 0) + 1
    return {
        "available": True,
        "steps": len(iterations),
        "iterations_min": min(iterations),
        "iterations_max": max(iterations),
        "iterations_mean": sum(iterations) / len(iterations),
        "zero_iteration_steps": len(zero),
        "first_zero_iteration_time": times[zero[0]] if zero else None,
        "converged_reasons": reason_counts,
        "residual_norm_final": residuals[-1],
        "residual_norm_min": min(residuals),
        "residual_norm_max": max(residuals),
    }


def main(case_dir: Path) -> int:
    params = json.loads((case_dir / "params.json").read_text())
    info = {"status": "failed", "kind": params["kind"], "started": time.time()}
    try:
        import festim

        info["festim_version"] = getattr(festim, "__version__", "unknown")
        builder = {"permeation": build_permeation, "tds": build_tds}[params["kind"]]
        model, exports = builder(params)
        model.show_progress_bar = False
        model.initialise()
        t0 = time.time()
        info["snes"] = run_with_snes_stats(model)
        info["wall_time_s"] = time.time() - t0
        info["n_steps"] = len(next(iter(exports.values())).t)

        # Write a single CSV with all exported quantities on the common time axis
        t = np.asarray(next(iter(exports.values())).t)
        columns = {"t": t}
        for name, exp in exports.items():
            data = np.asarray(exp.data, dtype=float)
            columns[name] = data if data.size == t.size else np.interp(t, np.asarray(exp.t), data)
        if params["kind"] == "tds":
            columns["desorption_flux"] = np.abs(columns["flux_left"]) + np.abs(
                columns["flux_right"]
            )
            columns["temperature"] = np.array([model.temperature(t=float(ti)) for ti in t])
        header = ",".join(columns)
        np.savetxt(
            case_dir / "results.csv",
            np.column_stack(list(columns.values())),
            delimiter=",",
            header=header,
            comments="",
        )
        info["status"] = "completed"
        return 0
    except Exception as exc:  # noqa: BLE001 - we want the traceback in the log
        info["error"] = repr(exc)
        info["traceback"] = traceback.format_exc()
        print(info["traceback"], file=sys.stderr)
        return 1
    finally:
        info["finished"] = time.time()
        (case_dir / "run_info.json").write_text(json.dumps(info, indent=2))


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent))
