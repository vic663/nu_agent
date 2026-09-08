import residualsFig from "../assets/figures/turbulent_residuals.png";
import gciFig from "../assets/figures/turbulent_gci.png";
import modelFormFig from "../assets/figures/turbulent_model_form.png";
import ribbedProfilesFig from "../assets/figures/ribbed_profiles.png";
import laminarProfilesFig from "../assets/figures/laminar_profiles.png";

// group: "workflow" (one entry per graph node) or "platform" (backends, executors, policies, evals).
// Provide either `image` (a report figure) or `icon` (a Font Awesome class).
const CapabilityData = [
  {
    id: 1,
    group: "workflow",
    tag: "plan",
    title: "Typed specification from YAML or natural language",
    description:
      "A SimulationSpec (Pydantic) is the only interface between the LLM and the solvers. It comes from a YAML file, or from natural language via nuagent ask, where the plan is validated against the same schema before anything runs. Field descriptions double as the prompt; every quantity is SI.",
    icon: "fa-solid fa-pen-ruler",
  },
  {
    id: 2,
    group: "workflow",
    tag: "review",
    title: "Pre-flight verifier",
    description:
      "An independent, deterministic reviewer checks every plan before compute is spent: correlation validity at the operating point, y+ against the wall treatment, entry length, known closure lessons, FESTIM time scales. Blocking findings stop the run before build. An LLM may add findings, never remove them.",
    icon: "fa-solid fa-clipboard-check",
  },
  {
    id: 3,
    group: "workflow",
    tag: "build",
    title: "Template-generated solver inputs and y+-targeted meshing",
    description:
      "Jinja2 templates turn the spec into OpenFOAM dictionaries or a FESTIM script: an axisymmetric heated pipe (laminar and RANS) and a multi-block rib-roughened tube. The first-cell y+ is targeted from the correlation-estimated wall shear and anchored to the coarsest grid level, so every level of the grid family stays in one near-wall regime.",
    icon: "fa-solid fa-cubes",
  },
  {
    id: 4,
    group: "workflow",
    tag: "run + monitor",
    title: "Execution with a live convergence monitor",
    description:
      "Cases are self-contained directories with an Allrun. The live monitor parses residuals while the solver runs and asks OpenFOAM to write and stop as soon as the physically meaningful residuals converge. The verdict additionally requires a clean termination and a zero exit status.",
    image: residualsFig,
  },
  {
    id: 5,
    group: "workflow",
    tag: "diagnose",
    title: "Bounded diagnose-and-retry",
    description:
      "When a run diverges or stalls, the diagnostician proposes changes only from a whitelist of numerics (under-relaxation, convection scheme, iteration or time-step budget) within hard bounds, and every proposal is re-validated. Stalled runs continue from their latest time instead of restarting; converged cases are reused idempotently.",
    icon: "fa-solid fa-stethoscope",
  },
  {
    id: 6,
    group: "workflow",
    tag: "postprocess",
    title: "Raw-field post-processing and consistency checks",
    description:
      "Quantities of interest come from the raw fields: the Nusselt number from wall heat flux and bulk temperature, the friction factor from both the pressure gradient and the wall shear, module-averaged values for ribbed passages. Energy and mass balances are reported as consistency checks.",
    image: laminarProfilesFig,
  },
  {
    id: 7,
    group: "workflow",
    tag: "verify",
    title: "Grid-convergence index",
    description:
      "Three-level grid study, Richardson extrapolation and the grid-convergence index after Celik et al. (2008) and ASME V&V 20. The report states the observed order, the extrapolated value and whether the realised grid family is a systematic refinement.",
    image: gciFig,
  },
  {
    id: 8,
    group: "workflow",
    tag: "model_form",
    title: "Closure ensemble",
    description:
      "Re-runs the converged base grid with alternative RANS closures (optionally in parallel) and reports the spread as a model-form band next to the GCI, with per-closure reattachment diagnostics for ribbed passages. Closure trust is case-dependent, so the workflow measures it instead of choosing a favourite.",
    image: modelFormFig,
  },
  {
    id: 9,
    group: "workflow",
    tag: "validate",
    title: "Validation with reference uncertainty bands",
    description:
      "Every quantity is compared against an exact solution (48/11, 64/Re, Crank, Oriani) or a correlation (Gnielinski, Petukhov, Dittus-Boelter, Webb) that carries its own uncertainty band. The report says whether the numerical band overlaps the reference band. Validation fails closed: only an explicit pass earns credit.",
    image: ribbedProfilesFig,
  },
  {
    id: 10,
    group: "workflow",
    tag: "calibrate + uq",
    title: "Bayesian calibration and Sobol sensitivity",
    description:
      "Bayesian calibration with emcee over reduced-order models or Gaussian-process surrogates, and Sobol sensitivity indices with SALib. Implemented and exercised, but their qualification is incomplete: convergence diagnostics and failed-sample handling are open items.",
    icon: "fa-solid fa-chart-line",
  },
  {
    id: 11,
    group: "workflow",
    tag: "critique + report",
    title: "Physics critique and the report",
    description:
      "A physics-sanity critique (rules, optionally an LLM) reviews the finished result and returns a verdict. The Markdown report carries plots, the decision log and provenance (git hash, versions, digests), and can be re-rendered from result.json and decisions.jsonl.",
    icon: "fa-solid fa-file-lines",
  },
  {
    id: 12,
    group: "platform",
    tag: "backend",
    title: "OpenFOAM",
    description:
      "Axisymmetric heated pipe, laminar and RANS (k-omega SST, k-epsilon family, Launder-Sharma), the Jayatilleke thermal law of the wall for wall-function cases, and the rib-roughened cooling tube. Tested on OpenFOAM v1912, targets v2312 to v2512.",
    icon: "fa-solid fa-water",
  },
  {
    id: 13,
    group: "platform",
    tag: "backend",
    title: "FESTIM 2.x",
    description:
      "The trap-free 1-D permeation path is qualified against analytical steady flux and time lag. Trapped-permeation and TDS paths are implemented, but their independent qualification is incomplete.",
    icon: "fa-solid fa-atom",
  },
  {
    id: 14,
    group: "platform",
    tag: "backend",
    title: "Mock solver",
    description:
      "An analytical solver with a deterministic C·h² discretisation error and controllable failures. It runs the whole graph in about five seconds without OpenFOAM, which is what CI and the qualification suite use.",
    icon: "fa-solid fa-flask-vial",
  },
  {
    id: 15,
    group: "platform",
    tag: "executor",
    title: "Local, Docker and SLURM",
    description:
      "Local and Docker execution are exercised in the current public evidence. A SLURM executor with sbatch, squeue and sacct plus a whole-job-budget approval gate is implemented; qualification on a real cluster is still pending.",
    icon: "fa-solid fa-server",
  },
  {
    id: 16,
    group: "platform",
    tag: "policy",
    title: "Rules and LLM policies",
    description:
      "The rules policy is deterministic and needs no model. The LLM policy enters at four bounded judgement points (plan, review, diagnose, critique), each a single structured-output call of 5 to 15k tokens, with Anthropic, OpenAI or any OpenAI-compatible local server (Ollama, vLLM), and falls back to the rules.",
    icon: "fa-solid fa-robot",
  },
  {
    id: 17,
    group: "platform",
    tag: "eval",
    title: "Agent qualification suite",
    description:
      "nuagent eval runs the task suite and scores success, retries, validation and GCI outcomes; --repeats adds the pass^k reliability statistic. Ten tasks: seven that must succeed and three negative controls that must be refused, because a success rate measured only on tasks that should succeed cannot detect a wrong answer.",
    icon: "fa-solid fa-vial-circle-check",
  },
];

export default CapabilityData;
