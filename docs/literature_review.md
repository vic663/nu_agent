# Literature review and scientific positioning

*Compiled September 2026. Items marked ✔ were checked against the arXiv abstract page during the
review; items marked (verify) are cited from memory and must be checked before any submission.*

## 1. Where the field is

### 1.1 LLM agents that drive CFD codes (2024 – 2026)

| Work | What it does | How it is evaluated | Take-away |
|---|---|---|---|
| **MetaOpenFOAM** — Chen et al., arXiv:2407.21320 ✔ | Multi-agent (role-based) framework with retrieval-augmented generation that turns natural-language requests into OpenFOAM cases | 8 CFD scenarios; 85 % success; ≈$0.22 per case | First demonstration that LLM agents can drive OpenFOAM end to end |
| **MetaOpenFOAM 2.0** — arXiv:2502.00498 ✔ | Adds chain-of-thought decomposition and *iterative verification* (does the case run?) | executability 6.3/7, 86.9 % pass, ≈$0.15 per case | "Verification" here means the case executes, not that the physics is right |
| **OpenFOAMGPT** — Pandey, Xu, Wang, Chu, arXiv:2501.06327 ✔ | RAG-augmented agent; compares GPT-4o and o1 on turbulence, BC and multiphase set-ups with iterative correction loops | Qualitative/quantitative case studies | Authors state that "human oversight remains crucial for ensuring accuracy" |
| **Foam-Agent** — Yue et al., arXiv:2505.04997 ✔ (rev. 2026) | Multi-agent workflow covering meshing, job configuration and visualisation | 110 tasks; 88.2 % *execution* success without expert intervention | Largest CFD-agent benchmark so far; metric is execution success |
| ChatCFD / CFD-copilot style tools (2025, verify) | Conversational case set-up assistants | small case sets | Same pattern: convenience and executability |

**Common denominator:** the success metric is *did the solver run and produce output*. None of these
systems performs solution verification (grid-convergence, error estimation), none compares against
references with stated uncertainty, none quantifies how often the LLM proposed something invalid, and none
runs a deterministic baseline against which the LLM's contribution can be measured. They are single-code
(OpenFOAM) and do not close the loop to calibration or UQ. In V&V language they demonstrate
*capability*, not *credibility*.

### 1.2 Autonomous "AI scientist" agents and how the community evaluates them

- **Coscientist** (Boiko et al., *Nature* 2023) and **ChemCrow** (Bran et al., *Nat. Mach. Intell.* 2024)
  showed LLM agents planning and executing chemistry with lab automation (verify exact citations).
- **The AI Scientist** (Lu et al., 2024, verify) automates paper-writing research loops; criticised for
  weak evaluation of correctness.
- **ScienceAgentBench** — Chen et al., arXiv:2410.05080 ✔: 102 expert-validated tasks from 44 papers;
  the best agent solves 32.4 % (42.2 % with o1-preview). Lesson: *rigorous, expert-validated benchmarks
  with ground truth are what moves the field*, and current agents are far from reliable.
- Simulation science has a structural advantage that these benchmarks lack: **ground truth exists** —
  exact solutions (Poiseuille, Crank, Hartmann), asymptotic correlations with stated uncertainty
  (Gnielinski, Petukhov, Webb), and community V&V cases. A simulation-agent benchmark can therefore
  score *physical correctness*, not only task completion.

### 1.3 Credibility frameworks the agent must live inside

- **ASME V&V 20-2009** and Roache's GCI (Celik et al. 2008): the discretisation-uncertainty procedure
  implemented in `verification/`.
- **Oberkampf & Roy, *Verification and Validation in Scientific Computing* (2010)**: validation metrics,
  model-form uncertainty — the vocabulary this project uses.
- **Nuclear**: NRC Regulatory Guide 1.203 (EMDAP) and the CSAU methodology define how an *evaluation
  model* earns credibility: phenomena identification, code assessment against separate- and
  integral-effects tests, scaling and uncertainty. **ASME V&V 40** (medical devices) introduced
  *risk-informed credibility*: how much V&V is enough depends on the decision consequence.
- No equivalent exists yet for **AI agents operating simulation codes**. NuAgent's "qualification suite"
  is a first attempt to give an agent the same treatment a code gets: known-answer tests, bounded
  behaviour, provenance.

### 1.4 Turbulence-model credibility in rib-roughened passages (the aerospace ↔ nuclear bridge)

- Webb, Eckert & Goldstein (1971) — repeated-rib tubes; roughness functions R(e⁺), G(e⁺) used here.
- Han (1988), Han & Park (1988) — rib-roughened channels for turbine-blade cooling, same framework.
- Rau, Çakan, Moeller & Arts (1998) — detailed measurements: reattachment ≈4–5 e for p/e ≈ 9–10.
- Iacovides & Raisee (1999); Ooi, Iaccarino, Durbin & Behnia (2002) — RANS assessment: low-Re k-ε and
  v²–f predict the flow topology; heat transfer in separated regions under-predicted by 20–40 % unless
  length-scale corrections (Yap) are used.
- Keshmiri, Cotton, Addad & Laurence (2012) — rib-roughened **AGR fuel-channel** flows with RANS/LES:
  the same deficits appear in a nuclear application, which is why this case matters to a reactor group.
- **NuAgent's own finding** (docs/case_catalogue.md §D1): steady k-ω SST predicts a cavity ("d-type")
  flow for p/e = 10 with no reattachment, giving f 47–55 % and Nu ≈ 65 % below Webb; the ε-family recovers
  reattachment at 4–5 e and friction within 4–15 %, leaving the well-known ≈25–30 % Nu deficit. The critique
  node detects this automatically from the reversed-flow fraction — an agent that *knows when its
  closure is wrong*.

### 1.5 Tritium transport and Bayesian calibration

- **FESTIM** — Delaporte-Mathurin et al., *Int. J. Hydrogen Energy* (2024) (verify) and the FESTIM V&V
  book: the open FEniCSx hydrogen-transport code used here; its V&V cases (permeation, Oriani effective
  diffusivity, TDS) are the references in `agent/vv.py`.
- Trap-parameter identification from TDS is a classical inverse problem (Hodille et al. 2015 with MHIMS;
  Delaporte-Mathurin et al. 2021 parametric optimisation, verify) usually solved by deterministic
  fitting; Bayesian treatments exist but are not routine. The *E_p–p_0* compensation ridge recovered by
  NuAgent's reduced-model posterior is the known identifiability problem of TDS.
- Reduced-order → high-fidelity calibration with surrogate-error accounting (Kennedy & O'Hagan 2001
  framing) is standard in UQ but has not been wired into an autonomous simulation workflow.

### 1.6 Agentic infrastructure for scientific computing

- LangGraph-style state machines with typed tool interfaces; the Model Context Protocol (MCP) for
  exposing tools to any agent client; DOE laboratories' 2024–2026 "AI for science" programmes explicitly
  call for agentic workflows on HPC — with on-premise (open-weights) models for security. NuAgent's
  provider-agnostic LLM layer and deterministic baseline are designed for that constraint.

## 2. The gap, stated plainly

1. Existing CFD agents measure **execution**, not **correctness**; there is no solution verification, no
   validation with uncertainty, no provenance.
2. There is no **qualification methodology** for simulation agents — no known-answer benchmark, no
   bounded-behaviour argument, no ablation separating the LLM from the scaffolding.
3. Agents are **single-code**; multiphysics credibility (FV CFD + FE transport) is untested.
4. Calibration and UQ — the very things a national laboratory does with simulations — are absent
   from the agent loop.
5. Nobody has shown an agent **detecting model-form failure** (e.g., a closure predicting the wrong flow
   topology) and reporting it instead of rubber-stamping a converged run.

## 3. The scientific story (for a top-tier venue)

**Title idea:** *From running to qualifying: verification-native LLM agents for engineering simulation*

**One-sentence claim:** An LLM agent that operates simulation codes can be made *credible* — in the
ASME/NRC sense — by construction: typed, bounded degrees of freedom; compulsory verification and
validation with uncertainty; a deterministic twin against which the LLM is measured; and a benchmark of
known-answer tasks that scores physical correctness. We demonstrate this across finite-volume CFD and
finite-element tritium transport, and show the agent catching a turbulence-model failure that
execution-based agents would have reported as success.

**Contributions**

1. **A qualification methodology and benchmark for simulation agents** — tasks with exact or
   correlation references and uncertainty bands, scored on verified-and-validated success, retries,
   invalid-proposal rate, cost; released openly.
2. **A guard-railed, V&V-native architecture** (spec contract, template-only inputs, bounded diagnostics,
   compulsory GCI, provenance) with an ablation: rules-only vs LLM policies vs guardrails removed
   (counterfactual replay of logged proposals).
3. **Cross-code generality** — the same workflow drives OpenFOAM and FESTIM; a coupled coolant-channel →
   tritium-permeation case as the multiphysics demonstration.
4. **Model-form discovery in the loop** — the ribbed-tube study: SST's d-type failure detected by a
   physics-aware critique; ε-family closure recovers topology and friction; residual Nu deficit quantified
   and traced to the literature.
5. **Reduced-order → high-fidelity Bayesian calibration** of tritium trap parameters with surrogate error
   accounting inside the same workflow.

**Why it is a story and not a tool:** the paper answers a question people are asking now — *can we
trust AI agents with simulations that inform engineering decisions?* — with a method (qualification),
an instrument (the benchmark), evidence (multi-model evaluation), and a cautionary tale with a happy
ending (the SST case). The nuclear framing gives it stakes; the aerospace case gives it a second domain
and the author's own experimental background.

**Venue strategy**

| Tier | Venue | Fit | What it needs |
|---|---|---|---|
| Top general | *Nature Computational Science*, *Nature Machine Intelligence* | agent-credibility methodology + benchmark + multi-domain evidence | ≥ 30 tasks, ≥ 4 models incl. open weights, human-analyst baseline, counterfactual guardrail study, released benchmark |
| Top methods | *Computer Methods in Applied Mechanics and Engineering*, *Journal of Computational Physics* (software/methods) | V&V-native agent architecture, GCI-in-the-loop, calibration | same, with emphasis on verification rigour |
| Domain | *Nuclear Engineering and Design*, *Annals of Nuclear Energy*, *Fusion Engineering and Design* | coupled channel→permeation, TDS calibration | the application cases fully validated |
| Companion physics paper | *International Journal of Heat and Mass Transfer* / *J. Turbomachinery* | RANS closure assessment for rib-roughened tubes across e/D, p/e, Re with GCI | the ribbed-tube study extended (Re, e/D sweep; LES reference) |
| Software | *JOSS*, *Computer Physics Communications* | the code | exists today |

**Minimum experiments before a top-tier submission** (maps to the 3-week roadmap): benchmark expansion
(A1–A6, D1, C1, adversarial tasks), model matrix (Claude, GPT, Llama/Qwen via vLLM) × 5 seeds, guardrail
ablation with counterfactual replay, human-analyst timing baseline (two engineers, three tasks), the
coupled multiphysics case, TDS calibration with FESTIM-in-the-loop, and full provenance release.
