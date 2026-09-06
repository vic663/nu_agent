# Documentation index

- [tutorial.md](tutorial.md) — **start here**: install, first run, reading a report, writing a spec, OpenFOAM/FESTIM/LLM/cluster set-up, qualification, troubleshooting, demo script
- [design.md](design.md) — architecture, workflow graph, guardrails, V&V logic, qualification
- [case_catalogue.md](case_catalogue.md) — benchmark and application cases (fission, fusion, aerospace)
- [roadmap.md](roadmap.md) — three-week plan and longer-term items
- [literature_review.md](literature_review.md) — state of the art, gap analysis, scientific story and venues
- [aerospace_review.md](aerospace_review.md) — aerospace needs and standards (CFD Vision 2030, AIAA G-077, ASME V&V 20, NASA-STD-7009B, certification by analysis), turbine cooling, anti-ice, hydrogen aircraft; gap analysis and roadmap
- [agent_architecture_review.md](agent_architecture_review.md) — widely cited agentic patterns with verified arXiv IDs; why NuAgent is a verifier-gated workflow with orchestrator–workers rather than a multi-agent chat
- [publication_plan.md](publication_plan.md) — research questions and experiment matrix
- [examples/laminar_pipe/report.md](examples/laminar_pipe/report.md) — generated report, real OpenFOAM run
- [examples/turbulent_pipe/report.md](examples/turbulent_pipe/report.md) — generated report, real OpenFOAM run, including the four-closure ensemble (§6: model-form ±20 % on Nu vs GCI < 0.1 %)
- [examples/ribbed_tube/report.md](examples/ribbed_tube/report.md) — generated report, rib-roughened cooling tube (aerospace case)

### How to read the example reports

These three reports are checked in as *illustrations of the output format*. Two caveats that the
reports themselves state, and that are repeated here so they are not missed:

- **`turbulent_pipe` and `ribbed_tube` were re-rendered from cached case directories** — their
  decision logs read `existing results reused; solver not re-run` and their wall time is `0.0 s`.
  The QoIs come from the earlier OpenFOAM execution of the identical specification; the report
  around them was regenerated later. `laminar_pipe` is a live run (10.1 s, local executor).
- **The provenance blocks record `"openfoam": null` and `"dirty": true`.** The solver version is
  probed in the *agent's* environment, which for a containerised run is not the environment that
  executed the case, and the tree was not clean at generation time. Neither report is therefore a
  reproducible artefact in the ASME V&V 20 / NASA-STD-7009 sense; they show what NuAgent writes,
  not a qualification record. Closing that gap (recording the solver version from the run's own
  `allrun.out`, refusing to reuse a case built by different template code, and shipping the run
  directory alongside the report) is tracked in [roadmap.md](roadmap.md).
