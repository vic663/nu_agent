"""Rib-roughened tube: correlations, spec, multi-block mesh, post-processing (real run if OpenFOAM present)."""

import math
import re
import subprocess

import pytest

from nuagent.backends.openfoam.backend import OpenFOAMBackend
from nuagent.backends.openfoam.mesh import size_ribbed_mesh
from nuagent.physics import correlations as corr
from nuagent.spec import FLUID_PRESETS, RibbedTubeCase, SimulationSpec
from tests.conftest import requires_openfoam


def rib_spec(**kw) -> SimulationSpec:
    case = dict(reynolds=2e4, fluid=FLUID_PRESETS["air_300K"], wall_heat_flux=1000.0)
    case.update(kw)
    return SimulationSpec(name="rib", backend="openfoam", case=RibbedTubeCase(**case))


class TestWebbCorrelation:
    def test_roughness_functions_by_hand(self):
        # p/e = 10 -> R = 0.95 * 10^0.53 = 3.220; e/D = 0.04 -> sqrt(2/f) = R - 2.5 ln(0.08) - 3.75
        r = corr.webb_ribbed_tube(2e4, 0.71, 0.04, 10.0)
        R = 0.95 * 10**0.53
        assert r.roughness_function_R == pytest.approx(R, rel=1e-9)
        f_fanning = 2.0 / (R - 2.5 * math.log(0.08) - 3.75) ** 2
        assert r.friction_darcy == pytest.approx(4 * f_fanning, rel=1e-9)
        assert r.e_plus == pytest.approx(0.04 * 2e4 * math.sqrt(f_fanning / 2), rel=1e-9)
        assert r.valid

    def test_enhancement_magnitudes_are_physical(self):
        # Webb's data: e/D = 0.02, p/e = 10 gives f/f_s ~ 5-6 and St/St_s ~ 2-2.5 for air
        r = corr.webb_ribbed_tube(3e4, 0.71, 0.02, 10.0)
        f0 = corr.friction_factor_petukhov(3e4).value
        nu0 = corr.nusselt_gnielinski(3e4, 0.71).value
        assert 4.5 < r.friction_darcy / f0 < 7.0
        assert 1.8 < r.nusselt / nu0 < 2.8
        assert 1.0 < corr.thermal_performance_factor(r.nusselt / nu0, r.friction_darcy / f0) < 1.6

    def test_registry_requires_geometry(self):
        with pytest.raises(KeyError):
            corr.reference_value("Nu", "webb", 2e4, 0.71)
        v = corr.reference_value("f", "webb", 2e4, 0.71, e_over_D=0.04, p_over_e=10.0)
        assert v.name == "webb" and v.valid
        assert not corr.reference_value("Nu", "webb", 2e4, 0.71, e_over_D=0.08, p_over_e=10.0).valid


class TestSpecAndMesh:
    def test_derived_geometry(self):
        c = RibbedTubeCase(
            reynolds=2e4, n_ribs=10, rib_height_over_diameter=0.05, rib_pitch_over_height=8
        )
        assert c.rib_height == pytest.approx(1e-3)
        assert c.rib_pitch == pytest.approx(8e-3)
        assert c.length == pytest.approx((5 + 2) * 0.02 + 10 * 8e-3)
        assert c.length_over_diameter == pytest.approx(c.length / 0.02)
        with pytest.raises(ValueError):
            RibbedTubeCase(reynolds=2e4, n_ribs=4, developed_modules=4)
        # w/e = 3 with p/e = 5 is a legal (if unusual) geometry: the rib is narrower than the pitch
        c = RibbedTubeCase(
            reynolds=2e4,
            rib_pitch_over_height=5,
            rib_width_over_height=3,
            n_ribs=3,
            developed_modules=1,
        )
        assert c.rib_width < c.rib_pitch

    def test_mesh_layout(self):
        c = RibbedTubeCase(reynolds=2e4, fluid=FLUID_PRESETS["air_300K"], n_ribs=6)
        m = size_ribbed_mesh(c)
        kinds = [s.kind for s in m.segments]
        assert kinds[0] == "smooth_in" and kinds[-1] == "smooth_out"
        assert kinds[1:-1] == ["gap", "rib"] * 6
        assert m.n_rib_layer % 2 == 0
        assert 0 < m.core_grading < 1
        assert m.rib_layer_grading.startswith("((0.5 0.5 ")
        assert abs(m.stations[-1] - c.length) < 1e-12
        m2 = size_ribbed_mesh(c, 2.0)
        assert 3.3 < m2.n_cells / m.n_cells < 4.7
        assert m2.first_cell_height == pytest.approx(0.5 * m.first_cell_height)

    def test_blockmesh_dict_is_consistent(self, tmp_path):
        spec = rib_spec(n_ribs=4, developed_modules=2)
        h = OpenFOAMBackend().build(spec, tmp_path / "rib")
        text = (h.path / "system/blockMeshDict").read_text()
        n_seg = 1 + 2 * 4 + 1
        assert text.count("hex (") == n_seg + (
            n_seg - 4
        )  # a core block per segment + layer blocks except ribs
        assert h.metadata["mesh"]["n_cells"] == h.n_cells
        assert "type wedge" in text and "type empty" in text
        # every station has 5 vertices
        assert (
            len(re.findall(r"station \d+ axis", text)) == n_seg + 1
        )  # one axis vertex per station


@requires_openfoam
@pytest.mark.openfoam
class TestRealOpenFOAMRibbed:
    def test_blockmesh_and_checkmesh(self, tmp_path):
        spec = rib_spec(
            n_ribs=4,
            developed_modules=2,
            mesh={"n_radial": 20, "n_radial_rib": 8, "cells_per_rib_height": 3},
        )
        h = OpenFOAMBackend().build(spec, tmp_path / "rib")
        script = (
            f"cd {h.path} && [ -z \"$WM_PROJECT_DIR\" ] && source $(python -c 'from nuagent.backends.openfoam.backend import find_foam_bashrc as f; print(f())') >/dev/null 2>&1; "
            "blockMesh > log.blockMesh 2>&1 && checkMesh -allTopology > log.checkMesh 2>&1; grep -E 'cells:|wall ' log.checkMesh; grep -c 'FOAM FATAL' log.blockMesh log.checkMesh || true"
        )
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=300)
        assert str(h.n_cells) in out.stdout, out.stdout + out.stderr
        assert (
            "singly connected" in out.stdout
        )  # wall patch (tube wall + rib faces) is one connected surface
