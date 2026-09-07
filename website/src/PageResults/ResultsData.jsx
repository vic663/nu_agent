import laminarGci from "../assets/figures/laminar_gci.png";
import laminarProfiles from "../assets/figures/laminar_profiles.png";
import turbulentProfiles from "../assets/figures/turbulent_profiles.png";
import turbulentGci from "../assets/figures/turbulent_gci.png";
import ribbedProfiles from "../assets/figures/ribbed_profiles.png";
import ribbedGci from "../assets/figures/ribbed_gci.png";
import modelForm from "../assets/figures/turbulent_model_form.png";

// Numbers are the "Results so far" table of the NuAgent README (real OpenFOAM runs, single core).
// tone: pass | fail | warn | info
const ResultsData = [
  {
    id: 1,
    group: "verification",
    title: "Laminar pipe, Re = 200",
    subtitle: "Nusselt number, exact solution",
    image: laminarGci,
    rows: [
      ["NuAgent", "Nu = 4.376"],
      ["Reference", "48/11 = 4.364 (exact)"],
      ["Deviation", "+0.3 %"],
      ["Grid convergence", "GCI 0.02 %"],
    ],
    verdict: "PASS",
    tone: "pass",
  },
  {
    id: 2,
    group: "verification",
    title: "Laminar pipe, Re = 200",
    subtitle: "Friction factor, exact solution",
    image: laminarProfiles,
    rows: [
      ["NuAgent", "f = 0.3203"],
      ["Reference", "64/Re = 0.3200 (exact)"],
      ["Deviation", "+0.1 %"],
      ["Grid convergence", "p = 1.92, GCI 0.15 %"],
    ],
    verdict: "PASS",
    tone: "pass",
  },
  {
    id: 3,
    group: "validation",
    title: "Turbulent pipe, Re = 20 000",
    subtitle: "Water, k-omega SST, wall-resolved (y+ about 1). Nusselt number.",
    image: turbulentProfiles,
    rows: [
      ["NuAgent", "Nu = 124.6"],
      ["Gnielinski (±10 %)", "137.8, deviation -9.6 %"],
      ["Dittus-Boelter (±25 %)", "128.4, deviation -3.0 %"],
      ["Grid convergence", "GCI below 0.1 %"],
    ],
    verdict: "PASS",
    tone: "pass",
    note: "Shows the well-known 5 to 10 % under-prediction of wall-resolved SST with Pr_t = 0.85.",
  },
  {
    id: 4,
    group: "validation",
    title: "Turbulent pipe, Re = 20 000",
    subtitle: "Water, k-omega SST. Friction factor.",
    image: turbulentGci,
    rows: [
      ["NuAgent", "f = 0.02416"],
      ["Petukhov (±5 %)", "0.02615, deviation -7.6 %"],
      ["Grid convergence", "GCI 0.9 %"],
    ],
    verdict: "WITHIN 10 % TOLERANCE",
    tone: "warn",
    note: "Inside the tolerance set in the spec, outside the correlation's own ±5 % band.",
  },
  {
    id: 5,
    group: "validation",
    title: "Rib-roughened tube, Re = 20 000",
    subtitle: "Air, e/D = 0.04, p/e = 10, low-Re k-epsilon. Nusselt number.",
    image: ribbedProfiles,
    rows: [
      ["NuAgent", "Nu = 112.9 (Nu/Nu0 = 2.18)"],
      ["Webb et al. 1971 (±15 %)", "141.9, deviation -20.4 %"],
      ["Base-temperature definition", "-13 %"],
      ["Grid convergence", "p = 2.1, GCI 2.5 %"],
    ],
    verdict: "FAIL",
    tone: "fail",
    note: "The well-documented RANS heat-transfer deficit in separated regions; the workflow reports it instead of hiding it.",
  },
  {
    id: 6,
    group: "validation",
    title: "Rib-roughened tube, Re = 20 000",
    subtitle: "Air, low-Re k-epsilon. Friction factor.",
    image: ribbedGci,
    rows: [
      ["NuAgent", "f = 0.2313 (f/f0 = 8.85)"],
      ["Webb et al. 1971 (±10 %)", "0.2392, deviation -3.3 %"],
      ["Grid convergence", "not asymptotic (p = 0.25)"],
      ["Two finest grids", "2.4 % change"],
    ],
    verdict: "PASS, GRID NOT ASYMPTOTIC",
    tone: "warn",
  },
  {
    id: 7,
    group: "ensemble",
    title: "Turbulent pipe, closure ensemble",
    subtitle: "SST (y+ about 1), k-epsilon and realizable k-epsilon with Jayatilleke wall functions (y+ about 38), Launder-Sharma (y+ about 1). Nusselt number.",
    image: modelForm,
    rows: [
      ["NuAgent", "124.6 / 132.3 / 130.0 / 174.2"],
      ["Gnielinski (±10 %)", "137.8"],
      ["Deviation", "-9.6 / -4.0 / -5.7 / +26.4 %"],
      ["Model form vs GCI", "±19.9 % vs below 0.1 %"],
    ],
    verdict: "MODEL FORM DOMINATES",
    tone: "info",
  },
  {
    id: 8,
    group: "ensemble",
    title: "Turbulent pipe, closure ensemble",
    subtitle: "Same four closures. Friction factor.",
    image: modelForm,
    rows: [
      ["NuAgent", "0.02416 / 0.02467 / 0.02366 / 0.03037"],
      ["Petukhov (±5 %)", "0.02615"],
      ["Deviation", "-7.6 / -5.7 / -9.5 / +16.1 %"],
      ["Model form vs GCI", "±13.9 % vs 0.9 %"],
    ],
    verdict: "MODEL FORM DOMINATES",
    tone: "info",
  },
  {
    id: 9,
    group: "qualification",
    title: "Agent qualification suite",
    subtitle: "nuagent eval, rules policy, mock backend",
    icon: "fa-solid fa-vial-circle-check",
    rows: [
      ["Tasks", "10"],
      ["Must succeed", "7 / 7"],
      ["Must be refused", "3 / 3 negative controls"],
      ["Behaved correctly", "10 / 10"],
    ],
    verdict: "10 / 10",
    tone: "pass",
    note: "The negative controls include a k-omega SST run on a ribbed passage that converges cleanly with Nu and f 50 % below Webb: execution succeeds, validation must fail.",
  },
  {
    id: 10,
    group: "qualification",
    title: "Consistency checks",
    subtitle: "Reported with every run",
    icon: "fa-solid fa-scale-balanced",
    rows: [
      ["Energy balance, smooth pipes", "0.06 to 0.1 %"],
      ["Energy balance, ribbed tube", "3 %"],
      ["Mass balance", "0.13 %"],
      ["f from dp/dx vs wall shear", "within 2 %"],
    ],
    verdict: "PASS",
    tone: "pass",
  },
];

export default ResultsData;
