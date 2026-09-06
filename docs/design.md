# NuAgent — design and architecture

## 1. Problem statement

Simulation engineers spend most of their time on the loop *set up → run → look at residuals → fix →
post-process → compare with something trustworthy → write it up*. Language-model agents can automate
that loop, but a national-laboratory environment asks a harder question than "can it run OpenFOAM?":
**can the agent's output be trusted, and can that trust be demonstrated?** NuAgent is an attempt to answer
"yes" by construction:

1. the agent's degrees of freedom are typed and bounded;
2. every step below the planner is deterministic, testable code;
3. verification and validation are compulsory nodes of the workflow, not an afterthought;
4. the agent itself has a test suite (evals) with problems whose answers are known.

## 2. Layered architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│ CLI / MCP (planned)          nuagent run | ask | build | eval | calibrate  │
├────────────────────────────────────────────────────────────────────────────┤
│ agent/    LangGraph state machine · policies (rules | LLM) · V&V logic     │
├────────────────────────────────────────────────────────────────────────────┤
│ calibration/ (emcee, GP)   uq/ (Sobol)   reporting/ (Markdown, provenance) │
├────────────────────────────────────────────────────────────────────────────┤
│ backends/   openfoam (templates, meshing, log & field readers)             │
│             festim   (params.json → run_festim.py → results.csv)           │
│             mock     (analytical results, controllable failures)           │
├────────────────────────────────────────────────────────────────────────────┤
│ executors/  local (live monitor) · docker · slurm (approval gate)          │
├────────────────────────────────────────────────────────────────────────────┤
│ physics/    correlations · analytical solutions · reduced-order models     │
│ spec.py     SimulationSpec (Pydantic) — the contract everything shares     │
└────────────────────────────────────────────────────────────────────────────┘
```

Each layer can be used without the ones above it: `physics` and `verification` are plain functions,
`backends` build cases that can be run by hand, `executors` run any `Allrun`, and the agent is a thin
orchestration on top. This separation makes the system testable: the fast unit suite runs without external solvers, while OpenFOAM and FESTIM integration tests are marked and exercised separately in CI.

## 3. The specification as contract

`SimulationSpec` (Pydantic v2) is the *only* artefact the planner produces:

```yaml
name: pipe-turbulent-Re20k
backend: openfoam
case:
  kind: heated_pipe          # discriminated union: heated_pipe | permeation | tds
  fluid: {name: water_300K, rho: 996, mu: 8.5e-4, cp: 4180, k: 0.61}
  diameter: 0.02
  reynolds: 20000
  turbulence_model: kOmegaSST
  mesh: {n_radial: 40, cells_per_diameter: 10, target_yplus: 1.0}
  numerics: {relax_U: 0.7, relax_p: 0.3, div_scheme: linearUpwind, max_iterations: 4000}
verification: {mesh_study: true, refinement_ratio: 2.0, n_levels: 3}
validation:
  references: [{quantity: Nu, source: gnielinski, tolerance: 0.15}, {quantity: f, source: petukhov, tolerance: 0.10}]
execution: {executor: local, n_procs: 1, max_attempts: 3}
```

Model validators encode physics consistency (a laminar Reynolds number with a turbulence model is
rejected; a FESTIM backend with a CFD case is rejected). Field descriptions double as the prompt for the
LLM's structured output, so the schema is documentation, validation and prompt at once.

## 4. The workflow graph

Implemented with LangGraph (`agent/graph.py`). Nodes are pure functions of the state; routing reads the
state written by deterministic nodes.

| Node | Deterministic? | What it does |
|---|---|---|
| `plan` | rules: yes / LLM: no | spec → validated; or natural language → `SimulationSpec` via structured output |
| `review` | rules: yes / LLM: adds | **independent pre-flight verifier** of the plan: correlation validity at (Re, Pr, geometry), y⁺ vs wall treatment, entry length vs evaluation region, closure lessons learned (SST on p/e = 10 ribs), FESTIM time scales (final time vs 3 L²/D, step vs time lag), blocking problems (TDS without traps); writes `preflight.json`; blocking → report |
| `build` | yes | backend renders the case (templates + validated numbers), computes mesh sizing, hashes inputs |
| `approve` | human | `interrupt()` before expensive/HPC runs when `require_approval` |
| `run` | yes | executor runs `Allrun`; local executor polls the log and can stop a converged run early |
| `monitor` | yes | parses residuals, continuity, bounding, fatal errors → `converged / stalled / diverged` |
| `diagnose` | rules: yes / LLM: no | proposes **bounded** numerics changes; decides whether to *continue* the case or rebuild; gives up when the table is exhausted or attempts run out |
| `postprocess` | yes | QoIs from raw fields (Nu, f, ΔT, balances) or `results.csv` |
| `verify` | yes | builds and runs coarser levels, Richardson extrapolation, GCI, exact-solution error |
| `model_form` | yes | **closure ensemble** (orchestrator–workers): re-runs the base grid with each closure in `spec.model_form.closures` (thread pool, `parallel`), reuses identical cases, reduces to spread / half-range model-form uncertainty vs GCI, deviation of every member from the reference, per-closure reattachment and y⁺ diagnostics; writes `model_form.json` |
| `validate` | yes | references from correlations (with uncertainty), analytical solutions or datasets — primary closure only |
| `calibrate` | yes | emcee on a reduced/surrogate/high-fidelity forward model |
| `uq` | yes | Saltelli/Sobol on the reduced model |
| `critique` | rules: yes / LLM: adds | physics sanity checks (balances, y⁺ vs wall treatment, GCI asymptotics, closure disagreement, members without reattachment, primary outside tolerance while another closure is inside); LLM may add warnings, never remove |
| `report` | yes | Markdown report, figures, `provenance.json`, `decisions.jsonl`, `result.json` |

### Why a workflow with a verifier, not a multi-agent chat

The choice is argued in `docs/agent_architecture_review.md` against the widely cited agent literature.
In short: multi-agent LLM systems fail predominantly through weak *verification and termination* (MAST),
fixed pipelines match autonomous agents at lower cost (Agentless), and sampling/debate only pays when a
verifier exists (Large Language Monkeys, More Agents). Simulation has cheap, deterministic verifiers —
residuals, balances, GCI, correlations — so the agentic patterns NuAgent adopts are exactly those that
exploit them: a generator–verifier split (`review`, `critique`), orchestrator–workers over independent
solver jobs (`model_form`, grid levels, sweeps), and repeated-trial reliability measurement (pass^k in the
evals). The graph itself is a state machine so that the qualification argument can be made at all.

### Guardrails

* **No free-text path to the solver.** Templates are rendered with `StrictUndefined` from validated
  numbers; the diagnostician's proposals are a Pydantic model (`Adjustments`) whose fields are a whitelist
  with hard bounds, and the backend clips them again (`ADJUSTABLE_NUMERICS`).
* **Budgets.** `max_attempts`, wall-clock, cell-count (`mesh.max_cells`).
* **Rules are authoritative in the critique.** An LLM review can add warnings but cannot turn a rule-based
  `reject` into an `accept`.
* **Fallback.** Every LLM call is wrapped: on any failure the rules decision is used and the fact is
  logged in the decision log.
* **Provenance.** Git commit, package and solver versions, spec hash, input digests, attempts, adjustments
  and the full decision log are written with every report.

### Continue, don't restart

A run that completes cleanly but misses the residual target is *continued*: the diagnostician's
numerics changes are re-rendered into the existing case, `startFrom latestTime` is set and
`Allrun --continue` skips meshing, so hours of HPC work are never discarded. Only a diverged run is
rebuilt from scratch. Cases are also idempotent — re-invoking the workflow on a directory whose case was
built from the identical specification reuses the results instead of re-running the solver.

### Physics-aware critique (model-form failure detection)

The critique node checks quantities a turbulence modeller would look at, not only residuals: for the
rib-roughened tube it computes the reversed-flow fraction of the inter-rib gap and the reattachment
location from the wall-adjacent velocity. A converged k-ω SST solution with a single recirculation
filling the gap (d-type cavity flow where p/e = 10 should give k-type reattachment at 4–5 e) is flagged
and a k-ε family closure is recommended — see `docs/case_catalogue.md` §D1 for the measured effect
(f from −55 % to −4 % of Webb's correlation).

### Convergence criterion (an example of "physics-aware" automation)

For an axisymmetric wedge the azimuthal velocity component is round-off noise, so its *normalised*
residual never falls below ~1e-5 and OpenFOAM's own `residualControl` never triggers. The monitor
therefore tracks the physically meaningful fields (`Ux, Uy, h, p_rgh, k, ω`) and ignores `Uz`; with
`runTimeModifiable`, it asks the solver to write and stop as soon as the criterion is met — 831 instead of
3000 iterations for the laminar benchmark, with identical QoIs.

## 5. Verification and validation

* **Solution verification.** Three grid levels formed by scaling the cell count in every direction (and
  the first-cell height) by the refinement ratio; representative size *h = √(A/N)*. Observed order *p*,
  Richardson-extrapolated value and *GCI* follow Celik et al. (2008); oscillatory/divergent convergence is
  flagged; when an exact solution exists, the fine-grid error is reported alongside.
* **Validation.** References are resolved from a registry: exact solutions (Nu = 48/11, f = 64/Re, Crank
  permeation series, Oriani effective diffusivity, Redhead peak temperature), correlations with stated
  uncertainty (Gnielinski ±10 %, Dittus–Boelter ±25 %, Petukhov ±5 %, Blasius ±5 %), or a CSV dataset.
  The report states the deviation, whether it is inside the reference band, and whether the GCI band
  overlaps the reference band.
* **Consistency checks** independent of the references: energy balance (outlet bulk temperature vs first
  principles), mass balance, friction factor from d*p*/d*x* vs from wall shear, y⁺ vs wall treatment.

## 6. Calibration and UQ

The forward-model interface is `model(params: dict) -> ndarray`, shared by reduced-order models
(`physics/reduced.py`), GP surrogates (`calibration/surrogate.py`, PCA + GP with hold-out error) and the
solvers. `BayesianCalibrator` (emcee) supports uniform/log-uniform priors and an inferred noise level.
The TDS example recovers the detrapping energy, pre-exponential and inventory of a trap from a
synthetic spectrum, showing the classic *E_p–p_0* compensation ridge. `uq/` propagates prior
uncertainty and computes first- and total-order Sobol indices (SALib).

The intended workflow for a real problem: calibrate cheaply with the reduced model, then refine with the
high-fidelity FESTIM/OpenFOAM model through a GP surrogate trained on a Latin-hypercube design
(embarrassingly parallel on SLURM).

## 7. Qualification of the agent

`nuagent eval` runs a task suite (`evals/tasks/*.yaml`) and scores: success, attempts used vs. expected,
validation pass, GCI monotonicity, expected critique warnings (e.g. task 07 must attribute the SST member's
low Nu to missing reattachment), and — for LLM policies — how well the planned spec reproduces the
essential physics of the reference spec. With `--repeats k` every task is run k times in fresh directories
and the τ-bench **pass^k** statistic (probability that all k trials succeed, unbiased estimator
C(c,k)/C(n,k)) is reported per task and averaged; a stochastic planner that is right 80 % of the time has
pass^5 ≈ 0.33, which is the number a qualification reviewer needs to see. The mock backend makes failure
modes reproducible (aggressive under-relaxation ⇒ divergence; tiny iteration budget ⇒ stall; closure-
dependent bias including a no-reattachment SST member for ribbed tubes). The same suite runs against
OpenFOAM in CI's container job. Current scoreboard (mock, rules policy, 2 repeats): 7/7 success, 7/7
validated, mean 1.43 attempts (two tasks are designed to need recovery), pass^1 = pass^2 = 1.0 — as expected
for a deterministic policy; the interesting numbers are the LLM policies' (publication plan RQ1).

## 8. Extending

* **New case type**: add a Pydantic model to the `CaseSpec` union, a template set under
  `backends/openfoam/templates/<name>/` (or a FESTIM builder), a QoI extractor, and reference entries in
  `agent/vv.py`. Nothing in the agent changes.
* **New solver**: implement the `SolverBackend` protocol (`build`, `parse_log`, `extract_qois`).
* **New executor**: implement `run(case, execution)`.
* **New policy**: implement `plan`, `diagnose`, `critique`.
