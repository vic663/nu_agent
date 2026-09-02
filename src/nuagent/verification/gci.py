"""Richardson extrapolation and the Grid Convergence Index (GCI).

Implements the procedure recommended by the ASME Journal of Fluids Engineering
(Celik, Ghia, Roache, Freitas, Coleman & Raad, 2008, "Procedure for Estimation
and Reporting of Uncertainty Due to Discretization in CFD Applications") and
ASME V&V 20-2009.

Given three systematically refined grids (fine ``h1 < h2 < h3``) with
solutions ``f1, f2, f3`` and refinement ratios ``r21 = h2/h1``, ``r32 = h3/h2``:

    eps21 = f2 - f1,  eps32 = f3 - f2
    p     = | ln|eps32/eps21| + q(p) | / ln r21          (observed order)
    q(p)  = ln( (r21^p - s) / (r32^p - s) ),  s = sign(eps32/eps21)
    f_ext = (r21^p f1 - f2) / (r21^p - 1)              (extrapolated value)
    GCI_fine = 1.25 |eps21 / f1| / (r21^p - 1)         (numerical uncertainty, 95 %)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


def relative_error(value: float, reference: float) -> float:
    """Signed relative error (value - reference) / |reference|."""
    if reference == 0:
        return math.inf if value != 0 else 0.0
    return (value - reference) / abs(reference)


@dataclass
class GridConvergenceResult:
    quantity: str
    h: list[float]  # representative cell sizes, fine -> coarse
    f: list[float]  # solutions, fine -> coarse
    observed_order: float | None
    extrapolated: float | None
    gci_fine: float | None  # relative, 95 % band on the fine-grid solution
    convergence: str  # "monotonic", "oscillatory", "divergent", "converged_exactly"
    asymptotic_ratio: float | None  # GCI32 / (r21^p GCI21) ~ 1 in the asymptotic range
    notes: str = ""

    @property
    def is_asymptotic(self) -> bool:
        return self.asymptotic_ratio is not None and 0.9 <= self.asymptotic_ratio <= 1.1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_asymptotic"] = self.is_asymptotic
        return d


def richardson_extrapolation(f1: float, f2: float, r: float, p: float) -> float:
    """Generalised Richardson extrapolation f_ext = (r^p f1 - f2) / (r^p - 1)."""
    return (r**p * f1 - f2) / (r**p - 1.0)


def _observed_order(
    eps21: float, eps32: float, r21: float, r32: float, max_iter: int = 200
) -> float:
    """Fixed-point iteration for the observed order p (Celik et al. 2008, eq. 3)."""
    ratio = eps32 / eps21
    s = 1.0 if ratio > 0 else -1.0
    p = abs(math.log(abs(ratio))) / math.log(r21)  # initial guess (equal ratios)
    for _ in range(max_iter):
        q = math.log((r21**p - s) / (r32**p - s)) if not math.isclose(r21, r32) else 0.0
        p_new = abs(math.log(abs(ratio)) + q) / math.log(r21)
        if abs(p_new - p) < 1e-10:
            return p_new
        p = p_new
    return p


def grid_convergence_index(
    quantity: str,
    h: list[float],
    f: list[float],
    safety_factor: float = 1.25,
    exact: float | None = None,
) -> GridConvergenceResult:
    """Three-grid GCI analysis.  ``h`` and ``f`` are ordered fine -> coarse.

    If only two grids are supplied the theoretical order ``p = 2`` is assumed
    and ``safety_factor`` should be 3 (Roache).  If ``exact`` is given the
    notes report the fine-grid discretisation error against it.
    """
    if len(h) != len(f) or len(h) < 2:
        raise ValueError("need at least two (h, f) pairs ordered fine -> coarse")
    if any(h[i] >= h[i + 1] for i in range(len(h) - 1)):
        raise ValueError("h must be strictly increasing (fine -> coarse)")

    notes = []
    if exact is not None:
        notes.append(f"fine-grid error vs exact: {relative_error(f[0], exact) * 100:.3f} %")

    if len(h) == 2:
        r21 = h[1] / h[0]
        p = 2.0
        eps21 = f[1] - f[0]
        if eps21 == 0:
            return GridConvergenceResult(
                quantity, h, f, None, f[0], 0.0, "converged_exactly", None, "; ".join(notes)
            )
        f_ext = richardson_extrapolation(f[0], f[1], r21, p)
        gci = 3.0 * abs(eps21 / f[0]) / (r21**p - 1.0) if f[0] != 0 else math.inf
        notes.append("two-grid estimate with assumed order p=2 and Fs=3")
        return GridConvergenceResult(
            quantity, h, f, p, f_ext, gci, "monotonic", None, "; ".join(notes)
        )

    f1, f2, f3 = f[:3]
    r21, r32 = h[1] / h[0], h[2] / h[1]
    eps21, eps32 = f2 - f1, f3 - f2

    if eps21 == 0 and eps32 == 0:
        return GridConvergenceResult(
            quantity, h[:3], f[:3], None, f1, 0.0, "converged_exactly", None, "; ".join(notes)
        )
    if eps21 == 0 or eps32 == 0:
        notes.append("one of the differences is exactly zero; order cannot be estimated")
        return GridConvergenceResult(
            quantity, h[:3], f[:3], None, f1, None, "monotonic", None, "; ".join(notes)
        )

    ratio = eps32 / eps21
    if ratio < 0:
        convergence = "oscillatory"
    elif abs(ratio) < 1.0:
        convergence = "divergent"
    else:
        convergence = "monotonic"

    p = _observed_order(eps21, eps32, r21, r32)
    if not math.isfinite(p) or p <= 0:
        notes.append("observed order not positive; grids are likely outside the asymptotic range")
        return GridConvergenceResult(
            quantity, h[:3], f[:3], p, None, None, convergence, None, "; ".join(notes)
        )

    f_ext = richardson_extrapolation(f1, f2, r21, p)
    ea21 = abs(eps21 / f1) if f1 != 0 else math.inf
    ea32 = abs(eps32 / f2) if f2 != 0 else math.inf
    gci21 = safety_factor * ea21 / (r21**p - 1.0)
    gci32 = safety_factor * ea32 / (r32**p - 1.0)
    asymptotic_ratio = gci32 / (r21**p * gci21) if gci21 > 0 else None

    if p > 4.0:
        notes.append(f"observed order p={p:.2f} exceeds the formal order; GCI may be optimistic")
    if convergence == "oscillatory":
        notes.append("oscillatory convergence: GCI reported but should be interpreted with caution")

    return GridConvergenceResult(
        quantity=quantity,
        h=h[:3],
        f=f[:3],
        observed_order=p,
        extrapolated=f_ext,
        gci_fine=gci21,
        convergence=convergence,
        asymptotic_ratio=asymptotic_ratio,
        notes="; ".join(notes),
    )
