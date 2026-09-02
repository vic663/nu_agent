"""Reduced-order forward models.

These are cheap (milliseconds) physics models that share parameters with the
high-fidelity FESTIM / OpenFOAM models.  They are used for

1. *reduced-order calibration*: obtain a posterior on trap parameters or
   diffusivities in seconds, then refine with the full model;
2. *UQ*: propagate parameter uncertainty through thousands of evaluations;
3. *CI*: exercise the full calibration and UQ machinery without a solver.

Every model implements ``__call__(params: dict) -> np.ndarray`` returning the
predicted observable on a fixed abscissa (``self.x``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp

from nuagent.physics.analytical import K_B_EV, arrhenius, permeation_flux


@dataclass
class FirstOrderDesorptionModel:
    """Kissinger/Redhead first-order desorption from a single trap during a linear ramp.

    dn_t/dt = -p_0 exp(-E_p / k_B T(t)) n_t,   T(t) = T0 + beta t

    The observable is the desorption flux per unit area, -L dn_t/dt [1/m^2/s],
    on the temperature grid ``temperatures``.  Diffusion is assumed fast
    compared with detrapping (thin sample / high diffusivity), which is the
    classical TDS analysis assumption; the FESTIM backend relaxes it.

    Calibratable parameters: ``E_p`` [eV], ``log10_p_0`` [1/s], ``n_t0`` [1/m^3]
    (initial trapped concentration), ``beta`` [K/s] optional.
    """

    temperatures: np.ndarray
    thickness: float = 1.0e-3
    T0: float = 300.0
    beta: float = 8.0
    defaults: dict = field(default_factory=lambda: {"E_p": 1.0, "log10_p_0": 13.0, "n_t0": 1.0e25})

    @property
    def x(self) -> np.ndarray:
        return self.temperatures

    def __call__(self, params: dict) -> np.ndarray:
        p = {**self.defaults, **params}
        E_p, p_0, n_t0 = p["E_p"], 10.0 ** p["log10_p_0"], p["n_t0"]
        beta = p.get("beta", self.beta)
        t_grid = (self.temperatures - self.T0) / beta

        def rhs(t, y):
            T = self.T0 + beta * t
            return [-arrhenius(p_0, E_p, T) * y[0]]

        sol = solve_ivp(
            rhs,
            (0.0, float(t_grid[-1])),
            [n_t0],
            t_eval=t_grid,
            method="LSODA",
            rtol=1e-8,
            atol=1e-30,
        )
        n_t = sol.y[0]
        T = self.temperatures
        rate = np.array([arrhenius(p_0, E_p, Ti) for Ti in T]) * n_t
        return self.thickness * rate  # flux per unit area [1/m^2/s]


@dataclass
class PermeationModel:
    """Transient permeation flux through a plane sheet (analytical series).

    Calibratable parameters: ``log10_D`` [m^2/s], ``c0`` [1/m^3], ``L`` [m].
    Alternatively ``D_0``/``E_D`` with a ``temperature`` in the defaults.
    """

    times: np.ndarray
    defaults: dict = field(default_factory=lambda: {"log10_D": -10.0, "c0": 1.0e20, "L": 1.0e-3})

    @property
    def x(self) -> np.ndarray:
        return self.times

    def __call__(self, params: dict) -> np.ndarray:
        p = {**self.defaults, **params}
        if "D_0" in p and "E_D" in p:
            D = arrhenius(p["D_0"], p["E_D"], p["temperature"])
        else:
            D = 10.0 ** p["log10_D"]
        return permeation_flux(self.times, D, p["c0"], p["L"])


@dataclass
class NusseltCorrelationModel:
    """Parametrised Dittus–Boelter-type law Nu = C Re^m Pr^n for calibration demos.

    Observable: Nu on the Reynolds-number grid ``reynolds`` at fixed Pr.
    Calibratable parameters: ``C``, ``m``, ``n``.
    """

    reynolds: np.ndarray
    prandtl: float = 5.8
    defaults: dict = field(default_factory=lambda: {"C": 0.023, "m": 0.8, "n": 0.4})

    @property
    def x(self) -> np.ndarray:
        return self.reynolds

    def __call__(self, params: dict) -> np.ndarray:
        p = {**self.defaults, **params}
        return p["C"] * self.reynolds ** p["m"] * self.prandtl ** p["n"]


def kissinger_check(E_p: float, log10_p_0: float, beta: float, T_peak: float) -> float:
    """Residual of the Redhead peak condition; ~0 when (E_p, p_0) are consistent with T_peak."""
    p_0 = 10.0**log10_p_0
    return E_p / (K_B_EV * T_peak**2) - (p_0 / beta) * np.exp(-E_p / (K_B_EV * T_peak))
