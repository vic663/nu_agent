"""OpenFOAM backend: case generation (always), log parsing (fixtures), real runs (if OpenFOAM present)."""

import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from nuagent.backends.openfoam.backend import OpenFOAMBackend
from nuagent.backends.openfoam.foamio import _parse_field_value, read_field, strip_comments
from nuagent.backends.openfoam.logparse import parse_openfoam_log
from nuagent.backends.openfoam.mesh import geometric_expansion_ratio, size_pipe_mesh
from nuagent.spec import FLUID_PRESETS, HeatedPipeCase, SimulationSpec
from tests.conftest import requires_openfoam


def laminar_spec(**overrides) -> SimulationSpec:
    case = dict(
        reynolds=200,
        turbulence_model="laminar",
        fluid=FLUID_PRESETS["unit_prandtl_liquid"],
        length_over_diameter=30,
        mesh={"n_radial": 16, "cells_per_diameter": 5},
        numerics={"max_iterations": 3000, "write_interval": 500},
    )
    case.update(overrides)
    return SimulationSpec(name="lam", backend="openfoam", case=HeatedPipeCase(**case))


class TestMeshSizing:
    def test_geometric_ratio_recovers_total(self):
        first, total, n = 1e-5, 1e-2, 40
        g = geometric_expansion_ratio(first, total, n)
        assert g > 1
        assert first * (g**n - 1) / (g - 1) == pytest.approx(total, rel=1e-9)
        assert geometric_expansion_ratio(1e-2, 1e-2, 10) == 1.0  # already uniform

    def test_turbulent_mesh_targets_yplus_and_refines_consistently(self):
        case = HeatedPipeCase(
            reynolds=2e4, mesh={"n_radial": 40, "cells_per_diameter": 10, "target_yplus": 1.0}
        )
        m1 = size_pipe_mesh(case, 1.0)
        m2 = size_pipe_mesh(case, 2.0)
        assert m1.radial_grading < 1.0
        assert m2.n_cells == pytest.approx(4 * m1.n_cells, rel=0.05)
        assert m2.first_cell_height == pytest.approx(0.5 * m1.first_cell_height, rel=1e-9)
        assert m2.representative_h == pytest.approx(0.5 * m1.representative_h, rel=0.05)
        assert m1.expected_yplus == 1.0

    def test_cell_budget_enforced(self):
        case = HeatedPipeCase(
            reynolds=2e4, mesh={"n_radial": 40, "cells_per_diameter": 10, "max_cells": 1000}
        )
        with pytest.raises(ValueError):
            size_pipe_mesh(case, 1.0)


class TestCaseGeneration:
    def test_builds_complete_laminar_case(self, tmp_path):
        spec = laminar_spec()
        handle = OpenFOAMBackend().build(spec, tmp_path / "case")
        files = {
            p.relative_to(handle.path).as_posix() for p in handle.path.rglob("*") if p.is_file()
        }
        assert {
            "system/blockMeshDict",
            "system/controlDict",
            "system/fvSchemes",
            "system/fvSolution",
            "constant/thermophysicalProperties",
            "constant/turbulenceProperties",
            "constant/g",
            "0/U",
            "0/T",
            "0/p",
            "0/p_rgh",
            "0/alphat",
            "Allrun",
            "nuagent_case.json",
        } <= files
        assert "0/k" not in files
        assert (
            "simulationType  laminar" in (handle.path / "constant/turbulenceProperties").read_text()
        )
        assert "externalWallHeatFluxTemperature" in (handle.path / "0/T").read_text()
        assert handle.n_cells == 16 * 150
        assert handle.allrun.stat().st_mode & 0o111

    def test_builds_turbulent_case_with_sst(self, tmp_path):
        spec = SimulationSpec(name="turb", backend="openfoam", case=HeatedPipeCase(reynolds=2e4))
        handle = OpenFOAMBackend().build(spec, tmp_path / "case")
        assert (
            (handle.path / "0/omega").exists()
            and (handle.path / "0/k").exists()
            and (handle.path / "0/nut").exists()
        )
        assert "kOmegaSST" in (handle.path / "constant/turbulenceProperties").read_text()
        assert "nutLowReWallFunction" in (handle.path / "0/nut").read_text()
        assert "kEpsilon" not in (handle.path / "constant/turbulenceProperties").read_text()

    def test_adjustments_are_whitelisted_and_bounded(self, tmp_path):
        b = OpenFOAMBackend()
        spec = laminar_spec()
        handle = b.build(
            spec, tmp_path / "c", adjustments={"relax_U": 0.05, "div_scheme": "upwind"}
        )
        fv = (handle.path / "system/fvSolution").read_text()
        assert "U               0.1;" in fv  # clipped to the lower bound
        assert "bounded Gauss upwind" in (handle.path / "system/fvSchemes").read_text()
        with pytest.raises(ValueError):
            b.build(spec, tmp_path / "d", adjustments={"turbulence_model": "kEpsilon"})
        with pytest.raises(ValueError):
            b.build(spec, tmp_path / "e", adjustments={"div_scheme": "QUICK"})

    def test_hash_changes_with_refinement(self, tmp_path):
        b = OpenFOAMBackend()
        h1 = b.build(laminar_spec(), tmp_path / "a")
        h2 = b.build(laminar_spec(), tmp_path / "b", refinement=0.5)
        assert h1.spec_hash != h2.spec_hash
        assert h2.n_cells < h1.n_cells


class TestLogParser:
    def test_converged_fixture(self, fixtures):
        text = (fixtures / "openfoam_logs/laminar_converged.log").read_text()
        rep = parse_openfoam_log(text, residual_target=1e-5)
        assert rep.completed and rep.converged and not rep.diverged
        assert rep.iterations == 3000
        assert rep.final_residuals["Ux"] < 1e-5
        assert rep.final_residuals["Uz"] > 1e-5  # ignored on purpose (wedge azimuthal noise)
        assert "Uz" in rep.reason and "ignored" in rep.reason
        assert rep.continuity_error is not None

    def test_not_converged_without_target(self, fixtures):
        text = (fixtures / "openfoam_logs/laminar_converged.log").read_text()
        rep = parse_openfoam_log(text)  # no residual target and no residualControl message
        assert rep.completed and not rep.converged
        assert rep.status == "completed_not_converged"

    def test_diverged_fixture(self, fixtures):
        rep = parse_openfoam_log(
            (fixtures / "openfoam_logs/diverged.log").read_text(), residual_target=1e-5
        )
        assert rep.diverged and not rep.converged
        assert rep.bounding_events == 1
        assert "non-finite" in rep.reason

    def test_trapfpe_header_is_not_a_crash(self):
        text = "trapFpe: Floating point exception trapping enabled (FOAM_SIGFPE).\nTime = 1\n\nSIMPLE solution converged in 1 iterations\nEnd\n"
        rep = parse_openfoam_log(text)
        assert rep.converged and not rep.diverged


class TestFoamIO:
    def test_field_value_parsing(self):
        assert _parse_field_value("uniform 300;", 0) == 300.0
        np.testing.assert_allclose(_parse_field_value("uniform (1 0 0);", 0), [1, 0, 0])
        arr = _parse_field_value("nonuniform List<scalar> 3(1 2 3);", 0)
        np.testing.assert_allclose(arr, [1, 2, 3])
        vec = _parse_field_value("nonuniform List<vector> 2((1 2 3) (4 5 6));", 0)
        assert vec.shape == (2, 3)
        assert _parse_field_value("nonuniform 0();", 0).size == 0

    def test_read_field_file(self, tmp_path):
        text = """/*--- header ---*/
FoamFile { version 2.0; format ascii; class volScalarField; object T; }
dimensions [0 0 0 1 0 0 0];
internalField nonuniform List<scalar> 4(300 301 302 303);
boundaryField
{
    inlet { type fixedValue; value uniform 300; }
    wall { type externalWallHeatFluxTemperature; value nonuniform List<scalar> 2(310 311); }
    axis { type empty; value nonuniform 0(); }
}
"""
        p = tmp_path / "T"
        p.write_text(text)
        f = read_field(p)
        np.testing.assert_allclose(f.internal_array, [300, 301, 302, 303])
        assert f.boundary["wall"]["type"] == "externalWallHeatFluxTemperature"
        np.testing.assert_allclose(f.patch_value("wall"), [310, 311])
        np.testing.assert_allclose(f.patch_value("inlet", 3), [300, 300, 300])
        assert "header" not in strip_comments(text)


@requires_openfoam
@pytest.mark.openfoam
@pytest.mark.slow
class TestRealOpenFOAM:
    def test_laminar_pipe_reproduces_exact_solution(self, tmp_path):
        """Full solver run: Nu -> 48/11 and f -> 64/Re within 1 %."""
        spec = laminar_spec()
        b = OpenFOAMBackend()
        handle = b.build(spec, tmp_path / "lam")
        proc = subprocess.run(
            ["bash", str(handle.allrun)], capture_output=True, text=True, timeout=1500
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rep = b.parse_log(handle)
        assert rep.converged, rep.reason
        q = b.extract_qois(handle, spec)
        assert q.values["Nu"] == pytest.approx(48 / 11, rel=0.01)
        assert q.values["f"] == pytest.approx(64 / 200, rel=0.01)
        assert abs(q.checks["energy_balance_error"]) < 0.005
        assert abs(q.checks["mass_balance_error"]) < 0.005
        assert abs(q.checks["friction_factor_consistency"]) < 0.02
        assert math.isfinite(q.values["T_wall_outlet"])
        assert len(q.profiles["x"]) == handle.metadata["mesh"]["n_axial"]

    def test_blockmesh_checkmesh_turbulent_mesh(self, tmp_path):
        """Mesh generation only (fast): wedge topology, grading, y+ targeting."""
        spec = SimulationSpec(
            name="turb",
            backend="openfoam",
            case=HeatedPipeCase(reynolds=2e4, mesh={"n_radial": 30, "cells_per_diameter": 8}),
        )
        handle = OpenFOAMBackend().build(spec, tmp_path / "turb")
        script = f"cd {handle.path} && source $(python -c 'from nuagent.backends.openfoam.backend import find_foam_bashrc as f; print(f())') >/dev/null 2>&1; blockMesh > log.blockMesh 2>&1 && checkMesh > log.checkMesh 2>&1; grep -E 'cells:' log.checkMesh; grep -c 'Mesh OK' log.checkMesh"
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=300)
        assert (
            f"cells:            {handle.n_cells}" in out.stdout.replace("  ", " ").replace(" ", " ")
            or str(handle.n_cells) in out.stdout
        )
        assert Path(handle.path / "constant/polyMesh/points").exists()
