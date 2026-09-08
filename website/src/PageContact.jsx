import contactBanner from "./assets/contact_banner.svg";
import CodeBlock from "./PageGetStarted/CodeBlock";
import { REPO_URL } from "./NavBar";

// Fill this in to show an e-mail line on the contact page (left empty on purpose).
const CONTACT_EMAIL = "";

const bibtex = `@software{ren2026nuagent,
  author  = {Ren, Baihua},
  title   = {NuAgent: an agentic workflow for verified, validated and calibrated
             convective heat-transfer and transport simulations},
  version = {0.1.4},
  year    = {2026},
  url     = {https://github.com/vic663/nu_agent},
  license = {MIT}
}`;

const contributing = `pip install -e ".[all]"
ruff check src tests && ruff format --check src tests
pytest -q                        # solver-free tests
nuagent eval evals/tasks         # agent qualification suite on the mock backend`;

const PageContact = () => {
  return (
    <>
      <div>
        <img className="w-full object-cover max-h-[360px]" src={contactBanner} alt="Contact banner" />
      </div>

      <div className="flex flex-col-reverse md:flex-row justify-between p-6 md:p-12 gap-8 max-w-6xl mx-auto">
        <div className="flex flex-col text-3xl font-lato text-brand-700 p-4 md:p-8 max-w-lg">
          <h2 className="font-serif_title">Contact us:</h2>

          <div className="mt-4 text-lg md:text-xl text-stone-800 font-lato space-y-2">
            <p className="font-semibold">Baihua Ren</p>
            <p>Author and maintainer of NuAgent</p>
            <a
              href={REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="block hover:text-brand-500"
            >
              <i className="fa-brands fa-github w-7"></i>github.com/vic663/nu_agent
            </a>
            <a
              href={`${REPO_URL}/issues`}
              target="_blank"
              rel="noopener noreferrer"
              className="block hover:text-brand-500"
            >
              <i className="fa-solid fa-circle-question w-7"></i>Questions and bug reports: GitHub issues
            </a>
            {CONTACT_EMAIL && (
              <a href={`mailto:${CONTACT_EMAIL}`} className="block hover:text-brand-500">
                <i className="fa-solid fa-envelope w-7"></i>E-mail: {CONTACT_EMAIL}
              </a>
            )}
            <p className="text-base text-stone-500 pt-2">
              MIT License. If you use NuAgent in your research, please cite it.
            </p>
          </div>

          <div className="mt-8 text-base">
            <h3 className="font-serif_title text-2xl text-brand-700 mb-2">Contributing</h3>
            <p className="text-sm text-stone-600 mb-2">
              Development set-up from CONTRIBUTING.md. Nothing in the backends or executors may import an
              LLM library, and every report must be reproducible from result.json and decisions.jsonl.
            </p>
            <CodeBlock code={contributing} />
          </div>
        </div>

        <div className="w-full md:w-1/2">
          <div className="rounded-lg overflow-hidden shadow-lg border border-stone-200 bg-white p-4">
            <h3 className="font-serif_title text-2xl text-brand-700 mb-3">Cite NuAgent</h3>
            <CodeBlock code={bibtex} label="BibTeX" />
            <p className="text-sm text-stone-500 mt-3">
              A machine-readable citation file (CITATION.cff) ships with the repository.
            </p>
          </div>
        </div>
      </div>
    </>
  );
};

export default PageContact;
