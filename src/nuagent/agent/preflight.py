"""Pre-flight review of a specification *before* any solver time is spent.

This is the "verifier" half of a generator–verifier pair: whatever produced the specification
(a human, the rules planner or an LLM), an independent, deterministic reviewer checks it against
the physics knowledge encoded in the correlation registry and in the lessons learned from earlier
runs.  Findings are advisory (the workflow proceeds) unless marked blocking.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from nuagent.physics import correlations as corr
from nuagent.spec import (
    HeatedPipeCase,
    PermeationCase,
    RibbedTubeCase,
    SimulationSpec,
    TDSCase,
    TurbulenceModel,
    WallTreatment,
)


@dataclass
class PreflightReview:
    warnings: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def preflight(spec: SimulationSpec) -> PreflightReview:
    r = PreflightReview()
    case = spec.case

    # ---- validation references: are the correlations valid for these inputs? ---------------
    if isinstance(case, HeatedPipeCase):
        geometry = {}
        if isinstance(case, RibbedTubeCase):
            geometry = {
                "e_over_D": case.rib_height_over_diameter,
                "p_over_e": case.rib_pitch_over_height,
            }
        for ref in spec.validation.references:
            if ref.source in ("analytical",) or ref.source.startswith("dataset:"):
                continue
            try:
                cv = corr.reference_value(
                    ref.quantity, ref.source, case.reynolds, case.fluid.pr, **geometry
                )
            except KeyError as exc:
                r.blocking.append(
                    f"reference {ref.quantity}/{ref.source} cannot be evaluated: {exc}"
                )
                continue
            if not cv.valid:
                r.warnings.append(
                    f"reference {ref.quantity} vs {ref.source} is outside the correlation's stated validity "
                    f"range for Re={case.reynolds:.3g}, Pr={case.fluid.pr:.2f}"
                    + (f" ({cv.notes})" if cv.notes else "")
                )

        # ---- wall treatment vs target y+ ----------------------------------------------------
        turbulent = case.turbulence_model is not TurbulenceModel.LAMINAR
        if (
            turbulent
            and case.wall_treatment is WallTreatment.RESOLVED
            and case.mesh.target_yplus > 2
        ):
            r.warnings.append(
                f"wall-resolved treatment with target y+ = {case.mesh.target_yplus:g}: low-Re integration "
                "needs y+ <~ 1-2 at the first cell"
            )

        # ---- development length -------------------------------------------------------------
        if not isinstance(case, RibbedTubeCase):
            x_eval = (1.0 - case.developed_fraction) * case.length
            l_hyd = corr.entry_length_hydrodynamic(case.reynolds, case.diameter)
            l_th = corr.entry_length_thermal(case.reynolds, case.fluid.pr, case.diameter)
            l_dev = max(l_hyd, l_th)
            detail = (
                f"entry length ~{l_dev / case.diameter:.1f} D (hydrodynamic "
                f"{l_hyd / case.diameter:.1f} D, thermal {l_th / case.diameter:.1f} D)"
            )
            developed_refs = {
                "laminar",
                "gnielinski",
                "dittus_boelter",
                "petukhov",
                "blasius",
                "prandtl_karman",
            }
            validates_developed = (
                any(ref.source in developed_refs for ref in spec.validation.references)
                or not spec.validation.references
            )
            if l_dev > case.length and validates_developed:
                # The flow never becomes fully developed anywhere in the domain, so the
                # fully-developed correlations this case is scored against are unreachable by
                # construction.  Blocking: no amount of mesh refinement or extra iterations fixes
                # a geometry that is too short.
                r.blocking.append(
                    f"the pipe is {case.length_over_diameter:.0f} D long but the flow needs "
                    f"{l_dev / case.diameter:.0f} D to become fully developed ({detail}); a "
                    "fully-developed correlation cannot be validated in this geometry — lengthen "
                    "the pipe, lower Re or Pr, or validate against a developing-flow reference"
                )
            elif x_eval < l_dev:
                r.warnings.append(
                    f"evaluation region starts at x = {x_eval / case.diameter:.1f} D but the "
                    f"{detail}: increase length_over_diameter or decrease developed_fraction"
                )

        # ---- lessons learned: closures for rib-roughened passages ---------------------------
        if isinstance(case, RibbedTubeCase):
            if case.turbulence_model is TurbulenceModel.K_OMEGA_SST:
                r.warnings.append(
                    "k-omega SST predicted a cavity (d-type) flow with no reattachment for p/e = 10 ribs in "
                    "earlier NuAgent runs (f and Nu 50-65 % low); prefer LaunderSharmaKE or kEpsilon, or "
                    "add a model_form closure ensemble"
                )
            if case.n_ribs < 8:
                r.warnings.append(
                    f"only {case.n_ribs} ribs: periodic fully developed flow needs ~6-8 pitches before the "
                    "averaged modules"
                )
            if case.mesh.cells_per_rib_height < 6:
                r.warnings.append(
                    f"{case.mesh.cells_per_rib_height:g} axial cells per rib height under-resolves the rib "
                    "faces (10 recommended)"
                )
            if not (0.01 <= case.rib_height_over_diameter <= 0.04) and any(
                ref.source == "webb" for ref in spec.validation.references
            ):
                r.warnings.append(
                    f"e/D = {case.rib_height_over_diameter:g} is outside Webb's 0.01-0.04 range; the Webb "
                    "reference is an extrapolation"
                )

    # ---- FESTIM cases --------------------------------------------------------------------
    if isinstance(case, PermeationCase):
        from nuagent.physics.analytical import arrhenius

        D = arrhenius(case.material.D_0, case.material.E_D, case.temperature)
        t_diff = case.thickness**2 / D
        if case.final_time is not None and case.final_time < 3.0 * t_diff:
            r.warnings.append(
                f"final_time = {case.final_time:.3g} s is shorter than 3 L^2/D = {3 * t_diff:.3g} s; the "
                "steady permeation flux will not be reached"
            )
        # Transient-resolution heuristic for trapped (nonlinear) cases only.  For trap-free
        # permeation the time lag is extracted exactly for any step size (right-endpoint sum over
        # the backward-Euler samples; CI run #4: 400 steps -> 0.002 %), so step count is not an
        # accuracy criterion there and must not read like one.  Advisory, never a gate.  The old
        # form `0.05 * t_diff / 6.0 * 6` collapsed to 0.05 t_diff = 0.3 t_lag, six times looser
        # than the t_lag / 20 it claimed.
        if case.traps:
            dt = (case.final_time or 6.0 * t_diff) / case.n_steps
            t_lag = t_diff / 6.0
            if dt > t_lag / 20.0:
                r.warnings.append(
                    f"transient resolution: time step {dt:.3g} s gives fewer than ~20 steps per "
                    f"nominal diffusion time lag L^2/6D = {t_lag:.3g} s; a heuristic for resolving "
                    "trapping transients, not a validation or accuracy criterion"
                )
    if isinstance(case, TDSCase) and not case.traps:
        r.blocking.append("TDS case needs at least one trap")

    # ---- execution --------------------------------------------------------------------------
    if spec.execution.executor.value == "slurm" and not spec.execution.require_approval:
        r.notes.append(
            "SLURM submission without human approval gate (execution.require_approval=false)"
        )
    if (
        spec.verification.mesh_study
        and spec.verification.refinement_ratio > 1.5
        and isinstance(case, RibbedTubeCase)
    ):
        r.warnings.append(
            f"refinement ratio {spec.verification.refinement_ratio:g} on a ribbed geometry leaves the coarse "
            "levels with too few cells across a rib; 1.3-1.5 keeps the grid family in the asymptotic range"
        )
    return r
