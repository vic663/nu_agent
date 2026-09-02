# NuAgent

**An agentic workflow that sets up, runs, monitors, verifies, validates and calibrates
thermal-fluids simulations — OpenFOAM heat transfer for reactor coolant channels and turbine-blade
cooling passages, FESTIM tritium transport for fusion — and writes the V&V report.**

[![CI](https://github.com/<your-github-user>/nuagent/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-github-user>/nuagent/actions)
![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green)

NuAgent is built around one idea: **an AI agent that drives simulation codes must itself be qualifiable.**
So every decision the agent makes is bounded by typed schemas, every solver input is generated from
validated templates, every result is verified (grid-convergence index, exact solutions) and validated
(correlations, experiments) before it is reported — and the whole loop runs *without* an LLM in CI, so the
LLM's contribution can be measured rather than assumed.

```
 "Water at Re = 20 000 in a 20 mm pipe with 50 kW/m² wall heating — validate Nu and f."
        │
        ▼
 plan ─► build ─► run ─► monitor ─┬─► postprocess ─► verify (GCI) ─► validate ─► calibrate ─► UQ ─► critique ─► report
                    ▲             │
                    └── diagnose ◄┘   (bounded numerics changes, max N attempts)
```

## What it does today (v0.1)

| Capability | Status |
|---|---|
| Typed simulation specs (Pydantic) as the only interface between LLM and solvers | ✅ |
| OpenFOAM backend: axisymmetric heated pipe, laminar & RANS (k-ω SST, k-ε family), template-generated, y⁺-targeted meshing | ✅ tested on OpenFOAM v1912, targets v2312–v2512 |
| **Rib-roughened cooling tube** (turbine-blade turbulator / AGR cladding analogue): multi-block mesh, module-averaged Nu & f, Webb–Eckert–Goldstein validation, reattachment diagnostic | ✅ real runs; SST model-form failure detected automatically |
| Continue-from-latest-time for stalled runs, idempotent case reuse | ✅ |
| FESTIM 2.x backend: 1-D tritium permeation (with McNabb–Foster traps) and TDS | ✅ generated & post-processed; solver run in the FESTIM container |
| Mock backend with controlled discretisation error for CI and agent evals | ✅ |
| Live convergence monitor (stops OpenFOAM early once *physically meaningful* residuals converge) | ✅ |
| Diagnose-and-retry loop with whitelisted, bounded numerics changes | ✅ rules policy; LLM policy with rule fallback |
| Solution verification: 3-level grid study, Richardson extrapolation, GCI (Celik 2008 / ASME V&V 20) | ✅ |
| Validation against exact solutions and correlations with their own uncertainty bands | ✅ |
| Bayesian calibration (emcee) with reduced-order models and GP surrogates | ✅ |
| Sobol sensitivity analysis (SALib) | ✅ |
| Markdown report with plots, decision log and provenance (git hash, versions, digests) | ✅ |
| Executors: local, Docker, SLURM (sbatch/squeue/sacct, approval gate) | ✅ |
| Agent qualification suite (`nuagent eval`) | ✅ 6 tasks, 100 % success / 100 % validated on the mock backend |
| LLM planning from natural language (`nuagent ask`) — Anthropic, OpenAI, or any OpenAI-compatible local server | ✅ |

### Results so far (real OpenFOAM runs, single core)

| Case | Quantity | NuAgent | Reference | Deviation | Grid convergence |
|---|---|---|---|---|---|
| Laminar pipe, Re = 200 | Nu | 4.376 | 48/11 = 4.364 (exact) | **+0.3 %** | GCI 0.02 % |
| Laminar pipe, Re = 200 | f | 0.3203 | 64/Re = 0.3200 (exact) | **+0.1 %** | p = 1.92, GCI 0.15 % |
| Turbulent pipe, Re = 20 000, water, k-ω SST (y⁺≈1) | Nu | 124.6 | Gnielinski 137.8 (±10 %) / Dittus–Boelter 128.4 (±25 %) | −9.6 % / −3.0 % | GCI < 0.1 % |
| Turbulent pipe, Re = 20 000 | f | 0.02416 | Petukhov 0.02615 (±5 %) | −7.6 % | GCI 0.9 % |
| **Rib-roughened tube**, air, Re = 20 000, e/D = 0.04, p/e = 10, low-Re k-ε | Nu (nominal area) | 112.9 (Nu/Nu₀ = 2.18) | Webb et al. 1971: 141.9 (±15 %) | −20.4 % (−13 % with base-temperature definition) | p = 2.1, GCI 2.5 % |
| Rib-roughened tube | f | 0.2313 (f/f₀ = 8.85) | Webb et al. 1971: 0.2392 (±10 %) | **−3.3 %** | not asymptotic (p = 0.25; 2.4 % change between the two finest grids) |

Energy-balance closure 0.06–0.1 % (smooth pipes) and 3 % (ribbed tube), mass-balance closure 0.13 %, friction factor from
d*p*/d*x* and from wall shear agree within 2 %. Full reports with figures: [`docs/examples/`](docs/examples/).

The turbulent Nusselt number sits inside the correlations' stated uncertainty and shows the well-known
5–10 % under-prediction of wall-resolved SST with Pr_t = 0.85 — which is exactly the kind of model-form
uncertainty the calibration module is designed to quantify next (roadmap week 2).

**The ribbed tube is where the workflow earns its keep.** With the default k-ω SST closure the run
converges cleanly but predicts a single recirculation filling the whole inter-rib gap (d-type cavity flow),
giving f 55 % and Nu 65 % below Webb's correlation; the physics-aware critique flags "no reattachment
between ribs" and recommends the k-ε family, which reattaches at 4–5 e as experiments do and brings f
within 4 % — leaving the well-documented RANS heat-transfer deficit in separated regions (see
[`docs/case_catalogue.md`](docs/case_catalogue.md) §D1 for the five-model comparison). An
execution-success metric would have reported the SST run as a success.

## Quick start

```bash
git clone https://github.com/<your-github-user>/nuagent && cd nuagent
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

# 6. qualify the agent: success rate, retries, validation and GCI outcomes over the task suite
nuagent eval evals/tasks --backend mock --policy rules
```

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
  agent/               LangGraph graph, nodes, policies (rules / LLM), V&V comparison logic
  calibration/         emcee Bayesian calibration, LHS + GP surrogate
  uq/                  Saltelli sampling and Sobol indices
  reporting/           Markdown report, plots, provenance
  evals/               agent qualification harness
examples/              ready-to-run specs (heated pipe laminar/turbulent/SLURM, permeation, TDS calibration)
evals/tasks/           qualification tasks with expected outcomes
docs/                  design, case catalogue, roadmap, publication plan, example reports
docker/, .github/      containers and CI (unit + OpenFOAM + FESTIM jobs)
```

## Documentation

- [Design and architecture](docs/design.md) — state machine, guardrails, qualification strategy
- [Case catalogue](docs/case_catalogue.md) — benchmark and application cases (fission, fusion, aerospace)
- [Roadmap](docs/roadmap.md) — 3-week plan: coupled CFD→tritium permeation, MHD duct, ribbed channel, HPC
- [Literature review and scientific positioning](docs/literature_review.md) — where the field is, the gap, the story
- [Publication plan](docs/publication_plan.md) — research questions and experiment matrix
- [Example reports](docs/examples/) — generated by the workflow from real OpenFOAM runs

## Acknowledgements

Built on [OpenFOAM](https://www.openfoam.com) (ESI), [FESTIM](https://github.com/festim-dev/FESTIM)
(FEniCSx), [LangGraph](https://github.com/langchain-ai/langgraph), [emcee](https://emcee.readthedocs.io)
and [SALib](https://salib.readthedocs.io). Verification procedures follow Celik et al. (2008) and
ASME V&V 20-2009; correlations and their uncertainties follow Incropera & DeWitt.

## License

MIT — see [LICENSE](LICENSE).
