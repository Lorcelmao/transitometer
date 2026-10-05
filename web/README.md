# Transitometer web (Next.js showcase)

A static Next.js site that presents the **validated snapshot** of the Spark pipeline's Gold tables. It is the public showcase; the Streamlit app (`src/transitometer/app/`) is the analyst console. Both read the same numbers from the same Python views.

## The one rule: no metric logic here

Every value, threshold, ranking, pass or fail verdict, label and definition is computed in Python (`src/transitometer/serve/views.py`, formatted by `serve/format.py`). `python tasks.py web-data` exports the views as JSON to `public/data/`. This app only lays them out: no sorting or filtering of metric rows, no thresholds, no arithmetic on metric values. Chart axes and tooltips use `src/lib/format.ts`, which reproduces Python's rounding exactly and is tested against the same vectors (`showcase/contract/format-cases.json`).

## Data flow

```
python tasks.py snapshot   # validated Spark Gold tables -> showcase/data/ (+ evidence, manifest)
python tasks.py web-data   # views over the snapshot -> web/public/data/*.json (+ parity file)
npm run build              # static export -> web/out/ (every JSON file schema-checked)
```

- The JSON in `public/data/` is committed. CI regenerates it from the snapshot and fails on any byte difference (`tests/test_web_export.py`).
- `src/data/schemas.ts` is the contract with the export (zod). A missing field, a retyped value or a schema-version change fails the build.
- The file for each page's default filters is built into the HTML. Other modes and days, and stop routes, are fetched from `/data/` when chosen, and are validated against the same schemas.

## Commands

| Command | What it does |
|---|---|
| `npm ci` | install (Node 22, see `.nvmrc`) |
| `npm run dev` | local development server |
| `npm run build` | static export to `out/` |
| `npm run lint`, `npm run typecheck`, `npm test` | ESLint, TypeScript, Vitest |
| `npm run e2e` | Playwright against the built `out/`: cross-frontend parity, axe accessibility (375 and 1280 px), keyboard use, navigation and deep links, the Content-Security-Policy |
| `npm run lhci` | Lighthouse CI budgets (`lighthouserc.json`) |

`npx playwright install chromium` once before the first `e2e` run.

## Deploying (Vercel Hobby)

- Vercel project with **root directory `web`**, framework Next.js. No environment variables or secrets.
- The analyst console link points to https://transitometer.streamlit.app/; set `NEXT_PUBLIC_STREAMLIT_URL` to point it elsewhere.
- `vercel.json` sets the security headers and skips builds when neither `web/` nor `showcase/` changed.
- The site is plain static files, so `out/` also deploys unchanged to Cloudflare Pages or GitHub Pages.

## Known issue (local Windows builds only)

Next.js 16 builds on Windows write route-prefetch files into nested folders ([vercel/next.js#92339](https://github.com/vercel/next.js/issues/92339)). Link prefetching then returns 404 in a local preview; navigation still works. Linux builds (CI, Vercel) are not affected.

## Design

The editorial design system (tokens, type, charts, accessibility rules) is specified in `plans/261003-1210-nextjs-showcase-frontend/design-system.md`, and implemented in `src/app/globals.css` and `src/charts/theme.ts`.
