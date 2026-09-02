"""Gaussian-process surrogate of an expensive forward model.

Trains on Latin-hypercube samples of the prior box (each sample = one solver
run, embarrassingly parallel) and then stands in for the solver inside the
MCMC.  Outputs are reduced with PCA so that a whole curve (e.g. a TDS
spectrum) can be emulated with a few GPs.  The surrogate reports its
leave-out validation error so the calibration can state whether the
emulator, not the physics, dominates the posterior width.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.stats import qmc

from nuagent.spec import ParameterPrior


def latin_hypercube(priors: list[ParameterPrior], n: int, seed: int = 0) -> list[dict[str, float]]:
    sampler = qmc.LatinHypercube(d=len(priors), seed=seed)
    u = sampler.random(n)
    out = []
    for row in u:
        p = {}
        for ui, pr in zip(row, priors, strict=True):
            if pr.log_scale:
                p[pr.name] = float(
                    10.0 ** (np.log10(pr.low) + ui * (np.log10(pr.high) - np.log10(pr.low)))
                )
            else:
                p[pr.name] = float(pr.low + ui * (pr.high - pr.low))
        out.append(p)
    return out


@dataclass
class GPSurrogate:
    priors: list[ParameterPrior]
    n_components: int = 8
    seed: int = 0

    def _encode(self, params: dict[str, float]) -> np.ndarray:
        x = []
        for pr in self.priors:
            v = params[pr.name]
            if pr.log_scale:
                lo, hi = np.log10(pr.low), np.log10(pr.high)
                x.append((np.log10(v) - lo) / (hi - lo))
            else:
                x.append((v - pr.low) / (pr.high - pr.low))
        return np.array(x)

    def fit(
        self, model: Callable[[dict[str, float]], np.ndarray], n_train: int = 64, holdout: int = 8
    ):
        from sklearn.decomposition import PCA
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

        samples = latin_hypercube(self.priors, n_train + holdout, seed=self.seed)
        X = np.array([self._encode(s) for s in samples])
        Y = np.array([np.asarray(model(s), dtype=float) for s in samples])
        self.y_scale = float(np.max(np.abs(Y))) or 1.0
        Yn = Y / self.y_scale
        Xtr, Xho, Ytr, Yho = X[:n_train], X[n_train:], Yn[:n_train], Yn[n_train:]
        k = min(self.n_components, Ytr.shape[0] - 1, Ytr.shape[1])
        self.pca = PCA(n_components=k).fit(Ytr)
        Z = self.pca.transform(Ytr)
        self.gps = []
        for j in range(k):
            kernel = ConstantKernel(1.0, (1e-3, 1e3)) * RBF(
                np.full(X.shape[1], 0.3), (1e-2, 1e2)
            ) + WhiteKernel(1e-6, (1e-10, 1e-2))
            gp = GaussianProcessRegressor(
                kernel=kernel, normalize_y=True, n_restarts_optimizer=2, random_state=self.seed
            )
            gp.fit(Xtr, Z[:, j])
            self.gps.append(gp)
        pred = self._predict_batch(Xho)
        self.holdout_rel_error = (
            float(np.sqrt(np.mean((pred - Yho) ** 2)) / (np.sqrt(np.mean(Yho**2)) or 1.0))
            if holdout
            else None
        )
        self.n_train = n_train
        return self

    def _predict_batch(self, X: np.ndarray) -> np.ndarray:
        Z = np.column_stack([gp.predict(X) for gp in self.gps])
        return self.pca.inverse_transform(Z)

    def __call__(self, params: dict[str, float]) -> np.ndarray:
        x = self._encode(params)[None, :]
        return self._predict_batch(x)[0] * self.y_scale
