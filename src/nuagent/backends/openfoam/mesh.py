"""Structured-mesh sizing helpers for the axisymmetric pipe."""

from __future__ import annotations

import math
from dataclasses import dataclass

from nuagent.physics.correlations import first_cell_height_for_yplus
from nuagent.spec import HeatedPipeCase, WallTreatment


@dataclass(frozen=True)
class PipeMesh:
    n_axial: int
    n_radial: int
    radial_grading: float  # blockMesh simpleGrading value: (wall cell size) / (axis cell size)
    first_cell_height: float  # wall-adjacent cell height [m]
    expected_yplus: float | None
    representative_h: float  # sqrt(area / n_cells) [m]
    n_cells: int

    def to_dict(self) -> dict:
        return {
            "n_axial": self.n_axial,
            "n_radial": self.n_radial,
            "radial_grading": self.radial_grading,
            "first_cell_height": self.first_cell_height,
            "expected_yplus": self.expected_yplus,
            "representative_h": self.representative_h,
            "n_cells": self.n_cells,
        }


def geometric_expansion_ratio(first: float, total: float, n: int) -> float:
    """Solve first * (g^n - 1)/(g - 1) = total for the growth ratio g > 0 (bisection)."""
    if n <= 1:
        return 1.0
    uniform = total / n
    if (
        first >= uniform
    ):  # a uniform (or wall-coarsened) distribution — do not coarsen toward the wall
        return 1.0

    def length(g: float) -> float:
        return first * n if abs(g - 1.0) < 1e-12 else first * (g**n - 1.0) / (g - 1.0)

    lo, hi = 1.0, 1.0
    while length(hi) < total:
        hi *= 1.5
        if hi > 1e3:  # pragma: no cover
            raise ValueError("cannot satisfy first-cell height with this cell count")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if length(mid) < total:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def size_pipe_mesh(case: HeatedPipeCase, refinement: float = 1.0) -> PipeMesh:
    """Choose Nx, Nr and the radial grading for the requested refinement level.

    ``refinement`` scales the cell count in *both* directions (and the target
    first-cell height), so successive levels form a consistent family for the
    grid-convergence study.
    """
    radius = 0.5 * case.diameter
    n_axial = max(
        4, int(round(case.mesh.cells_per_diameter * case.length_over_diameter * refinement))
    )
    n_radial = max(4, int(round(case.mesh.n_radial * refinement)))

    turbulent = case.turbulence_model.value != "laminar"
    if turbulent and case.wall_treatment is WallTreatment.RESOLVED:
        y_centre = first_cell_height_for_yplus(
            case.mesh.target_yplus, case.reynolds, case.diameter, case.fluid.nu
        )
        first = 2.0 * y_centre / refinement
        expected_yplus = case.mesh.target_yplus / refinement
    elif turbulent:
        # wall functions: aim for y+ ~ 40 on the base grid
        y_centre = first_cell_height_for_yplus(40.0, case.reynolds, case.diameter, case.fluid.nu)
        first = 2.0 * y_centre / refinement
        expected_yplus = 40.0 / refinement
    else:
        # laminar: mild wall refinement helps the wall temperature gradient
        first = 0.5 * radius / n_radial
        expected_yplus = None

    g = geometric_expansion_ratio(first, radius, n_radial)
    # cells grow away from the wall, i.e. shrink toward the wall: blockMesh grading = wall/axis = 1/g^(n-1)
    grading = 1.0 / g ** (n_radial - 1)
    actual_first = radius / n_radial if g == 1.0 else first

    n_cells = n_axial * n_radial
    if n_cells > case.mesh.max_cells:
        raise ValueError(f"mesh of {n_cells} cells exceeds budget of {case.mesh.max_cells}")
    area = case.length * radius
    return PipeMesh(
        n_axial=n_axial,
        n_radial=n_radial,
        radial_grading=grading,
        first_cell_height=actual_first,
        expected_yplus=expected_yplus,
        representative_h=math.sqrt(area / n_cells),
        n_cells=n_cells,
    )
