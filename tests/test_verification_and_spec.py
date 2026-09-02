import pytest
from pydantic import ValidationError

from nuagent.spec import (
    FLUID_PRESETS,
    HeatedPipeCase,
    PermeationCase,
    SimulationSpec,
    TurbulenceModel,
)
from nuagent.verification import grid_convergence_index, relative_error


class TestGCI:
    def test_recovers_second_order_convergence(self):
        # f(h) = f_exact + C h^2 on grids h = 1, 2, 4
        f_exact, C = 4.3636, 0.05
        h = [1.0, 2.0, 4.0]
        f = [f_exact + C * hi**2 for hi in h]
        res = grid_convergence_index("Nu", h, f, exact=f_exact)
        assert res.observed_order == pytest.approx(2.0, abs=1e-6)
        assert res.extrapolated == pytest.approx(f_exact, rel=1e-8)
        assert res.convergence == "monotonic"
        assert res.gci_fine == pytest.approx(1.25 * abs(f[1] - f[0]) / f[0] / 3.0, rel=1e-8)
        assert res.is_asymptotic
        assert "fine-grid error" in res.notes

    def test_first_order_unequal_ratios(self):
        f_exact, C = 10.0, 1.0
        h = [1.0, 1.5, 3.0]
        f = [f_exact + C * hi for hi in h]
        res = grid_convergence_index("f", h, f)
        assert res.observed_order == pytest.approx(1.0, abs=1e-6)
        assert res.extrapolated == pytest.approx(f_exact, rel=1e-6)

    def test_oscillatory_flagged(self):
        res = grid_convergence_index("Nu", [1, 2, 4], [4.0, 4.4, 4.2])
        assert res.convergence == "oscillatory"

    def test_two_grid_estimate(self):
        res = grid_convergence_index("Nu", [1, 2], [4.0, 4.3])
        assert res.observed_order == 2.0
        assert res.extrapolated == pytest.approx(4.0 - 0.3 / 3.0)
        assert "assumed order" in res.notes

    def test_bad_inputs(self):
        with pytest.raises(ValueError):
            grid_convergence_index("Nu", [2, 1, 4], [1, 2, 3])
        with pytest.raises(ValueError):
            grid_convergence_index("Nu", [1], [1])
        assert relative_error(1.1, 1.0) == pytest.approx(0.1)


class TestSpec:
    def test_laminar_case_requires_laminar_model(self):
        with pytest.raises(ValidationError):
            HeatedPipeCase(reynolds=500)  # default kOmegaSST
        case = HeatedPipeCase(reynolds=500, turbulence_model=TurbulenceModel.LAMINAR)
        assert case.regime.value == "laminar"
        assert case.inlet_velocity == pytest.approx(
            500 * case.fluid.mu / (case.fluid.rho * case.diameter)
        )

    def test_turbulent_case_rejects_laminar_model(self):
        with pytest.raises(ValidationError):
            HeatedPipeCase(reynolds=2e4, turbulence_model=TurbulenceModel.LAMINAR)

    def test_backend_case_consistency(self):
        with pytest.raises(ValidationError):
            SimulationSpec(name="bad", backend="festim", case=HeatedPipeCase(reynolds=2e4))
        with pytest.raises(ValidationError):
            SimulationSpec(name="bad", backend="openfoam", case=PermeationCase())
        spec = SimulationSpec(name="ok", backend="mock", case={"kind": "permeation"})
        assert isinstance(spec.case, PermeationCase)

    def test_yaml_roundtrip(self, tmp_path):
        spec = SimulationSpec(
            name="pipe",
            backend="openfoam",
            case=HeatedPipeCase(reynolds=2e4, fluid=FLUID_PRESETS["water_300K"]),
            validation={
                "references": [{"quantity": "Nu", "source": "gnielinski", "tolerance": 0.15}]
            },
        )
        p = tmp_path / "spec.yaml"
        spec.to_yaml(p)
        again = SimulationSpec.from_yaml(p)
        assert again == spec
        assert again.case.fluid.pr == pytest.approx(5.82, rel=1e-2)

    def test_json_schema_is_llm_friendly(self):
        schema = SimulationSpec.model_json_schema()
        assert "HeatedPipeCase" in schema["$defs"]
        assert schema["$defs"]["HeatedPipeCase"]["properties"]["reynolds"]["description"]
