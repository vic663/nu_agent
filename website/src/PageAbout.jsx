import aboutBanner from "./assets/about_banner.svg";
import modelFormFig from "./assets/figures/turbulent_model_form.png";

const principles = [
  {
    title: "LLM in the loop, never in the syntax.",
    text:
      "The planner produces a SimulationSpec; templates turn it into OpenFOAM dictionaries or a FESTIM script. Hallucinated boundary conditions cannot reach the solver because there is no free-text path to it. The diagnostician may only change whitelisted numerics within hard bounds, and every proposal is re-validated.",
  },
  {
    title: "Deterministic baseline.",
    text:
      "The rules policy implements planning-from-spec, a diagnosis table and a physics-sanity critique with no model calls. The LLM policy layers a model on top and falls back to the rules if the model is unavailable. Because the workflow is identical, nuagent eval can compare policies and models on the same tasks.",
  },
  {
    title: "V&V is not optional.",
    text:
      "Every run performs a grid-refinement study and reports observed order, Richardson-extrapolated value and GCI. Every quantity of interest is compared against an exact solution or a correlation with the correlation's own uncertainty band.",
  },
  {
    title: "Model-form uncertainty is measured, not assumed.",
    text:
      "A model_form block re-runs the converged base grid with alternative closures. The report shows the spread as a model-form band next to the GCI and says which one dominates. In the ribbed tube it is model form by an order of magnitude.",
  },
  {
    title: "Verify the plan before you pay for it.",
    text:
      "Whoever wrote the specification (human, rules or LLM), an independent deterministic reviewer checks correlation validity at the operating point, wall resolution, development length and known closure pitfalls, and blocks impossible cases before a single cell is meshed.",
  },
  {
    title: "Solver isolation.",
    text:
      "Cases are self-contained directories with an Allrun; the agent never imports OpenFOAM or dolfinx. The same case runs on a laptop, in a container, or under SLURM with a human approval gate, and can be re-run by hand.",
  },
];

const qualified = [
  "Typed simulation specs (Pydantic) as the only interface between the LLM and the solvers",
  "OpenFOAM backend: heated pipe (laminar, k-omega SST, k-epsilon family) and rib-roughened cooling tube, y+-targeted meshing",
  "FESTIM 2.x backend: 1-D tritium permeation with McNabb-Foster traps, and thermal desorption spectroscopy",
  "Pre-flight review, closure ensemble, live convergence monitor, bounded diagnose-and-retry",
  "Grid-convergence index (Celik 2008 / ASME V&V 20) and validation against exact solutions and correlations",
  "Executors: local, Docker, SLURM with an approval gate that discloses the whole job budget",
  "Markdown report with plots, decision log and provenance; qualification suite with negative controls",
  "LLM planning from natural language: Anthropic, OpenAI, or any OpenAI-compatible local server",
];

const pending = [
  "Bayesian calibration (emcee): convergence diagnostics pending. No thinning or effective sample size, and the shipped TDS example is not converged.",
  "Sobol sensitivity (SALib): failed-sample handling pending. Failed model evaluations are imputed with the sample mean and not reported, which biases the indices.",
];

const PageAbout = () => {
  return (
    <>
      <div className="w-full max-w-6xl mx-auto flex flex-col-reverse md:flex-row items-center text-center justify-center font-serif_title">
        <div className="text-brand-700 text-2xl md:text-4xl font-medium max-w-[450px] m-10 font-serif_title">
          What NuAgent Is
        </div>
      </div>

      <img
        className="w-full object-cover max-h-[420px]"
        src={aboutBanner}
        alt="Rib-roughened cooling tube"
      />

      <div className="flex justify-center items-center">
        <div className="max-w-6xl flex flex-col-reverse md:flex-row py-4">
          <div className="text-stone-800 mt-4 text-base md:text-2xl font-lato font-medium p-4 mb-2">
            <span className="text-brand-700 font-semibold text-xl md:text-3xl font-lato">NuAgent</span>{" "}
            is an open-source (MIT) research code by Baihua Ren. It is an agentic workflow that sets up,
            runs, monitors, verifies, validates and calibrates convective heat-transfer and transport
            simulations, and writes the V&amp;V report. The cases it handles today are turbine-blade
            cooling passages, heat-exchanger and reactor coolant channels (OpenFOAM), and tritium
            transport in fusion materials (FESTIM).
            <div className="mt-4 text-base md:text-2xl">
              The architecture follows what the agent literature actually supports: a deterministic
              workflow backbone with typed contracts, an independent verifier that reviews every plan
              before compute is spent, and orchestrator-workers fan-out where sub-tasks are independent
              solver runs. Verification procedures follow Celik et al. (2008) and ASME V&amp;V 20-2009;
              correlations and their uncertainties follow Incropera &amp; DeWitt.
            </div>
          </div>
        </div>
      </div>

      <div className="bg-brand-50 w-full mx-auto flex flex-col-reverse md:flex-row items-center text-center justify-center font-serif_title shadow-lg">
        <div className="text-brand-700 text-2xl md:text-4xl font-medium max-w-[450px] p-4 m-4 font-serif_title">
          Why This Design
        </div>
      </div>

      <div className="flex items-center md:ml-16 md:p-4 flex-col md:flex-row gap-6">
        <img
          className="w-full md:max-w-xl mt-8 md:mt-0 object-contain rounded-lg shadow-lg border border-stone-200 bg-white"
          src={modelFormFig}
          alt="Closure ensemble: model-form band next to the GCI"
        />
        <div className="text-stone-800 text-sm md:text-lg font-lato mt-4 md:p-4 md:mb-2 px-4">
          <ul className="space-y-4">
            {principles.map((p) => (
              <li key={p.title}>
                <span className="text-brand-700 font-semibold text-base md:text-xl">{p.title}</span>{" "}
                <span className="text-stone-700">{p.text}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="bg-brand-50 w-full mx-auto flex flex-col-reverse md:flex-row items-center text-center justify-center font-serif_title shadow-lg mt-10">
        <div className="text-brand-700 text-2xl md:text-4xl font-medium max-w-[450px] p-4 m-4 font-serif_title">
          Where It Stands (v0.1.4)
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-10 grid grid-cols-1 md:grid-cols-2 gap-8 font-lato">
        <div>
          <h3 className="font-serif_title text-2xl text-brand-700 mb-4">Implemented and qualified</h3>
          <ul className="space-y-2 text-sm md:text-base text-stone-700">
            {qualified.map((item) => (
              <li key={item} className="flex gap-3">
                <i className="fa-solid fa-circle-check text-green-600 mt-1"></i>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="font-serif_title text-2xl text-brand-700 mb-4">Implemented, qualification pending</h3>
          <ul className="space-y-2 text-sm md:text-base text-stone-700">
            {pending.map((item) => (
              <li key={item} className="flex gap-3">
                <i className="fa-solid fa-triangle-exclamation text-amber-500 mt-1"></i>
                <span>{item}</span>
              </li>
            ))}
          </ul>
          <p className="mt-6 text-sm text-stone-500">
            Implementation existing is not the same as the result being trustworthy, and this project's
            whole argument is that the difference matters. The open items are tracked under Known
            limitations in the changelog.
          </p>
        </div>
      </div>
    </>
  );
};

export default PageAbout;
