"""Reference lookup and comparison logic used by the validation node."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from nuagent.physics import analytical, correlations
from nuagent.spec import (
    HeatedPipeCase,
    PermeationCase,
    ReferenceSpec,
    RibbedTubeCase,
    SimulationSpec,
    TDSCase,
)


def analytical_reference(spec: SimulationSpec, quantity: str) -> tuple[float, str] | None:
    """Exact reference values where they exist."""
    case = spec.case
    if isinstance(case, HeatedPipeCase):
        if case.regime.value != "laminar" or isinstance(case, RibbedTubeCase):
            return None
        if quantity == "Nu":
            return (
                correlations.LAMINAR_NU_UNIFORM_HEAT_FLUX,
                "fully developed laminar, uniform heat flux: Nu = 48/11",
            )
        if quantity == "f":
            return 64.0 / case.reynolds, "Hagen-Poiseuille: f = 64/Re"
        return None
    if isinstance(case, PermeationCase):
        D = analytical.arrhenius(case.material.D_0, case.material.E_D, case.temperature)
        d_eff = D
        for tr in case.traps:
            d_eff = analytical.effective_diffusivity_from_trap(
                d_eff, case.temperature, tr.k_0, tr.E_k, tr.p_0, tr.E_p, tr.n
            )
        if quantity == "permeation_flux_ss":
            return analytical.permeation_steady_flux(
                D, case.upstream_concentration, case.thickness
            ), "J_ss = D c0 / L"
        if quantity == "time_lag":
            return analytical.permeation_time_lag(
                d_eff, case.thickness
            ), "t_lag = L^2 / (6 D_eff) (Oriani D_eff if traps)"
        if quantity == "D_eff":
            return d_eff, "Oriani effective diffusivity"
        return None
    if isinstance(case, TDSCase) and quantity == "T_peak" and case.traps:
        tr = case.traps[0]
        return (
            analytical.redhead_peak_temperature(
                tr.E_p, tr.p_0, case.ramp_rate, case.implantation_temperature
            ),
            "Redhead first-order peak temperature (fast-diffusion limit)",
        )
    return None


def dataset_reference(path: str, quantity: str) -> tuple[float, float, str]:
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if row.get("quantity") == quantity:
                return (
                    float(row["value"]),
                    float(row.get("uncertainty", 0.0) or 0.0),
                    f"dataset {Path(path).name}",
                )
    raise KeyError(f"{quantity} not found in dataset {path}")


def reference_for(spec: SimulationSpec, ref: ReferenceSpec) -> dict[str, Any]:
    """Resolve a ReferenceSpec into {value, uncertainty, source, valid, notes}."""
    if ref.source == "analytical":
        res = analytical_reference(spec, ref.quantity)
        if res is None:
            raise KeyError(f"no analytical reference for {ref.quantity} in this case")
        value, notes = res
        return {
            "value": value,
            "uncertainty": 0.0,
            "source": "analytical",
            "valid": True,
            "notes": notes,
        }
    if ref.source.startswith("dataset:"):
        value, unc, notes = dataset_reference(ref.source.split(":", 1)[1], ref.quantity)
        return {
            "value": value,
            "uncertainty": unc,
            "source": ref.source,
            "valid": True,
            "notes": notes,
        }
    case = spec.case
    if not isinstance(case, HeatedPipeCase):
        raise KeyError(f"correlation {ref.source!r} only applies to pipe-flow cases")
    geometry = {}
    if isinstance(case, RibbedTubeCase):
        geometry = {
            "e_over_D": case.rib_height_over_diameter,
            "p_over_e": case.rib_pitch_over_height,
        }
    cv = correlations.reference_value(
        ref.quantity, ref.source, case.reynolds, case.fluid.pr, **geometry
    )
    return {
        "value": cv.value,
        "uncertainty": cv.uncertainty,
        "source": cv.name,
        "valid": cv.valid,
        "notes": cv.notes,
    }


def compare(
    value: float, reference: dict[str, Any], tolerance: float, gci: float | None = None
) -> dict[str, Any]:
    ref = reference["value"]
    rel = (value - ref) / ref if ref else math.inf
    passed = abs(rel) <= tolerance
    band = reference.get("uncertainty", 0.0)
    within_band = abs(rel) <= band if band else None
    # numerical uncertainty band (GCI) overlapping the reference band counts as "consistent"
    consistent = None
    if gci is not None:
        lo, hi = value * (1 - gci), value * (1 + gci)
        rlo, rhi = ref * (1 - band), ref * (1 + band)
        consistent = not (hi < rlo or lo > rhi)
    return {
        "value": value,
        "reference": ref,
        "relative_error": rel,
        "tolerance": tolerance,
        "passed": bool(passed),
        "reference_uncertainty": band,
        "within_reference_band": within_band,
        "consistent_with_gci": consistent,
        "source": reference["source"],
        "reference_valid": reference.get("valid", True),
        "notes": reference.get("notes", ""),
    }
