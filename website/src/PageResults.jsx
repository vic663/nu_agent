import ResultItem from "./PageResults/ResultItem";
import ResultsData from "./PageResults/ResultsData";
import { REPO_URL } from "./NavBar";

const groups = [
  { key: "verification", heading: "Verification against exact solutions:" },
  { key: "validation", heading: "Validation against correlations:" },
  { key: "ensemble", heading: "Closure ensemble (model-form uncertainty):" },
  { key: "qualification", heading: "Qualification and consistency:" },
];

const PageResults = () => {
  return (
    <div className="grid gap-12 p-6 max-w-6xl mx-auto">
      <div>
        <h1 className="text-4xl font-bold text-brand-700 mb-2 font-serif_title">Results</h1>
        <p className="font-lato text-stone-600">
          Real OpenFOAM runs on a single core, produced by the deterministic rules policy with zero LLM
          tokens. Each card shows the computed value, the reference with its stated uncertainty, the
          deviation, and the grid-convergence result.
        </p>
      </div>

      {groups.map((g) => (
        <div key={g.key}>
          <h1 className="text-3xl md:text-4xl font-bold text-brand-700 mb-8 font-serif_title">{g.heading}</h1>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {ResultsData.filter((item) => item.group === g.key).map((item) => (
              <ResultItem item={item} key={item.id} />
            ))}
          </div>
        </div>
      ))}

      <div className="bg-brand-50 rounded-lg p-6 md:p-8 font-lato text-stone-700 space-y-4 border border-brand-100">
        <h2 className="font-serif_title text-2xl text-brand-700">Where the workflow earns its keep</h2>
        <p>
          With the default k-omega SST closure the ribbed-tube run converges cleanly but predicts a single
          recirculation filling the whole inter-rib gap, giving f 55 % and Nu 65 % below the Webb correlation.
          The physics-aware critique flags no reattachment between ribs and recommends the k-epsilon family.
          Across the tested cases, k–ε-family closures restore reattachment at x/e ≈ 3–5; the final twelve-rib
          Launder–Sharma run gives x/e = 3.3, and the best case brings f within 4 %. An execution-success metric
          would have reported the SST run as a success.
        </p>
        <p>
          The closure ensemble puts a number on the model-form uncertainty that a single run hides. For the
          smooth turbulent pipe three closures agree with Gnielinski within its band while Launder-Sharma
          over-predicts both Nu and f by 16 to 26 %; for the ribbed tube the same model is the one that reproduces
          the flow topology and SST is the outlier. Closure trust is case-dependent, which is why the workflow
          measures it instead of choosing a favourite.
        </p>
        <a
          href={`${REPO_URL}/tree/main/docs/examples`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block text-brand-700 font-semibold hover:text-brand-500"
        >
          <i className="fa-solid fa-arrow-up-right-from-square mr-2"></i>
          Full generated reports with figures
        </a>
      </div>
    </div>
  );
};

export default PageResults;
