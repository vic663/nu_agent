# NuAgent website

Public site for [NuAgent](https://github.com/vic663/nuagent), the agentic V&V workflow for convective
heat-transfer (OpenFOAM) and tritium-transport (FESTIM) simulations.

Built with **React 19 + Vite 6**, styled with **Tailwind CSS 3**, routed with **React Router 7**. The
project layout and page structure follow the
[MHEF website](https://github.com/Ericalyhan94/MHEF_website): a top `NavBar`, a set of page components,
and a `NavBar2` footer.

## Run it

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # production bundle in dist/
npm run preview    # serve the production bundle locally
npm run lint

npm run build:pages    # the same bundle with the GitHub Pages base path /nuagent/
npm run preview:pages  # serve that build at http://localhost:4173/nuagent/
```

Node.js 20 or newer is required (React Router 7 sets that floor; the deploy workflow uses 22).

## Pages

| Route | File | Content |
|---|---|---|
| `/` | `src/HomePage.jsx` | full-screen hero, three full-bleed sections with floating cards, headline numbers, "built on" grid, call to action |
| `/About` | `src/PageAbout.jsx` | what NuAgent is, the six design principles, honest status of every capability |
| `/Capabilities` | `src/PageCapabilities.jsx` | one card per workflow node, then backends, executors, policies and the eval suite (`PageCapabilities/CapabilityData.jsx`) |
| `/Results` | `src/PageResults.jsx` | card grid of the real OpenFOAM results (`PageResults/ResultsData.jsx`) |
| `/GetStarted` | `src/PageGetStarted.jsx` | install, the six quick-start commands, LLM options, documentation links |
| `/Contact` | `src/PageContact.jsx` | author, repository links, BibTeX citation, contributing |

## Editing content

- **Text and numbers** live in plain arrays at the top of each page file, or in the `*Data.jsx` files.
  Results mirror the "Results so far" table of the NuAgent README; update both together.
- **Figures** under `src/assets/figures/` are copied from `nuagent/docs/examples/*/figures/`. Re-copy them
  after regenerating a report.
- **Artwork** (`hero.svg`, `section_*.svg`, `*_banner.svg`, `logo.svg`) are hand-written SVGs; replace
  them with photographs if you have them, the components only need an image URL.
- **Colours**: the whole palette is the `brand` and `accent` entries in `tailwind.config.js`.
- **Fonts**: DM Serif Display (titles), Merriweather Sans, Lato and JetBrains Mono, loaded from Google
  Fonts in `index.html`. Icons are Font Awesome 6 Free from cdnjs.
- **Contact e-mail**: set `CONTACT_EMAIL` in `src/PageContact.jsx`.

## Deploy

**GitHub Pages (the live site).** `.github/workflows/pages.yml` at the repository root runs on every push
to `main` that touches `website/`: it installs, lints, builds with `npm run build:pages` (which sets the
Vite base path to `/nuagent/`), copies `index.html` to `404.html` so deep links survive Pages' lack of an
SPA rewrite, and publishes `dist/` to https://vic663.github.io/nuagent/. One-time setup, best done
**before** the first push that contains `website/`: Settings, Pages, Build and deployment, Source:
**GitHub Actions**. If the workflow ran before Pages was enabled, its deploy job fails; enable Pages, then
re-run the workflow from the Actions tab (it has a manual "Run workflow" trigger). The router reads the base
path from `import.meta.env.BASE_URL`, so the same code runs at `/` locally and at `/nuagent/` on Pages.

**Anywhere else.** `npm run build` produces a root-based `dist/`. `vercel.json` rewrites every path to `/`
so client-side routing works on Vercel; on any other static host configure a single-page-app fallback to
`index.html`.
