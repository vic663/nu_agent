# Roadmap

This file is forward-looking. Everything below is **planned** unless explicitly stated otherwise.
It is not evidence of implemented or qualified capability. Current evidence is summarized in the
README, case catalogue and generated example reports.

## Near-term hardening

- Replace the current three-grid asymptotic-range classification with an explicit convergence-quality assessment and regenerate affected reports.
- Complete convergence diagnostics for Bayesian calibration.
- Replace mean-imputation of failed Sobol samples with explicit failure handling and reporting.
- Exercise the LLM policy against the deterministic baseline with recorded evaluation results.
- Qualify the SLURM executor on a real cluster and document the execution/provenance path.
- Regenerate closure-ensemble reports directly through the workflow rather than hand-collated development runs.
- Add an MCP interface only after the underlying deterministic tools remain independently testable.

## Planned physics extensions — not implemented or qualified

- One-way OpenFOAM -> FESTIM coolant-temperature/permeation coupling.
- Hartmann/Shercliff MHD duct benchmark.
- Conjugate heat-transfer tube benchmark.
- FESTIM-in-the-loop TDS calibration against real spectra.
- Rod-bundle/subchannel CFD benchmark.
- Impinging-jet heat-transfer benchmark.
- Divertor-monoblock heat and hydrogen-isotope transport case.

## Later

- NASA TMR verification cases.
- SU2 and additional solver backends behind the same `SolverBackend` contract.
- Credibility scorecard aligned with documented V&V evidence.
- GPU-enabled FEM/linear-solver experiments.
- Two-way multiphysics coupling.
- Expanded campaign/DoE and uncertainty-aware acceptance studies.

Items move out of this file and into the evidence sections only after they are implemented, exercised
and assigned an explicit qualification status.
