"""Glue between a :class:`SimulationSpec` and the calibration machinery."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from nuagent.calibration.bayes import BayesianCalibrator, posterior_predictive
from nuagent.calibration.surrogate import GPSurrogate
from nuagent.physics import reduced
from nuagent.spec import HeatedPipeCase, PermeationCase, SimulationSpec, TDSCase


def load_dataset(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    data = np.genfromtxt(path, delimiter=",", names=True)
    x = np.asarray(data["x"], dtype=float)
    y = np.asarray(data["y"], dtype=float)
    sigma = np.asarray(data["sigma"], dtype=float) if "sigma" in data.dtype.names else None
    return x, y, sigma


def reduced_model_for(spec: SimulationSpec, x: np.ndarray):
    """Reduced-order forward model sharing parameters with the high-fidelity case."""
    case = spec.case
    if isinstance(case, TDSCase):
        tr = case.traps[0]
        return reduced.FirstOrderDesorptionModel(
            temperatures=x,
            thickness=case.thickness,
            T0=case.implantation_temperature,
            beta=case.ramp_rate,
            defaults={
                "E_p": tr.E_p,
                "log10_p_0": math.log10(tr.p_0),
                "n_t0": min(tr.n, case.implantation_flux * case.implantation_time / case.thickness),
            },
        )
    if isinstance(case, PermeationCase):
        from nuagent.physics.analytical import arrhenius

        D = arrhenius(case.material.D_0, case.material.E_D, case.temperature)
        return reduced.PermeationModel(
            times=x,
            defaults={
                "log10_D": math.log10(D),
                "c0": case.upstream_concentration,
                "L": case.thickness,
                "D_0": case.material.D_0,
                "E_D": case.material.E_D,
                "temperature": case.temperature,
            },
        )
    if isinstance(case, HeatedPipeCase):
        return reduced.NusseltCorrelationModel(reynolds=x, prandtl=case.fluid.pr)
    raise TypeError(f"no reduced model for {type(case).__name__}")


def synthetic_dataset(
    spec: SimulationSpec,
    truth: dict[str, float],
    noise_rel: float = 0.03,
    n: int = 60,
    seed: int = 1,
):
    """Generate a synthetic observation from the reduced model (for demos and tests)."""
    case = spec.case
    rng = np.random.default_rng(seed)
    if isinstance(case, TDSCase):
        x = np.linspace(case.implantation_temperature + 1.0, case.final_temperature, n)
    elif isinstance(case, PermeationCase):
        from nuagent.physics.analytical import arrhenius

        D = arrhenius(case.material.D_0, case.material.E_D, case.temperature)
        x = np.linspace(0.0, 4.0 * case.thickness**2 / D, n)[1:]
    else:
        x = np.geomspace(1e4, 1e5, n)
    model = reduced_model_for(spec, x)
    y_true = model(truth)
    sigma = noise_rel * float(np.max(np.abs(y_true)))
    y = y_true + rng.normal(0.0, sigma, size=y_true.shape)
    return x, y, np.full_like(y, sigma), model


def run_calibration_for_spec(spec: SimulationSpec, outdir: Path, seed: int = 0) -> dict[str, Any]:
    cal = spec.calibration
    assert cal is not None
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    truth: dict[str, float] | None = None

    if cal.dataset == "synthetic":
        # "true" parameters: geometric centre of each prior box (log-centre for log priors)
        truth = {}
        for p in cal.parameters:
            truth[p.name] = (
                float(10 ** (0.5 * (np.log10(p.low) + np.log10(p.high))))
                if p.log_scale
                else 0.5 * (p.low + p.high)
            )
        x, y, sigma, model = synthetic_dataset(spec, truth, seed=seed + 1)
        np.savetxt(
            outdir / "synthetic_dataset.csv",
            np.column_stack([x, y, sigma]),
            delimiter=",",
            header="x,y,sigma",
            comments="",
        )
    else:
        x, y, sigma = load_dataset(cal.dataset)
        model = reduced_model_for(spec, x)
        if sigma is None and cal.noise_sigma is not None:
            sigma = np.full_like(y, cal.noise_sigma)

    forward = model
    surrogate_info = None
    if cal.surrogate == "gp":
        gp = GPSurrogate(cal.parameters, seed=seed).fit(model, n_train=cal.surrogate_samples)
        forward = gp
        surrogate_info = {"n_train": gp.n_train, "holdout_rel_error": gp.holdout_rel_error}

    calibrator = BayesianCalibrator(
        forward, cal.parameters, x, y, sigma=sigma, infer_noise=sigma is None
    )
    result = calibrator.run(
        n_walkers=cal.n_walkers, n_steps=cal.n_steps, burn_in=cal.burn_in, seed=seed
    )

    np.save(outdir / "posterior_samples.npy", result.samples)
    pp = posterior_predictive(model, result, n=100, seed=seed)
    np.save(outdir / "posterior_predictive.npy", pp)

    from nuagent.reporting.plots import plot_posterior

    plot_path = plot_posterior(result.samples, result.names, truth, outdir / "posterior.png")

    lines = [
        f"Parameters calibrated with emcee ({cal.n_walkers} walkers × {cal.n_steps} steps, burn-in {cal.burn_in}); "
        f"acceptance fraction {result.acceptance_fraction:.2f}; {result.n_model_evaluations} model evaluations.",
        "",
    ]
    lines.append(
        "| Parameter | MAP | posterior mean ± std | 90 % credible interval |"
        + (" truth |" if truth else "")
    )
    lines.append("|---|---|---|---|" + ("---|" if truth else ""))
    coverage = {}
    for n_ in result.names:
        s = result.summary[n_]
        row = f"| {n_} | {result.map_estimate[n_]:.4g} | {s['mean']:.4g} ± {s['std']:.2g} | [{s['q05']:.4g}, {s['q95']:.4g}] |"
        if truth:
            inside = s["q05"] <= truth[n_] <= s["q95"]
            coverage[n_] = bool(inside)
            row += f" {truth[n_]:.4g} {'✓' if inside else '✗'} |"
        lines.append(row)
    if surrogate_info:
        lines.append("")
        lines.append(
            f"GP surrogate trained on {surrogate_info['n_train']} model runs; hold-out relative RMS error {surrogate_info['holdout_rel_error']:.2%}."
        )
    summary_md = "\n".join(lines)

    out = {
        **result.to_dict(),
        "truth": truth,
        "coverage_90": coverage or None,
        "surrogate": surrogate_info,
        "dataset": cal.dataset,
        "n_data": int(len(x)),
        "posterior_plot": str(plot_path.relative_to(outdir.parent))
        if plot_path.is_relative_to(outdir.parent)
        else str(plot_path),
        "summary_markdown": summary_md,
    }
    (outdir / "calibration.json").write_text(json.dumps(out, indent=2, default=str))
    return out
