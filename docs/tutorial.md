# Running NuAgent — a hands-on guide

This walks you from a fresh checkout to a validated CFD result, one command at a time, and explains what
the agent is doing at each step so you can narrate a live demo. Every command below was executed while
writing this page; timings are for a laptop core.

## 0. The mental model (30 seconds)

You give NuAgent a **specification** (a YAML file, or a sentence that an LLM turns into that YAML). The
workflow then walks a fixed graph:

```
plan → review → build → approve → run → monitor → postprocess → verify → model_form → validate
                                    ↑        ↓ diverged / stalled
                                    └── diagnose (bounded numerics changes, max N attempts)
                        … → calibrate → uq → critique → report
```

* `plan` validates the spec (or asks an LLM to write one and validates *that*).
* `review` is an independent pre-flight check: are the validation correlations valid at this Reynolds
  number, is the mesh consistent with the wall treatment, is the pipe long enough, is a known-bad closure
  being used? Blocking problems stop the run here, before any solver time.
* `build` renders the solver case from templates (no free text reaches the solver), `run` executes it,
  `monitor` reads residuals, `diagnose` proposes bounded numerics changes if it diverged or stalled.
* `verify` runs two coarser grids and computes the grid-convergence index (GCI); `model_form` re-runs the
  case with alternative turbulence closures and reports the spread as model-form uncertainty;
  `validate` compares against exact solutions or correlations *with their own uncertainty band*.
* `critique` applies physics sanity rules (balances, y⁺, reattachment, closure disagreement) and `report`
  writes a Markdown report with figures, the decision log and a provenance record.

By default no LLM is involved at all (`--policy rules`). That is deliberate: the deterministic path is the
baseline against which an LLM policy is measured (`nuagent eval`).

## 1. Install (5 minutes)

You need Python 3.10 or newer. The repository lives in `D:\CFD_Agent\nuagent` on your machine.

**Windows (PowerShell)**

```powershell
cd D:\CFD_Agent\nuagent
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if scripts are blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -U pip
pip install -e ".[dev]"               # add ,anthropic or ,openai inside the brackets if you want an LLM
nuagent --version
nuagent doctor                        # tells you which solvers / LLM keys it can see
```

**Linux, macOS or WSL2 Ubuntu**

```bash
cd ~/nuagent            # or /mnt/d/CFD_Agent/nuagent from WSL
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
nuagent doctor
```

Everything except the real solvers works on native Windows (the mock solver, the LLM policies,
calibration, UQ, the evals). OpenFOAM and FESTIM need a Unix environment — WSL2 or Docker, see §5–6.

## 2. Your first run: the mock solver (1 minute, no OpenFOAM, no LLM)

```bash
nuagent run examples/heated_pipe/laminar_verification.yaml --backend mock
```

`--backend mock` swaps OpenFOAM for an analytical "solver" that has controlled discretisation error and
can be made to misbehave on purpose. The console prints the QoIs, the validation table, the GCI table and
the review verdict; the last line is the path of the report, `runs/pipe-laminar-Re200/report.md`.

Open that folder. It is the whole audit trail:

| File | What it is |
|---|---|
| `report.md`, `figures/` | the human-readable report: problem, pre-flight review, run summary, QoIs, GCI, (closure ensemble), validation, review, decision log, provenance |
| `decisions.jsonl` | one line per agent decision, in order — this is what to show when someone asks "what did the agent do?" |
| `provenance.json` | git commit, package and solver versions, spec hash, input digests |
| `preflight.json` | the pre-flight findings |
| `result.json` | everything machine-readable (QoIs, verification, validation, critique) |
| `spec.yaml` | the exact specification that was run |
| `attempt_1/` | the solver case as built and run (`Allrun`, input files, log) |
| `verify_r0.5/`, `verify_r0.25/` | the coarser grids of the grid-convergence study |

Read the report top to bottom once. Section 2 ("Pre-flight review") says *no findings* for this clean
case; section 5 shows the observed order of convergence (2.0 for the mock) and the GCI; section 6 shows
Nu within 1.7 % of 48/11 and f within 0.8 % of 64/Re, marked PASS with the tolerance and the reference
band; the decision log at the end lists every node in order.

Re-render the report from the stored results any time (useful after editing the template):

```bash
nuagent report runs/pipe-laminar-Re200
```

## 3. Watch the agent recover from a bad setup (1 minute)

The evaluation tasks double as demos. Task 03 deliberately asks for an unstable under-relaxation factor
(`relax_U: 0.9` on a turbulent case) and task 04 for an iteration budget too small to converge:

```bash
nuagent run evals/tasks/03_diverging_setup_recovery.yaml --backend mock --workdir runs/demo-diverge
nuagent run evals/tasks/04_stalled_run_recovery.yaml --backend mock --workdir runs/demo-stall
```

(Task files carry an extra `task:`/`expect:` block; `nuagent run` uses their `spec:` part.) In
`runs/demo-diverge/decisions.jsonl` you will see
`monitor: diverged`, then `diagnose` proposing *bounded* changes (switch to upwind, cut `relax_U` to 0.5),
then a second `build`/`run` that converges. In the stalled case the diagnosis doubles the iteration budget
and the case is *continued* from its last iteration rather than rebuilt. Attempts are capped by
`execution.max_attempts`; when the table of remedies is exhausted the agent gives up and says so.

## 4. Write your own specification

Copy `examples/heated_pipe/turbulent_validation.yaml` and edit. The important blocks:

```yaml
name: my-pipe-Re50k
backend: openfoam                 # openfoam | festim | mock
case:
  kind: heated_pipe               # heated_pipe | ribbed_tube | permeation | tds
  fluid: {name: water_300K, rho: 996.0, mu: 8.5e-4, cp: 4180.0, k: 0.61}
  diameter: 0.02
  length_over_diameter: 40
  reynolds: 50000
  wall_heat_flux: 5.0e4
  turbulence_model: kOmegaSST     # laminar | kOmegaSST | kEpsilon | realizableKE | LaunderSharmaKE
  wall_treatment: resolved        # resolved (y+ ~ 1) | wall_function (y+ ~ 40)
  mesh: {n_radial: 40, cells_per_diameter: 10, target_yplus: 1.0}
verification: {mesh_study: true, refinement_ratio: 2.0, n_levels: 3}
validation:
  references:
    - {quantity: Nu, source: gnielinski, tolerance: 0.15}
    - {quantity: f,  source: petukhov,   tolerance: 0.10}
model_form:                       # optional closure ensemble
  closures: [kEpsilon, realizableKE, LaunderSharmaKE]
  parallel: 2
execution: {executor: local, n_procs: 1, max_attempts: 3, wallclock_minutes: 60}
```

The schema is strict on purpose: a laminar Reynolds number with a turbulence model or an out-of-range
relaxation factor is rejected at `plan`, and an unknown correlation name or a correlation outside its
validity range is caught by the pre-flight `review` — each with a message that says what to fix. Before running a spec you can look at exactly what would be sent to the solver:

```bash
nuagent build my-pipe.yaml --out runs/inspect         # dry run: writes the case, runs nothing
```

Available reference sources: `laminar` (exact), `gnielinski`, `dittus_boelter`, `petukhov`, `blasius`,
`prandtl_karman`, `webb` (ribbed tubes), `analytical` (FESTIM cases), and `dataset:path/to/file.csv`
for your own measurements (columns `quantity,value,uncertainty`).

## 5. Real CFD with OpenFOAM

OpenFOAM does not run on native Windows. Two routes:

**Route A — WSL2 (recommended for development).** In an Ubuntu WSL2 terminal:

```bash
curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt-get install -y openfoam2412-default
source /usr/lib/openfoam/openfoam2412/etc/bashrc     # NuAgent also finds it automatically
cd /mnt/d/CFD_Agent/nuagent && source .venv/bin/activate   # a venv created inside WSL, not the Windows one
nuagent doctor                                       # OpenFOAM: /usr/lib/openfoam/openfoam2412/etc/bashrc
nuagent run examples/heated_pipe/laminar_verification.yaml           # ≈ 30 s incl. the 3-level grid study
nuagent run examples/heated_pipe/turbulent_validation.yaml           # ≈ 2 min; add model_form for the ensemble
nuagent run examples/aerospace/ribbed_cooling_tube.yaml              # ≈ 15 min + ≈ 15 min per ensemble member
```

Working under `/mnt/d/...` is slower than the WSL file system; for long runs copy the repo to `~/nuagent`.

**Route B — Docker Desktop (no OpenFOAM install).** The Python workflow runs on Windows, only the solver
runs in the official container:

```powershell
nuagent run examples/heated_pipe/laminar_verification.yaml --executor docker
```

The first call pulls `opencfd/openfoam-default:2512` (≈ 1 GB). Or run everything inside a container that
has both NuAgent and OpenFOAM:

```bash
docker compose -f docker/compose.yaml build openfoam
docker compose -f docker/compose.yaml run openfoam nuagent run examples/heated_pipe/laminar_verification.yaml
```

While a real run is going, the local executor polls the log every few seconds and asks OpenFOAM to write
and stop as soon as NuAgent's convergence criterion is met (`stopAt writeNow`), so you rarely wait for the
full iteration budget. You can watch a run with `tail -f runs/<name>/attempt_1/log.buoyantSimpleFoam`.

## 6. Hydrogen transport with FESTIM

FESTIM needs dolfinx; use the container:

```bash
docker compose -f docker/compose.yaml build festim
docker compose -f docker/compose.yaml run festim nuagent run examples/tritium_permeation/permeation_verification.yaml
docker compose -f docker/compose.yaml run festim nuagent run examples/tritium_permeation/permeation_with_trap.yaml
```

The permeation case is verified against the Crank series (steady flux and time lag) and the trap case
against the Oriani effective diffusivity. Note: the FESTIM runner is unit-tested for case generation and
post-processing but the end-to-end container run has not yet been exercised in this repository — run it,
and if the FESTIM 2.x API has moved, `src/nuagent/backends/festim/run_festim.py` is the only file to touch.

## 7. Adding an LLM (optional)

The LLM does three things and nothing else: it can write the specification from a sentence (`plan`), add
concerns to the pre-flight review (`review`), propose bounded numerics changes (`diagnose`), and add
warnings to the critique. Every proposal passes through the same schema validators as a human-written
spec, and the rules verdict cannot be overturned.

```powershell
pip install -e ".[anthropic]"            # or .[openai]
$env:ANTHROPIC_API_KEY = "sk-ant-..."    # PowerShell; bash: export ANTHROPIC_API_KEY=...
nuagent ask "Turbulent water flow in a 20 mm pipe at Re=20000 with 50 kW/m2 heating; validate Nu and f" --backend mock --plan-only
```

`--plan-only` prints the validated spec the model produced and stops — the cheapest way to see what the
planner does. Drop `--plan-only` to run it. To use an LLM for diagnosis/critique on an existing spec:

```bash
nuagent run examples/heated_pipe/turbulent_validation.yaml --backend mock --policy llm --model anthropic:claude-sonnet-4-5
```

**Local, no tokens.** Any OpenAI-compatible server works (Ollama, vLLM, LM Studio):

```bash
ollama pull qwen2.5:14b
export OPENAI_BASE_URL=http://localhost:11434/v1
nuagent ask "..." --model openai:qwen2.5:14b --backend mock --plan-only
```

If nothing is configured, `nuagent ask` prints exactly which variables to set instead of a traceback.

## 8. Qualify the agent (the part reviewers care about)

```bash
nuagent eval evals/tasks --backend mock --policy rules --repeats 3
```

This runs all ten tasks — seven positive tasks and three negative controls that must be refused — three times each and prints a table plus `pass^k`, the probability that *all*
k independent trials are graded correctly (τ-bench). With the deterministic rules policy on the mock backend, 100 % and pass^3 = 1.0 are control-flow/qualification checks, not evidence of CFD accuracy; the informative model-comparison experiment is the same command with `--policy llm --model ...`, which
answers "how reliable is the LLM planner, and how many attempts does it need?" Details are in
`runs/evals/scoreboard.json` (`per_task`, `pass_hat_k`, `tasks`), and every task's full run directory sits
beside it. Task 07 additionally checks that the critique attributes the SST closure's low Nu to the
missing reattachment, so a policy that silently accepts the wrong closure fails the task.

## 9. Calibration and UQ (no solver needed)

```bash
nuagent calibrate examples/tds_calibration/tds_reduced_calibration.yaml --out runs/tds-cal   # ≈ 1.5 min, emcee
nuagent uq        examples/tds_calibration/tds_reduced_calibration.yaml --out runs/tds-uq    # ≈ 10 s, Sobol
```

The calibration recovers the trap energy, pre-exponential and inventory from a synthetic thermal-desorption
spectrum and prints the MAP, posterior mean and credible interval against the truth; the UQ prints
first-order and total Sobol indices. Both blocks also run automatically inside `nuagent run` when a spec
contains `calibration:` or `uq:` sections.

## 10. Clusters and the approval gate

```bash
export NUAGENT_SLURM_MODULES="openfoam/2412"       # or NUAGENT_FOAM_BASHRC=/path/to/etc/bashrc
nuagent run examples/heated_pipe/turbulent_slurm.yaml --executor slurm
```

With `execution.require_approval: true` the workflow stops before submission and prints the case path,
cell count, partition and wall-clock request; re-run with `--auto-approve` (or answer the interrupt from
Python) to submit. The SLURM executor polls `squeue`/`sacct`, and the same `Allrun --continue` mechanism
extends a stalled job without re-meshing.

## 11. From Python

```python
from nuagent.agent import Runtime, RulesPolicy, run_workflow
from nuagent.backends import get_backend
from nuagent.executors import LocalExecutor
from nuagent.spec import SimulationSpec, RibbedTubeCase

spec = SimulationSpec(
    name="ribs-demo", backend="mock",
    case=RibbedTubeCase(reynolds=2e4, turbulence_model="LaunderSharmaKE"),
    model_form={"closures": ["kOmegaSST", "kEpsilon"], "parallel": 2},
)
rt = Runtime(backend=get_backend("mock"), executor=LocalExecutor(), policy=RulesPolicy())
state = run_workflow(rt, spec=spec.model_dump(mode="json"), workdir="runs/ribs-demo")
print(state["status"], state["validation"]["passed"])
print(state["model_form"]["spread"]["Nu"]["model_form_uncertainty"])
for d in state["decisions"]:
    print(d["node"], "—", d["message"])
```

`build_graph(rt)` returns the compiled LangGraph if you want to step through it node by node or draw it
(`build_graph(rt).get_graph().draw_mermaid()`).

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `bash: ... No such file or directory` or `no 'bash' on PATH` | Native Windows without Git Bash. The mock backend runs anyway (it ships an `Allrun.py` twin); OpenFOAM/FESTIM need WSL2 or `--executor docker`. |
| `OpenFOAM: not found` in `nuagent doctor` | Set `NUAGENT_FOAM_BASHRC=/path/to/OpenFOAM/etc/bashrc` or use `--executor docker`. |
| `Value error, Re=... is laminar but turbulence_model=...` | The schema refuses inconsistent physics; set `turbulence_model: laminar` or change Re. |
| Pre-flight warning "outside the correlation's stated validity range" | Your Re/Pr is outside Gnielinski/Dittus–Boelter/Webb limits; pick another reference or accept that the comparison is an extrapolation. |
| Run ends `completed_with_issues` | Everything ran but validation or a physics check did not pass; read the "Review" section of the report — it says which. |
| `could not obtain a converged solution: attempt budget exhausted` | Raise `execution.max_attempts`, loosen `numerics.residual_target`, or look at `attempt_N/log.*` — the agent will not guess beyond its whitelist. |
| Repeated `nuagent run` is instant | Intentional: a case built from an identical spec in the same directory is reused. Change the spec or the `--workdir` to recompute. |

## 13. What to say when demoing each node

* **review** — "Nothing reaches the solver until an independent checker has looked at the plan. This is
  the generator–verifier split from the agent literature; here the verifier is deterministic code."
* **build** — "The solver input is rendered from validated numbers through strict templates. There is no
  path for a hallucinated boundary condition."
* **diagnose** — "It may only change whitelisted numerics within hard bounds, and the run is *continued*
  from its last iteration when possible — hours of HPC time are never thrown away."
* **verify** — "Three grids, Richardson extrapolation, GCI per ASME V&V 20, and the report says whether
  the grid family is in the asymptotic range."
* **model_form** — "For separated flows the closure is the dominant uncertainty, so we measure it: the
  same case with four closures, spread reported next to the GCI. In the ribbed tube it is an order of
  magnitude larger."
* **validate** — "Reference values carry their own uncertainty band; validation is a consistency statement
  between the numerical band and the reference band, not a claim of truth."
* **eval** — "The agent has a test suite with known answers and a reliability statistic over repeats; the
  deterministic policy is the baseline the LLM has to beat."
