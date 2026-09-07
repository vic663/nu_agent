# NuAgent

**An agentic workflow that sets up, runs, monitors, verifies, validates and calibrates
convective heat-transfer and transport simulations — turbine-blade cooling passages, heat-exchanger and
reactor coolant channels (OpenFOAM), tritium transport in fusion materials (FESTIM) — and writes the
V&V report.** The *Nu* is the Nusselt number, the quantity every case here is validated on (and ν, the
kinematic viscosity); the physics is the same in an aircraft engine and in a reactor core.

[![CI](https://github.com/vic663/nuagent/actions/workflows/ci.yml/badge.svg)](https://github.com/vic663/nuagent/actions)
![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green)

NuAgent is built around one idea: **an AI agent that drives simulation codes must itself be qualifiable.**
So every decision the agent makes is bounded by typed schemas, every solver input is generated from
validated templates, every result is verified (grid-convergence index, exact solutions) and validated
(correlations, experiments) before it is reported — and the whole loop runs *without* an LLM in CI, so the
LLM's contribution can be measured rather than assumed.

```
 "Air at Re = 20 000 through a ribbed cooling tube (e/D = 0.04, p/e = 10) — validate Nu and f against Webb."
        │
        ▼
 plan ─► review ─► build ─► run ─► monitor ─┬─► postprocess ─► verify (GCI) ─► model_form ─► validate ─► calibrate ─► UQ ─► critique ─► report
          (pre-flight       ▲               │                                  (closure ensemble:
           verifier)        └── diagnose ◄──┘  (bounded numerics changes)       model-form vs numerical uncertainty)
```

The architecture follows what the agent literature actually supports (see
[`docs/agent_architecture_review.md`](docs/agent_architecture_review.md)): a deterministic **workflow**
backbone with typed contracts, an independent **verifier** that reviews every plan before compute is spent,
and **orchestrator–workers** fan-out where sub-tasks are independent solver runs — not a conversation
between role-playing agents.

## What it does today (v0.1.4)

| Capability | Status |
|---|---|
| Typed simulation specs (Pydantic) as the only interface between LLM and solvers | ✅ |
| OpenFOAM backend: axisymmetric heated pipe, laminar & RANS (k-ω SST, k-ε family), template-generated, y⁺-targeted meshing | ✅ tested on OpenFOAM v1912, targets v2312–v2512 |
| **Rib-roughened cooling tube** (turbine-blade turbulator / AGR cladding analogue): multi-block mesh, module-averaged Nu & f, Webb–Eckert–Goldstein validation, reattachment diagnostic | ✅ real runs; SST model-form failure detected automatically |
| Continue-from-latest-time for stalled runs, idempotent case reuse | ✅ reuse identity includes the template code and the NuAgent version, and refuses a case whose previous run did not converge |
| **Pre-flight review** node: correlation validity at the operating point, y⁺ vs wall treatment, entry length, closure lessons, FESTIM time scales — blocking findings stop the run before build | ✅ rules; LLM may add findings, never remove |
| **Closure ensemble** (`model_form`): re-runs the base grid with alternative RANS closures (optionally in parallel) and reports model-form uncertainty next to the GCI, with per-closure reattachment diagnostics | ✅ |
| FESTIM 2.x backend: 1-D tritium permeation (with McNabb–Foster traps) and TDS | ✅ generated & post-processed; solver run in the FESTIM container |
| Mock backend with controlled discretisation error for CI and agent evals | ✅ |
| Live convergence monitor (stops OpenFOAM early once *physically meaningful* residuals converge) | ✅ the residual criterion is the live stop signal; the *verdict* additionally requires a clean termination and a zero exit status |
| Diagnose-and-retry loop with whitelisted, bounded numerics changes | ✅ rules policy; LLM policy with rule fallback |
| Solution verification: 3-level grid study, Richardson extrapolation, GCI (Celik 2008 / ASME V&V 20) | ✅ the y⁺ target is anchored to the *coarsest* level so every level stays in one near-wall regime, and the report states whether the realised family is a systematic refinement |
| Validation against exact solutions and correlations with their own uncertainty bands | ✅ |
| Bayesian calibration (emcee) with reduced-order models and GP surrogates | ⚠ implemented; **convergence diagnostics pending** — `get_autocorr_time(tol=0)` disables emcee's own guard, there is no thinning or ESS, and the shipped TDS example is not converged |
| Sobol sensitivity analysis (SALib) | ⚠ implemented; **failed-sample handling pending** — failed model evaluations are imputed with the sample mean and not reported, which biases the indices |
| Markdown report with plots, decision log and provenance (git hash, versions, digests) | ✅ |
| Executors: local, Docker, SLURM (sbatch/squeue/sacct, approval gate) | ✅ the gate discloses the whole job budget (solve attempts + grid levels + ensemble members) and covers every child submission, not only the first |
| Agent qualification suite (`nuagent eval`, `--repeats` for τ-bench **pass^k** reliability) | ✅ 10 tasks — 7 that must succeed and **3 negative controls that must be refused**; the agent behaves correctly on 10/10 (rules policy, mock backend). See the note below for what this does and does not measure |
| LLM planning from natural language (`nuagent ask`) — Anthropic, OpenAI, or any OpenAI-compatible local server | ✅ |

> **⚠ vs ✅ in the table above.** A ⚠ means the capability is implemented and exercised, but its
> *qualification* is incomplete — implementation existing is not the same as the result being
> trustworthy, and this repository's whole argument is that the difference matters. The open
> items behind each ⚠ are listed in [CHANGELOG.md](CHANGELOG.md) under *Known limitations*.

> **What the eval suite does and does not measure.** The mock backend generates each QoI from the
> same correlation the validation node then compares it against, plus a deterministic `C·h²` term
> and a per-closure bias factor. On the seven positive tasks its observed order is therefore 2.000
> by construction and its validation deviation is a fixed fraction: those tasks exercise the graph,
> the retry logic, the GCI arithmetic and the report, and they *cannot* fail on physics. A success
> rate measured only on tasks that are supposed to succeed is not evidence that the agent would
> catch a wrong answer, so the suite also carries **three negative controls that must be refused**:
>
> | Negative control | Defect | Required behaviour |
> |---|---|---|
> | `08_negative_control_no_traps` | TDS spectrum with no traps defined | pre-flight **blocks** before meshing |
> | `09_negative_control_entry_length` | Re = 800 water validated against fully developed 48/11 in a 40 D pipe (entry length ~233 D) | pre-flight **blocks**: the target is unreachable in this geometry |
> | `10_negative_control_wrong_closure` | k-ω SST on a p/e = 10 ribbed passage — converges cleanly, Nu and f ~50 % below Webb | run completes, **validation FAILS**, critique verdict `reject` |
>
> The third is the important one: nothing about its *execution* fails, so an execution-success
> metric records it as a success. Control 09 is not hypothetical — it was task 04 of this suite
> until 2026-09-06, and it scored `+0.50 % PASS` against a value the flow could not physically
> reach. It is kept as a permanent regression test against that class of error. The physics
> evidence in this repository remains the OpenFOAM table below, not the eval scoreboard.

### Results so far (real OpenFOAM runs, single core)

| Case | Quantity | NuAgent | Reference | Deviation | Grid convergence |
|---|---|---|---|---|---|
| Laminar pipe, Re = 200 | Nu | 4.376 | 48/11 = 4.364 (exact) | **+0.3 %** | GCI 0.02 % |
| Laminar pipe, Re = 200 | f | 0.3203 | 64/Re = 0.3200 (exact) | **+0.1 %** | p = 1.92, GCI 0.15 % |
| Turbulent pipe, Re = 20 000, water, k-ω SST (y⁺≈1) | Nu | 124.6 | Gnielinski 137.8 (±10 %) / Dittus–Boelter 128.4 (±25 %) | −9.6 % / −3.0 % | GCI < 0.1 % |
| Turbulent pipe, Re = 20 000 | f | 0.02416 | Petukhov 0.02615 (±5 %) | −7.6 % | GCI 0.9 % |
| **Rib-roughened tube**, air, Re = 20 000, e/D = 0.04, p/e = 10, low-Re k-ε | Nu (nominal area) | 112.9 (Nu/Nu₀ = 2.18) | Webb et al. 1971: 141.9 (±15 %) | −20.4 % (−13 % with base-temperature definition) | p = 2.1, GCI 2.5 % |
| Rib-roughened tube | f | 0.2313 (f/f₀ = 8.85) | Webb et al. 1971: 0.2392 (±10 %) | **−3.3 %** | not asymptotic (p = 0.25; 2.4 % change between the two finest grids) |
| **Turbulent pipe, closure ensemble** (SST y⁺≈1 · k-ε and realizable k-ε with Jayatilleke wall functions y⁺≈38 · Launder–Sharma y⁺≈1) | Nu | 124.6 / 132.3 / 130.0 / 174.2 | Gnielinski 137.8 (±10 %) | −9.6 / −4.0 / −5.7 / +26.4 % | **model-form ±19.9 % vs GCI < 0.1 %** |
| Turbulent pipe, closure ensemble | f | 0.02416 / 0.02467 / 0.02366 / 0.03037 | Petukhov 0.02615 (±5 %) | −7.6 / −5.7 / −9.5 / +16.1 % | **model-form ±13.9 % vs GCI 0.9 %** |

Energy-balance closure 0.06–0.1 % (smooth pipes) and 3 % (ribbed tube), mass-balance closure 0.13 %, friction factor from
d*p*/d*x* and from wall shear agree within 2 %. Full reports with figures: [`docs/examples/`](docs/examples/).

The turbulent Nusselt number sits inside the correlations' stated uncertainty and shows the well-known
5–10 % under-prediction of wall-resolved SST with Pr_t = 0.85. The closure ensemble puts a number on the
model-form uncertainty that a single run hides: three closures agree with Gnielinski within its band, the
Launder–Sharma low-Re k-ε model over-predicts both Nu and f by 16–26 % — while for the *ribbed* tube the
same model is the one that reproduces the flow topology and k-ω SST is the outlier. Closure trust is
case-dependent, which is why the workflow measures it instead of choosing a favourite. (The ensemble also
exposed a set-up defect worth recording: with the plain `alphatWallFunction`, wall-function members gave
Nu ≈ 285 — 2.2× the correlation — because that function ignores the molecular Prandtl number; the
Jayatilleke thermal law of the wall is now used for wall-function cases and brings them to within 4 % of
Gnielinski. The first-order wall-shear estimate likewise now includes ν_t at the wall, so f from d*p*/d*x*
and from τ_w agree within 2 % for every member.)

**The ribbed tube is where the workflow earns its keep.** With the default k-ω SST closure the run
converges cleanly but predicts a single recirculation filling the whole inter-rib gap (d-type cavity flow),
giving f 55 % and Nu 65 % below Webb's correlation; the physics-aware critique flags "no reattachment
between ribs" and recommends the k-ε family, which reattaches at 4–5 e as experiments do and brings f
within 4 % — leaving the well-documented RANS heat-transfer deficit in separated regions (see
[`docs/case_catalogue.md`](docs/case_catalogue.md) §D1 for the five-model comparison). An
execution-success metric would have reported the SST run as a success.

## Quick start

(Step-by-step version with Windows/WSL2/Docker instructions: [`docs/tutorial.md`](docs/tutorial.md).)

```bash
git clone https://github.com/vic663/nuagent && cd nuagent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # add ,anthropic or ,openai for LLM planning

nuagent doctor                      # what solvers / executors / LLM keys are available?
pytest -q                           # unit tests: no solver needed (OpenFOAM/FESTIM tests auto-skip)

# 1. deterministic V&V workflow on the mock solver (≈5 s, no OpenFOAM needed) — see runs/…/report.md
nuagent run examples/heated_pipe/laminar_verification.yaml --backend mock

# 2. the same workflow on real OpenFOAM (≈30 s incl. the 3-level grid study)
nuagent run examples/heated_pipe/laminar_verification.yaml          # needs OpenFOAM on PATH …
docker compose -f docker/compose.yaml run openfoam \
    nuagent run examples/heated_pipe/laminar_verification.yaml     # … or use the container

# 3. tritium permeation with FESTIM (dolfinx) in its container
docker compose -f docker/compose.yaml run festim \
    nuagent run examples/tritium_permeation/permeation_verification.yaml

# 4. Bayesian calibration + Sobol UQ of TDS trap parameters (reduced-order model, no solver)
nuagent run examples/tds_calibration/tds_reduced_calibration.yaml

# 5. natural-language planning with an LLM (the plan is validated, then the deterministic pipeline runs)
export ANTHROPIC_API_KEY=…   # or OPENAI_API_KEY / OPENAI_BASE_URL for a local vLLM/Ollama server
nuagent ask "Turbulent water flow in a 20 mm pipe at Re=20000 with 50 kW/m2 heating; validate Nu and f" --plan-only

# 6. qualify the agent: success rate, retries, validation and GCI outcomes over the task suite;
#    --repeats N adds the pass^k reliability statistic (probability that all N trials succeed)
nuagent eval evals/tasks --backend mock --policy rules --repeats 3
```

## LLM options and cost

Everything shown above — every run, report, grid study, calibration and the qualification suite — was
produced with the **rules policy, i.e. with zero LLM tokens**. The language model is optional and enters in
exactly **four bounded judgement points**, each a single structured-output call: `plan` (a specification
from natural language, `nuagent ask`), `review` (adding — never removing — pre-flight findings),
`diagnose` (proposing whitelisted numerics changes after a failed run) and `critique` (remarks on the
finished result). Each call is roughly 5–15k tokens, so a full LLM-assisted run costs cents with a hosted
model and nothing with a local one. No LLM output reaches a solver, a shell or a file path except through
a validated `SimulationSpec` or the bounded `Adjustments` schema.

| Option | Setting | Notes |
|---|---|---|
| No LLM (default) | `--policy rules` | deterministic, reproducible; what CI and the evals use |
| Hosted, Anthropic | `pip install -e ".[anthropic]"`, `ANTHROPIC_API_KEY`, `NUAGENT_LLM_MODEL=anthropic:claude-sonnet-4-5` | structured output via tool calling |
| Hosted, OpenAI | `pip install -e ".[openai]"`, `OPENAI_API_KEY`, `NUAGENT_LLM_MODEL=openai:gpt-4o` | |
| **Local, Ollama** (free, on-premise) | `pip install -e ".[openai]"`, `ollama pull qwen2.5:14b`, `OPENAI_BASE_URL=http://localhost:11434/v1`, `NUAGENT_LLM_MODEL=openai:qwen2.5:14b` | any model that supports tool calling (Llama 3.1/3.2, Qwen 2.5, Mistral); 7–14B quantised models run on a laptop with 16 GB RAM or an 8 GB GPU |
| Local, vLLM (cluster) | same as above with the vLLM server's `OPENAI_BASE_URL` | 70B-class open-weights models for the model-comparison study |
| Local via `langchain-ollama` | `pip install -e ".[ollama]"`, `NUAGENT_LLM_MODEL=ollama:qwen2.5:14b` | alternative to the OpenAI-compatible route |

Because the deterministic path is complete, the interesting scientific question — *what does the LLM add,
and does an open-weights model on an air-gapped machine add as much as a frontier model?* — can be
answered with `nuagent eval … --policy llm` at negligible cost.

## Why this design

**LLM in the loop, never in the syntax.** The planner produces a `SimulationSpec`; templates turn it into
OpenFOAM dictionaries or a FESTIM script. Hallucinated boundary conditions cannot reach the solver because
there is no free-text path to it. The diagnostician can only change whitelisted numerics
(under-relaxation, convection scheme, iteration/time-step budget) within hard bounds, and every proposal is
re-validated — the same way a code-qualification reviewer would insist on for a human analyst.

**Deterministic baseline.** `RulesPolicy` implements planning-from-spec, a diagnosis table and a
physics-sanity critique with no model calls. `LLMPolicy` layers a model on top and falls back to the rules
if the model is unavailable. Because the workflow is identical, `nuagent eval` can compare policies and
models (hosted vs. open-weights on an air-gapped cluster) on the same tasks — the evidence a lab needs
before trusting an agent with allocation hours.

**V&V is not optional.** Every run performs a grid-refinement study (coarser levels are cheap) and
reports observed order, Richardson-extrapolated value and GCI; every QoI is compared against an exact
solution or a correlation *with the correlation's own uncertainty band*, and the report states whether
the numerical-uncertainty band overlaps the reference band.

**Model-form uncertainty is measured, not assumed.** For separated internal flows the RANS closure is the
dominant uncertainty (NASA CFD Vision 2030's central complaint). A `model_form` block in the spec re-runs
the converged base grid with alternative closures; the report shows the spread as a model-form band next to
the GCI and says which one dominates. In the ribbed tube it is model form by an order of magnitude.

**Verify the plan before you pay for it.** The `review` node is a generator–verifier split: whoever wrote
the specification (human, rules, LLM), an independent deterministic reviewer checks correlation validity
at the operating point, wall resolution, development length and known closure pitfalls, and blocks
impossible cases (a TDS spectrum with no traps) before a single cell is meshed.

**Solver isolation.** Cases are self-contained directories with an `Allrun`; the agent never imports
OpenFOAM or dolfinx. The same case runs on a laptop, in `opencfd/openfoam-default` /
`dolfinx/dolfinx` containers, or under SLURM with a human approval gate — and can be re-run by hand.

## Repository layout

```
src/nuagent/
  spec.py              typed simulation specification (the LLM↔solver contract)
  physics/             correlations (Gnielinski, Petukhov, Dittus–Boelter…), analytical solutions
                       (Crank permeation, Oriani, Redhead, Hartmann), reduced-order models
  verification/        Richardson extrapolation and GCI
  backends/openfoam    Jinja2 templates, y⁺-targeted meshing, log parser, raw-field post-processing
  backends/festim      FESTIM 2.x runner (params.json → results.csv) and post-processing
  backends/mock        analytical "solver" with controllable failures for CI and evals
  executors/           local (with live monitor), Docker, SLURM
  agent/               LangGraph graph, nodes, policies (rules / LLM), pre-flight review, closure ensemble, V&V logic
  calibration/         emcee Bayesian calibration, LHS + GP surrogate
  uq/                  Saltelli sampling and Sobol indices
  reporting/           Markdown report, plots, provenance
  evals/               agent qualification harness
examples/              ready-to-run specs (ribbed cooling tube with closure ensemble, heated pipe laminar/turbulent/SLURM,
                       permeation, TDS calibration)
evals/tasks/           qualification tasks with expected outcomes
docs/                  design, case catalogue, roadmap, publication plan, example reports
website/               project website (React + Vite + Tailwind), published to GitHub Pages by .github/workflows/pages.yml
docker/, .github/      containers and CI (unit + OpenFOAM + FESTIM jobs)
```

## Documentation

- [Project website](https://vic663.github.io/nuagent/) — overview, capabilities, results and quick start (source in [`website/`](website/))
- [Hands-on guide](docs/tutorial.md) — install, first run, how to read a report, writing your own spec, OpenFOAM / FESTIM / LLM / SLURM set-up, qualification, troubleshooting
- [Design and architecture](docs/design.md) — state machine, guardrails, qualification strategy
- [Case catalogue](docs/case_catalogue.md) — benchmark and application cases (fission, fusion, aerospace)
- [Roadmap](docs/roadmap.md) — 3-week plan: coupled CFD→tritium permeation, MHD duct, ribbed channel, HPC
- [Literature review and scientific positioning](docs/literature_review.md) — where the field is, the gap, the story
- [Aerospace needs review](docs/aerospace_review.md) — CFD Vision 2030, AIAA G-077 / ASME V&V 20 / NASA-STD-7009 / certification by analysis, turbine cooling, anti-ice, hydrogen aircraft — and the gap NuAgent fills
- [Agent architecture review](docs/agent_architecture_review.md) — the widely cited agentic patterns (ReAct, Reflexion, AutoGen, MetaGPT, SWE-agent, Agentless, MAST, τ-bench…), why NuAgent is a workflow with a verifier and orchestrator–workers rather than a multi-agent chat
- [Publication plan](docs/publication_plan.md) — research questions and experiment matrix
- [Example reports](docs/examples/) — generated by the workflow from real OpenFOAM runs

## Acknowledgements

Built on [OpenFOAM](https://www.openfoam.com) (ESI), [FESTIM](https://github.com/festim-dev/FESTIM)
(FEniCSx), [LangGraph](https://github.com/langchain-ai/langgraph), [emcee](https://emcee.readthedocs.io)
and [SALib](https://salib.readthedocs.io). Verification procedures follow Celik et al. (2008) and
ASME V&V 20-2009; correlations and their uncertainties follow Incropera & DeWitt.

## License

MIT — see [LICENSE](LICENSE).
