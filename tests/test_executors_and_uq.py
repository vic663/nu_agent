import os
import stat
from pathlib import Path

import numpy as np
import pytest

from nuagent.backends.base import CaseHandle
from nuagent.calibration import BayesianCalibrator, GPSurrogate, latin_hypercube
from nuagent.executors import DockerExecutor, LocalExecutor, SlurmExecutor
from nuagent.executors.local import request_openfoam_stop
from nuagent.physics import reduced
from nuagent.spec import ExecutionSpec, ParameterPrior
from nuagent.uq import sobol_analysis


def _case(tmp_path: Path, script: str, backend: str = "mock") -> CaseHandle:
    d = tmp_path / "case"
    d.mkdir(parents=True)
    allrun = d / "Allrun"
    allrun.write_text("#!/bin/bash\n" + script)
    allrun.chmod(allrun.stat().st_mode | stat.S_IEXEC)
    return CaseHandle(path=d, backend=backend, spec_hash="x")


class TestLocalExecutor:
    def test_runs_and_captures_output(self, tmp_path):
        case = _case(tmp_path, "echo hello; exit 0")
        res = LocalExecutor(poll_interval=0.1).run(case, ExecutionSpec())
        assert res.ok and "hello" in res.stdout_tail and res.executor == "local"

    def test_nonzero_exit(self, tmp_path):
        case = _case(tmp_path, "echo boom >&2; exit 3")
        res = LocalExecutor(poll_interval=0.1).run(case, ExecutionSpec())
        assert res.returncode == 3 and not res.ok

    def test_timeout_kills_process(self, tmp_path):
        case = _case(tmp_path, "sleep 30")
        res = LocalExecutor(poll_interval=0.1).run(case, ExecutionSpec(), timeout_s=0.5)
        assert res.returncode == 124 and res.details["timed_out"]

    def test_poll_callback_can_request_stop(self, tmp_path):
        case = _case(
            tmp_path,
            "for i in $(seq 1 40); do sleep 0.1; grep -q writeNow system/controlDict && exit 0; done; exit 7",
            backend="openfoam",
        )
        (case.path / "system").mkdir()
        (case.path / "system/controlDict").write_text("stopAt          endTime;\n")
        calls = []

        def on_poll(c, elapsed):
            calls.append(elapsed)
            return "stop"

        res = LocalExecutor(poll_interval=0.2, on_poll=on_poll).run(case, ExecutionSpec())
        assert res.ok and res.details["stopped_early"] and calls
        assert "writeNow" in (case.path / "system/controlDict").read_text()

    def test_request_stop_without_controldict(self, tmp_path):
        assert request_openfoam_stop(_case(tmp_path, "true")) is False


class TestDockerExecutor:
    def test_command_construction(self, tmp_path):
        case = _case(tmp_path, "true", backend="openfoam")
        cmd = DockerExecutor(user_mapping=False).command(case, ExecutionSpec())
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert "opencfd/openfoam-default:2512" in cmd and cmd[-1] == "./Allrun"
        cmd2 = DockerExecutor(user_mapping=False).command(
            _case(tmp_path / "b", "true", backend="festim"),
            ExecutionSpec(docker_image="my/festim:1"),
        )
        assert "my/festim:1" in cmd2 and cmd2[-2:] == ["bash", "./Allrun"]


class TestSlurmExecutor:
    @pytest.fixture
    def fake_slurm(self, tmp_path, monkeypatch):
        bindir = tmp_path / "bin"
        bindir.mkdir()
        state_file = tmp_path / "state"
        (bindir / "sbatch").write_text(
            "#!/bin/bash\n# run the script immediately in the background, print a job id\n"
            'nohup bash "${@: -1}" > /dev/null 2>&1 &\necho 4242\n'
        )
        (bindir / "squeue").write_text(
            f"#!/bin/bash\nif [ -f {state_file} ]; then echo ''; else echo RUNNING; fi\n"
        )
        (bindir / "sacct").write_text("#!/bin/bash\necho COMPLETED\n")
        for f in bindir.iterdir():
            f.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.setenv("NUAGENT_SLURM_MODULES", "openfoam/2412:gcc/13")
        monkeypatch.setenv("NUAGENT_SLURM_EXTRA", "--mem=8G;--qos=debug")
        return state_file

    def test_render_script(self, tmp_path, fake_slurm):
        case = _case(tmp_path, "true", backend="openfoam")
        ex = SlurmExecutor(cores_per_node=8)
        script = ex.render_script(
            case,
            ExecutionSpec(
                n_procs=20, wallclock_minutes=90, slurm_partition="compute", slurm_account="acct"
            ),
        )
        assert "#SBATCH --ntasks=20" in script and "#SBATCH --nodes=3" in script
        assert (
            "#SBATCH --time=01:30:00" in script
            and "--partition=compute" in script
            and "--account=acct" in script
        )
        assert "module load openfoam/2412" in script and "module load gcc/13" in script
        assert "#SBATCH --mem=8G" in script and "#SBATCH --qos=debug" in script
        assert "bash ./Allrun" in script

    def test_submit_poll_complete(self, tmp_path, fake_slurm):
        state_file = fake_slurm
        case = _case(
            tmp_path,
            f"echo ran > {tmp_path}/ran.txt; touch {state_file}; echo 0 > .nuagent_exit_code; exit 0",
            backend="mock",
        )
        ex = SlurmExecutor(poll_interval=0.2)
        res = ex.run(case, ExecutionSpec(executor="slurm", n_procs=1, wallclock_minutes=1))
        assert res.job_id == "4242"
        assert res.ok and res.details["state"] in ("COMPLETED",)
        assert (tmp_path / "ran.txt").exists()
        assert (case.path / "job.sbatch").exists()


class TestCalibration:
    def test_recovers_parameters_of_reduced_tds_model(self):
        T = np.linspace(310, 900, 60)
        model = reduced.FirstOrderDesorptionModel(T, beta=8.0)
        truth = {"E_p": 1.0, "n_t0": 1e25}
        rng = np.random.default_rng(3)
        y = model({**truth, "log10_p_0": 13.0})
        sigma = 0.03 * y.max()
        y_obs = y + rng.normal(0, sigma, size=y.shape)
        priors = [
            ParameterPrior(name="E_p", low=0.8, high=1.2),
            ParameterPrior(name="n_t0", low=1e24, high=1e26, log_scale=True),
        ]
        cal = BayesianCalibrator(model, priors, T, y_obs, sigma=sigma)
        res = cal.run(n_walkers=16, n_steps=250, burn_in=100, seed=1)
        ep, nt = res.summary["E_p"], res.summary["n_t0"]
        assert (
            abs(ep["mean"] - 1.0) < 3 * ep["std"] + 1e-3
        )  # truth within the 3-sigma posterior band
        assert nt["q05"] * 0.5 <= 1e25 <= nt["q95"] * 2.0
        assert abs(res.map_estimate["E_p"] - 1.0) < 0.03
        assert ep["std"] < 0.05
        assert 0.1 < res.acceptance_fraction < 0.9
        assert res.n_model_evaluations > 1000

    def test_inferred_noise(self):
        x = np.linspace(1e4, 1e5, 20)
        model = reduced.NusseltCorrelationModel(x, prandtl=1.0)
        y = model({}) * (1 + np.random.default_rng(0).normal(0, 0.02, size=x.shape))
        cal = BayesianCalibrator(
            model, [ParameterPrior(name="C", low=0.01, high=0.04)], x, y, sigma=None
        )
        res = cal.run(n_walkers=12, n_steps=200, burn_in=50, seed=0)
        assert isinstance(res.noise_sigma, dict) and res.noise_sigma["median"] > 0
        assert res.summary["C"]["q05"] <= 0.023 <= res.summary["C"]["q95"]

    def test_latin_hypercube_and_gp_surrogate(self):
        priors = [
            ParameterPrior(name="C", low=0.01, high=0.04),
            ParameterPrior(name="m", low=0.7, high=0.9),
        ]
        samples = latin_hypercube(priors, 10, seed=1)
        assert len(samples) == 10 and all(0.01 <= s["C"] <= 0.04 for s in samples)
        model = reduced.NusseltCorrelationModel(np.geomspace(1e4, 1e5, 12), prandtl=1.0)
        gp = GPSurrogate(priors, n_components=3, seed=0).fit(model, n_train=24, holdout=6)
        assert gp.holdout_rel_error < 0.05
        p = {"C": 0.023, "m": 0.8}
        rel = np.abs(gp(p) - model(p)) / model(p)
        assert rel.max() < 0.05


class TestUQ:
    def test_sobol_on_ishigami(self):
        # Ishigami function: known analytical Sobol indices S1 = (0.3139, 0.4424, 0), ST = (0.558, 0.442, 0.244)
        a, b = 7.0, 0.1

        def ishigami(p):
            x1, x2, x3 = p["x1"], p["x2"], p["x3"]
            return np.array([np.sin(x1) + a * np.sin(x2) ** 2 + b * x3**4 * np.sin(x1)])

        priors = [ParameterPrior(name=n, low=-np.pi, high=np.pi) for n in ("x1", "x2", "x3")]
        res = sobol_analysis(ishigami, priors, n_base=1024, seed=0)
        assert res.first_order["x1"] == pytest.approx(0.3139, abs=0.06)
        assert res.first_order["x2"] == pytest.approx(0.4424, abs=0.06)
        assert abs(res.first_order["x3"]) < 0.06
        assert res.total_order["x3"] == pytest.approx(0.244, abs=0.06)
        assert res.n_evaluations == 1024 * (3 + 2)

    def test_log_scale_parameter_decoding(self):
        priors = [ParameterPrior(name="D", low=1e-12, high=1e-8, log_scale=True)]
        seen = []

        def model(p):
            seen.append(p["D"])
            return np.array([np.log10(p["D"])])

        sobol_analysis(model, priors, n_base=8, seed=0)
        assert min(seen) >= 1e-12 * 0.999 and max(seen) <= 1e-8 * 1.001
