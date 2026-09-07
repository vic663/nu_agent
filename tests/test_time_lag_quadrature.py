"""Time-lag quadrature contract for FESTIM output (fixture-free, NumPy only; no solver needed).

Backward Euler for the semi-discrete diffusion problem  M y' = K y + b  makes the deficits
d_n = y_ss - y_n obey  M (d_{n+1} - d_n) = dt_n K d_{n+1}.  Summing from n = 0 with d_inf = 0:

    sum_{n>=1} dt_{n-1} d_n  =  -K^-1 M d_0  =  integral_0^inf d(t) dt   (of the semi-discrete system)

for *any* step sequence.  The downstream flux is a linear functional of the state, so the
Daynes-Barrer time lag  integral (J_ss - J) dt / J_ss  evaluated as a right-endpoint sum over the
exported samples (t_1 = dt ... t_N; FESTIM writes no t = 0 row) reproduces the discrete integral
exactly, whereas the trapezoidal rule on the same samples is short by exactly dt (d_1 + d_N) / 2 -
about dt J_ss / 2, which made the 400-step tungsten verification case read 5 % low in the first
real-solver CI run.  These tests pin that contract; they deliberately do not compare with the
continuum value L^2 / 6D, so a passing run says "the extractor honours the integrator", not
"the number happens to look right".
"""

import numpy as np
import pytest

from nuagent.backends.festim.backend import FESTIMBackend, _right_endpoint_time_lag
from nuagent.physics import analytical
from nuagent.spec import PermeationCase, SimulationSpec

L, C0, T_K = 1e-3, 1e20, 600.0
D = analytical.arrhenius(4.1e-7, 0.39, T_K)  # tungsten, the verification case
T_FINAL = 6 * L**2 / D  # what FESTIMBackend uses for final_time (36 time lags)


def p1_system(n_cells: int):
    """Consistent-mass P1 FEM on [0, L] with c(0) = C0, c(L) = 0; interior unknowns only."""
    h = L / n_cells
    m = n_cells - 1
    K = (D / h) * (2 * np.eye(m) - np.eye(m, k=1) - np.eye(m, k=-1))
    M = (h / 6) * (4 * np.eye(m) + np.eye(m, k=1) + np.eye(m, k=-1))
    b = np.zeros(m)
    b[0] = D * C0 / h
    y_ss = np.linalg.solve(K, b)

    def flux(y: np.ndarray) -> float:
        # |J| at x = L from the last element's P1 gradient: what FESTIM's SurfaceFlux evaluates
        return float(D * y[-1] / h)

    return K, M, b, y_ss, flux


def discrete_time_lag(K, M, y_ss, flux) -> float:
    """The identity: sum dt d_n = -K^-1 M d_0, with d_0 = y_ss for a zero initial state."""
    return flux(np.linalg.solve(K, M @ y_ss)) / flux(y_ss)


def backward_euler(K, M, b, flux, steps: np.ndarray):
    """Backward Euler from y = 0; returns the exported samples (t_n, J_n), n = 1..N - no t = 0 row."""
    y = np.zeros(K.shape[0])
    solvers: dict[float, np.ndarray] = {}
    t, ts, js = 0.0, [], []
    for dt in steps:
        if dt not in solvers:
            solvers[dt] = np.linalg.inv(M + dt * K)
        y = solvers[dt] @ (M @ y + dt * b)
        t += dt
        ts.append(t)
        js.append(flux(y))
    return np.asarray(ts), np.asarray(js)


def steady_flux_estimate(J: np.ndarray) -> float:
    """The estimator extract_qois uses: mean of the last 10 % of the samples."""
    return float(np.mean(J[int(0.9 * len(J)) :]))


@pytest.mark.parametrize("n_steps", [400, 1600])
def test_right_endpoint_sum_recovers_the_backward_euler_integral_identity(n_steps):
    K, M, b, y_ss, flux = p1_system(200)
    t, J = backward_euler(K, M, b, flux, np.full(n_steps, T_FINAL / n_steps))
    j_ss = steady_flux_estimate(J)
    assert j_ss == pytest.approx(flux(y_ss), rel=1e-10)  # transient gone: exp(-59) by t = 36 t_lag
    assert _right_endpoint_time_lag(t, J, j_ss) == pytest.approx(
        discrete_time_lag(K, M, y_ss, flux), rel=1e-8
    )


@pytest.mark.parametrize("n_steps, min_bias", [(400, 0.04), (1600, 0.01)])
def test_trapezoid_on_right_endpoint_samples_is_short_by_half_a_panel(n_steps, min_bias):
    K, M, b, y_ss, flux = p1_system(200)
    dt = T_FINAL / n_steps
    t, J = backward_euler(K, M, b, flux, np.full(n_steps, dt))
    j_ss = steady_flux_estimate(J)
    d = j_ss - J
    old = float(np.trapezoid(d, t) / j_ss)  # what extract_qois computed before
    # algebraic identity for uniform steps: trapezoid = right-endpoint sum - dt (d_1 + d_N) / 2
    assert old == pytest.approx(
        _right_endpoint_time_lag(t, J, j_ss) - dt * (d[0] + d[-1]) / (2 * j_ss), rel=1e-9
    )
    # 400 steps: more than 4 % low; 1600 steps: still more than 1 % low - refinement only dilutes it
    assert old < (1 - min_bias) * discrete_time_lag(K, M, y_ss, flux)


def test_actual_time_stamps_handle_non_uniform_steps():
    K, M, b, y_ss, flux = p1_system(200)
    steps = [T_FINAL / 4000]
    while sum(steps) < T_FINAL:  # geometric growth from a fine start, capped
        steps.append(min(steps[-1] * 1.05, T_FINAL / 100))
    t, J = backward_euler(K, M, b, flux, np.asarray(steps))
    j_ss = steady_flux_estimate(J)
    exact = discrete_time_lag(K, M, y_ss, flux)
    assert _right_endpoint_time_lag(t, J, j_ss) == pytest.approx(exact, rel=1e-8)
    # a fixed-width rectangle rule (mean dt) is not a substitute for the actual stamps
    assert abs(float(np.mean(np.diff(t)) * np.sum(j_ss - J) / j_ss) - exact) > 0.05 * exact


def test_leading_t0_row_is_a_zero_width_panel():
    K, M, b, y_ss, flux = p1_system(50)
    t, J = backward_euler(K, M, b, flux, np.full(400, T_FINAL / 400))
    j_ss = steady_flux_estimate(J)
    assert _right_endpoint_time_lag(np.r_[0.0, t], np.r_[0.0, J], j_ss) == pytest.approx(
        _right_endpoint_time_lag(t, J, j_ss), rel=1e-12
    )


def test_extract_qois_uses_the_right_endpoint_sum(tmp_path):
    """Through the real CSV path, with the samples laid out exactly as run_festim.py writes them."""
    K, M, b, y_ss, flux = p1_system(200)
    n_steps = 400
    t, J = backward_euler(K, M, b, flux, np.full(n_steps, T_FINAL / n_steps))
    spec = SimulationSpec(
        name="quadrature",
        backend="festim",
        case=PermeationCase(
            thickness=L, temperature=T_K, upstream_concentration=C0, n_cells=200, n_steps=n_steps
        ),
    )
    h = FESTIMBackend().build(spec, tmp_path / "c")
    np.savetxt(
        h.path / "results.csv",
        np.column_stack([t, -J, J, np.zeros_like(t)]),
        delimiter=",",
        header="t,flux_downstream,flux_upstream,mobile_inventory",
        comments="",
    )
    q = FESTIMBackend().extract_qois(h, spec)
    assert q.values["time_lag"] == pytest.approx(discrete_time_lag(K, M, y_ss, flux), rel=1e-8)
    assert q.values["D_eff"] == pytest.approx(L**2 / (6 * q.values["time_lag"]), rel=1e-12)
