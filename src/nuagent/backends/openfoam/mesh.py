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
    radial_count_clamped: bool = False  # the wall-function floor bound n_radial (degenerate family)
    yplus_note: str = ""

    def to_dict(self) -> dict:
        return {
            "n_axial": self.n_axial,
            "n_radial": self.n_radial,
            "radial_grading": self.radial_grading,
            "first_cell_height": self.first_cell_height,
            "expected_yplus": self.expected_yplus,
            "representative_h": self.representative_h,
            "n_cells": self.n_cells,
            "radial_count_clamped": self.radial_count_clamped,
            "yplus_note": self.yplus_note,
        }


def family_min_refinement(spec) -> float:
    """Coarsest refinement factor in the grid family a specification will actually run.

    ``verify`` builds levels at ``refinement_ratio ** -k`` for k = 0 .. n_levels-1, so the
    coarsest level is ``refinement_ratio ** -(n_levels - 1)``.  Returns 1.0 when no mesh study
    is requested, which reproduces single-grid behaviour.
    """
    v = getattr(spec, "verification", None)
    if v is None or not getattr(v, "mesh_study", False):
        return 1.0
    return float(v.refinement_ratio ** -(v.n_levels - 1))


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


def size_pipe_mesh(
    case: HeatedPipeCase, refinement: float = 1.0, family_min_refinement: float = 1.0
) -> PipeMesh:
    """Choose Nx, Nr and the radial grading for the requested refinement level.

    ``refinement`` scales the cell count in *both* directions (and the first-cell height), so
    successive levels are geometrically similar, as Celik et al. (2008) / ASME V&V 20 require.

    ``family_min_refinement`` is the *coarsest* refinement factor in the planned grid family
    (e.g. 0.25 for a three-level study at ratio 2).  It matters because a wall-resolved RANS
    closure is not the same model at y+ = 1 and at y+ = 4: if the y+ target were anchored to the
    base grid, the coarse levels would drift out of the wall-resolved regime and the family would
    mix discretisation error with a change of wall treatment.  The target is therefore anchored to
    the coarsest level, so **every** level satisfies it and the base grid is correspondingly finer.
    The default of 1.0 reproduces single-grid behaviour for a standalone build.
    """
    radius = 0.5 * case.diameter
    n_axial = max(
        4, int(round(case.mesh.cells_per_diameter * case.length_over_diameter * refinement))
    )
    n_radial = max(4, int(round(case.mesh.n_radial * refinement)))
    clamped = False
    yplus_note = ""
    family_min = min(max(family_min_refinement, 1e-6), 1.0)

    turbulent = case.turbulence_model.value != "laminar"
    if turbulent and case.wall_treatment is WallTreatment.RESOLVED:
        y_centre = first_cell_height_for_yplus(
            case.mesh.target_yplus, case.reynolds, case.diameter, case.fluid.nu
        )
        # anchored to the coarsest level: base y+ = target * family_min, coarsest y+ = target
        first = 2.0 * y_centre * family_min / refinement
        expected_yplus = case.mesh.target_yplus * family_min / refinement
        if family_min < 1.0:
            yplus_note = (
                f"y+ target {case.mesh.target_yplus:g} anchored to the coarsest level of the "
                f"family (refinement {family_min:g}); every level stays wall-resolved"
            )
    elif turbulent:
        # Wall functions need the first cell in the log layer, so here the *finest* level is the
        # binding constraint and the target is anchored to the base grid; coarser levels sit
        # higher in the log layer, which remains valid.
        y_centre = first_cell_height_for_yplus(40.0, case.reynolds, case.diameter, case.fluid.nu)
        first = 2.0 * y_centre / refinement
        expected_yplus = 40.0 / refinement
        n_radial_wanted = n_radial
        n_radial = max(4, min(n_radial, int(radius / first)))
        clamped = n_radial != n_radial_wanted
        if clamped:
            yplus_note = (
                f"radial count clamped from {n_radial_wanted} to {n_radial} so the first cell fits "
                "in the log layer; consecutive levels may not differ radially — check the family"
            )
    else:
        # laminar: mild wall refinement helps the wall temperature gradient
        first = 0.5 * radius / n_radial
        expected_yplus = None

    g = geometric_expansion_ratio(first, radius, n_radial)
    # cells grow away from the wall, i.e. shrink toward the wall: blockMesh grading = wall/axis = 1/g^(n-1)
    grading = 1.0 / g ** (n_radial - 1)
    actual_first = radius / n_radial if g == 1.0 else first
    if expected_yplus is not None and first > 0:
        expected_yplus *= actual_first / first  # uniform grids give a slightly taller first cell

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
        radial_count_clamped=clamped,
        yplus_note=yplus_note,
    )


# --------------------------------------------------------------------------- #
# Rib-roughened tube: multi-block wedge (core blocks + rib-layer blocks)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Segment:
    """One axial segment of the ribbed tube: ``kind`` in {smooth_in, gap, rib, smooth_out}."""

    kind: str
    x0: float
    x1: float
    n_axial: int
    axial_grading: str  # blockMesh grading spec along x (number or multi-grading list)
    module: int  # rib-module index (-1 for the smooth sections)


@dataclass(frozen=True)
class RibbedMesh:
    segments: list[Segment]
    n_core: int
    n_rib_layer: int
    core_grading: float  # (cell at rib-tip radius) / (cell at axis)
    rib_layer_grading: str  # blockMesh multi-grading spec for the rib layer
    first_cell_height: float
    expected_yplus: float | None
    representative_h: float
    n_cells: int
    radius: float
    rib_tip_radius: float
    yplus_note: str = ""

    @property
    def stations(self) -> list[float]:
        return [self.segments[0].x0] + [s.x1 for s in self.segments]

    def to_dict(self) -> dict:
        return {
            "n_segments": len(self.segments),
            "n_core": self.n_core,
            "n_rib_layer": self.n_rib_layer,
            "core_grading": self.core_grading,
            "rib_layer_grading": self.rib_layer_grading,
            "first_cell_height": self.first_cell_height,
            "expected_yplus": self.expected_yplus,
            "representative_h": self.representative_h,
            "n_cells": self.n_cells,
            "yplus_note": self.yplus_note,
            "modules": [{"x_start": s.x0, "x_end": s.x1} for s in self.segments if s.kind == "rib"],
        }


def _graded_cell_count(length: float, first: float, last: float) -> int:
    """Cells needed to span ``length`` with a geometric distribution from ``first`` to ``last``."""
    if abs(last - first) < 1e-12 * max(first, last):
        return max(1, int(round(length / first)))
    n = 2
    while True:
        q = (last / first) ** (1.0 / (n - 1))
        total = first * (q**n - 1.0) / (q - 1.0)
        if total >= length or n > 10_000:
            return n
        n += 1


def size_ribbed_mesh(
    case, refinement: float = 1.0, family_min_refinement: float = 1.0
) -> RibbedMesh:
    """Block layout and cell counts for :class:`~nuagent.spec.RibbedTubeCase`.

    All blocks share the core radial distribution (fine at the rib-tip radius, which is a
    wall in rib segments and the rib shear layer in gap segments) and the rib-layer
    distribution (double-graded: fine at the rib tip and at the tube wall).  ``refinement``
    scales every cell count and the first-cell height.
    """
    from nuagent.physics.correlations import webb_ribbed_tube

    R = 0.5 * case.diameter
    e, p, w = case.rib_height, case.rib_pitch, case.rib_width
    r1 = R - e
    mesh = case.mesh

    # First-cell height from the *local* wall shear between the ribs.
    #
    # Webb's correlation returns the TOTAL pressure-drop friction factor, which for e/D = 0.04,
    # p/e = 10 at Re = 2e4 is 9.15x the smooth-tube value -- but that excess is form drag on the
    # rib faces, not shear on the inter-rib floor.  Using it inflates u_tau by sqrt(9.15) ~ 3, so a
    # requested y+ = 40 wall-function mesh actually lands near y+ = 13, inside the buffer layer
    # where wall functions are invalid, while the metadata still claims 40.
    #
    # The floor shear lies between the smooth-tube value and the total; the smooth-tube value is
    # used as the defensible lower bound on u_tau (upper bound on the cell height), and BOTH
    # bounds are recorded so the reported y+ carries its own uncertainty instead of a false point
    # value.
    if case.turbulence_model.value != "laminar":
        from nuagent.physics.correlations import friction_factor_petukhov

        f_total = webb_ribbed_tube(
            case.reynolds, case.fluid.pr, case.rib_height_over_diameter, case.rib_pitch_over_height
        ).friction_darcy
        f_smooth = friction_factor_petukhov(case.reynolds).value
        u_tau = case.inlet_velocity * math.sqrt(f_smooth / 8.0)  # lower bound on the floor shear
        u_tau_hi = case.inlet_velocity * math.sqrt(f_total / 8.0)  # upper bound (total, incl. form)
        resolved = case.wall_treatment is WallTreatment.RESOLVED
        target = mesh.target_yplus if resolved else 40.0
        # wall-resolved families anchor the target to the coarsest level (see size_pipe_mesh)
        anchor = min(max(family_min_refinement, 1e-6), 1.0) if resolved else 1.0
        first = 2.0 * target * anchor * case.fluid.nu / u_tau / refinement
        expected_yplus = target * anchor / refinement
        yplus_hi = expected_yplus * u_tau_hi / u_tau
        yplus_note = (
            f"y+ estimated from the smooth-tube wall shear: {expected_yplus:.3g} "
            f"(upper bound {yplus_hi:.3g} if the floor carried Webb's total friction factor "
            f"f={f_total:.4g} rather than the smooth-tube f={f_smooth:.4g}); the rib form drag "
            "does not act on the inter-rib floor, so the true value sits between the two"
        )
    else:
        yplus_note = ""
        first = 0.5 * e / max(2, mesh.n_radial_rib)
        expected_yplus = None

    n_core = max(4, int(round(mesh.n_radial * refinement)))
    n_layer = max(2, int(round(mesh.n_radial_rib * refinement)))
    n_layer += n_layer % 2  # even, for the symmetric double grading
    g_core = geometric_expansion_ratio(first, r1, n_core)
    core_grading = 1.0 / g_core ** (n_core - 1)
    m = n_layer // 2
    g_layer = geometric_expansion_ratio(first, 0.5 * e, m)
    ratio = g_layer ** (m - 1)
    layer_grading = f"(({0.5} {0.5} {ratio:.6g}) ({0.5} {0.5} {1.0 / ratio:.6g}))"

    dx_fine = e / (mesh.cells_per_rib_height * refinement)
    dx_coarse = case.diameter / (mesh.cells_per_diameter * refinement)
    n_rib = max(2, int(round(w / dx_fine)))

    # gap segments: fine cells (dx_fine) at both rib faces growing by `stretch` toward the middle
    stretch = 4.0
    gap_len = p - w
    end_len = 0.25 * gap_len
    n_end = _graded_cell_count(end_len, dx_fine, stretch * dx_fine)
    n_mid = max(1, int(round(0.5 * gap_len / (stretch * dx_fine))))
    n_gap = 2 * n_end + n_mid
    f_end, f_mid = n_end / n_gap, n_mid / n_gap
    gap_grading = (
        f"((0.25 {f_end:.6g} {stretch:g}) (0.5 {f_mid:.6g} 1) (0.25 {f_end:.6g} {1.0 / stretch:g}))"
    )

    segments: list[Segment] = []
    x = 0.0
    L_in = case.inlet_length_over_diameter * case.diameter
    if L_in > 0:
        n_in = _graded_cell_count(L_in, dx_coarse, dx_fine)
        segments.append(Segment("smooth_in", x, x + L_in, n_in, f"{dx_fine / dx_coarse:.6g}", -1))
        x += L_in
    for k in range(case.n_ribs):
        segments.append(Segment("gap", x, x + p - w, n_gap, gap_grading, k))
        x += p - w
        segments.append(Segment("rib", x, x + w, n_rib, "1", k))
        x += w
    L_out = case.outlet_length_over_diameter * case.diameter
    if L_out > 0:
        n_out = _graded_cell_count(L_out, dx_fine, dx_coarse)
        segments.append(
            Segment("smooth_out", x, x + L_out, n_out, f"{dx_coarse / dx_fine:.6g}", -1)
        )
        x += L_out

    n_cells = sum(s.n_axial * (n_core + (n_layer if s.kind != "rib" else 0)) for s in segments)
    if n_cells > mesh.max_cells:
        raise ValueError(f"mesh of {n_cells} cells exceeds budget of {mesh.max_cells}")
    area = x * R - case.n_ribs * w * e
    return RibbedMesh(
        segments=segments,
        n_core=n_core,
        n_rib_layer=n_layer,
        core_grading=core_grading,
        rib_layer_grading=layer_grading,
        first_cell_height=first,
        expected_yplus=expected_yplus,
        yplus_note=yplus_note,
        representative_h=math.sqrt(area / n_cells),
        n_cells=n_cells,
        radius=R,
        rib_tip_radius=r1,
    )
