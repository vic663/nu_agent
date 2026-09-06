"""Bayesian calibration with affine-invariant ensemble MCMC (emcee).

The calibrator is model-agnostic: any callable ``model(params: dict) -> np.ndarray``
that returns the observable on the same abscissa as the data can be
calibrated — a reduced-order model (milliseconds), a Gaussian-process
surrogate trained on a handful of high-fidelity runs, or the high-fidelity
solver itself when it is cheap enough (1-D FESTIM).

Likelihood: independent Gaussian noise, optionally with a calibrated
log-noise term (``infer_noise=True``).  Priors: uniform (or log-uniform) boxes
from :class:`~nuagent.spec.ParameterPrior`.

References: Foreman-Mackey et al. (2013) *emcee: The MCMC Hammer*, PASP 125;
Kennedy & O'Hagan (2001) for the calibration framing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nuagent.spec import ParameterPrior

ForwardModel = Callable[[dict[str, float]], np.ndarray]


@dataclass
class CalibrationResult:
    names: list[str]
    samples: (
        np.ndarray
    )  # (n_samples, n_params) in *physical* units (log-scale priors are exponentiated)
    log_prob: np.ndarray
    acceptance_fraction: float
    autocorr_time: list[float] | None
    map_estimate: dict[str, float]
    summary: dict[str, dict[str, float]]  # name -> {mean, std, q05, q50, q95}
    noise_sigma: float | dict[str, float]
    n_model_evaluations: int
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "names": self.names,
            "map_estimate": self.map_estimate,
            "summary": self.summary,
            "acceptance_fraction": self.acceptance_fraction,
            "autocorr_time": self.autocorr_time,
            "noise_sigma": self.noise_sigma,
            "n_model_evaluations": self.n_model_evaluations,
            "n_samples": int(self.samples.shape[0]),
            **self.extra,
        }


class BayesianCalibrator:
    def __init__(
        self,
        model: ForwardModel,
        priors: list[ParameterPrior],
        x: np.ndarray,
        y_obs: np.ndarray,
        sigma: float | np.ndarray | None = None,
        infer_noise: bool = False,
    ):
        self.model = model
        self.priors = priors
        self.x = np.asarray(x, dtype=float)
        self.y_obs = np.asarray(y_obs, dtype=float)
        self.infer_noise = infer_noise or sigma is None
        self.sigma = (
            None
            if self.infer_noise
            else np.broadcast_to(np.asarray(sigma, dtype=float), self.y_obs.shape)
        )
        self.n_eval = 0
        self.scale = (
            float(np.max(np.abs(self.y_obs))) or 1.0
        )  # noise parameterised relative to the data scale

    # -- parameter mapping ---------------------------------------------- #
    @property
    def names(self) -> list[str]:
        return [p.name for p in self.priors]

    @property
    def ndim(self) -> int:
        return len(self.priors) + (1 if self.infer_noise else 0)

    def _bounds(self) -> np.ndarray:
        b = [
            (np.log10(p.low), np.log10(p.high)) if p.log_scale else (p.low, p.high)
            for p in self.priors
        ]
        if self.infer_noise:
            b.append((-6.0, 0.0))  # log10(sigma / scale)
        return np.array(b)

    def to_physical(self, theta: np.ndarray) -> dict[str, float]:
        out = {}
        for i, p in enumerate(self.priors):
            out[p.name] = float(10.0 ** theta[i]) if p.log_scale else float(theta[i])
        return out

    # -- probability ------------------------------------------------------ #
    def log_prior(self, theta: np.ndarray) -> float:
        b = self._bounds()
        if np.any(theta < b[:, 0]) or np.any(theta > b[:, 1]):
            return -np.inf
        return 0.0

    def log_likelihood(self, theta: np.ndarray) -> float:
        params = self.to_physical(theta)
        try:
            y = np.asarray(self.model(params), dtype=float)
        except Exception:  # noqa: BLE001 - a failed model evaluation has zero likelihood
            return -np.inf
        self.n_eval += 1
        if y.shape != self.y_obs.shape or not np.all(np.isfinite(y)):
            return -np.inf
        sigma = np.asarray(
            10.0 ** theta[-1] * self.scale if self.infer_noise else self.sigma, dtype=float
        )
        r = (self.y_obs - y) / sigma
        return float(-0.5 * np.sum(r**2 + np.log(2.0 * np.pi * sigma**2)))

    def log_prob(self, theta: np.ndarray) -> float:
        lp = self.log_prior(theta)
        if not np.isfinite(lp):
            return -np.inf
        return lp + self.log_likelihood(theta)

    # -- sampling --------------------------------------------------------- #
    def run(
        self,
        n_walkers: int = 32,
        n_steps: int = 2000,
        burn_in: int = 500,
        seed: int = 0,
        progress: bool = False,
    ) -> CalibrationResult:
        import emcee

        rng = np.random.default_rng(seed)
        b = self._bounds()
        n_walkers = max(n_walkers, 2 * self.ndim + 2)
        p0 = b[:, 0] + (b[:, 1] - b[:, 0]) * rng.uniform(0.3, 0.7, size=(n_walkers, self.ndim))
        sampler = emcee.EnsembleSampler(n_walkers, self.ndim, self.log_prob)
        sampler.run_mcmc(p0, n_steps, progress=progress)
        chain = sampler.get_chain(discard=burn_in, flat=True)
        logp = sampler.get_log_prob(discard=burn_in, flat=True)
        try:
            tau = [float(t) for t in sampler.get_autocorr_time(tol=0)]
        except Exception:  # noqa: BLE001
            tau = None

        phys = np.array([[self.to_physical(t)[n] for n in self.names] for t in chain])
        i_map = int(np.argmax(logp))
        map_est = self.to_physical(chain[i_map])
        summary = {}
        for j, n in enumerate(self.names):
            col = phys[:, j]
            q05, q50, q95 = np.percentile(col, [5, 50, 95])
            summary[n] = {
                "mean": float(col.mean()),
                "std": float(col.std()),
                "q05": float(q05),
                "q50": float(q50),
                "q95": float(q95),
            }
        noise: dict[str, float] | float
        if self.infer_noise:
            sig = 10.0 ** chain[:, -1] * self.scale
            noise = {
                "median": float(np.median(sig)),
                "q05": float(np.percentile(sig, 5)),
                "q95": float(np.percentile(sig, 95)),
            }
        else:
            noise = float(np.mean(self.sigma))
        return CalibrationResult(
            names=self.names,
            samples=phys,
            log_prob=logp,
            acceptance_fraction=float(np.mean(sampler.acceptance_fraction)),
            autocorr_time=tau,
            map_estimate=map_est,
            summary=summary,
            noise_sigma=noise,
            n_model_evaluations=self.n_eval,
        )


def posterior_predictive(
    model: ForwardModel, result: CalibrationResult, n: int = 200, seed: int = 0
) -> np.ndarray:
    """Evaluate the model on ``n`` posterior samples -> array (n, len(x))."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(result.samples.shape[0], size=min(n, result.samples.shape[0]), replace=False)
    return np.array([model(dict(zip(result.names, result.samples[i], strict=True))) for i in idx])
