"""Glue between a :class:`SimulationSpec` and the UQ machinery."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from nuagent.calibration.workflow import reduced_model_for
from nuagent.spec import HeatedPipeCase, PermeationCase, SimulationSpec, TDSCase
from nuagent.uq.sensitivity import sobol_analysis

QOI_FUNCTIONS = {
    # permeation model returns flux(t): steady flux is the last value; time lag from the curve
    "permeation_flux_ss": lambda y: float(np.asarray(y)[-1]),
    # TDS: peak flux / peak temperature are functionals of the spectrum
    "peak_flux": lambda y: float(np.max(y)),
    # Nu model returns Nu(Re): take the last (highest Re) value
    "Nu": lambda y: float(np.asarray(y)[-1]),
}


def run_uq_for_spec(spec: SimulationSpec, outdir: Path, seed: int = 0) -> dict[str, Any]:
    uq = spec.uq
    assert uq is not None
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    case = spec.case

    if isinstance(case, PermeationCase):
        from nuagent.physics.analytical import arrhenius

        D = arrhenius(case.material.D_0, case.material.E_D, case.temperature)
        x = np.linspace(0.0, 6.0 * case.thickness**2 / D, 200)[1:]
        default_qois = ["permeation_flux_ss"]
    elif isinstance(case, TDSCase):
        x = np.linspace(case.implantation_temperature + 1.0, case.final_temperature, 300)
        default_qois = ["peak_flux", "T_peak"]
    elif isinstance(case, HeatedPipeCase):
        x = np.array([case.reynolds])
        default_qois = ["Nu"]
    else:
        raise TypeError(type(case))
    model = reduced_model_for(spec, x)
    qois = uq.qois or default_qois

    results: dict[str, Any] = {}
    fn: Callable[..., float]
    for q in qois:
        if q == "T_peak":
            fn = lambda y, x=x: float(x[int(np.argmax(y))])  # noqa: E731
        else:
            fn = QOI_FUNCTIONS.get(q, QOI_FUNCTIONS["Nu"])
        res = sobol_analysis(model, uq.parameters, n_base=uq.n_samples, qoi_fn=fn, seed=seed)
        results[q] = res.to_dict()
        np.save(outdir / f"samples_{q}.npy", np.column_stack([res.samples, res.outputs]))

    from nuagent.reporting.plots import plot_sobol

    first_q = qois[0]
    plot_path = plot_sobol(
        results[first_q]["first_order"],
        results[first_q]["total_order"],
        outdir / "sobol.png",
        title=f"Sobol indices — {first_q}",
    )

    lines = []
    for q, r in results.items():
        lines.append(
            f"**{q}**: mean {r['qoi_mean']:.4g}, std {r['qoi_std']:.3g} (CoV {100 * (r['qoi_cov'] or 0):.1f} %), 90 % interval [{r['qoi_quantiles']['q05']:.4g}, {r['qoi_quantiles']['q95']:.4g}] from {r['n_evaluations']} model evaluations."
        )
        lines.append("")
        lines.append("| Parameter | S1 (first order) | ST (total) |")
        lines.append("|---|---|---|")
        for n in r["names"]:
            lines.append(
                f"| {n} | {r['first_order'][n]:.3f} ± {r['first_order_conf'][n]:.3f} | {r['total_order'][n]:.3f} ± {r['total_order_conf'][n]:.3f} |"
            )
        lines.append("")
    out = {
        "qois": results,
        "first_order": results[first_q]["first_order"],
        "sobol_plot": str(plot_path.relative_to(outdir.parent))
        if plot_path.is_relative_to(outdir.parent)
        else str(plot_path),
        "summary_markdown": "\n".join(lines),
    }
    (outdir / "uq.json").write_text(json.dumps(out, indent=2, default=str))
    return out
