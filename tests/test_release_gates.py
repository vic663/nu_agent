"""Regression tests for the gates that make V&V binding rather than advisory.

Each test here corresponds to a defect found by audit, in which the workflow could report — or the
qualification suite could score — a result that had not been earned.  They are grouped separately
from the physics tests because what they protect is the *meaning* of a NuAgent verdict.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nuagent.agent.graph import run_workflow
from nuagent.agent.nodes import Runtime
from nuagent.backends.mock.backend import MockBackend
from nuagent.evals.harness import task_success
from nuagent.executors.local import LocalExecutor
from nuagent.spec import FLUID_PRESETS, RibbedTubeCase, SimulationSpec

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def rt():
    return Runtime(backend=MockBackend(), executor=LocalExecutor())


class TestCritiqueIsAGate:
    """`critique.verdict` used to be computed and then never consulted by the status."""

    def test_rejected_result_is_reported_as_failed(self, rt, tmp_path):
        # k-omega SST on a p/e = 10 ribbed passage: the run converges cleanly and is still wrong.
        spec = SimulationSpec(
            name="reject",
            backend="mock",
            case=RibbedTubeCase(
                fluid=FLUID_PRESETS["air_300K"],
                reynolds=20000,
                turbulence_model="kOmegaSST",
                rib_height_over_diameter=0.04,
                rib_pitch_over_height=10,
                n_ribs=10,
            ),
            validation={
                "references": [
                    {"quantity": "Nu", "source": "webb", "tolerance": 0.20},
                    {"quantity": "f", "source": "webb", "tolerance": 0.15},
                ]
            },
        )
        out = run_workflow(rt, spec=spec.model_dump(mode="json"), workdir=str(tmp_path / "reject"))
        assert out["convergence"]["converged"], "the run itself must converge — that is the point"
        assert out["critique"]["verdict"] == "reject"
        assert out["validation"]["passed"] is False
        # the verdict, not the execution, decides
        assert out["status"] == "failed"
        report = Path(out["report_path"]).read_text()
        assert "**Status:** FAILED" in report
        assert "critique rejected" in report, "the reader must see why a converged run failed"


class TestQualificationGrading:
    """An ordinary task must produce a *credible* answer, not merely a finished one."""

    def _row(self, **kw):
        row = {
            "status": "success",
            "validated": True,
            "critique_verdict": "accept",
            "expected_ranges_ok": True,
            "attempts_ok": True,
            "expect": {},
        }
        row.update(kw)
        return row

    def test_good_run_scores_success(self):
        assert task_success(self._row())
        assert task_success(self._row(critique_verdict="accept_with_warnings"))

    @pytest.mark.parametrize(
        "kw",
        [
            # QoIs in range, but V&V did not clear the result: the masquerade case
            {"status": "completed_with_issues", "validated": False, "critique_verdict": "reject"},
            {"validated": False},
            {"critique_verdict": "reject"},
            {"status": "completed_with_issues"},
            {"expected_ranges_ok": False},
            {"attempts_ok": False},
        ],
    )
    def test_uncredible_run_does_not_score_success(self, kw):
        assert not task_success(self._row(**kw))

    def test_negative_control_is_graded_in_the_opposite_direction(self):
        expect = {"outcome": "fail", "validation_passed": False, "critique_verdict": "reject"}
        caught = self._row(
            status="failed", validated=False, critique_verdict="reject", expect=expect
        )
        assert task_success(caught), "refusing a defective set-up is the correct outcome"
        missed = self._row(expect=expect)  # validated a case it should have refused
        assert not task_success(missed)

    def test_suite_contains_negative_controls(self):
        """A suite whose only possible outcome is 'pass' qualifies nothing."""
        tasks = sorted((REPO / "evals" / "tasks").glob("*.yaml"))
        negatives = [
            f
            for f in tasks
            if (yaml.safe_load(f.read_text()).get("expect") or {}).get("outcome") == "fail"
        ]
        assert len(negatives) >= 3, f"only {len(negatives)} negative controls in {len(tasks)} tasks"


class TestValidationFailsClosed:
    """Only an explicit ``passed is True`` earns validation credit.

    Absence of evidence is not evidence of validation: ASME V&V 20 defines validation as the
    quantified comparison of a solution with referent data, so a comparison that was never formed
    cannot support a positive claim.  These tests pin the *default*, not a reproducible escape
    path — ``validate()`` writes ``passed: False`` on both of its error branches today, and this
    is what stops a future writer of a validation record from failing open by omission.
    """

    def _spec(self):
        from nuagent.spec import HeatedPipeCase

        return SimulationSpec(name="fc", backend="mock", case=HeatedPipeCase(reynolds=20000))

    def test_unevaluable_reference_cannot_be_treated_as_passed(self):
        from nuagent.agent.policy import rules_critique

        results = {
            "validation": {
                "results": {
                    # intentionally no "passed" key at all
                    "Nu": {"quantity": "Nu", "error": "reference unavailable"}
                }
            }
        }
        crit = rules_critique(self._spec(), results)
        assert crit.verdict == "reject"
        assert any("validation unevaluable for: Nu" in w for w in crit.warnings)

    def test_none_is_not_a_pass(self):
        from nuagent.agent.policy import rules_critique

        results = {"validation": {"results": {"Nu": {"quantity": "Nu", "passed": None}}}}
        assert rules_critique(self._spec(), results).verdict == "reject"

    def test_failed_and_unevaluable_are_reported_separately(self):
        from nuagent.agent.policy import rules_critique

        results = {
            "validation": {
                "results": {
                    # a comparison that ran and disagreed
                    "Nu": {
                        "quantity": "Nu",
                        "passed": False,
                        "relative_error": -0.5,
                        "source": "webb",
                        "tolerance": 0.2,
                    },
                    # a comparison that could not be formed
                    "f": {"quantity": "f", "passed": False, "error": "no such reference"},
                }
            }
        }
        crit = rules_critique(self._spec(), results)
        assert crit.verdict == "reject"
        assert any(w.startswith("validation failed for: Nu") for w in crit.warnings)
        assert any(w.startswith("validation unevaluable for: f") for w in crit.warnings)

    def test_missing_dataset_file_is_a_structured_error_not_a_traceback(self, rt, tmp_path):
        """`dataset:<path>` used to raise FileNotFoundError out of validate(); only KeyError was caught."""
        from nuagent.spec import HeatedPipeCase

        spec = SimulationSpec(
            name="nodataset",
            backend="mock",
            case=HeatedPipeCase(reynolds=20000),
            validation={
                "references": [
                    {
                        "quantity": "Nu",
                        "source": f"dataset:{tmp_path / 'does-not-exist.csv'}",
                        "tolerance": 0.1,
                    }
                ]
            },
        )
        out = run_workflow(rt, spec=spec.model_dump(mode="json"), workdir=str(tmp_path / "nd"))
        row = out["validation"]["results"]["Nu"]
        assert row["passed"] is False
        assert "FileNotFoundError" in row["error"]
        assert out["validation"]["passed"] is False
        # a reference that could not be evaluated blocks certification
        assert out["critique"]["verdict"] == "reject"
        assert out["status"] == "failed"


class TestWorkflowFileIsUsable:
    """The CI workflow was invalid YAML from the first commit, so no job had ever run."""

    def test_ci_workflow_parses_and_defines_the_expected_jobs(self):
        ci = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
        assert set(ci["jobs"]) == {"unit", "openfoam", "festim"}

    def test_ci_triggers_on_the_default_branch(self):
        """`push.branches` matches the literal ref name; `master` would never fire a `main` trigger."""
        ci = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
        # yaml parses the bare key `on` as the boolean True
        trigger = ci.get("on") or ci.get(True)
        assert "main" in trigger["push"]["branches"]
        head = REPO / ".git" / "HEAD"
        if head.exists() and "ref:" in head.read_text():
            branch = head.read_text().strip().rsplit("/", 1)[-1]
            assert branch in trigger["push"]["branches"], (
                f"the repository is on '{branch}' but CI only triggers on "
                f"{trigger['push']['branches']}"
            )


class TestNoUnreleasedDateClaims:
    def test_citation_does_not_claim_a_release_that_has_not_happened(self):
        cff = yaml.safe_load((REPO / "CITATION.cff").read_text())
        changelog = (REPO / "CHANGELOG.md").read_text()
        version = cff["version"]
        unreleased = f"## {version} — Unreleased" in changelog
        if unreleased:
            assert "date-released" not in cff, (
                f"CHANGELOG marks {version} unreleased but CITATION.cff carries a release date"
            )
