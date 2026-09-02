# What aerospace thermal-fluids engineering needs from automated simulation V&V — and how NuAgent answers

*Literature review prepared for the NuAgent project (September 2026). Citations marked "(verify)" could not
be checked against a primary source at the time of writing and must be confirmed before publication;
all others were checked against the publisher, agency or NTRS record.*

---

## 1. The problem aerospace has already named

The single most influential planning document in aerospace CFD, NASA's **CFD Vision 2030 Study**
(Slotnick et al., NASA/CR-2014-218178, 2014), does not describe a shortage of solvers. It describes a
shortage of *trust and throughput*. Its diagnosis has four parts that read like a requirements list for an
automated V&V assistant:

* **Turbulence is the dominant physics gap.** "The use of CFD in the aerospace design process is severely
  limited by the inability to accurately and reliably predict turbulent flows with significant regions of
  separation" (p. 1). Smooth-body separation "remains very hard to simulate" (p. 12).
* **Error estimation and adaptivity are not routine.** Adaptive refinement "offer[s] the potential for
  superior accuracy at reduced cost, but [has] not seen widespread use due to robustness, error estimation,
  and software complexity issues" (p. 8); V&V "techniques are not widely used in the aerospace industry"
  (p. 8).
* **Mesh generation is the workflow bottleneck** ("a principal bottleneck in the simulation workflow
  process", p. 15).
* **Automation is the remedy the study asks for**: "a much higher degree of automation in all steps of the
  analysis process", with "less emphasis on the mechanics of running and collecting the information, and
  more emphasis on interpreting and understanding the results" (pp. 5–6).

The 2021 progress review (Cary et al., *CFD Vision 2030 Road Map: Progress and Perspectives*,
AIAA 2021-2726) re-baselined the milestones and folded in emerging technologies; the AIAA CFD 2030
Integration Committee continues to track them. The community's own workshops quantify how far trust
still has to go. In the Sixth Drag Prediction Workshop (Tinoco et al., AIAA SciTech 2017, NTRS 20170001397)
grid-convergence scatter across codes had narrowed from about 150 drag counts in DPW-I to about 40, with
extrapolated results converging to a 5–10 count band — but scatter widened again at the high-lift, buffet-
onset conditions where separation matters. The 4th High Lift Prediction Workshop (Rumsey, Slotnick &
Woeber, NTRS 20220005271, 2022; 44 participants, 184 datasets) reported fixed-grid RANS scatter in
maximum lift "near 0.68", against roughly 0.15 for adapted-mesh RANS and scale-resolving methods.

Two conclusions follow for anyone building an agent for this field. First, the value is not in generating
a case that runs; it is in producing a result whose numerical and model-form uncertainties are quantified
and whose validation status is explicit. Second, RANS closure choice is not a detail to be left to a
language model's prior — it is *the* dominant uncertainty for separated flows, and the workflow must treat
it as an uncertainty to be measured (a closure ensemble), not a parameter to be picked.

---

## 2. The standards landscape and what it asks of an automated workflow

| Standard / guide | What it requires | NuAgent artefact that answers it |
|---|---|---|
| **AIAA G-077-1998(2002)**, *Guide for the Verification and Validation of CFD Simulations* | Defines *verification* ("the process of determining that a model implementation accurately represents the developer's conceptual description of the model and the solution to the model") and *validation* ("the degree to which a model is an accurate representation of the real world from the perspective of the intended uses") — and insists they are separate activities | Separate `verify` (GCI, exact-solution error) and `validate` (reference with uncertainty band) nodes; the report never conflates them |
| **ASME V&V 20-2009 (R2021)**, *Standard for Verification and Validation in Computational Fluid Dynamics and Heat Transfer* | Numerical uncertainty from grid studies (GCI / Richardson extrapolation), input uncertainty, and a validation comparison error with its own uncertainty | `verification/gci.py` (Celik et al. 2008 procedure), `compare()` reports deviation, tolerance, reference band and whether the GCI band overlaps it |
| **NASA-STD-7009B** (2024), *Standard for Models and Simulations* | Credibility assessed by factors — development phase: data pedigree, verification, validation, technical review, process management; use phase: use assessment, input pedigree, uncertainty characterisation, results robustness, technical review, process management | Provenance record (solver/package versions, spec hash, input digests), decision log, `preflight.json` (technical review before use), GCI + model-form uncertainty, closure ensemble (results robustness) |
| **NASA/CR-20210015404** (Mauery et al., 2021), *A Guide for Aircraft Certification by Analysis* | Industry consensus that "current certification flight tests could be reduced by approximately 50 % by utilizing CbA"; four elements: numerical simulation capability, uncertainty quantification, rigorous validation against full-scale data, and a documented, configuration-managed analysis process; cites FAA AC 20-146A and draft EASA CM-25 as precedents | A configuration-managed process is exactly what a typed spec + template-only solver input + append-only decision log provides; UQ and validation are compulsory nodes; *full-scale validation data* remains the human's contribution |
| **FAA AC 20-73A** (2006), *Aircraft Ice Protection* | "The certification applicant should perform analyses to show compliance"; analyses must be verified by flight and ground tests; ice-accretion codes are acceptable analysis methods, trajectory analyses alone are not acceptable for shed-ice | An agent that documents which quantities were verified, against what, with what uncertainty is the analysis half of this analysis-plus-test loop |
| AIAA R-154-2021 (verify), recommended practice for using flight modelling to reduce flight testing | Credibility evidence for models used in lieu of tests | Same as above |
| **NASA Turbulence Modeling Resource** (Rumsey et al.; turbmodels.larc.nasa.gov → tmbwg.github.io) | Canonical *verification* cases for RANS closures (2-D zero-pressure-gradient flat plate, bump-in-channel, NACA 0012, axisymmetric subsonic jet, backward-facing step, wall-mounted hump…) with reference solutions from established codes | The natural next benchmark family for NuAgent's evals (§5): solver-agnostic tasks with known answers |

The pattern in the right-hand column is deliberate: every standard asks for the same three things — a
documented, reproducible process; separated verification and validation with quantified uncertainty; and
independent technical review — and each of them is a *workflow* property, not a solver property. That is
the case for an agentic layer whose contribution is process discipline rather than physics.

---

## 3. Application areas, their needs, and NuAgent's cases

### 3.1 Turbine internal cooling: rib turbulators

Internal cooling passages of gas-turbine blades and vanes are lined with transverse or angled ribs
("turbulators") that trip the boundary layer and roughly double the heat-transfer coefficient at a
friction penalty (Han, Dutta & Ekkad, *Gas Turbine Heat Transfer and Cooling Technology*, 2nd ed., CRC
2012; Han & Park, *Int. J. Heat Mass Transfer* 31, 1988). The design correlations descend from the
roughness-function approach of Webb, Eckert & Goldstein (*Int. J. Heat Mass Transfer* 14, 601–617, 1971):
friction from a momentum roughness function R(e⁺) and heat transfer from a heat-transfer roughness
function G(e⁺), both tabulated from repeated-rib tube experiments over 0.01 ≤ e/D ≤ 0.04 and
10 ≤ p/e ≤ 40 — exactly the correlations NuAgent's `webb` reference implements, with their validity
range enforced by the pre-flight review.

Local measurements (Rau, Çakan, Moeller & Arts, *J. Turbomachinery* 120, 368–375, 1998) show the
mechanism the correlations average over: for p/e around 9–10 the separated shear layer behind each rib
reattaches on the floor between ribs (k-type roughness), producing the high-heat-transfer reattachment
zone; for tightly spaced ribs the cavity fills with a single recirculation (d-type) and the enhancement
collapses. Reviews of RANS for these passages (Iacovides & Raisee, *Int. J. Heat Fluid Flow* 20, 320–328,
1999; Ooi, Iaccarino, Durbin & Behnia, *Int. J. Heat Fluid Flow* 23, 750–757, 2002) report that closure
choice changes predicted Nusselt numbers substantially, that wall-function k-ε is inadequate near the
ribs, and that low-Reynolds-number and v²–f type models do better — i.e. the model-form problem of §1 in
miniature. Data-driven turbulence modelling (Duraisamy, Iaccarino & Xiao, *Annu. Rev. Fluid Mech.* 51,
357–377, 2019) is the community's long-term answer; in the meantime the honest short-term answer is to
*measure* the model-form spread.

**What NuAgent does.** The rib-roughened tube (`examples/aerospace/ribbed_cooling_tube.yaml`) is the
flagship case: an axisymmetric tube with twelve square ribs (e/D = 0.04, p/e = 10) at Re = 20 000, module-
averaged Nu and f over the periodic fully developed pitches, validated against Webb with explicit
tolerances, a three-level grid study (GCI 2.5 % on Nu with the fine grid), and now a **closure ensemble**
(`model_form`) that re-runs the base grid with k-ω SST, standard k-ε and realizable k-ε. The finding that
motivated the ensemble came from the agent's own diagnostics: k-ω SST converged cleanly yet predicted a
single recirculation filling the whole inter-rib gap — d-type behaviour at k-type spacing — with f and Nu
50–65 % below Webb, while the Launder–Sharma model reattached at 4–5 rib heights and landed within the
correlation band (f −3 %, Nu −20 %). The physics critique detects this from the reversed-flow fraction of
the gap, the pre-flight review warns when SST is chosen for such ribs, and the report now states the
model-form uncertainty (half-range across closures) next to the numerical GCI so that a reader sees which
one dominates. Running the same ensemble on the *smooth* turbulent pipe (real OpenFOAM runs,
`docs/examples/turbulent_pipe/report.md` §6) gives the opposite ranking — k-ω SST and the two k-ε models
with Jayatilleke wall functions agree with Gnielinski within its band while Launder–Sharma over-predicts
Nu by 26 % — which is the point: closure trust is case-dependent and has to be measured per case
(model-form ±20 % on Nu against a GCI below 0.1 %).

### 3.2 Ice protection systems (the applicant's industry background)

Wing and engine anti-ice systems are certified against the 14 CFR Part 25 Appendix C icing envelopes
(continuous-maximum, intermittent-maximum and take-off conditions) through analysis verified by test
(FAA AC 20-73A). The analyses combine droplet-impingement and ice-accretion codes (NASA LEWICE,
Ruff & Berkowitz 1990 and successors) with conjugate heat-transfer CFD of the hot-air (piccolo-tube) or
electrothermal system: impinging-jet heat transfer inside the leading edge, external convective heat
transfer with roughness, and the runback-water energy balance. The recurring V&V questions are the ones
NuAgent already automates in the pipe cases — is the wall heat flux consistent with the enthalpy rise
(energy balance), is the near-wall resolution consistent with the wall treatment (y⁺), does the mesh study
show asymptotic convergence, and does the convective coefficient agree with an established correlation
within its band? The natural next aerospace case is therefore an **impinging-jet / heated-plate** module
validated against the Martin (1977) and Goldstein-type correlations, followed by a rough-wall heat-transfer
case (the Webb roughness functions are the same machinery).

### 3.3 Hydrogen aircraft and hydrogen in materials

Airbus announced its ZEROe hydrogen concepts in September 2020 with a 2035 entry-into-service ambition; its
March 2025 update restated the commitment while presenting a revised roadmap centred on technology
maturation (integrated ground tests in Munich from 2027) without restating the 2035 date. The UK ATI
FlyZero programme (reports published March 2022) mapped the liquid-hydrogen storage and fuel-system
technologies. Whatever the timeline, hydrogen introduces two materials problems aerospace has little
operational history with: **permeation** through tank liners, seals and pipe walls, and **embrittlement**
of structural alloys (e.g. recent work on environmental hydrogen embrittlement in TiAl aerospace alloys,
Li et al., *Results in Engineering* 29, 2026). These are precisely the phenomena the fusion community
models with hydrogen-transport codes: diffusion with trapping, surface recombination, temperature-
dependent Arrhenius kinetics.

**What NuAgent does.** The FESTIM backend (Delaporte-Mathurin et al., *Int. J. Hydrogen Energy* 63,
786–802, 2024; FESTIM V&V book) runs the permeation-transient and thermal-desorption cases; verification
against the Crank series and the Oriani effective diffusivity, time-lag checks in the pre-flight review, and
Bayesian calibration of trap parameters from a desorption spectrum. Swapping tungsten or Eurofer for an
aluminium liner or a polymer is a change of material preset, not of code. This is the concrete sense in
which a fusion-tritium workflow transfers to hydrogen aviation.

### 3.4 Certification by analysis as the organising goal

The CbA guide's four elements — simulation capability, UQ, rigorous validation, documented process — define
what "trustworthy automation" must produce. NuAgent's contribution is to the second and fourth: every run
carries its GCI and (where relevant) model-form uncertainty, and every decision — including the LLM's,
when one is used — is logged with the inputs that produced it. What no agent can supply is the full-scale
validation data; the design principle that follows is that the workflow must make it trivial to attach such
data (`dataset:` references with uncertainties) and impossible to claim validation without it.

---

## 4. Gap analysis: aerospace needs vs. LLM-CFD agents vs. NuAgent

| Need (from §1–3) | MetaOpenFOAM / OpenFOAMGPT / Foam-Agent (2024–25) | NuAgent |
|---|---|---|
| Result runs without error | Yes — the reported success metric (≈ 85–88 %) | Yes, with bounded, logged retries |
| Verification separated from validation (AIAA G-077) | No | Compulsory `verify` and `validate` nodes |
| Numerical uncertainty (ASME V&V 20 GCI) | No | Three-level grid study, observed order, GCI, asymptotic-range flag |
| Model-form uncertainty for separated flows | No — closure chosen by the LLM | Closure ensemble on the base grid; spread vs GCI; physics diagnostics per closure |
| Independent technical review before spending compute (NASA-STD-7009 review factor) | LLM "reviewer" agents check the case files, not the physics | Deterministic pre-flight review (correlation validity, y⁺, entry length, closure lessons, time scales); LLM may add, not remove |
| Reproducible, configuration-managed process (CbA) | Free-text edits of solver files; retries by error-message patching | Typed spec, strict templates, whitelisted numerics, provenance record, decision log |
| Reliability over repeated trials | pass@1 reported | pass^k in the eval harness (`--repeats`) |
| Reference data with uncertainty | Not modelled | Correlations with stated bands; exact solutions; datasets with uncertainties |
| Transfer across solvers (FV CFD and FE transport) | OpenFOAM only | OpenFOAM + FESTIM behind one spec and one graph |

---

## 5. Roadmap: aerospace-facing work for the next stages

1. **NASA TMR verification cases as eval tasks.** 2-D zero-pressure-gradient flat plate (skin friction and
   Cf vs Re_x), bump-in-channel, backward-facing step (reattachment length — the same diagnostic as the
   ribs). These have reference solutions from multiple codes and exercise precisely the RANS behaviour
   §1 worries about.
2. **Impinging-jet / heated-plate case** for anti-ice relevance (Martin 1977 stagnation Nu; energy
   balance), then film cooling effectiveness.
3. **A second CFD backend (SU2, open-source, aerospace-native)** to show the graph is solver-agnostic,
   and to run the TMR airfoil cases where OpenFOAM is not the community reference.
4. **Hydrogen-tank liner permeation**: replace the fusion material presets with liner alloys/polymers,
   couple a cryogenic wall temperature profile from the CFD side (one-way), and quantify inventory and
   leak-rate uncertainty.
5. **Credibility scorecard per NASA-STD-7009B** emitted with each report: which factors the run addresses
   (verification, validation, uncertainty characterisation, results robustness, technical review) and
   which remain for the human (input pedigree, use assessment).
6. **Data-driven closures as ensemble members**: an ML-augmented closure (Duraisamy et al. 2019 line of
   work) is just another `TurbulenceModel` for the ensemble to run and the critique to judge.

---

## References

Airbus, "Airbus reveals new zero-emission concept aircraft", press release, 21 Sep 2020; "Airbus showcases
hydrogen aircraft technologies during its 2025 Airbus Summit", 25 Mar 2025 · AIAA G-077-1998(2002),
*Guide for the Verification and Validation of Computational Fluid Dynamics Simulations* · ASME V&V 20-2009
(R2021), *Standard for Verification and Validation in Computational Fluid Dynamics and Heat Transfer* ·
ATI FlyZero, *Cryogenic Hydrogen Fuel System and Storage Roadmap* and companion reports, March 2022 · Cary
et al., *CFD Vision 2030 Road Map: Progress and Perspectives*, AIAA 2021-2726 · Celik, Ghia, Roache,
Freitas, Coleman & Raad, "Procedure for estimation and reporting of uncertainty due to discretization in
CFD applications", *J. Fluids Eng.* 130, 078001, 2008 · Delaporte-Mathurin et al., "FESTIM: An open-source
code for hydrogen transport simulations", *Int. J. Hydrogen Energy* 63, 786–802, 2024 · Duraisamy,
Iaccarino & Xiao, "Turbulence modeling in the age of data", *Annu. Rev. Fluid Mech.* 51, 357–377, 2019 ·
FAA AC 20-73A, *Aircraft Ice Protection*, 16 Aug 2006 · Han, Dutta & Ekkad, *Gas Turbine Heat Transfer and
Cooling Technology*, 2nd ed., CRC Press, 2012 · Han & Park, "Developing heat transfer in rectangular
channels with rib turbulators", *Int. J. Heat Mass Transfer* 31(1), 183–195, 1988 · Iacovides & Raisee,
"Recent progress in the computation of flow and heat transfer in internal cooling passages of turbine
blades", *Int. J. Heat Fluid Flow* 20(3), 320–328, 1999 · Li et al., "Research progress on high-temperature
coupling damage in TiAl alloys", *Results in Engineering* 29, 109754, 2026 · Mauery et al., *A Guide for
Aircraft Certification by Analysis*, NASA/CR-20210015404, 2021 · NASA-STD-7009B, *Standard for Models and
Simulations*, 2024 · NASA Turbulence Modeling Resource, https://turbmodels.larc.nasa.gov · Ooi, Iaccarino,
Durbin & Behnia, "Reynolds averaged simulation of flow and heat transfer in ribbed ducts", *Int. J. Heat
Fluid Flow* 23(6), 750–757, 2002 · Rau, Çakan, Moeller & Arts, "The effect of periodic ribs on the local
aerodynamic and heat transfer performance of a straight cooling channel", *J. Turbomachinery* 120(2),
368–375, 1998 · Ruff & Berkowitz, *Users Manual for the NASA Lewis Ice Accretion Prediction Code (LEWICE)*,
NASA CR-185129, 1990 · Rumsey, Slotnick & Woeber, *HLPW-4/GMGW-3: Overview and Workshop Summary*, NTRS
20220005271, 2022 · Slotnick et al., *CFD Vision 2030 Study: A Path to Revolutionary Computational
Aerosciences*, NASA/CR-2014-218178, 2014 · Tinoco et al., *Summary of Data from the Sixth AIAA CFD Drag
Prediction Workshop: CRM Cases 2 to 5*, AIAA SciTech 2017, NTRS 20170001397 · Webb, Eckert & Goldstein,
"Heat transfer and friction in tubes with repeated-rib roughness", *Int. J. Heat Mass Transfer* 14,
601–617, 1971 · 14 CFR Part 25 Appendix C, *Atmospheric icing conditions*.

LLM-agents-for-CFD references (MetaOpenFOAM, OpenFOAMGPT, Foam-Agent, CFDLLMBench) are listed with arXiv
identifiers in `docs/agent_architecture_review.md`.
