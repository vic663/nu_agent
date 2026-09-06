"""End-to-end workflow tests on the mock backend (no solver, no LLM)."""

import json
from pathlib import Path

import pytest

from nuagent.agent import RulesPolicy, Runtime, build_graph, run_workflow
from nuagent.agent.policy import Adjustments, Critique, LLMPolicy, rules_critique, rules_diagnose
from nuagent.backends import get_backend
from nuagent.backends.base import ConvergenceReport
from nuagent.executors import LocalExecutor
from nuagent.spec import FLUID_PRESETS, HeatedPipeCase, PermeationCase, SimulationSpec


@pytest.fixture
def rt():
    return Runtime(
        backend=get_backend("mock"), executor=LocalExecutor(poll_interval=0.2), policy=RulesPolicy()
    )


def _spec(name, case, **kw):
    return SimulationSpec(name=name, backend="mock", case=case, **kw).model_dump(mode="json")


class TestWorkflow:
    def test_happy_path_laminar(self, rt, tmp_path):
        out = run_workflow(
            rt,
            spec=_spec(
                "lam",
                HeatedPipeCase(
                    reynolds=500,
                    turbulence_model="laminar",
                    fluid=FLUID_PRESETS["unit_prandtl_liquid"],
                ),
            ),
            workdir=str(tmp_path / "lam"),
        )
        assert out["status"] == "success", out.get("error")
        assert out["attempt"] == 1
        nodes = [d["node"] for d in out["decisions"]]
        assert nodes[:6] == ["plan", "review", "build", "run", "monitor", "postprocess"]
        assert out["preflight"]["ok"] and not out["preflight"]["blocking"]
        assert out["validation"]["passed"]
        gci = out["verification"]["gci"]
        assert gci["Nu"]["observed_order"] == pytest.approx(2.0, abs=1e-6)
        assert gci["Nu"]["convergence"] == "monotonic"
        assert out["verification"]["exact_error"]["Nu"]["exact"] == pytest.approx(48 / 11)
        report = Path(out["report_path"])
        assert report.exists()
        text = report.read_text()
        assert "## 6. Validation" in text and "PASS" in text
        assert "## 2. Pre-flight review" in text
        assert (report.parent / "provenance.json").exists()
        assert (report.parent / "decisions.jsonl").exists()
        assert (report.parent / "figures" / "gci.png").exists()

    def test_diverging_numerics_are_repaired(self, rt, tmp_path):
        spec = _spec(
            "bad",
            HeatedPipeCase(reynolds=3e4, numerics={"relax_U": 0.9}),
            execution={"max_attempts": 3},
        )
        out = run_workflow(rt, spec=spec, workdir=str(tmp_path / "bad"))
        assert out["status"] == "success", out.get("error")
        assert out["attempt"] == 2
        assert out["adjustments"]["div_scheme"] == "upwind"
        assert out["adjustments"]["relax_U"] <= 0.5
        diag = [d for d in out["decisions"] if d["node"] == "diagnose"]
        assert len(diag) == 1 and "Divergence" in diag[0]["message"]

    def test_gives_up_after_budget(self, rt, tmp_path):
        # relax_U is clipped to >= 0.1 by the backend but the mock diverges for relax_U > 0.8 only;
        # force repeated failure by allowing a single attempt
        spec = _spec(
            "bad1",
            HeatedPipeCase(reynolds=3e4, numerics={"relax_U": 0.9}),
            execution={"max_attempts": 1},
        )
        out = run_workflow(rt, spec=spec, workdir=str(tmp_path / "bad1"))
        assert out["status"] == "failed"
        assert "budget" in out["error"] or "could not" in out["error"]
        assert Path(out["report_path"]).exists()

    def test_stalled_run_gets_more_iterations(self, rt, tmp_path):
        spec = _spec(
            "stall",
            HeatedPipeCase(
                reynolds=800,
                turbulence_model="laminar",
                # Pr = 1 and 100 D of pipe: at the water default the thermal entry length is
                # 233 D and pre-flight blocks the case as unvalidatable against 48/11.
                fluid=FLUID_PRESETS["unit_prandtl_liquid"],
                length_over_diameter=100,
                numerics={"max_iterations": 200},
            ),
            execution={"max_attempts": 3},
        )
        out = run_workflow(rt, spec=spec, workdir=str(tmp_path / "stall"))
        assert out["status"] == "success"
        assert out["adjustments"]["max_iterations"] >= 500

    def test_permeation_case_validates_against_analytical(self, rt, tmp_path):
        out = run_workflow(rt, spec=_spec("perm", PermeationCase()), workdir=str(tmp_path / "perm"))
        assert out["status"] == "success"
        res = out["validation"]["results"]
        assert res["permeation_flux_ss"]["passed"] and res["time_lag"]["passed"]
        assert res["time_lag"]["source"] == "analytical"

    def test_human_approval_gate(self, rt, tmp_path):
        spec = _spec(
            "hitl",
            HeatedPipeCase(
                reynolds=500,
                turbulence_model="laminar",
                fluid=FLUID_PRESETS["unit_prandtl_liquid"],
            ),
            execution={"require_approval": True},
        )
        paused = run_workflow(rt, spec=spec, workdir=str(tmp_path / "hitl"), auto_approve=False)
        assert paused["status"] == "needs_human"
        assert "__interrupt__" in paused
        resumed = run_workflow(rt, spec=spec, workdir=str(tmp_path / "hitl2"), auto_approve=True)
        assert resumed["status"] == "success"
        assert any(d["node"] == "approve" for d in resumed["decisions"])

    def test_graph_compiles_and_has_expected_nodes(self, rt):
        g = build_graph(rt)
        nodes = set(g.get_graph().nodes)
        assert {
            "plan",
            "review",
            "build",
            "approve",
            "run",
            "monitor",
            "diagnose",
            "postprocess",
            "verify",
            "model_form",
            "validate",
            "calibrate",
            "uq",
            "critique",
            "report",
        } <= nodes


class TestPolicies:
    def test_rules_diagnose_escalates(self):
        spec = SimulationSpec(name="x", backend="mock", case=HeatedPipeCase(reynolds=2e4))
        div = ConvergenceReport(converged=False, diverged=True, completed=False, iterations=50)
        a1 = rules_diagnose(spec, div, {}, 1)
        assert a1.div_scheme == "upwind" and not a1.give_up
        a2 = rules_diagnose(spec, div, {"div_scheme": "upwind", "relax_U": 0.5, "relax_p": 0.2}, 2)
        assert a2.relax_U < 0.5 and not a2.give_up
        a3 = rules_diagnose(
            spec,
            div,
            {"div_scheme": "upwind", "relax_U": 0.1, "relax_p": 0.05, "relax_turbulence": 0.1},
            3,
        )
        assert a3.give_up
        stalled = ConvergenceReport(
            converged=False, diverged=False, completed=True, iterations=3000, bounding_events=3
        )
        a4 = rules_diagnose(spec, stalled, {}, 1)
        assert a4.max_iterations == 6000 and a4.relax_turbulence is not None

    def test_rules_critique_flags_problems(self):
        spec = SimulationSpec(name="x", backend="mock", case=HeatedPipeCase(reynolds=2e4))
        results = {
            "qois": {
                "values": {"Nu": 100.0},
                "checks": {"energy_balance_error": 0.05, "yplus_avg": 12.0},
            },
            "verification": {"gci": {"Nu": {"convergence": "oscillatory", "gci_fine": 0.2}}},
            "validation": {"results": {"Nu": {"passed": False}}},
        }
        c = rules_critique(spec, results)
        assert c.verdict == "reject"
        assert (
            any("energy" in w for w in c.warnings)
            and any("y+" in w for w in c.warnings)
            and any("oscillatory" in w for w in c.warnings)
        )
        good = rules_critique(
            spec,
            {
                "qois": {"values": {"Nu": 100.0}, "checks": {}},
                "verification": {},
                "validation": {"results": {"Nu": {"passed": True}}},
            },
        )
        assert good.verdict == "accept"

    def test_llm_policy_falls_back_to_rules_when_model_fails(self):
        class BrokenModel:
            def with_structured_output(self, schema):
                raise RuntimeError("no network")

        pol = LLMPolicy(model=BrokenModel())
        spec = SimulationSpec(name="x", backend="mock", case=HeatedPipeCase(reynolds=2e4))
        rep = ConvergenceReport(converged=False, diverged=True, completed=False, iterations=10)
        adj = pol.diagnose(spec, rep, "", {}, 1)
        assert adj.div_scheme == "upwind" and "rules applied" in adj.rationale
        crit = pol.critique(
            spec, {"qois": {"values": {}, "checks": {}}, "verification": {}, "validation": {}}
        )
        assert isinstance(crit, Critique)

    def test_llm_policy_uses_structured_output(self):
        class FakeStructured:
            def __init__(self, schema):
                self.schema = schema

            def invoke(self, messages):
                if self.schema is SimulationSpec:
                    return SimulationSpec(
                        name="planned", backend="mock", case=HeatedPipeCase(reynolds=1e4)
                    )
                if self.schema is Adjustments:
                    return Adjustments(relax_U=0.4, rationale="LLM says relax")
                return Critique(verdict="accept", warnings=["llm note"], summary="ok")

        class FakeModel:
            def with_structured_output(self, schema):
                return FakeStructured(schema)

        pol = LLMPolicy(model=FakeModel())
        spec = pol.plan("simulate a pipe")
        assert spec.name == "planned"
        adj = pol.diagnose(spec, ConvergenceReport(False, True, False, 5), "", {}, 1)
        assert adj.relax_U == 0.4
        crit = pol.critique(
            spec,
            {
                "qois": {"values": {}, "checks": {}},
                "verification": {},
                # a real comparison that ran and disagreed (a row with no relative_error and no
                # error key is malformed, and is now classified as "unevaluable" instead)
                "validation": {
                    "results": {
                        "Nu": {
                            "quantity": "Nu",
                            "passed": False,
                            "relative_error": -0.42,
                            "source": "gnielinski",
                            "tolerance": 0.15,
                        }
                    }
                },
            },
        )
        assert crit.verdict == "reject"  # rules verdict is authoritative
        assert "llm note" in crit.warnings and any("validation failed" in w for w in crit.warnings)

    def test_adjustments_schema_bounds(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Adjustments(relax_U=1.5)
        a = Adjustments(relax_U=0.3, rationale="x")
        assert a.as_dict() == {"relax_U": 0.3}


def test_result_json_is_written(rt, tmp_path):
    out = run_workflow(
        rt,
        spec=_spec(
            "lam2",
            HeatedPipeCase(
                reynolds=500,
                turbulence_model="laminar",
                fluid=FLUID_PRESETS["unit_prandtl_liquid"],
            ),
        ),
        workdir=str(tmp_path / "lam2"),
    )
    data = json.loads((Path(out["report_path"]).parent / "result.json").read_text())
    assert data["status"] == "success" and "qois" in data


def test_relative_workdir_works_from_any_cwd(rt, tmp_path, monkeypatch):
    """`nuagent run spec.yaml` without --workdir uses runs/<name>: relative paths must survive the
    executor's change of directory into the case (regression)."""
    monkeypatch.chdir(tmp_path)
    out = run_workflow(
        rt,
        spec=_spec(
            "rel",
            HeatedPipeCase(
                reynolds=500,
                turbulence_model="laminar",
                fluid=FLUID_PRESETS["unit_prandtl_liquid"],
            ),
        ),
        workdir="runs/rel",
    )
    assert out["status"] == "success", out.get("error")
    assert Path(out["workdir"]).is_absolute()
    assert (tmp_path / "runs" / "rel" / "report.md").exists()
