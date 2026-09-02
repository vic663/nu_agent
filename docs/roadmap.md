# Roadmap

Status legend: ✅ done · 🔄 in progress · ⏳ planned

## v0.1 — foundation (this release)

- ✅ Typed specification, correlations, analytical solutions, reduced-order models
- ✅ OpenFOAM heated-pipe backend (laminar + k-ω SST), y⁺-targeted meshing, raw-field post-processing
- ✅ FESTIM 2.x permeation/TDS runner and post-processing
- ✅ Mock backend with controlled error and controllable failures
- ✅ LangGraph workflow with live monitor, bounded diagnose-and-retry, human approval gate
- ✅ GCI verification, correlation/analytical validation with uncertainty bands
- ✅ Bayesian calibration (emcee, GP surrogate) and Sobol UQ
- ✅ Markdown report, provenance, decision log; CLI; eval harness; Docker; CI
- ✅ Rib-roughened cooling tube (aerospace / AGR-cladding physics) with model-form diagnostics; continue-from-latest-time and idempotent case reuse
- ✅ Pre-flight `review` node (independent deterministic verifier of the plan; LLM may add findings), `model_form` closure-ensemble node (orchestrator–workers; model-form vs numerical uncertainty), pass^k reliability in the evals (`--repeats`), 7-task suite
- ✅ Literature reviews: aerospace needs and standards (`docs/aerospace_review.md`), agentic-architecture evidence and the multi-agent verdict (`docs/agent_architecture_review.md`)

## Week 1 — harden and publish

| Item | Deliverable | Notes |
|---|---|---|
| ⏳ Push to GitHub, enable CI | green badges for unit + OpenFOAM (+ FESTIM) jobs | CI containers: `opencfd/openfoam-default:2512`, `dolfinx/dolfinx:stable` |
| ⏳ FESTIM end-to-end in the container | A3/A4 reports; fix API details surfaced by the real run | `docker compose run festim nuagent run examples/tritium_permeation/permeation_verification.yaml` |
| ⏳ LLM policy smoke test | `nuagent ask … --plan-only` with Claude and with a local model (Ollama/vLLM via `OPENAI_BASE_URL`) | record plan-grade scores in `evals/` |
| ⏳ Turbulent case refinement | L/D = 60, `cells_per_diameter` 15, wall-function variant; run the `model_form` ensemble (SST, k-ε, realizable k-ε, Launder–Sharma) on real OpenFOAM for both the smooth and the ribbed tube | expect Nu closer to Gnielinski; report model-form band vs GCI in the README table |
| ⏳ Real-OpenFOAM closure ensemble for the ribbed tube | `examples/aerospace/ribbed_cooling_tube.yaml` now carries `model_form`; run it (≈ 4 fine-grid runs) and replace the D1 hand-assembled table with the generated §6 of the report | parallel: 3 on a 4-core machine |
| ✅ Rib-roughened cooling tube (D1) | multi-block axisymmetric template, Webb (1971) validation, turbulence-model comparison, reattachment diagnostic | next: sweep e/D and Re; add PI's thermography data as a second reference; LES reference case |
| ⏳ MCP server | expose `build_case`, `run_case`, `extract_qois`, `validate` as MCP tools so any agent client (Claude Code, etc.) can drive the workflow | `nuagent mcp` (FastMCP) |

## Week 2 — multiphysics and calibration

| Item | Deliverable |
|---|---|
| ⏳ **C1 coupled coolant channel → tritium permeation** | OpenFOAM wall temperature → FESTIM `temperature=lambda x` + Sieverts BCs; report permeation flux distribution and inventory; verify limits against A2 + A3 |
| ⏳ **C2 Hartmann/Shercliff MHD duct** | `mhdFoam` template from the OpenFOAM tutorial; verification vs exact profile at Ha = 5, 20, 50 |
| ⏳ **B1 conjugate heat transfer tube** | `chtMultiRegionSimpleFoam` wedge with solid annulus; interface temperature vs 1-D conduction |
| ⏳ **C4 TDS calibration with FESTIM in the loop** | GP surrogate trained on 64 FESTIM runs (SLURM array), posterior compared with the reduced-model posterior; surrogate-error accounting |
| ⏳ Turbulent-Prandtl calibration | Bayesian calibration of Pr_t against Gnielinski over Re ∈ [1e4, 1e5] using a GP surrogate of the SST heated pipe |
| ⏳ SLURM validation on the university cluster | `examples/heated_pipe/turbulent_slurm.yaml` with the approval gate; parallel scaling note |

## Week 3 — evaluation, application, write-up

| Item | Deliverable |
|---|---|
| ⏳ **Agent qualification study** | eval suite (≥ 12 tasks incl. adversarial specs) × policies (rules, Claude, GPT, open-weights local) × `--repeats 5`; metrics: pass^1…pass^5, retries, invalid-proposal rate, verifier interventions (review/critique changed the outcome), cost, plan-grade |
| ⏳ **NASA TMR verification tasks** | 2-D flat plate (Cf), bump-in-channel, backward-facing step (reattachment length) as solver-agnostic eval tasks with reference solutions — the aerospace benchmark family (`docs/aerospace_review.md` §5) |
| ⏳ **D2 impinging jet / heated plate** | anti-ice (piccolo tube) relevance; validate stagnation Nu against Martin (1977) |
| ⏳ Plan sampling with the verifier as selector | sample N LLM plans, rank with `preflight` findings (fewest warnings, no blocking) — the "Large Language Monkeys" coverage argument with a deterministic verifier |
| ⏳ **B2 rod-bundle subchannel** (or D2 impinging jet) | one application case with experimental validation data |
| ⏳ **C3 divertor monoblock** | FESTIM coupled heat + hydrogen transport, 2-D |
| ⏳ Technical report / arXiv preprint | see `publication_plan.md` |
| ⏳ Docs site | mkdocs with the reports as pages |

## Later

- SU2 backend (aerospace-native open-source CFD) behind the same `SolverBackend` protocol; NASA TMR airfoil cases
- Credibility scorecard per NASA-STD-7009B factor emitted with each report
- Hydrogen-tank liner permeation with FESTIM (aircraft LH₂ storage): liner alloy/polymer presets, cryogenic wall temperature from CFD
- Specialist tool-agents behind typed interfaces (retrieval of validation references with citations; campaign/DoE planner) orchestrated by the deterministic graph — see `docs/agent_architecture_review.md` §4
- GPU: PETSc/dolfinx GPU backends for FESTIM; OpenFOAM `-parallel` with GPU linear solvers (PETSc4FOAM)
- VertexCFD / Nek5000 backends (ORNL codes) behind the same `SolverBackend` protocol
- Two-way coupling (temperature-dependent trapping feeding back to heat transfer) via preCICE
- Streaming ParaView/pyvista post-processing for 3-D cases
- Uncertainty-aware acceptance: validation decisions from the *joint* GCI + reference-band probability
