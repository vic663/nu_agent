# Agentic architectures for simulation V&V: what the literature says, and what NuAgent adopts

*Question addressed: should a verification-and-validation workflow for CFD/FEM simulations be built as a
multi-agent LLM system? Short answer: not as a conversation between role-playing agents — but yes to three
specific multi-agent **patterns** (generator–verifier separation, orchestrator–workers for embarrassingly
parallel physics studies, and repeated-trial reliability evaluation), all sitting on a deterministic
workflow backbone with typed contracts. This document gives the evidence and maps each decision to code.*

All arXiv identifiers below were checked against the arXiv abstract pages on 2026-09-02.

---

## 1. A map of the widely cited agentic patterns

| Pattern | Representative papers (arXiv) | Core idea | What it means for simulation V&V |
|---|---|---|---|
| Reasoning + acting loops | Chain-of-Thought (Wei 2022, 2201.11903); ReAct (Yao 2022, 2210.03629); Self-Ask (Press 2022, 2210.03350); Plan-and-Solve (Wang 2023, 2305.04091); Toolformer (Schick 2023, 2302.04761) | Interleave explicit reasoning with tool calls; plan first, then execute | The planner may reason, but the *action space* must be typed: a `SimulationSpec`, not shell commands |
| Self-correction | Self-Refine (Madaan 2023, 2303.17651); Reflexion (Shinn 2023, 2303.11366); CRITIC (Gou 2023, 2305.11738) | Iterate on feedback; keep verbal memory of past failures; **critique with tools, not introspection** | CRITIC's finding matters most: feedback should come from *external* checks (residuals, balances, GCI, correlations), which CFD has in abundance |
| Search over reasoning | Tree of Thoughts (Yao 2023, 2305.10601); LATS (Zhou 2023, 2310.04406) | Explore several candidate paths, evaluate, backtrack | Expensive when each "path" is an HPC run; cheap when it is a *plan* — so search plans, not runs |
| Sampling / ensembles | Self-Consistency (Wang 2022, 2203.11171); More Agents Is All You Need (Li 2024, 2402.05120); Large Language Monkeys (Brown 2024, 2407.21787); Mixture-of-Agents (Wang 2024, 2406.04692) | Draw many samples, vote or select; coverage grows log-linearly with samples — **if a verifier exists** | Voting is meaningless for a Nusselt number; selecting with a physics-based verifier is not |
| Multi-agent conversation frameworks | AutoGen (Wu 2023, 2308.08155); MetaGPT (Hong 2023, 2308.00352); CAMEL (Li 2023, 2303.17760); ChatDev (Qian 2023, 2307.07924); Generative Agents (Park 2023, 2304.03442); HuggingGPT (Shen 2023, 2303.17580); Magentic-One (Fourney 2024, 2411.04468) | Role-specialised LLM agents pass messages; MetaGPT encodes *standard operating procedures* into roles; Magentic-One uses a lead orchestrator with task/progress ledgers | The SOP idea is right; the *implementation as chat* is the weak part (see §2). NuAgent encodes the SOP as a state machine |
| Debate | Multiagent Debate (Du 2023, 2305.14325); "Should we be going MAD?" (Smit 2023, 2311.17371) | Several instances argue to a consensus | Benefits found inconsistent and hyper-parameter sensitive; irrelevant when the ground truth is computable |
| Software-engineering agents | SWE-bench (Jimenez 2023, 2310.06770); SWE-agent (Yang 2024, 2405.15793); OpenHands (Wang 2024, 2407.16741); CodeAct (Wang 2024, 2402.01030); **Agentless** (Xia 2024, 2407.01489) | The *agent–computer interface* matters more than agent cleverness (SWE-agent); executable code as action space (CodeAct); a fixed 3-phase pipeline matches agents at lower cost (Agentless) | Interface design (typed spec, template-only solver input) is the lever; Agentless is direct evidence for workflow-over-agent |
| Lifelong skill libraries | Voyager (Wang 2023, 2305.16291) | Store verified skills for reuse | "Lessons learned" (e.g. SST on p/e = 10 ribs) belong in a curated, testable rule store |
| Cognitive architecture | CoALA (Sumers 2023, 2309.02427) | Memory / action space / decision loop taxonomy | A useful vocabulary for documenting *which* memory an agent has (NuAgent: the spec, the decision log, the rule base) |
| Science agents | ChemCrow (Bran 2023, 2304.05376); The AI Scientist (Lu 2024, 2408.06292); Agent Laboratory (Schmidgall 2025, 2501.04227) | Tool-augmented LLMs for domain workflows; end-to-end automation of research | Success is judged by human/LLM review; none has a compulsory, code-based V&V gate |
| Agent evaluation | AgentBench (Liu 2023, 2308.03688); AgentBoard (Ma 2024, 2401.13178); **τ-bench** (Yao 2024, 2406.12045, *pass^k*); LLM-as-a-judge (Zheng 2023, 2306.05685); ScienceAgentBench (Chen 2024, 2410.05080); MLE-bench (Chan 2024, 2410.07095); **MAST** (Cemri 2025, 2503.13657) | Reliability over repeated trials; fine-grained progress; a taxonomy of why multi-agent systems fail | Qualification of an engineering agent needs pass^k, not pass@1, and needs known answers, not judges |
| Surveys | Wang 2023 (2308.11432); Xi 2023 (2309.07864); RAG survey (Gao 2023, 2312.10997) | Profiling / memory / planning / action framework | — |
| LLM agents for CFD | MetaOpenFOAM (Chen 2024, 2407.21320); MetaOpenFOAM 2.0 (2502.00498); OpenFOAMGPT (Pandey 2025, 2501.06327); Foam-Agent (Yue 2025, 2505.04997); CFDLLMBench (Somasekharan 2025, 2509.20374); fine-tuned CFD LLM (Dong 2025, 2504.09602) | Multi-agent + RAG pipelines that turn natural language into runnable OpenFOAM cases; success = case runs (85–88 % reported) | The **direct predecessors**; their success metric is "runs", not "verified and validated" — the gap NuAgent targets |

---

## 2. What the evidence says about multi-agent systems

**Multi-agent systems fail in systematic ways.** MAST (Cemri et al. 2025) analysed more than a thousand
execution traces of popular multi-agent frameworks and organised the failures into three categories:
specification and system-design failures (poor task decomposition, role violations), inter-agent
misalignment (agents ignoring or misunderstanding each other), and task verification and termination
failures (no or weak final verification, premature termination). The third category is the one that
matters most for engineering: **a multi-agent system with an LLM "reviewer" still ships wrong answers**
because the reviewer has no ground truth.

**Simple pipelines are competitive.** Agentless (Xia et al. 2024) showed that a fixed
localise → repair → validate pipeline matched or beat autonomous agents on SWE-bench Lite at a fraction of
the cost; the authors argue the community should question whether autonomy is buying anything. Anthropic's
engineering guidance ("Building effective agents", December 2024) draws the same line between *workflows*
(LLM calls orchestrated through predefined code paths) and *agents* (LLMs that direct their own process),
recommends the simplest structure that works, and names the composable workflow patterns: prompt
chaining, routing, parallelisation (sectioning and voting), orchestrator–workers, and evaluator–optimiser.

**Debate and voting need a verifier to be useful.** Self-consistency, "More agents", Mixture-of-Agents and
Large Language Monkeys all show that sampling increases *coverage* — the chance that at least one sample is
right — but turning coverage into accuracy requires a selector. For arithmetic or code with unit tests the
selector exists; for open-ended text it degenerates into majority vote or LLM-as-judge, and Smit et al.
(2023) found debate gains inconsistent. For a simulation the situation is unusually favourable: residual
histories, conservation balances, grid-convergence indices and correlation bands *are* a verifier, and a
deterministic one.

**Interfaces beat cleverness.** SWE-agent's central result is that carefully designed agent–computer
interfaces (bounded, well-formatted commands with guardrails) improved success far more than prompt
engineering. CodeAct argues for executable code as the action space; for a solver that would mean letting
an LLM write `fvSolution` or a `blockMeshDict` by hand — exactly the failure mode MetaOpenFOAM's iterative
"run, read the error, patch" loop spends most of its retries on. NuAgent's answer is a typed, validated
`SimulationSpec` rendered through strict templates.

**Reflection helps when the memory is verified.** Reflexion and Voyager improve by storing verbal lessons or
skills; CRITIC shows that self-critique *without* tools is unreliable. The engineering analogue is a curated
rule base: "k-ω SST predicted d-type cavity flow for p/e = 10 ribs in run X; prefer a k-ε family model or
run a closure ensemble" is a lesson that was *measured*, is now a pre-flight rule, and is covered by a test.

**Reliability must be measured over repeats.** τ-bench introduced pass^k — the probability that *all* of k
independent trials succeed — and showed that agents with respectable pass^1 collapse at k = 8. An
engineering assistant that is right 80 % of the time is not usable; the qualification question is whether
pass^k stays flat. This is why the NuAgent evals now take `--repeats`.

**Where multi-agent structure genuinely helps.** Two situations recur across the literature: (i) parallel,
independent sub-tasks (orchestrator–workers; Magentic-One's ledger design; Anthropic's parallelisation
pattern) and (ii) separating the generator from the verifier (evaluator–optimiser; CRITIC; generator–
verifier splits in code agents), so that the entity checking the work is not the one that produced it.
Both map naturally onto simulation V&V — but the workers are *solver jobs* and the verifier is *code*.

---

## 3. Verdict and the design decisions it produced

| Pattern | Adopted? | Where in NuAgent | Rationale |
|---|---|---|---|
| Deterministic workflow backbone (state machine) | **Yes** | `agent/graph.py` (LangGraph) | MAST + Agentless: predictable control flow, reproducible; qualification demands it |
| Typed action space (agent–computer interface) | **Yes** | `spec.py` (`SimulationSpec`), `policy.py` (`Adjustments` whitelist) | SWE-agent lesson; no free-text path to the solver |
| Generator–verifier separation | **Yes** — new `review` node | `agent/preflight.py`; LLM may only *add* findings | CRITIC (tool-grounded critique), evaluator–optimiser; the verifier is deterministic and testable |
| Orchestrator–workers | **Yes** — new `model_form` node; grid study; (planned) LHS sweeps | `agent/model_form.py` (thread pool over closures) | Parallelism where the sub-tasks are independent solver runs; reduction is code |
| Reflexion-style memory | **Yes, as rules** | Lessons encoded in `preflight.py` / `rules_critique` with tests | Verified memory, not verbal memory |
| Sampling + verifier selection | **Partly** | `evals/harness.py` pass^k; (planned) sample N plans, select with `preflight` | Coverage scaling only pays with a verifier |
| Human-in-the-loop gate | **Yes** | `approve` node (`interrupt`) before HPC | Irreversible/expensive actions need a person |
| Role-playing agent conversation | **No** | — | MAST failure modes; no ground truth in the chat |
| LLM as final judge of validity | **No** | Rules verdict is authoritative in `critique` | LLM-as-judge is for text, not for Nusselt numbers |
| LLM-written solver input files | **No** | Strict Jinja templates from validated numbers | Removes the dominant retry loop of prior CFD agents |
| Unbounded autonomy | **No** | `max_attempts`, wall-clock, cell budgets | Cost and safety |

The resulting graph:

```
plan → review → build → approve → run → monitor → postprocess → verify → model_form → validate
          ↓                          ↑        ↓ (diverged / stalled)
      (blocking)                     └──── diagnose (bounded retries)
          ↓
        report ← critique ← uq ← calibrate ←──────────────────────────────────────┘
```

Three nodes may consult an LLM (`plan`, `review`, `diagnose`, `critique` — `review` and `critique` only
additively); everything else is deterministic code with a test suite. With the rules policy the whole graph
runs without a language model, which is what makes A/B comparison of policies (and therefore
qualification) possible.

---

## 4. When a fuller multi-agent design would be justified

1. **Heterogeneous multiphysics with different expertise per sub-problem** — e.g. a coolant-channel CFD
   agent feeding a tritium-permeation agent. Even then, the coupling variables should be typed and the
   handshake deterministic; the "agents" are specialists behind interfaces (MCP tools), not chat partners.
2. **Literature/data retrieval** for validation references — a RAG agent that proposes reference values
   with citations (OpenFOAMGPT-style retrieval), whose proposals enter the same `ReferenceSpec` schema.
3. **Campaign planning** — designing a matrix of runs (DoE, adaptive sampling for surrogates) where a
   planner–worker split is natural and the workers are the existing workflow.
4. **Tool federation via MCP** — exposing `build`, `run`, `verify`, `validate` as tools lets other agents
   (or IDE assistants) call NuAgent as a *verified tool* rather than reimplementing it.

The roadmap therefore reads "specialist tool-agents behind typed interfaces, orchestrated by the
deterministic graph", not "a society of agents".

---

## 5. How this will be evaluated (publication plan, RQ1–RQ3)

* **pass^k reliability** for k = 1…5 on the task suite, per policy and model (τ-bench).
* **Invalid-proposal rate**: how many LLM plans/adjustments the schema rejects (a direct measure of what the
  guardrails prevent), plus counterfactual replay with validators disabled.
* **Verifier value**: runs where `review` or `critique` changed the outcome (blocked, warned, or triggered a
  closure ensemble) versus a no-review ablation.
* **Cost**: tokens and wall-clock per validated result; comparison of hosted vs local open-weights models.
* **Baseline**: the rules policy — the deterministic workflow with no LLM at all.

---

## References (arXiv identifiers verified 2026-09-02)

Wei et al. 2022, *Chain-of-Thought Prompting*, 2201.11903 · Wang et al. 2022, *Self-Consistency*, 2203.11171 ·
Yao et al. 2022, *ReAct*, 2210.03629 · Press et al. 2022, *Self-Ask / compositionality gap*, 2210.03350 ·
Schick et al. 2023, *Toolformer*, 2302.04761 · Shinn et al. 2023, *Reflexion*, 2303.11366 · Madaan et al.
2023, *Self-Refine*, 2303.17651 · Li et al. 2023, *CAMEL*, 2303.17760 · Shen et al. 2023, *HuggingGPT*,
2303.17580 · Park et al. 2023, *Generative Agents*, 2304.03442 · Bran et al. 2023, *ChemCrow*, 2304.05376 ·
Wang et al. 2023, *Plan-and-Solve*, 2305.04091 · Yao et al. 2023, *Tree of Thoughts*, 2305.10601 · Gou et al.
2023, *CRITIC*, 2305.11738 · Du et al. 2023, *Multiagent Debate*, 2305.14325 · Wang et al. 2023, *Voyager*,
2305.16291 · Zheng et al. 2023, *LLM-as-a-Judge*, 2306.05685 · Qian et al. 2023, *ChatDev*, 2307.07924 ·
Hong et al. 2023, *MetaGPT*, 2308.00352 · Liu et al. 2023, *AgentBench*, 2308.03688 · Wu et al. 2023,
*AutoGen*, 2308.08155 · Wang et al. 2023, *Survey of LLM-based autonomous agents*, 2308.11432 · Sumers et
al. 2023, *CoALA*, 2309.02427 · Xi et al. 2023, *Rise and potential of LLM-based agents*, 2309.07864 · Zhou
et al. 2023, *LATS*, 2310.04406 · Jimenez et al. 2023, *SWE-bench*, 2310.06770 · Smit et al. 2023, *Should
we be going MAD?*, 2311.17371 · Gao et al. 2023, *RAG survey*, 2312.10997 · Ma et al. 2024, *AgentBoard*,
2401.13178 · Wang et al. 2024, *CodeAct*, 2402.01030 · Li et al. 2024, *More Agents Is All You Need*,
2402.05120 · Yang et al. 2024, *SWE-agent*, 2405.15793 · Wang et al. 2024, *Mixture-of-Agents*, 2406.04692 ·
Yao et al. 2024, *τ-bench*, 2406.12045 · Xia et al. 2024, *Agentless*, 2407.01489 · Wang et al. 2024,
*OpenHands*, 2407.16741 · Chen et al. 2024, *MetaOpenFOAM*, 2407.21320 · Brown et al. 2024, *Large Language
Monkeys*, 2407.21787 · Lu et al. 2024, *The AI Scientist*, 2408.06292 · Chen et al. 2024,
*ScienceAgentBench*, 2410.05080 · Chan et al. 2024, *MLE-bench*, 2410.07095 · Fourney et al. 2024,
*Magentic-One*, 2411.04468 · Schmidgall et al. 2025, *Agent Laboratory*, 2501.04227 · Pandey et al. 2025,
*OpenFOAMGPT*, 2501.06327 · Chen et al. 2025, *MetaOpenFOAM 2.0*, 2502.00498 · Cemri et al. 2025, *Why Do
Multi-Agent LLM Systems Fail?* (MAST), 2503.13657 · Dong et al. 2025, *Fine-tuning an LLM for CFD
automation*, 2504.09602 · Yue et al. 2025, *Foam-Agent*, 2505.04997 · Somasekharan et al. 2025,
*CFDLLMBench*, 2509.20374.

Anthropic, *Building effective agents*, engineering blog, December 2024 (workflow patterns: prompt
chaining, routing, parallelisation, orchestrator–workers, evaluator–optimiser).
