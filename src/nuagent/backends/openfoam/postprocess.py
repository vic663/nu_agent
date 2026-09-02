"""Derive heated-pipe QoIs from the raw fields written by OpenFOAM.

Everything is computed from ``T``, ``U``, ``p``, ``phi`` at the latest time and
the ``constant/polyMesh`` geometry, so the extraction does not depend on
function objects or ParaView and behaves identically on every OpenFOAM
version.  When ``wallShearStress`` / ``yPlus`` fields exist (written by
``postProcess`` in ``Allrun``) they are used; otherwise a near-wall
finite-difference estimate is reported and flagged as such.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from nuagent.backends.base import QoIResult
from nuagent.backends.openfoam.foamio import PolyMesh, latest_time_dir, read_field
from nuagent.physics import correlations as corr
from nuagent.spec import HeatedPipeCase


def _developed_mask(x: np.ndarray, case: HeatedPipeCase) -> np.ndarray:
    L = case.length
    mask = (x >= (1.0 - case.developed_fraction) * L) & (x <= 0.97 * L)
    return mask


def extract_heated_pipe_qois(
    case_dir: Path, case: HeatedPipeCase, stations: list[float]
) -> QoIResult:
    """Compute Nu, f and consistency checks for a finished heated-pipe run."""
    case_dir = Path(case_dir)
    fluid = case.fluid
    D, L, R = case.diameter, case.length, 0.5 * case.diameter
    q = case.wall_heat_flux
    u_b = case.inlet_velocity
    mdot = corr.mass_flow_rate(fluid.rho, u_b, D)
    notes: list[str] = []
    checks: dict[str, float] = {}

    mesh = PolyMesh(case_dir / "constant" / "polyMesh")
    tdir = latest_time_dir(case_dir)
    T = read_field(tdir / "T")
    U = read_field(tdir / "U")
    p = read_field(tdir / "p")

    # ---- wall temperature and local Nusselt number ----------------------
    wall_fc = mesh.patch_face_centres("wall")
    x_w = wall_fc[:, 0]
    order = np.argsort(x_w)
    x_w = x_w[order]
    t_wall = np.asarray(T.patch_value("wall", mesh.patches["wall"].n_faces), dtype=float)[order]
    t_bulk = np.array(
        [corr.bulk_temperature(xi, case.inlet_temperature, q, D, mdot, fluid.cp) for xi in x_w]
    )
    nu_local = np.array(
        [corr.nusselt_local(q, D, fluid.k, tw, tb) for tw, tb in zip(t_wall, t_bulk, strict=True)]
    )

    developed = _developed_mask(x_w, case)
    if developed.sum() < 2:
        developed = x_w >= 0.5 * L
        notes.append("fewer than two wall faces in the requested developed region; using x > L/2")
    nu_fd = float(np.mean(nu_local[developed]))
    nu_std = float(np.std(nu_local[developed]))

    # ---- pressure gradient along the pipe (near-axis cells) -------------
    cc = mesh.cell_centres
    tree = cKDTree(cc)
    probe_pts = np.array([[xs, 0.3 * R, 0.0] for xs in stations])
    _, idx = tree.query(probe_pts)
    p_int = p.internal_array
    p_axis = p_int[idx]
    x_p = cc[idx, 0]
    dev_p = _developed_mask(x_p, case)
    if dev_p.sum() >= 2:
        slope = float(np.polyfit(x_p[dev_p], p_axis[dev_p], 1)[0])  # dp/dx (negative)
        f_dp = corr.darcy_from_pressure_drop(-slope, 1.0, D, fluid.rho, u_b)
    else:
        slope, f_dp = math.nan, math.nan
        notes.append("not enough axial stations for dp/dx")

    # ---- wall shear stress: postProcess field if present, else estimate --
    tau_source = "wallShearStress field"
    tau_file = tdir / "wallShearStress"
    if tau_file.exists():
        tau_vec = np.asarray(
            read_field(tau_file).patch_value("wall", mesh.patches["wall"].n_faces), dtype=float
        )[order]
        tau_x = np.abs(tau_vec[:, 0])
    else:
        tau_source = "near-wall velocity gradient (first-order estimate)"
        owners = mesh.patch_owner_cells("wall")[order]
        u_cell = U.internal_array[owners, 0]
        dn = np.linalg.norm(cc[owners] - wall_fc[order], axis=1)
        tau_x = fluid.mu * np.abs(u_cell) / dn
        notes.append(f"wall shear stress from {tau_source}")
    f_tau = float(corr.darcy_from_wall_shear(np.mean(tau_x[developed]), fluid.rho, u_b))
    checks["tau_wall_developed"] = float(np.mean(tau_x[developed]))
    if math.isfinite(f_dp) and f_tau:
        checks["friction_factor_consistency"] = float((f_dp - f_tau) / f_tau)

    # ---- y+ ---------------------------------------------------------------
    yplus_file = tdir / "yPlus"
    if yplus_file.exists():
        yp = np.asarray(
            read_field(yplus_file).patch_value("wall", mesh.patches["wall"].n_faces), dtype=float
        )
        checks["yplus_min"], checks["yplus_max"], checks["yplus_avg"] = (
            float(yp.min()),
            float(yp.max()),
            float(yp.mean()),
        )
    else:
        owners = mesh.patch_owner_cells("wall")[order]
        dn = np.linalg.norm(cc[owners] - wall_fc[order], axis=1)
        u_tau = np.sqrt(np.mean(tau_x[developed]) / fluid.rho)
        yp_est = float(np.mean(dn[developed]) * u_tau / fluid.nu)
        checks["yplus_avg_estimate"] = yp_est

    # ---- mass and energy balance ------------------------------------------
    try:
        phi = read_field(tdir / "phi")
        phi_out = np.asarray(phi.patch_value("outlet", mesh.patches["outlet"].n_faces), dtype=float)
        t_out = np.asarray(T.patch_value("outlet", mesh.patches["outlet"].n_faces), dtype=float)
        wedge_fraction = math.radians(case.mesh.wedge_angle_deg) / math.pi
        mdot_wedge = mdot * wedge_fraction
        checks["mass_balance_error"] = float((phi_out.sum() - mdot_wedge) / mdot_wedge)
        t_out_cfd = float((phi_out * t_out).sum() / phi_out.sum())
        t_out_eb = corr.bulk_temperature(L, case.inlet_temperature, q, D, mdot, fluid.cp)
        rise_eb = t_out_eb - case.inlet_temperature
        checks["outlet_bulk_temperature"] = t_out_cfd
        checks["energy_balance_error"] = (
            float(((t_out_cfd - case.inlet_temperature) - rise_eb) / rise_eb)
            if rise_eb
            else math.nan
        )
    except (FileNotFoundError, KeyError, ValueError) as exc:
        notes.append(f"mass/energy balance unavailable: {exc}")

    values = {
        "Nu": nu_fd,
        "Nu_std_developed": nu_std,
        "f": f_dp if math.isfinite(f_dp) else f_tau,
        "f_dp": f_dp,
        "f_tau": f_tau,
        "Re": case.reynolds,
        "Pr": fluid.pr,
        "T_wall_outlet": float(t_wall[-1]),
        "dp_per_length": float(-slope) if math.isfinite(slope) else math.nan,
        "n_cells": float(mesh.n_cells),
    }
    profiles = {
        "x": x_w.tolist(),
        "T_wall": t_wall.tolist(),
        "T_bulk": t_bulk.tolist(),
        "Nu_local": nu_local.tolist(),
        "tau_wall": tau_x.tolist(),
        "x_p": x_p.tolist(),
        "p": p_axis.tolist(),
    }
    notes.append(f"friction factor 'f' taken from dp/dx; f_tau uses {tau_source}")
    return QoIResult(values=values, profiles=profiles, checks=checks, notes=notes)
