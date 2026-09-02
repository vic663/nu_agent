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


def _wall_nut(tdir: Path, mesh, patch: str) -> np.ndarray:
    """Turbulent viscosity on a wall patch (zero for wall-resolved / laminar cases).

    Wall functions (``nutkWallFunction``) store the wall value of nu_t that makes
    tau_w = rho (nu + nu_t,w) dU/dn reproduce the log law; using it here makes the first-order wall-shear
    and y+ estimates consistent with OpenFOAM's own ``wallShearStress`` function object.
    """
    n = mesh.patches[patch].n_faces
    f = tdir / "nut"
    if not f.exists():
        return np.zeros(n)
    try:
        val = read_field(f).patch_value(patch, n)
        arr = np.asarray(val, dtype=float).reshape(-1)
        if arr.size == 1:
            arr = np.full(n, float(arr[0]))
        return np.nan_to_num(arr, nan=0.0)
    except Exception:  # noqa: BLE001 - fall back to the molecular estimate
        return np.zeros(n)


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
        tau_source = "near-wall velocity gradient (first-order estimate, mu + rho*nut_wall)"
        owners = mesh.patch_owner_cells("wall")[order]
        u_cell = U.internal_array[owners, 0]
        dn = np.linalg.norm(cc[owners] - wall_fc[order], axis=1)
        nut_w = _wall_nut(tdir, mesh, "wall")[order]
        tau_x = (fluid.mu + fluid.rho * nut_w) * np.abs(u_cell) / dn
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


# --------------------------------------------------------------------------- #
# Rib-roughened tube: module-averaged (periodic fully developed) quantities
# --------------------------------------------------------------------------- #


def extract_ribbed_tube_qois(case_dir: Path, case, stations: list[float]) -> QoIResult:
    """Per-pitch Nusselt number and friction factor of the rib-roughened tube.

    Conventions follow Webb, Eckert & Goldstein (1971): the heat-transfer coefficient is based
    on the *nominal* (smooth-tube) area pi*D*p of a pitch and on the bulk temperature from an
    energy balance that includes the heat added through the rib faces; the friction factor is
    based on the nominal diameter and bulk velocity.  The last ``developed_modules`` pitches
    before the final rib are averaged, and their spread is reported as a periodicity check.
    """
    case_dir = Path(case_dir)
    fluid = case.fluid
    D, R = case.diameter, 0.5 * case.diameter
    q = case.wall_heat_flux
    u_b = case.inlet_velocity
    mdot = corr.mass_flow_rate(fluid.rho, u_b, D)
    wedge_fraction = math.radians(case.mesh.wedge_angle_deg) / math.pi
    notes: list[str] = []
    checks: dict[str, float] = {}

    mesh = PolyMesh(case_dir / "constant" / "polyMesh")
    tdir = latest_time_dir(case_dir)
    T = read_field(tdir / "T")
    p = read_field(tdir / "p")

    # ---- wetted wall faces: centres, areas (wedge sector), temperatures ----------------
    fc = mesh.patch_face_centres("wall")
    areas = (
        np.linalg.norm(mesh.patch_face_areas("wall"), axis=1) / wedge_fraction
    )  # full-annulus areas
    t_wall = np.asarray(T.patch_value("wall", mesh.patches["wall"].n_faces), dtype=float)
    order = np.argsort(fc[:, 0])
    x_f, areas, t_wall, r_f = (
        fc[order, 0],
        areas[order],
        t_wall[order],
        np.hypot(fc[order, 1], fc[order, 2]),
    )

    # bulk temperature from the cumulative heat input (tube wall + rib faces)
    q_cum = np.cumsum(q * areas)
    t_bulk_faces = case.inlet_temperature + q_cum / (mdot * fluid.cp)

    # ---- module boundaries -------------------------------------------------------------
    L_in = case.inlet_length_over_diameter * case.diameter
    pitch = case.rib_pitch
    n = case.n_ribs
    first = (
        n - 1 - case.developed_modules
    )  # modules [first, n-1) are averaged; the last one is excluded
    module_nu, module_area_ratio, module_tw = [], [], []
    for k in range(first, n - 1):
        x0, x1 = L_in + k * pitch, L_in + (k + 1) * pitch
        sel = (x_f >= x0 - 1e-9) & (x_f < x1 - 1e-9)
        if sel.sum() == 0:
            continue
        a_wet = areas[sel].sum()
        a_nom = math.pi * D * pitch
        q_module = q * a_wet
        tw_mean = float((t_wall[sel] * areas[sel]).sum() / a_wet)
        tb_mid = float(np.interp(0.5 * (x0 + x1), x_f, t_bulk_faces))
        h = q_module / (a_nom * (tw_mean - tb_mid))
        module_nu.append(h * D / fluid.k)
        module_area_ratio.append(a_wet / a_nom)
        module_tw.append(tw_mean)
    if not module_nu:
        raise ValueError("no wall faces found in the developed modules; check the mesh layout")
    nu = float(np.mean(module_nu))
    checks["module_nu_spread"] = float(np.std(module_nu) / nu)
    # alternative definition used by wall-thermocouple experiments: nominal area with the *tube-wall*
    # (base) temperature rather than the average over all wetted faces (ribs run hotter)
    normals_all = mesh.patch_face_areas("wall")[order]
    radial_face = np.abs(normals_all[:, 0]) <= 0.5 * np.linalg.norm(normals_all, axis=1)
    base = radial_face & (r_f > R - 0.5 * case.rib_height)
    nu_base_modules = []
    for k in range(first, n - 1):
        x0, x1 = L_in + k * pitch, L_in + (k + 1) * pitch
        sel_all = (x_f >= x0 - 1e-9) & (x_f < x1 - 1e-9)
        sel_base = sel_all & base
        if sel_base.sum() == 0:
            continue
        tw_base = float((t_wall[sel_base] * areas[sel_base]).sum() / areas[sel_base].sum())
        tb_mid = float(np.interp(0.5 * (x0 + x1), x_f, t_bulk_faces))
        h_base = q * areas[sel_all].sum() / (math.pi * D * pitch * (tw_base - tb_mid))
        nu_base_modules.append(h_base * D / fluid.k)
    nu_base = float(np.mean(nu_base_modules)) if nu_base_modules else math.nan
    checks["wetted_to_nominal_area_ratio"] = float(np.mean(module_area_ratio))

    # ---- pressure gradient over the developed modules (near-axis cells) ---------------
    cc = mesh.cell_centres
    tree = cKDTree(cc)
    x_dev0, x_dev1 = L_in + first * pitch, L_in + (n - 1) * pitch
    xs = np.linspace(x_dev0, x_dev1, 41)
    _, idx = tree.query(np.array([[x, 0.3 * R, 0.0] for x in xs]))
    p_axis = p.internal_array[idx]
    slope = float(np.polyfit(cc[idx, 0], p_axis, 1)[0])
    f_dp = corr.darcy_from_pressure_drop(-slope, 1.0, D, fluid.rho, u_b)
    # per-pitch pressure drop from the mean module values (robust to the periodic wiggle)
    dp_pitch = -slope * pitch

    # ---- smooth-tube baselines and enhancement ratios ----------------------------------
    nu0 = corr.nusselt(case.reynolds, fluid.pr).value
    f0 = corr.friction_factor(case.reynolds).value
    nu_ratio, f_ratio = nu / nu0, f_dp / f0
    eta = corr.thermal_performance_factor(nu_ratio, f_ratio)

    # ---- mass and energy balances ---------------------------------------------------------
    try:
        phi = read_field(tdir / "phi")
        phi_out = np.asarray(phi.patch_value("outlet", mesh.patches["outlet"].n_faces), dtype=float)
        t_out = np.asarray(T.patch_value("outlet", mesh.patches["outlet"].n_faces), dtype=float)
        mdot_wedge = mdot * wedge_fraction
        checks["mass_balance_error"] = float((phi_out.sum() - mdot_wedge) / mdot_wedge)
        t_out_cfd = float((phi_out * t_out).sum() / phi_out.sum())
        rise_eb = float(q_cum[-1] / (mdot * fluid.cp))
        checks["outlet_bulk_temperature"] = t_out_cfd
        checks["energy_balance_error"] = float(
            ((t_out_cfd - case.inlet_temperature) - rise_eb) / rise_eb
        )
    except (FileNotFoundError, KeyError, ValueError) as exc:
        notes.append(f"mass/energy balance unavailable: {exc}")

    # ---- surface breakdown of the developed modules: tube wall / rib tops / rib sides ------
    # (face-centre radius of the wedge wall is R*cos(theta), so classify with rib-height tolerances)
    e = case.rib_height
    dev = (x_f >= L_in + first * pitch - 1e-9) & (x_f < L_in + (n - 1) * pitch - 1e-9)
    normals = mesh.patch_face_areas("wall")[order]
    axial_face = np.abs(normals[:, 0]) > 0.5 * np.linalg.norm(normals, axis=1)
    rib_side = axial_face  # upstream/downstream rib faces
    tube_wall = ~axial_face & (r_f > R - 0.5 * e)
    rib_top = ~axial_face & ~tube_wall
    for name, mask in (("tube_wall", tube_wall), ("rib_top", rib_top), ("rib_side", rib_side)):
        m = mask & dev
        if m.any():
            h_loc = q / (t_wall[m] - t_bulk_faces[m])
            checks[f"Nu_{name}_developed"] = float(
                (h_loc * areas[m]).sum() / areas[m].sum() * D / fluid.k
            )
            checks[f"area_fraction_{name}"] = float(areas[m].sum() / areas[dev].sum())

    # ---- reattachment point on the inter-rib wall (k-type vs d-type roughness diagnostic) ----
    U = read_field(tdir / "U")
    owners = mesh.patch_owner_cells("wall")[order]
    k_mod = n - 2  # a developed module
    x_mod = L_in + k_mod * pitch
    sel = tube_wall & (x_f >= x_mod - 1e-9) & (x_f < x_mod + pitch - 1e-9)
    if sel.sum() > 3:
        ux_wall = U.internal_array[owners[sel], 0]
        xs = x_f[sel]
        # first downstream location where the near-wall streamwise velocity turns positive after the rib
        neg = np.where(ux_wall < 0)[0]
        if neg.size == 0:
            checks["reattachment_x_over_e"] = 0.0
        else:
            after = np.where((np.arange(len(xs)) > neg[0]) & (ux_wall > 0))[0]
            checks["reattachment_x_over_e"] = (
                float((xs[after[0]] - x_mod) / e) if after.size else float("nan")
            )
        checks["reversed_flow_fraction_of_gap"] = float(
            areas[sel][ux_wall < 0].sum() / areas[sel].sum()
        )

    # ---- y+ estimate on the tube wall between ribs (near-wall gradient) -------------------
    if tube_wall.any():
        dn = np.linalg.norm(cc[owners[tube_wall]] - fc[order][tube_wall], axis=1)
        u_cell = np.abs(U.internal_array[owners[tube_wall], 0])
        nut_w = _wall_nut(tdir, mesh, "wall")[order][tube_wall]
        tau = (fluid.mu + fluid.rho * nut_w) * u_cell / dn
        u_tau = np.sqrt(np.mean(tau) / fluid.rho)
        checks["yplus_avg_estimate"] = float(np.mean(dn) * u_tau / fluid.nu)
    notes.append(
        "Nu: nominal area pi*D*p with the area-weighted temperature of all wetted faces; "
        "Nu_base: same heat input but the tube-wall (base) temperature, as wall-thermocouple experiments measure"
    )
    notes.append(
        f"averaged modules {first + 1}-{n - 1} of {n}; last module excluded (exit effects)"
    )

    values = {
        "Nu": nu,
        "Nu_base": nu_base,
        "f": f_dp,
        "Nu_over_Nu0": nu_ratio,
        "f_over_f0": f_ratio,
        "thermal_performance": eta,
        "dp_per_pitch": dp_pitch,
        "Re": case.reynolds,
        "Pr": fluid.pr,
        "e_plus": float(case.rib_height_over_diameter * case.reynolds * math.sqrt(f_dp / 8.0)),
        "n_cells": float(mesh.n_cells),
    }
    profiles = {
        "x": x_f.tolist(),
        "T_wall": t_wall.tolist(),
        "T_bulk": t_bulk_faces.tolist(),
        "module_Nu": module_nu,
        "module_T_wall": module_tw,
        "x_p": cc[idx, 0].tolist(),
        "p": p_axis.tolist(),
    }
    return QoIResult(values=values, profiles=profiles, checks=checks, notes=notes)
