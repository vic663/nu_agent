"""Closed-form solutions used as verification references.

References
----------
- Crank, J. (1975). *The Mathematics of Diffusion*, 2nd ed., §4.3.3 (permeation
  through a plane sheet, time-lag method).
- Oriani, R.A. (1970). The diffusion and trapping of hydrogen in steel.
  *Acta Metall.* 18, 147-157 (effective diffusivity with equilibrium traps).
- McNabb, A., Foster, P.K. (1963). A new analysis of the diffusion of hydrogen
  in iron and ferritic steels. *Trans. AIME* 227, 618-627.
- Redhead, P.A. (1962). Thermal desorption of gases. *Vacuum* 12, 203-211.
- Hartmann, J. (1937). Hg-dynamics I. *K. Dan. Vidensk. Selsk. Mat.-Fys. Medd.* 15(6).
- Müller, U., Bühler, L. (2001). *Magnetofluiddynamics in Channels and Containers*.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq

K_B_EV = 8.617333262e-5  # Boltzmann constant [eV/K]


def arrhenius(pre_exponential: float, activation_energy_ev: float, temperature: float) -> float:
    """A exp(-E / k_B T) with E in eV."""
    return pre_exponential * math.exp(-activation_energy_ev / (K_B_EV * temperature))


# --------------------------------------------------------------------------- #
# Hydrogen-isotope permeation through a plane sheet
# --------------------------------------------------------------------------- #


def permeation_flux(t, D: float, c0: float, L: float, n_terms: int = 200):
    """Downstream flux of a plane sheet, c(0,t)=c0, c(L,t)=0, c(x,0)=0.

    J(t) = (D c0 / L) [ 1 + 2 sum_{n>=1} (-1)^n exp(-n^2 pi^2 D t / L^2) ]

    Parameters are in SI (D [m^2/s], c0 [1/m^3], L [m]); the flux is in
    [1/m^2/s].  Vectorised over ``t``.
    """
    t = np.atleast_1d(np.asarray(t, dtype=float))
    tau = D * t / L**2
    flux = np.zeros_like(t)
    j_ss = D * c0 / L

    # Long-time series (Crank eq. 4.24a): converges fast for tau > ~0.05
    long_mask = tau > 0.05
    if np.any(long_mask):
        n = np.arange(1, n_terms + 1)[:, None]
        series = ((-1.0) ** n * np.exp(-(n**2) * math.pi**2 * tau[None, long_mask])).sum(axis=0)
        flux[long_mask] = j_ss * (1.0 + 2.0 * series)

    # Short-time series (Crank eq. 4.24b): J = 2 c0 sqrt(D/(pi t)) sum exp(-(2n+1)^2 L^2 / (4 D t))
    short_mask = (~long_mask) & (tau > 0)
    if np.any(short_mask):
        ts = t[short_mask]
        n = np.arange(0, 20)[:, None]
        series = np.exp(-((2 * n + 1) ** 2) * L**2 / (4.0 * D * ts[None, :])).sum(axis=0)
        flux[short_mask] = 2.0 * c0 * np.sqrt(D / (math.pi * ts)) * series

    return np.clip(flux, 0.0, None)


def permeation_steady_flux(D: float, c0: float, L: float) -> float:
    """Steady permeation flux J_ss = D c0 / L."""
    return D * c0 / L


def permeation_time_lag(D: float, L: float) -> float:
    """Time lag t_lag = L^2 / (6 D) (Daynes/Barrer method)."""
    return L**2 / (6.0 * D)


def breakthrough_time(D: float, L: float) -> float:
    """Time at which J reaches ~1 % of steady state: t_b ~= L^2 / (2 pi^2 D)... Using the common
    engineering definition t_b = L^2 / (15.3 D) (Crank)."""
    return L**2 / (15.3 * D)


def effective_diffusivity_oriani(D: float, n_trap: float, k_trap: float, p_detrap: float) -> float:
    """Oriani effective diffusivity for a dilute single trap in local equilibrium.

    D_eff = D / (1 + n_t k / p), with k, p the trapping / detrapping rates.  Valid when
    the trap occupancy is small (k c_m << p).
    """
    return D / (1.0 + n_trap * k_trap / p_detrap)


def effective_diffusivity_from_trap(
    D: float, temperature: float, k_0, E_k, p_0, E_p, n_trap
) -> float:
    k = arrhenius(k_0, E_k, temperature)
    p = arrhenius(p_0, E_p, temperature)
    return effective_diffusivity_oriani(D, n_trap, k, p)


def effective_diffusivity_multitrap(D: float, temperature: float, traps) -> float:
    """Oriani/McNabb-Foster effective diffusivity for an arbitrary number of traps.

    With local equilibrium between mobile and trapped hydrogen, each trap adds an independent
    trapped population to the mobile balance,

        d(c_m + sum_i c_t,i)/dt = D grad^2 c_m,

    so the retardation factors **add in the denominator**:

        D_eff = D / (1 + sum_i n_i k_i / p_i).

    Applying the single-trap formula recursively (``D_eff <- D_eff / (1 + n k / p)`` per trap)
    would give ``D / prod_i (1 + n_i k_i / p_i)``, which is wrong as soon as there are two traps
    -- for two traps with n k / p = 1e7 each it under-predicts D_eff by six orders of magnitude.

    References: Oriani (1970) Acta Metall. 18, 147; McNabb & Foster (1963) Trans. AIME 227, 618;
    FESTIM theory documentation (independent c_t,i summed in the mobile balance).
    """
    retardation = 0.0
    for tr in traps:
        k = arrhenius(tr.k_0, tr.E_k, temperature)
        p = arrhenius(tr.p_0, tr.E_p, temperature)
        if p <= 0.0:  # pragma: no cover - guarded by the schema (p_0 > 0)
            raise ValueError(
                f"trap {getattr(tr, 'name', '?')!r} has a non-positive detrapping rate"
            )
        retardation += tr.n * k / p
    return D / (1.0 + retardation)


# --------------------------------------------------------------------------- #
# Thermal desorption: Redhead peak temperature for first-order desorption
# --------------------------------------------------------------------------- #


def redhead_peak_temperature(E_p: float, p_0: float, beta: float, T0: float = 300.0) -> float:
    """Temperature of the desorption peak for first-order kinetics with a linear ramp.

    Solves E_p / (k_B T_p^2) = (p_0 / beta) exp(-E_p / k_B T_p) for T_p.
    """

    def g(T):
        return E_p / (K_B_EV * T**2) - (p_0 / beta) * math.exp(-E_p / (K_B_EV * T))

    lo, hi = T0, 5000.0
    if g(lo) * g(hi) > 0:  # pragma: no cover - degenerate parameter sets
        raise ValueError("no desorption peak in the search interval")
    return brentq(g, lo, hi, xtol=1e-6)


# --------------------------------------------------------------------------- #
# Fluid mechanics
# --------------------------------------------------------------------------- #


def poiseuille_pipe_velocity(r, radius: float, mean_velocity: float):
    """Fully developed laminar pipe flow u(r) = 2 U_m (1 - (r/R)^2)."""
    r = np.asarray(r, dtype=float)
    return 2.0 * mean_velocity * (1.0 - (r / radius) ** 2)


def poiseuille_pressure_gradient(mu: float, mean_velocity: float, radius: float) -> float:
    """-dp/dx = 8 mu U_m / R^2 for laminar pipe flow."""
    return 8.0 * mu * mean_velocity / radius**2


def hartmann_velocity(y, half_width: float, hartmann_number: float, mean_velocity: float):
    """Fully developed MHD channel flow between insulating plates at y = +/- a.

    u(y)/U_m = Ha (cosh Ha - cosh(Ha y/a)) / (Ha cosh Ha - sinh Ha).
    Reduces to the plane Poiseuille profile 1.5 U_m (1 - (y/a)^2) as Ha -> 0.
    """
    y = np.asarray(y, dtype=float)
    ha = hartmann_number
    if ha < 1e-6:
        return 1.5 * mean_velocity * (1.0 - (y / half_width) ** 2)
    num = np.cosh(ha) - np.cosh(ha * y / half_width)
    den = np.cosh(ha) - np.sinh(ha) / ha
    return mean_velocity * num / den


def hartmann_number(B: float, half_width: float, sigma: float, mu: float) -> float:
    """Ha = B a sqrt(sigma / mu)."""
    return B * half_width * math.sqrt(sigma / mu)
