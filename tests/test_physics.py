import math

import numpy as np
import pytest

from nuagent.physics import analytical, correlations, reduced


class TestCorrelations:
    def test_reynolds_prandtl(self):
        assert correlations.reynolds(1000, 1.0, 0.02, 1e-3) == pytest.approx(20000)
        assert correlations.prandtl(8.5e-4, 4180, 0.61) == pytest.approx(5.82, rel=1e-2)

    def test_laminar_exact_values(self):
        assert correlations.nusselt_laminar().value == pytest.approx(4.3636, abs=1e-3)
        assert correlations.nusselt_laminar("uniform_wall_temperature").value == pytest.approx(
            3.657, abs=1e-3
        )
        assert correlations.friction_factor_laminar(1000).value == pytest.approx(0.064)

    def test_gnielinski_textbook_value(self):
        # Incropera Example 8.6-type check: Re=1e4, Pr=0.7 -> Nu ~ 30 (Gnielinski ~ 31)
        nu = correlations.nusselt_gnielinski(1e4, 0.7)
        assert 28 < nu.value < 34
        assert nu.valid
        # Dittus-Boelter within 25% of Gnielinski at Re=5e4, Pr=6
        g = correlations.nusselt_gnielinski(5e4, 6.0).value
        db = correlations.nusselt_dittus_boelter(5e4, 6.0).value
        assert abs(db - g) / g < 0.25

    def test_friction_factors_consistent(self):
        re = 5e4
        blas = correlations.friction_factor_blasius(re).value
        pet = correlations.friction_factor_petukhov(re).value
        pk = correlations.friction_factor_prandtl_karman(re).value
        assert blas == pytest.approx(0.0211, rel=2e-2)
        assert pet == pytest.approx(pk, rel=3e-2)
        assert correlations.friction_factor(500).name.startswith("laminar")
        assert correlations.friction_factor(5e4).name == "petukhov"

    def test_regime_and_registry(self):
        assert correlations.flow_regime(1000) == "laminar"
        assert correlations.flow_regime(3000) == "transitional"
        assert correlations.flow_regime(10000) == "turbulent"
        ref = correlations.reference_value("Nu", "gnielinski", 2e4, 5.8)
        assert ref.name == "gnielinski"
        with pytest.raises(KeyError):
            correlations.reference_value("Nu", "nonexistent", 1, 1)

    def test_energy_balance_and_local_nu(self):
        mdot = correlations.mass_flow_rate(1000, 0.5, 0.02)
        tb = correlations.bulk_temperature(1.0, 300.0, 1e4, 0.02, mdot, 4180)
        assert tb > 300.0
        assert correlations.nusselt_local(1e4, 0.02, 0.6, 310.0, 300.0) == pytest.approx(
            1e4 * 0.02 / (0.6 * 10)
        )
        assert math.isinf(correlations.nusselt_local(1e4, 0.02, 0.6, 300.0, 300.0))

    def test_yplus_cell_height_scales_with_re(self):
        nu = 1e-6
        y_lo = correlations.first_cell_height_for_yplus(1.0, 1e4, 0.02, nu)
        y_hi = correlations.first_cell_height_for_yplus(1.0, 1e5, 0.02, nu)
        assert y_hi < y_lo
        assert 1e-7 < y_hi < 1e-4


class TestAnalytical:
    def test_permeation_limits(self):
        D, c0, L = 1e-10, 1e20, 1e-3
        t = np.array([0.0, 1e2, 1e9])
        J = analytical.permeation_flux(t, D, c0, L)
        assert J[0] == pytest.approx(0.0, abs=1e-6 * D * c0 / L)
        assert J[-1] == pytest.approx(analytical.permeation_steady_flux(D, c0, L), rel=1e-9)
        assert np.all(np.diff(J) >= -1e-12)
        assert analytical.permeation_time_lag(D, L) == pytest.approx(L**2 / (6 * D))

    def test_time_lag_property(self):
        # Integral of (J_ss - J) dt from 0 to inf equals J_ss * t_lag
        D, c0, L = 2e-10, 1e20, 5e-4
        Jss = analytical.permeation_steady_flux(D, c0, L)
        t = np.linspace(0, 40 * L**2 / D, 200001)
        J = analytical.permeation_flux(t, D, c0, L)
        integral = np.trapezoid(Jss - J, t)
        assert integral / Jss == pytest.approx(analytical.permeation_time_lag(D, L), rel=1e-3)

    def test_oriani_effective_diffusivity(self):
        D = 1e-9
        assert analytical.effective_diffusivity_oriani(D, 0.0, 1.0, 1.0) == D
        deff = analytical.effective_diffusivity_from_trap(
            D, 600, k_0=1e-15, E_k=0.2, p_0=1e13, E_p=1.0, n_trap=1e25
        )
        assert 0 < deff < D

    def test_redhead_peak_consistency(self):
        E_p, p_0, beta = 1.0, 1e13, 8.0
        Tp = analytical.redhead_peak_temperature(E_p, p_0, beta)
        assert 300 < Tp < 1000
        assert reduced.kissinger_check(E_p, math.log10(p_0), beta, Tp) == pytest.approx(
            0.0, abs=1e-6
        )

    def test_hartmann_limits(self):
        y = np.linspace(-1, 1, 201)
        u0 = analytical.hartmann_velocity(y, 1.0, 0.0, 1.0)
        assert u0.max() == pytest.approx(1.5)
        u_high = analytical.hartmann_velocity(y, 1.0, 50.0, 1.0)
        # flat core, mean velocity preserved
        assert abs(u_high[100] - 1.0) < 0.03
        assert np.trapezoid(u_high, y) / 2 == pytest.approx(1.0, rel=1e-2)
        assert analytical.hartmann_number(1.0, 0.05, 3.3e6, 1.8e-3) == pytest.approx(
            0.05 * math.sqrt(3.3e6 / 1.8e-3)
        )

    def test_poiseuille(self):
        r = np.linspace(0, 0.01, 101)
        u = analytical.poiseuille_pipe_velocity(r, 0.01, 1.0)
        assert u[0] == pytest.approx(2.0)
        assert u[-1] == pytest.approx(0.0)
        assert analytical.poiseuille_pressure_gradient(1e-3, 1.0, 0.01) == pytest.approx(80.0)


class TestReducedModels:
    def test_first_order_desorption_peak_matches_redhead(self):
        T = np.linspace(300, 1200, 901)
        model = reduced.FirstOrderDesorptionModel(T, beta=8.0)
        flux = model({"E_p": 1.2, "log10_p_0": 13.0, "n_t0": 1e25})
        T_peak_num = T[np.argmax(flux)]
        T_peak_ref = analytical.redhead_peak_temperature(1.2, 1e13, 8.0)
        assert T_peak_num == pytest.approx(T_peak_ref, abs=3.0)
        # conservation: integral of flux over time equals initial inventory per area
        t = (T - 300) / 8.0
        assert np.trapezoid(flux, t) == pytest.approx(1e25 * model.thickness, rel=2e-2)

    def test_permeation_model_arrhenius_path(self):
        t = np.linspace(0, 1e4, 50)
        m = reduced.PermeationModel(t)
        a = m({"log10_D": -10})
        b = m({"D_0": 1e-7, "E_D": 0.0, "temperature": 600, "log10_D": -7})
        assert a.shape == t.shape
        assert b[-1] > a[-1]

    def test_nusselt_model(self):
        m = reduced.NusseltCorrelationModel(np.array([1e4, 5e4]), prandtl=1.0)
        assert m({})[0] == pytest.approx(0.023 * 1e4**0.8)
