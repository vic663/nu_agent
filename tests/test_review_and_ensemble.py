"""Pre-flight review, closure-ensemble (model-form) node and pass^k reliability scoring."""

from pathlib import Path

import pytest
import yaml

from nuagent.agent import RulesPolicy, Runtime, run_workflow
from nuagent.agent.model_form import closure_variant, ensemble_warnings, summarise_ensemble
from nuagent.agent.policy import LLMPolicy, ReviewFindings, rules_critique
from nuagent.agent.preflight import preflight
from nuagent.backends import get_backend
from nuagent.evals.harness import pass_hat_k, run_suite
from nuagent.executors import LocalExecutor
from nuagent.spec import FLUID_PRESETS, HeatedPipeCase, RibbedTubeCase, SimulationSpec, TDSCase


@pytest.fixture
def rt():
    return Runtime(
        backend=get_backend("mock"), executor=LocalExecutor(poll_interval=0.2), policy=RulesPolicy()
    )


def _spec(name, case, **kw):
    return SimulationSpec(name=name, backend="mock", case=case, **kw)


class TestPreflight:
    def test_clean_spec_has_no_findings(self):
        pf = preflight(_spec("ok", HeatedPipeCase(reynolds=2e4)))
        assert pf.ok and not pf.warnings and not pf.blocking

    def test_sst_on_ribs_and_short_domain_are_flagged(self):
        pf = preflight(
            _spec(
                "ribs",
                RibbedTubeCase(
                    reynolds=2e4, turbulence_model="kOmegaSST", n_ribs=6, developed_modules=2
                ),
                verification={"refinement_ratio": 2.0},
            )
        )
        assert pf.ok
        joined = " ".join(pf.warnings)
        assert "SST" in joined and "ribs" in joined and "refinement ratio" in joined

    def test_out_of_range_correlation_is_a_warning(self):
        spec = _spec(
            "lowre",
            HeatedPipeCase(reynolds=2500, turbulence_model="kOmegaSST"),
            validation={"references": [{"quantity": "Nu", "source": "dittus_boelter"}]},
        )
        pf = preflight(spec)
        assert any("validity" in w for w in pf.warnings)

    def test_tds_without_traps_blocks(self):
        pf = preflight(SimulationSpec(name="tds", backend="mock", case=TDSCase(traps=[])))
        assert not pf.ok and "trap" in pf.blocking[0]

    def test_short_pipe_blocks_when_flow_cannot_develop(self):
        """A domain shorter than the entry length cannot validate a fully-developed correlation."""
        pf = preflight(_spec("short", HeatedPipeCase(reynolds=2e4, length_over_diameter=5)))
        assert not pf.ok
        assert any("fully developed" in b for b in pf.blocking)

    def test_entry_length_warns_when_the_flow_develops_but_late(self):
        """The flow does develop, but the averaging window starts inside the developing region."""
        pf = preflight(
            _spec(
                "late",
                HeatedPipeCase(
                    reynolds=500,
                    turbulence_model="laminar",
                    fluid=FLUID_PRESETS["unit_prandtl_liquid"],  # entry length 25 D
                    length_over_diameter=30,
                    developed_fraction=0.1,  # evaluation starts at 27 D... just past 25 D
                ),
            )
        )
        assert pf.ok, pf.blocking
        pf2 = preflight(
            _spec(
                "late2",
                HeatedPipeCase(
                    reynolds=500,
                    turbulence_model="laminar",
                    fluid=FLUID_PRESETS["unit_prandtl_liquid"],  # entry length 25 D
                    length_over_diameter=30,
                    developed_fraction=0.9,  # evaluation starts at 3 D, deep in the entry region
                ),
            )
        )
        assert pf2.ok and any("entry length" in w for w in pf2.warnings)

    def test_blocking_finding_stops_workflow_before_build(self, rt, tmp_path):
        spec = SimulationSpec(name="tds0", backend="mock", case=TDSCase(traps=[]))
        out = run_workflow(rt, spec=spec.model_dump(mode="json"), workdir=str(tmp_path / "t"))
        assert out["status"] == "failed" and "pre-flight" in out["error"]
        nodes = [d["node"] for d in out["decisions"]]
        assert "build" not in nodes and nodes[:2] == ["plan", "review"]
        assert Path(out["report_path"]).exists()
        assert (tmp_path / "t" / "preflight.json").exists()

    def test_llm_review_only_adds_warnings(self):
        class FakeStructured:
            def invoke(self, messages):
                return ReviewFindings(warnings=["inlet turbulence intensity unspecified"])

        class FakeModel:
            def with_structured_output(self, schema):
                assert schema is ReviewFindings
                return FakeStructured()

        pol = LLMPolicy(model=FakeModel())
        spec = _spec("x", RibbedTubeCase(reynolds=2e4, turbulence_model="kOmegaSST"))
        pf = preflight(spec)
        extra = pol.review(spec, pf)
        assert extra == ["[llm] inlet turbulence intensity unspecified"]

        class Broken:
            def with_structured_output(self, schema):
                raise RuntimeError("offline")

        assert LLMPolicy(model=Broken()).review(spec, pf) == []


class TestModelForm:
    def test_closure_variant_keeps_everything_but_the_closure(self):
        spec = _spec(
            "ribs",
            RibbedTubeCase(reynolds=2e4, turbulence_model="LaunderSharmaKE"),
            model_form={"closures": ["kOmegaSST", "kEpsilon"]},
        )
        v = closure_variant(spec, spec.model_form.closures[0])
        assert v.case.turbulence_model.value == "kOmegaSST"
        assert v.case.reynolds == spec.case.reynolds and v.model_form is None
        assert v.name.endswith("kOmegaSST")
        assert v.case.wall_treatment.value == "resolved"  # SST keeps the primary's treatment
        ke = closure_variant(spec, "kEpsilon")
        assert ke.case.wall_treatment.value == "wall_function"  # high-Re closure → log-law wall
        kept = closure_variant(spec, "kEpsilon", adapt_wall_treatment=False)
        assert kept.case.wall_treatment.value == "resolved"

    def test_laminar_closure_is_skipped_for_turbulent_re(self):
        spec = _spec("p", HeatedPipeCase(reynolds=2e4))
        with pytest.raises(ValueError):
            closure_variant(spec, "laminar")

    def test_summary_and_warnings_on_synthetic_members(self):
        spec = _spec(
            "ribs",
            RibbedTubeCase(reynolds=2e4, turbulence_model="kOmegaSST"),
            validation={"references": [{"quantity": "Nu", "source": "webb", "tolerance": 0.2}]},
        )
        # water at Re 2e4: Webb gives Nu ≈ 392; SST member mimics the observed cavity flow
        members = [
            {
                "closure": "kOmegaSST",
                "converged": True,
                "values": {"Nu": 200.0, "f": 0.10},
                "checks": {"reversed_flow_fraction_of_gap": 0.95},
            },
            {
                "closure": "kEpsilon",
                "wall_treatment": "wall_function",
                "converged": True,
                "values": {"Nu": 380.0, "f": 0.20},
                "checks": {"reversed_flow_fraction_of_gap": 0.4, "yplus_avg_estimate": 8.0},
            },
            {"closure": "realizableKE", "converged": False, "reason": "diverged"},
        ]
        s = summarise_ensemble(spec, members, ["Nu", "f"], gci={"Nu": {"gci_fine": 0.02}})
        assert s["n_converged"] == 2
        nu = s["spread"]["Nu"]
        assert nu["range_over_primary"] == pytest.approx(180 / 200)
        assert nu["dominant"] == "model_form"
        assert nu["reference"]["source"].lower().startswith("webb")
        assert "kEpsilon" in nu["reference"]["within_tolerance"]
        w = ensemble_warnings(spec, s)
        joined = " ".join(w)
        assert "disagree" in joined and "model form" in joined
        assert "realizableKE did not converge" in joined
        assert "no reattachment" in joined
        assert "not a valid wall-function solution" in joined  # y+ = 8 with wall functions
        # the critique picks the same warnings up through the results dict
        crit = rules_critique(spec, {"qois": {"values": {}, "checks": {}}, "model_form": s})
        assert any("disagree" in x for x in crit.warnings)

    def test_ensemble_runs_end_to_end_on_mock(self, rt, tmp_path):
        spec = _spec(
            "ens",
            RibbedTubeCase(reynolds=2e4, turbulence_model="LaunderSharmaKE"),
            model_form={"closures": ["kOmegaSST", "kEpsilon", "LaunderSharmaKE"], "parallel": 2},
        )
        out = run_workflow(rt, spec=spec.model_dump(mode="json"), workdir=str(tmp_path / "ens"))
        assert out["status"] in ("success", "completed_with_issues"), out.get("error")
        mf = out["model_form"]
        assert mf["primary"] == "LaunderSharmaKE"
        assert sorted(mf["closures"]) == ["LaunderSharmaKE", "kEpsilon", "kOmegaSST"]
        assert mf["n_converged"] == 3
        assert mf["spread"]["Nu"]["model_form_uncertainty"] > 0.1  # SST mock mimics cavity flow
        # the mock's SST member has no reattachment → physics warning in the critique
        assert any("kOmegaSST predicts no reattachment" in w for w in out["critique"]["warnings"])
        assert (tmp_path / "ens" / "model_form_kOmegaSST").is_dir()
        assert (tmp_path / "ens" / "model_form.json").exists()
        text = Path(out["report_path"]).read_text()
        assert "Model-form uncertainty" in text and "model_form.png" in text
        # validation still uses the primary closure only
        assert out["validation"]["passed"]

    def test_ensemble_is_idempotent(self, rt, tmp_path):
        spec = _spec(
            "ens2",
            HeatedPipeCase(reynolds=2e4),
            model_form={"closures": ["kEpsilon"]},
        )
        out1 = run_workflow(rt, spec=spec.model_dump(mode="json"), workdir=str(tmp_path / "e"))
        out2 = run_workflow(rt, spec=spec.model_dump(mode="json"), workdir=str(tmp_path / "e"))
        m2 = [m for m in out2["model_form"]["members"] if m["closure"] == "kEpsilon"][0]
        assert m2.get("reused") is True
        assert (
            out1["model_form"]["spread"]["Nu"]["min"] == out2["model_form"]["spread"]["Nu"]["min"]
        )

    def test_laminar_case_skips_ensemble(self, rt, tmp_path):
        spec = _spec(
            "lam",
            HeatedPipeCase(
                reynolds=500,
                turbulence_model="laminar",
                fluid=FLUID_PRESETS["unit_prandtl_liquid"],
            ),
            model_form={"closures": ["kEpsilon"]},
        )
        out = run_workflow(rt, spec=spec.model_dump(mode="json"), workdir=str(tmp_path / "l"))
        assert out["status"] == "success"
        assert "model_form" not in out or not out["model_form"].get("members")


class TestPassK:
    def test_pass_hat_k_matches_closed_forms(self):
        assert pass_hat_k(5, 5, 3) == 1.0
        assert pass_hat_k(5, 0, 1) == 0.0
        assert pass_hat_k(4, 2, 1) == pytest.approx(0.5)
        assert pass_hat_k(4, 2, 2) == pytest.approx(1 / 6)  # C(2,2)/C(4,2)
        with pytest.raises(ValueError):
            pass_hat_k(3, 1, 4)

    def test_suite_with_repeats_reports_pass_k(self, rt, tmp_path):
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "01_lam.yaml").write_text(
            yaml.safe_dump(
                {
                    "task": "laminar pipe",
                    "spec": {
                        "name": "t-lam",
                        "case": {
                            "kind": "heated_pipe",
                            "reynolds": 500,
                            "turbulence_model": "laminar",
                            # Pr = 1: the water default needs 146 D to develop and pre-flight
                            # blocks a fully-developed reference in the default 40 D pipe.
                            "fluid": FLUID_PRESETS["unit_prandtl_liquid"].model_dump(),
                        },
                    },
                    "expect": {"max_attempts": 1, "qoi_ranges": {"Nu": [4.0, 4.7]}},
                }
            )
        )
        board = run_suite(tasks, rt, tmp_path / "out", repeats=2)
        assert board["repeats"] == 2 and board["n_runs"] == 2
        assert board["pass_hat_k"] == {1: 1.0, 2: 1.0}
        assert board["per_task"][0]["n_success"] == 2
        assert (tmp_path / "out" / "t-lam_rep1").is_dir()
