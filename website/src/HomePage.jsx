import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import heroImg from "./assets/hero.svg";
import workflowImg from "./assets/section_workflow.svg";
import vvImg from "./assets/section_vv.svg";
import closuresImg from "./assets/section_closures.svg";
import { REPO_URL } from "./NavBar";

// Headline numbers from real OpenFOAM runs (see the Results page for the full table).
const stats = [
  { value: "+0.3 %", label: "Nu against the exact 48/11 solution, laminar pipe" },
  { value: "< 0.1 %", label: "grid-convergence index, turbulent pipe" },
  { value: "±19.9 %", label: "model-form uncertainty exposed by the closure ensemble" },
  { value: "10 / 10", label: "qualification tasks passed, including 3 negative controls" },
];

const builtOn = [
  { name: "OpenFOAM", icon: "fa-solid fa-water", note: "RANS heat transfer" },
  { name: "FESTIM", icon: "fa-solid fa-atom", note: "tritium transport" },
  { name: "LangGraph", icon: "fa-solid fa-diagram-project", note: "workflow graph" },
  { name: "Pydantic", icon: "fa-solid fa-shield-halved", note: "typed contracts" },
  { name: "emcee", icon: "fa-solid fa-dice", note: "Bayesian calibration" },
  { name: "SALib", icon: "fa-solid fa-chart-simple", note: "Sobol sensitivity" },
  { name: "Docker", icon: "fa-brands fa-docker", note: "solver containers" },
  { name: "SLURM", icon: "fa-solid fa-server", note: "HPC executor" },
];

const HomePage = () => {
  const picRef = useRef(null);
  const [activeIndex, setActiveIndex] = useState(null);

  const scrollToRef = (ref) => {
    const yOffset = -80; // keep the sticky header from covering the section
    const y = ref.current.getBoundingClientRect().top + window.pageYOffset + yOffset;
    window.scrollTo({ top: y, behavior: "smooth" });
  };

  const sections = [
    {
      photo: workflowImg,
      title: "What NuAgent does",
      paragraphs: [
        "NuAgent sets up, runs, monitors, verifies, validates and calibrates convective heat-transfer and transport simulations: turbine-blade cooling passages, heat-exchanger and reactor coolant channels in OpenFOAM, and tritium transport in fusion materials with FESTIM. Then it writes the V&V report.",
        "The Nu is the Nusselt number, the quantity every case here is validated on. The physics is the same in an aircraft engine and in a reactor core.",
      ],
    },
    {
      photo: vvImg,
      title: "One idea",
      paragraphs: [
        "An AI agent that drives simulation codes must itself be qualifiable.",
        "Every decision the agent makes is bounded by typed schemas, every solver input is generated from validated templates, and every result is verified (grid-convergence index, exact solutions) and validated (correlations, experiments) before it is reported.",
        "The whole loop runs without an LLM in CI, so the LLM's contribution can be measured rather than assumed.",
      ],
    },
    {
      photo: closuresImg,
      title: "A workflow, not a chat",
      paragraphs: [
        "plan → review → build → run → monitor → postprocess → verify → model_form → validate → calibrate → UQ → critique → report",
        "A deterministic workflow backbone with typed contracts, an independent verifier that reviews every plan before compute is spent, and orchestrator–workers fan-out where sub-tasks are independent solver runs. Not a conversation between role-playing agents.",
      ],
    },
  ];

  return (
    <div>
      {/* --- Hero Section --- */}
      <div className="relative">
        <img
          className="w-full h-screen object-cover"
          src={heroImg}
          alt="Flow through a heated, rib-roughened cooling passage"
        />
        <div className="absolute inset-0 w-full max-w-6xl mx-auto flex flex-col items-center justify-center text-center px-4">
          <div className="text-brand-700 text-2xl md:text-4xl font-sans font-medium max-w-[600px]">
            <div className="shadow-lg bg-[rgba(245,245,245,0.95)] rounded-lg p-6">
              Verified, validated, calibrated:{" "}
              <span className="text-stone-800">simulations driven by an agent you can qualify.</span>
            </div>
            <p className="mt-4 text-base md:text-lg font-lato font-normal text-brand-100">
              An open-source agentic V&amp;V workflow for convective heat transfer (OpenFOAM) and
              tritium transport (FESTIM). Every number it reports carries a grid-convergence index
              and a reference band.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center mt-4">
              <button
                className="border-2 border-accent-500 text-xl font-medium px-6 py-2 bg-[rgba(245,245,245,0.85)] rounded-full hover:bg-white transition"
                onClick={() => scrollToRef(picRef)}
              >
                Learn More
              </button>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xl font-medium px-6 py-2 rounded-full bg-accent-500 text-white hover:bg-accent-600 transition"
              >
                <i className="fa-brands fa-github mr-2"></i>View on GitHub
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* --- Description Sections (full-bleed image with a floating card) --- */}
      {sections.map((section, index) => (
        <section className="relative" key={index}>
          <img
            className="w-full h-screen object-cover"
            src={section.photo}
            ref={index === 0 ? picRef : null}
            alt={section.title}
          />
          <div
            className={`absolute inset-0 flex items-center ${
              index % 2 === 0 ? "justify-end" : "justify-start"
            } p-4`}
          >
            <div
              className={`
                shadow-lg text-black text-sm md:text-lg font-lato font-medium max-w-[460px]
                bg-[rgba(245,245,245,0.9)] rounded-lg p-5 space-y-3
                transform transition-transform duration-300
                ${activeIndex === index ? "scale-105 z-30" : "scale-100"}
                cursor-pointer mt-64 md:mt-0
              `}
              onClick={() => setActiveIndex(activeIndex === index ? null : index)}
            >
              <h2 className="font-serif_title text-2xl md:text-3xl text-brand-700">{section.title}</h2>
              {section.paragraphs.map((para, idx) => (
                <p
                  key={idx}
                  className={idx === 0 && index === 2 ? "font-mono text-xs md:text-sm text-brand-800" : ""}
                >
                  {para}
                </p>
              ))}
            </div>
          </div>
        </section>
      ))}

      {/* --- Headline numbers --- */}
      <div className="bg-brand-700 text-white py-12">
        <div className="max-w-6xl mx-auto px-4 grid grid-cols-2 md:grid-cols-4 gap-6">
          {stats.map((s) => (
            <div key={s.label} className="text-center">
              <div className="font-serif_title text-4xl md:text-5xl text-accent-400">{s.value}</div>
              <div className="font-lato text-sm md:text-base text-brand-100 mt-2">{s.label}</div>
            </div>
          ))}
        </div>
        <p className="text-center font-lato text-xs text-brand-200 mt-8 px-4">
          Every result on this site was produced with the deterministic rules policy, i.e. with zero LLM tokens.
        </p>
      </div>

      {/* --- Built-on Section --- */}
      <div className="bg-brand-50 py-10">
        <div className="text-brand-700 text-3xl md:text-4xl font-serif_title font-medium max-w-[450px] p-10">
          Built on:
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-4 px-4 max-w-6xl mx-auto">
          {builtOn.map((b) => (
            <div
              key={b.name}
              className="flex flex-col items-center justify-center p-4 bg-white rounded-lg shadow hover:scale-105 transition-transform duration-300"
            >
              <i className={`${b.icon} text-4xl text-brand-600`}></i>
              <div className="font-sans font-semibold text-stone-800 mt-2">{b.name}</div>
              <div className="font-lato text-xs text-stone-500">{b.note}</div>
            </div>
          ))}
        </div>
      </div>

      {/* --- Call to action --- */}
      <div className="py-12 px-4 text-center">
        <h2 className="font-serif_title text-3xl text-brand-700">Run your first case in five seconds.</h2>
        <p className="font-lato text-stone-600 mt-2 max-w-2xl mx-auto">
          The mock solver exercises the entire graph, the retry logic, the GCI arithmetic and the report
          without OpenFOAM installed.
        </p>
        <Link
          to="/GetStarted"
          className="inline-block mt-6 px-6 py-2 rounded-full border-2 border-brand-700 text-brand-700 text-lg font-medium hover:bg-brand-700 hover:text-white transition"
        >
          Get Started
        </Link>
      </div>
    </div>
  );
};

export default HomePage;
