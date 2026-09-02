"""Forward uncertainty propagation and variance-based (Sobol) sensitivity analysis.

Uses SALib's Saltelli sampling and Sobol analysis (Saltelli 2002, 2010).
The forward model has the same ``dict -> array`` interface as in calibration,
so a reduced model, a surrogate or a solver wrapper can be plugged in; the
QoI is a scalar functional of the model output (``qoi_fn``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nuagent.spec import ParameterPrior


@dataclass
class SobolResult:
    names: list[str]
    first_order: dict[str, float]
    first_order_conf: dict[str, float]
    total_order: dict[str, float]
    total_order_conf: dict[str, float]
    qoi_mean: float
    qoi_std: float
    qoi_quantiles: dict[str, float]
    n_evaluations: int
    samples: np.ndarray = field(repr=False, default=None)
    outputs: np.ndarray = field(repr=False, default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "names": self.names,
            "first_order": self.first_order,
            "first_order_conf": self.first_order_conf,
            "total_order": self.total_order,
            "total_order_conf": self.total_order_conf,
            "qoi_mean": self.qoi_mean,
            "qoi_std": self.qoi_std,
            "qoi_cov": self.qoi_std / abs(self.qoi_mean) if self.qoi_mean else None,
            "qoi_quantiles": self.qoi_quantiles,
            "n_evaluations": self.n_evaluations,
        }


def _problem(priors: list[ParameterPrior]) -> dict[str, Any]:
    bounds = []
    for p in priors:
        bounds.append([np.log10(p.low), np.log10(p.high)] if p.log_scale else [p.low, p.high])
    return {"num_vars": len(priors), "names": [p.name for p in priors], "bounds": bounds}


def _decode(row: np.ndarray, priors: list[ParameterPrior]) -> dict[str, float]:
    return {
        p.name: float(10.0**v) if p.log_scale else float(v)
        for v, p in zip(row, priors, strict=True)
    }


def sobol_analysis(
    model: Callable[[dict[str, float]], np.ndarray | float],
    priors: list[ParameterPrior],
    n_base: int = 256,
    qoi_fn: Callable[[np.ndarray | float], float] | None = None,
    seed: int = 0,
) -> SobolResult:
    from SALib.analyze import sobol as sobol_analyze
    from SALib.sample import sobol as sobol_sample

    problem = _problem(priors)
    X = sobol_sample.sample(problem, n_base, calc_second_order=False, seed=seed)
    qoi_fn = qoi_fn or (lambda y: float(np.asarray(y).ravel()[-1]))
    Y = np.empty(X.shape[0])
    for i, row in enumerate(X):
        try:
            Y[i] = qoi_fn(model(_decode(row, priors)))
        except Exception:  # noqa: BLE001
            Y[i] = np.nan
    ok = np.isfinite(Y)
    if not ok.all():
        # SALib requires the full Saltelli block structure; fill failures with the mean (and report it)
        Y[~ok] = np.nanmean(Y)
    Si = sobol_analyze.analyze(
        problem, Y, calc_second_order=False, seed=seed, print_to_console=False
    )
    names = problem["names"]
    q = np.percentile(Y, [5, 50, 95])
    return SobolResult(
        names=names,
        first_order={n: float(v) for n, v in zip(names, Si["S1"], strict=True)},
        first_order_conf={n: float(v) for n, v in zip(names, Si["S1_conf"], strict=True)},
        total_order={n: float(v) for n, v in zip(names, Si["ST"], strict=True)},
        total_order_conf={n: float(v) for n, v in zip(names, Si["ST_conf"], strict=True)},
        qoi_mean=float(Y.mean()),
        qoi_std=float(Y.std()),
        qoi_quantiles={"q05": float(q[0]), "q50": float(q[1]), "q95": float(q[2])},
        n_evaluations=int(X.shape[0]),
        samples=X,
        outputs=Y,
    )
