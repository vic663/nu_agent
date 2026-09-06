"""FESTIM backend: case generation and post-processing always; solver runs only where dolfinx exists."""

import json
import subprocess

import numpy as np
import pytest

from nuagent.backends.festim.backend import FESTIMBackend
from nuagent.physics import analytical
from nuagent.spec import PermeationCase, SimulationSpec, TDSCase, TrapSpec
from tests.conftest import requires_festim


def perm_spec(**kw) -> SimulationSpec:
    case = dict(
        thickness=1e-3, temperature=600.0, upstream_concentration=1e20, n_cells=100, n_steps=200
    )
    case.update(kw)
    return SimulationSpec(name="perm", backend="festim", case=PermeationCase(**case))


class TestCaseGeneration:
    def test_permeation_case_files(self, tmp_path):
        spec = perm_spec()
        h = FESTIMBackend().build(spec, tmp_path / "c")
        params = json.loads((h.path / "params.json").read_text())
        assert params["kind"] == "permeation" and params["n_cells"] == 100
        D = analytical.arrhenius(4.1e-7, 0.39, 600.0)
        assert params["diffusivity"] == pytest.approx(D)
        assert params["final_time"] == pytest.approx(6 * 1e-6 / D)
        assert (h.path / "run_festim.py").exists() and (h.path / "Allrun").exists()
        assert h.representative_h == pytest.approx(1e-5)

    def test_refinement_scales_cells_and_steps(self, tmp_path):
        b = FESTIMBackend()
        h = b.build(perm_spec(), tmp_path / "r", refinement=2.0)
        p = json.loads((h.path / "params.json").read_text())
        assert p["n_cells"] == 200 and p["n_steps"] == 400

    def test_adjustments(self, tmp_path):
        b = FESTIMBackend()
        h = b.build(perm_spec(), tmp_path / "a", adjustments={"n_steps": 800, "rtol": 1e-20})
        p = json.loads((h.path / "params.json").read_text())
        assert p["n_steps"] == 800 and p["rtol"] == 1e-14  # clipped
        with pytest.raises(ValueError):
            b.build(perm_spec(), tmp_path / "b", adjustments={"relax_U": 0.3})

    def test_tds_case_params(self, tmp_path):
        trap = TrapSpec(k_0=3.8e-17, E_k=0.39, p_0=1e13, E_p=1.0, n=1e25)
        spec = SimulationSpec(name="tds", backend="festim", case=TDSCase(traps=[trap]))
        h = FESTIMBackend().build(spec, tmp_path / "t")
        p = json.loads((h.path / "params.json").read_text())
        assert p["kind"] == "tds" and p["traps"][0]["E_p"] == 1.0

    def test_parse_log_without_run(self, tmp_path):
        h = FESTIMBackend().build(perm_spec(), tmp_path / "n")
        rep = FESTIMBackend().parse_log(h)
        assert not rep.completed and "runner did not start" in rep.reason
        (h.path / "log.festim").write_text("ModuleNotFoundError: No module named 'dolfinx'\n")
        rep = FESTIMBackend().parse_log(h)
        assert "not importable" in rep.reason

    def test_runner_script_is_valid_python(self, tmp_path):
        h = FESTIMBackend().build(perm_spec(), tmp_path / "v")
        proc = subprocess.run(
            ["python3", "-m", "py_compile", str(h.path / "run_festim.py")],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr


class TestPostProcessing:
    def test_qois_from_analytical_results(self, tmp_path):
        """Feed the analytical solution through the CSV path and check the extracted QoIs."""
        spec = perm_spec()
        h = FESTIMBackend().build(spec, tmp_path / "pp")
        p = json.loads((h.path / "params.json").read_text())
        D, c0, L = p["diffusivity"], 1e20, 1e-3
        t = np.linspace(0, p["final_time"], 2001)
        J = analytical.permeation_flux(t, D, c0, L)
        np.savetxt(
            h.path / "results.csv",
            np.column_stack([t, -J, J, np.zeros_like(t)]),
            delimiter=",",
            header="t,flux_downstream,flux_upstream,mobile_inventory",
            comments="",
        )
        q = FESTIMBackend().extract_qois(h, spec)
        assert q.values["permeation_flux_ss"] == pytest.approx(D * c0 / L, rel=1e-3)
        assert q.values["time_lag"] == pytest.approx(L**2 / (6 * D), rel=2e-2)
        assert q.values["D_eff"] == pytest.approx(D, rel=2e-2)


@requires_festim
@pytest.mark.festim
class TestRealFESTIM:
    def test_permeation_matches_analytical(self, tmp_path):
        # dt ~ 0.02 t_lag: the Daynes-Barrer time lag integrates the transient, so it is far more
        # sensitive to the time step than the steady flux (400 steps, dt ~ 0.09 t_lag, came out
        # 5.5 % low against the 5 % gate).
        spec = perm_spec(n_cells=200, n_steps=1600)
        b = FESTIMBackend()
        h = b.build(spec, tmp_path / "real")
        proc = subprocess.run(["bash", str(h.allrun)], capture_output=True, text=True, timeout=1200)
        assert proc.returncode == 0, (h.path / "log.festim").read_text()[-3000:]
        rep = b.parse_log(h)
        assert rep.converged, rep.reason
        q = b.extract_qois(h, spec)
        D = analytical.arrhenius(4.1e-7, 0.39, 600.0)
        assert q.values["permeation_flux_ss"] == pytest.approx(D * 1e20 / 1e-3, rel=0.02)
        assert q.values["time_lag"] == pytest.approx(1e-6 / (6 * D), rel=0.05)
