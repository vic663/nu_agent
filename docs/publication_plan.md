# Publication plan

**Working title:** *Qualifying LLM agents for simulation verification and validation: a benchmark and a
guard-railed workflow for nuclear thermal-hydraulics and tritium transport*

**Target:** arXiv preprint (≈ week 4), then *Nuclear Engineering and Design* or *Annals of Nuclear Energy*
(CFD/V&V audience); the tritium component alone fits *Fusion Engineering and Design*. A shorter version
fits the AI4Science / *Computer Physics Communications* software track. Conference option: ANS M&C /
NURETH (agentic workflows are a hot topic there).

## Research questions

1. **RQ1 — Reliability.** On tasks with known answers, how often does an LLM-driven workflow produce a
   converged, verified and validated result, and how does that compare with a deterministic rules
   baseline?
2. **RQ2 — Guardrails.** How many LLM proposals (plans, numerics changes) are rejected by typed
   validation, and what would have happened without the validators (counterfactual replay)?
3. **RQ3 — Model dependence.** Do hosted frontier models and open-weights models deployable on air-gapped
   clusters differ materially in plan quality, retries and cost?
4. **RQ4 — Reduced-order calibration.** Can trap parameters calibrated with a first-order desorption model
   initialise and accelerate high-fidelity FESTIM calibration (surrogate error vs posterior width)?
5. **RQ5 — Multiphysics.** Does the one-way coupled channel→permeation workflow reproduce the analytical
   limits and produce inventory estimates with quantified numerical uncertainty?

## Contributions (as the abstract would state them)

1. An open benchmark of simulation tasks with analytical/correlation references spanning finite-volume
   CFD (OpenFOAM) and finite-element hydrogen transport (FESTIM), with an automated scorer.
2. A guard-railed agent architecture (typed specs, template-only solver input, bounded diagnostics,
   compulsory GCI/validation, provenance) and evidence that it turns LLM variability into measured,
   bounded behaviour.
3. Evaluation across policies and models with success/retry/cost/invalid-proposal metrics.
4. Reduced-order → high-fidelity Bayesian calibration of tritium trap parameters with surrogate error
   accounting.
5. A coupled coolant-channel → tritium-permeation demonstration.
6. Model-form discovery in the loop: the rib-roughened tube where k-ω SST predicts a d-type cavity flow and the
   physics-aware critique detects it (see `docs/case_catalogue.md` §D1 and `docs/literature_review.md`).

## Experiment matrix

| Factor | Levels |
|---|---|
| Tasks | 12–15: A1–A6 benchmarks, 3 adversarial (inconsistent Re/model, out-of-range correlations, mis-specified units), 2 multiphysics |
| Backend | mock (all), OpenFOAM (A1, A2, A6), FESTIM (A3–A5) |
| Policy | rules; LLM (Claude Sonnet, GPT-4-class, Llama/Qwen 70B-class via vLLM) |
| Seeds | 5 (LLM temperature 0 still varies through tool/ordering effects) |
| Metrics | success rate; validated rate; mean attempts; invalid-proposal rate (planner and diagnostician); plan-grade vs reference spec; tokens and cost; wall-clock; GCI asymptotic rate |

Counterfactual replay for RQ2: log every raw LLM proposal, then re-run the workflow with validators
disabled in a sandbox to count runs that would have produced wrong-but-plausible results.

## Figures planned

1. Architecture / state machine with guardrails highlighted.
2. Laminar verification: Nu(x) and f vs exact; GCI convergence plot.
3. Turbulent validation across Re ∈ {1e4, 2e4, 5e4, 1e5} with Gnielinski band; SST vs k-ε; effect of Pr_t calibration.
4. Permeation verification and trap effective-diffusivity check.
5. TDS posterior (reduced vs FESTIM-surrogate) with E_p–p_0 compensation ridge.
6. Agent scoreboard: success/retries/cost by policy and model; invalid-proposal rates.
7. Coupled channel→permeation flux distribution with GCI bands.

## Threats to validity (to be discussed)

- Benchmarks are canonical; real geometries stress meshing far more than this suite does.
- Correlation uncertainty is itself approximate; validation "pass" is a consistency statement, not truth.
- LLM APIs change; results are pinned to model versions and dates; open-weights results are reproducible.
- The rules baseline was written by the authors — bias is mitigated by publishing it and the tasks.

## Related work to cite (verify exact references before submission)

- MetaOpenFOAM (Chen et al., 2024) and OpenFOAMGPT (Pandey et al., 2025): LLM agents that generate and run
  OpenFOAM cases from natural language — establishes feasibility, no compulsory V&V or qualification.
- Foam-Agent (Yue et al., 2025): multi-agent OpenFOAM automation with retrieval of tutorial cases.
- Agent evaluation frameworks in science (e.g., ScienceAgentBench, 2024) — benchmarking methodology.
- FESTIM (Delaporte-Mathurin et al., 2024) and its V&V book — the tritium verification cases used here.
- ASME V&V 20-2009 and Celik et al. (2008) — the verification procedure implemented in `verification/`.

**Positioning:** prior agentic-CFD work asks *whether* an LLM can drive a solver; this work asks *how to
qualify* such an agent: bounded degrees of freedom, compulsory GCI and validation with uncertainty bands,
a deterministic baseline, a benchmark with known answers, and calibration/UQ — across CFD and FEM codes.
