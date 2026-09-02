"""Engineering correlations for internal forced convection in circular pipes.

Every correlation returns a :class:`CorrelationValue` carrying the value, the
name of the correlation, its stated validity range and a representative
relative uncertainty (from the original papers / Incropera & DeWitt), so that
validation can be reported as "within the correlation's own uncertainty band"
rather than as a bare percentage.

References
----------
- Gnielinski, V. (1976). New equations for heat and mass transfer in turbulent
  pipe and channel flow. *Int. Chem. Eng.* 16, 359-368.
- Petukhov, B.S. (1970). Heat transfer and friction in turbulent pipe flow with
  variable physical properties. *Adv. Heat Transfer* 6, 503-564.
- Dittus, F.W., Boelter, L.M.K. (1930). *Univ. Calif. Publ. Eng.* 2, 443.
- Incropera, DeWitt, Bergman, Lavine. *Fundamentals of Heat and Mass Transfer*,
  7th ed., Ch. 8 (laminar fully developed: Nu = 4.36 for uniform q'', 3.66 for
  uniform T_w; f = 64/Re).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Dimensionless groups and derived quantities
# --------------------------------------------------------------------------- #


def reynolds(rho: float, velocity: float, diameter: float, mu: float) -> float:
    """Bulk Reynolds number Re = rho U D / mu."""
    return rho * velocity * diameter / mu


def prandtl(mu: float, cp: float, k: float) -> float:
    """Prandtl number Pr = mu cp / k."""
    return mu * cp / k


def velocity_from_reynolds(reynolds_number: float, rho: float, diameter: float, mu: float) -> float:
    return reynolds_number * mu / (rho * diameter)


def bulk_temperature(
    x: float, t_in: float, q_wall: float, diameter: float, mdot: float, cp: float
) -> float:
    """Bulk temperature from an energy balance for uniform wall heat flux.

    T_b(x) = T_in + q'' * (pi D x) / (mdot cp).  Exact for steady flow with
    constant properties and negligible viscous heating.
    """
    return t_in + q_wall * math.pi * diameter * x / (mdot * cp)


def mass_flow_rate(rho: float, velocity: float, diameter: float) -> float:
    return rho * velocity * math.pi * diameter**2 / 4.0


def nusselt_local(q_wall: float, diameter: float, k: float, t_wall: float, t_bulk: float) -> float:
    """Local Nusselt number Nu = h D / k with h = q'' / (T_w - T_b)."""
    dt = t_wall - t_bulk
    if abs(dt) < 1e-12:
        return math.inf
    return q_wall * diameter / (k * dt)


def darcy_from_pressure_drop(
    dp: float, length: float, diameter: float, rho: float, velocity: float
) -> float:
    """Darcy friction factor from the pressure drop over a fully developed length."""
    return dp * diameter / (length * 0.5 * rho * velocity**2)


def darcy_from_wall_shear(tau_wall: float, rho: float, velocity: float) -> float:
    """Darcy friction factor from wall shear stress: f = 8 tau_w / (rho U^2)."""
    return 8.0 * tau_wall / (rho * velocity**2)


def friction_velocity(tau_wall: float, rho: float) -> float:
    return math.sqrt(tau_wall / rho)


def first_cell_height_for_yplus(
    target_yplus: float, reynolds_number: float, diameter: float, nu: float
) -> float:
    """Wall-adjacent cell *centre* distance giving the target y+.

    Uses the Petukhov (turbulent) or laminar friction factor to estimate the
    wall shear stress: tau_w = f rho U^2 / 8  ->  u_tau = U sqrt(f/8).
    """
    velocity = reynolds_number * nu / diameter
    f = friction_factor(reynolds_number).value
    u_tau = velocity * math.sqrt(f / 8.0)
    return target_yplus * nu / u_tau


# --------------------------------------------------------------------------- #
# Correlations
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CorrelationValue:
    """Value of a correlation together with its provenance."""

    value: float
    name: str
    uncertainty: float  # representative relative uncertainty (1 = 100 %)
    valid: bool = True
    notes: str = ""
    inputs: dict = field(default_factory=dict)

    @property
    def low(self) -> float:
        return self.value * (1.0 - self.uncertainty)

    @property
    def high(self) -> float:
        return self.value * (1.0 + self.uncertainty)


LAMINAR_NU_UNIFORM_HEAT_FLUX = 48.0 / 11.0  # 4.3636...
LAMINAR_NU_UNIFORM_WALL_TEMP = 3.6568


def flow_regime(reynolds_number: float) -> str:
    if reynolds_number < 2300:
        return "laminar"
    if reynolds_number < 4000:
        return "transitional"
    return "turbulent"


def friction_factor_laminar(reynolds_number: float) -> CorrelationValue:
    """Hagen–Poiseuille: f = 64 / Re (exact for fully developed laminar flow)."""
    return CorrelationValue(
        64.0 / reynolds_number,
        "laminar (64/Re)",
        uncertainty=0.0,
        valid=reynolds_number < 2300,
        notes="exact analytical solution",
        inputs={"Re": reynolds_number},
    )


def friction_factor_blasius(reynolds_number: float) -> CorrelationValue:
    """Blasius: f = 0.316 Re^-0.25, valid 4e3 < Re < 1e5 (smooth pipe)."""
    return CorrelationValue(
        0.316 * reynolds_number**-0.25,
        "blasius",
        uncertainty=0.05,
        valid=4e3 <= reynolds_number <= 1e5,
        inputs={"Re": reynolds_number},
    )


def friction_factor_petukhov(reynolds_number: float) -> CorrelationValue:
    """Petukhov (1970): f = (0.790 ln Re - 1.64)^-2, valid 3e3 < Re < 5e6."""
    return CorrelationValue(
        (0.790 * math.log(reynolds_number) - 1.64) ** -2,
        "petukhov",
        uncertainty=0.05,
        valid=3e3 <= reynolds_number <= 5e6,
        inputs={"Re": reynolds_number},
    )


def friction_factor_prandtl_karman(reynolds_number: float, tol: float = 1e-12) -> CorrelationValue:
    """Prandtl–von Kármán smooth-pipe law: 1/sqrt(f) = 2 log10(Re sqrt(f)) - 0.8 (iterative)."""
    f = friction_factor_petukhov(reynolds_number).value
    for _ in range(100):
        f_new = (2.0 * math.log10(reynolds_number * math.sqrt(f)) - 0.8) ** -2
        if abs(f_new - f) < tol:
            f = f_new
            break
        f = f_new
    return CorrelationValue(
        f,
        "prandtl_karman",
        uncertainty=0.03,
        valid=reynolds_number >= 4e3,
        inputs={"Re": reynolds_number},
    )


def friction_factor(reynolds_number: float) -> CorrelationValue:
    """Regime-aware default: laminar exact solution or Petukhov."""
    if reynolds_number < 2300:
        return friction_factor_laminar(reynolds_number)
    return friction_factor_petukhov(reynolds_number)


def nusselt_laminar(boundary_condition: str = "uniform_heat_flux") -> CorrelationValue:
    """Fully developed laminar Nusselt number (exact)."""
    if boundary_condition == "uniform_heat_flux":
        return CorrelationValue(
            LAMINAR_NU_UNIFORM_HEAT_FLUX,
            "laminar (48/11)",
            uncertainty=0.0,
            notes="exact, uniform wall heat flux",
        )
    if boundary_condition == "uniform_wall_temperature":
        return CorrelationValue(
            LAMINAR_NU_UNIFORM_WALL_TEMP,
            "laminar (3.657)",
            uncertainty=0.0,
            notes="exact, uniform wall temperature",
        )
    raise ValueError(f"unknown boundary condition {boundary_condition!r}")


def nusselt_dittus_boelter(
    reynolds_number: float, prandtl_number: float, heating: bool = True
) -> CorrelationValue:
    """Dittus–Boelter: Nu = 0.023 Re^0.8 Pr^n, n = 0.4 (heating) / 0.3 (cooling).

    Valid for Re > 1e4, 0.6 <= Pr <= 160, L/D > 10.  Uncertainty up to 25 %.
    """
    n = 0.4 if heating else 0.3
    return CorrelationValue(
        0.023 * reynolds_number**0.8 * prandtl_number**n,
        "dittus_boelter",
        uncertainty=0.25,
        valid=reynolds_number >= 1e4 and 0.6 <= prandtl_number <= 160,
        inputs={"Re": reynolds_number, "Pr": prandtl_number, "heating": heating},
    )


def nusselt_gnielinski(
    reynolds_number: float, prandtl_number: float, friction: float | None = None
) -> CorrelationValue:
    """Gnielinski (1976): Nu = (f/8)(Re-1000)Pr / (1 + 12.7 sqrt(f/8)(Pr^(2/3)-1)).

    Valid for 3e3 <= Re <= 5e6 and 0.5 <= Pr <= 2000; accurate to ~10 %.
    ``friction`` defaults to Petukhov's smooth-pipe friction factor.
    """
    f = friction_factor_petukhov(reynolds_number).value if friction is None else friction
    f8 = f / 8.0
    nu = (
        f8
        * (reynolds_number - 1000.0)
        * prandtl_number
        / (1.0 + 12.7 * math.sqrt(f8) * (prandtl_number ** (2.0 / 3.0) - 1.0))
    )
    return CorrelationValue(
        nu,
        "gnielinski",
        uncertainty=0.10,
        valid=3e3 <= reynolds_number <= 5e6 and 0.5 <= prandtl_number <= 2000,
        inputs={"Re": reynolds_number, "Pr": prandtl_number, "f": f},
    )


def nusselt_petukhov(reynolds_number: float, prandtl_number: float) -> CorrelationValue:
    """Petukhov (1970): Nu = (f/8) Re Pr / (1.07 + 12.7 sqrt(f/8)(Pr^(2/3)-1)), 1e4 < Re < 5e6."""
    f8 = friction_factor_petukhov(reynolds_number).value / 8.0
    nu = (
        f8
        * reynolds_number
        * prandtl_number
        / (1.07 + 12.7 * math.sqrt(f8) * (prandtl_number ** (2.0 / 3.0) - 1.0))
    )
    return CorrelationValue(
        nu,
        "petukhov_nu",
        uncertainty=0.06,
        valid=1e4 <= reynolds_number <= 5e6 and 0.5 <= prandtl_number <= 2000,
        inputs={"Re": reynolds_number, "Pr": prandtl_number},
    )


def nusselt(reynolds_number: float, prandtl_number: float) -> CorrelationValue:
    """Regime-aware default: laminar exact value or Gnielinski."""
    if reynolds_number < 2300:
        return nusselt_laminar()
    return nusselt_gnielinski(reynolds_number, prandtl_number)


def entry_length_hydrodynamic(reynolds_number: float, diameter: float) -> float:
    """Hydrodynamic entry length: 0.05 Re D (laminar) or ~10 D (turbulent)."""
    if reynolds_number < 2300:
        return 0.05 * reynolds_number * diameter
    return 10.0 * diameter


def entry_length_thermal(reynolds_number: float, prandtl_number: float, diameter: float) -> float:
    """Thermal entry length: 0.05 Re Pr D (laminar) or ~10 D (turbulent)."""
    if reynolds_number < 2300:
        return 0.05 * reynolds_number * prandtl_number * diameter
    return 10.0 * diameter


# Registry used by the validation node ------------------------------------- #

REFERENCE_REGISTRY = {
    ("Nu", "laminar"): lambda Re, Pr: nusselt_laminar(),
    ("Nu", "gnielinski"): nusselt_gnielinski,
    ("Nu", "dittus_boelter"): nusselt_dittus_boelter,
    ("Nu", "petukhov"): nusselt_petukhov,
    ("f", "laminar"): lambda Re, Pr: friction_factor_laminar(Re),
    ("f", "blasius"): lambda Re, Pr: friction_factor_blasius(Re),
    ("f", "petukhov"): lambda Re, Pr: friction_factor_petukhov(Re),
    ("f", "prandtl_karman"): lambda Re, Pr: friction_factor_prandtl_karman(Re),
}


def reference_value(
    quantity: str, source: str, reynolds_number: float, prandtl_number: float
) -> CorrelationValue:
    """Look up a reference correlation by (quantity, source)."""
    key = (quantity, source)
    if key not in REFERENCE_REGISTRY:
        raise KeyError(f"no reference for {key}; available: {sorted(REFERENCE_REGISTRY)}")
    return REFERENCE_REGISTRY[key](reynolds_number, prandtl_number)
