# Launch report + September product update on the docs site — manifest and handover

Date: 2026-10-04 · Scope: **documentation site + one backend script + a
small frontend change (where /gallery opens).** No API, schema or version
change; the frontend image rebuild carries both the docs and the app change. Implements the sketch round of 3–4 October (`launch-report.html` v12,
`september-update.html`); the sketches were the spec, this is the port.

## What changed

- **A new sidebar group, _Product and development updates_,** between
  _Feedback_ and _The model_, with two pages:
  - **Product update: September 2026** (`/docs/updates/2026-09`) — the
    changelog page: Launched (8 entries), Fixed and improved in the first
    two weeks (5), What we are building next (9, numbered), Read next.
    Hand-written markdown around `<ChangelogEntry>` tags. One per month
    from now on.
  - **Launch report: the first twelve days** (`/docs/reports/2026-10-launch`)
    — the "wrapped" page: hero with four tiles, ten story cards (big number,
    chart, prose), footer. **Every figure is read from
    `docs-site/reports/data/2026-10-launch.json`**, written by the new
    backend script; the markdown holds prose with `{{ }}` interpolations
    and the two hand-picked lists (six quotes, the missing-station list).
  - Both end with the **sticky action dock** (Suggest a new route → `/proposal-builder`,
    Visit the gallery → `/gallery`, Provide feedback → `/docs/feedback`) and
    link each other. The update page's one in-text button, _Suggest a
    feature_, opens `/docs/feedback?topic=feature` with the category
    preselected (new topic in `GeneralFeedbackForm.vue`).
- **Nav:** _Costs_ → **Costs & revenues**; new entry **Updates** (→ the
  September page).
- **Sidebar renames to remove the "revenue" duplication** (it appeared in
  _The model_ twice and in the cost tree once): _Costs_ → **Costs &
  revenues**; _Demand and revenue_ → **Demand and fares**; _Views of costs
  and revenue_ → **Breakdown views**. The two model pages' H1 and
  frontmatter title follow (URLs and the `{#…}` anchors the app links to
  are unchanged). The model entries are now named for what you _set_, the
  cost tree for what comes out.
- **Backend script `scripts/crowdsourcing_report.py`** — the generator of
  the sketch round, refactored into the repo: reads the pgAdmin CSV
  (`--from-csv`) or runs the export itself (`--db`, through
  `adapters/db_pool`), filters on `--window`, computes every figure, the
  chart series, the corridor de-duplication and the map positions, and
  writes the edition JSON. `--emit-pgadmin-sql` regenerates the
  single-statement pgAdmin variant from the psql source;
  `--basemap-source` rebuilds the shared Europe basemap from a Natural
  Earth GeoJSON (committed once, ~100 KB, simplified to 0.8 px).
  Composition places come from `models.compositions.catalog.load_catalog()`
  — no more `comp_places.json`; country names from `pycountry`.
- **Export SQL** now lives in `backend/scripts/sql/`. One addition to
  `proposals_list`: `country_relations` (the served relations of
  `summary.py::country_relations`), so the "most-served country pair" is
  windowed like everything else.

## Second round (same day): gallery entry, new tabs, no underlines, city links

- **Where `/gallery` opens** (`frontend/src/lib/galleryEntry.ts`, `Gallery.vue`,
  `router/index.ts`, `ProposalWorkspace.vue`): the landing pitch stays the
  first screen only for someone entering the site itself (origin root →
  `/gallery`, or a reload of a plain `/gallery`). A link that **names a
  filter** (any query key beyond the always-present `tab/kind/sort/dir` —
  a station, city, country, range, scenario, `mine`, `src`, legacy `mode`)
  or carries **`#gallery`** opens scrolled to the search bar and the map,
  instantly, once the search bar is hydrated. The proposal page's _Gallery_
  pill now pushes `#gallery`; the router leaves that navigation's scroll to
  the gallery (it previously restored `{top: 0}`, i.e. the pitch). The hash
  is dropped from the address bar once read. Test:
  `lib/galleryEntry.test.ts` (3 cases).
- **Address bar already carries every filter and sort option** — nothing to
  add: `tab` (station/city/country) · `kind` (via/fromTo) · `a`, `b` (stop
  id, city OSM id or ISO code) · `sort`, `dir` · `src` · `mine=1` · ranges
  `km`, `h`, `kmh`, `stops` as `min-max` (absent = typical-night-train
  preset, `typical=0` = none) · `scenario`. Legacy `?mode=…&from/to/station/
  country/relFrom/relTo` still resolves. City filtering is
  `/gallery?tab=city&kind=via&a=<city_osm_id>`.
- **Report links by city**: `stop_coords` in the export now carries
  `city_osm_id`; with it the script links the top city pairs as
  `tab=city&kind=fromTo&a=…&b=…` (whole cities, both directions). The
  3 October export predates the column, so the committed JSON still links
  the two centre stations — the next export switches it automatically.
- **Docs → tool links open a new tab** (dock, map, bars; `rel="noopener"`),
  and the dock's _Visit the gallery_ is `/gallery#gallery`.
- **No underlined links on the report page** (`.report-page .vp-doc a`);
  the chart and map links never had any affordance but the row itself.

## Figures: the 4 October export

The committed JSON is built from the export of **4 October 2026, 16:32**,
window **22 September – 3 October** (the last full day; 4 October had four
proposals by then). Headline: 451 people, 1 321 proposals by 449 people,
94 % cross a border, 924 typical night trains → 531 city pairs → about
319 corridors, Paris – Praha 15× by 12 people, 427 M train-km, 1 047 → 553
trainsets, median 23.1 €/train-km, 115 likes, 28 comments, 37 pieces of
feedback. Country pairs are now the served relations inside the window
(Germany–France 145, Germany–Sweden 108, France–Italy 81), seat-km the
summaries' own `available_place_km_per_year`, and the city-pair bars link
the gallery's city tab (`tab=city&kind=fromTo&a=<osm>&b=<osm>`). To end the
window on another day: re-run with `--window 2026-09-22..<day>` on the same
CSV; the titles say "twelve days" in two places (`config.ts` sidebar,
page frontmatter) and would need the word changed.

## Figures: what moved since the sketch

The gallery's _typical night trains_ preset was widened on 2026-10-03/04 to
**7–21 h** (from 7–16 h) at **≥ 50 km/h** (`frontend/src/lib/typicalNightTrain.ts`),
and the report must state the gallery's bound. With the 3 October export
that changes the sieve: **914 typical night trains (was 629), 525 distinct
city pairs (379), about 318 corridors (249)**; top pair Paris – Praha 15×
by 12 people (unchanged); supply 423 M train-km, 324 397 departures,
124 bn seat-km, 1 036 → 548 trainsets, median 23.1 €/train-km. The prose
("are we nearly done? No") still carries, but the "about 318 corridors
against the paper's 300" line deserves a read before publishing — if you
would rather report with the paper's 16 h, change `ENVELOPE_H` in the
script _and_ the gallery preset together, never one of them.

Other deltas, all from counting inside the window rather than all-time:
likes 111 (sketch: 117), feedback 37 (41), stations 958 (960). The country
pair ranking is still all-time (150 / 110 / 81) because the 3 October
export predates the new `country_relations` column — **re-run the export
once** and the script switches to windowed figures by itself (it logs a
warning until then). The same re-run brings `available_place_km_per_year`
per proposal; until then seat-km is train-km × catalogue places.

## Updates by file

| File                                                                 | Change                                                                                                                                                                                                                                         |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **new** `backend/scripts/crowdsourcing_report.py`                    | The report script (see above). Ruff-clean; stdlib + `pycountry` + the compositions catalogue; `psycopg2` only on `--db`.                                                                                                                         |
| **new** `backend/scripts/sql/crowdsourcing_report_export.sql`        | psql source of the export (46 sections, `\echo '## name'` markers), `country_relations` added to `proposals_list`.                                                                                                                              |
| **new** `backend/scripts/sql/crowdsourcing_report_export_pgadmin.sql` | Generated single-statement variant — the one to paste into pgAdmin. Regenerate after any edit of the psql file.                                                                                                                                 |
| **new** `docs-site/reports/2026-10-launch.md`                        | The launch report page (`pageClass: report-page`, `aside: false`).                                                                                                                                                                              |
| **new** `docs-site/reports/data/2026-10-launch.json`                 | Figures of the 22 Sep – 3 Oct window from the 4 Oct 16:32 export.                                                                                                                                                                               |
| **new** `docs-site/reports/data/europe-basemap.json`                 | Projected country outlines (Natural Earth 50 m, public domain), shared by all editions.                                                                                                                                                         |
| **new** `docs-site/reports/README.md`                                | Conventions, component reference, data pipeline, how to add an edition. Excluded from the build (`srcExclude`).                                                                                                                                 |
| **new** `docs-site/updates/2026-09.md`                               | The September product update.                                                                                                                                                                                                                   |
| **new** `docs-site/.vitepress/theme/components/ReportCard.vue`       | Story card: kicker / big / title / prose slot / `#viz` slot; `wide`.                                                                                                                                                                            |
| **new** `…/ReportTiles.vue`, `…/ReportQuotes.vue`, `…/ReportChips.vue` | Number tiles, quotes by route, station chips.                                                                                                                                                                                                  |
| **new** `…/ReportBars.vue`                                           | Inline-SVG bars, horizontal (rows, optional gallery link) and vertical; re-measures its width after mount so labels stay 12 px on a phone, stacks label-over-bar below 440 px.                                                                   |
| **new** `…/ReportMap.vue`                                            | Europe map: shaded countries and station bubbles, every one a gallery link (new `?tab&kind&a&b` query shape).                                                                                                                                   |
| **new** `…/ChangelogEntry.vue`                                       | Tagged entry (Launched / Shipped / Fixed / Improved / Next with running number) inside `<ul class="changelog">`.                                                                                                                                 |
| **new** `…/ActionDock.vue`                                           | Fixed bottom action bar + spacer; offsets itself past the desktop sidebar.                                                                                                                                                                      |
| **new** `docs-site/.vitepress/theme/lib/format.ts`                   | `formatNumber` / `formatPercent` / `formatCompact` (narrow no-break-space thousands, "50 %").                                                                                                                                                   |
| `docs-site/.vitepress/theme/index.ts`                                | Registers the eight components globally.                                                                                                                                                                                                        |
| `docs-site/.vitepress/theme/custom.css`                              | Page-level rules: `.report-page` content width 960 px, hero, update-page meta/callout/button styles.                                                                                                                                             |
| `docs-site/.vitepress/theme/components/GeneralFeedbackForm.vue`      | `?topic=feature` → category _Feature request_, sub-category free text, lead sentence.                                                                                                                                                           |
| `docs-site/.vitepress/config.ts`                                     | Sidebar group, nav entries, the three renames, `srcExclude` for README files.                                                                                                                                                                   |
| `docs-site/demand.md`, `docs-site/views.md`                          | Title/H1 renamed (_Demand and fares_, _Breakdown views_); body unchanged.                                                                                                                                                                       |
| `docs-site/.prettierignore`, `.pre-commit-config.yaml`               | `reports/data/` is script output — prettier leaves it alone.                                                                                                                                                                                    |
| `AGENTS.md`, `docs/DEPLOY_HANDOVER.md` §25                           | Key-files row for the script; deploy note (frontend image only).                                                                                                                                                                                |
| **new** `frontend/src/lib/galleryEntry.ts` (+ `.test.ts`)            | `GALLERY_HASH`, `queryNamesAFilter`, `entersAtGallery` — the rule for where /gallery opens.                                                                                                                                                     |
| `frontend/src/components/Gallery.vue`                                | `scrollToGallery(behavior)`; `openAtGalleryIfLinked()` after hydration; `onActivated` honours `#gallery` and strips it.                                                                                                                         |
| `frontend/src/components/ProposalWorkspace.vue`, `router/index.ts`    | Back pill pushes `#gallery`; `scrollBehavior` returns `false` for it.                                                                                                                                                                           |

## Before the mail goes out — David

1. **Read the two Fixed/Improved texts you supplied** (gallery loading,
   mobile devices) on the update page; I reworded _Gallery search and
   filters_ and _Map display_ to the 4 October state (search tabs,
   distribution panel, hover highlights).
2. **Decide on the envelope** (7–21 h, see above) and whether to re-export
   on a later date; both are one command away.
3. Gallery links open in a new tab and land on the gallery proper; the
   city-pair bars filter the gallery by city (both directions).

## Deployment handover

Frontend image only (the docs bundle and the app change are built into
it). No environment variable, no migration, no data task. The member mail links to
`/docs/reports/2026-10-launch` and `/docs/updates/2026-09` — deploy first.

## Re-running the report

```powershell
# 1. pgAdmin → Query Tool on production → paste backend\scripts\sql\crowdsourcing_report_export_pgadmin.sql → F5 → save grid as CSV
# 2. from the repo root
cd backend
uv run python scripts\crowdsourcing_report.py --from-csv C:\path\to\export.csv --edition 2026-10-launch --window 2026-09-22..2026-10-02
cd ..\docs-site
npm run ci
```

Against the dev stack the export can also run directly:
`uv run python scripts\crowdsourcing_report.py --db --edition … --window …`.

## Verification (this session)

Frontend (Node 22): `eslint` clean · `prettier --check` clean · `vue-tsc
--noEmit` clean · `vitest run` **435 passed** (41 files, 3 new) ·
`vite build` OK. The scroll itself was not exercised against a running API
here — check once on staging: enter at the root (pitch), open
`/gallery?tab=country&kind=via&a=DE` (gallery), press _Gallery_ on a
proposal (gallery), reload a plain `/gallery` (pitch).

Docs site (Node 22, VitePress 1.6.4): `prettier --check` clean on every
touched file · `vitepress build` OK with the dead-link check on · both
pages rendered headless at 1440 px and 390 px, no console errors, no
horizontal overflow; map, bars, tiles, dock and the two-row phone dock
checked by eye. Backend: `ruff format --check` + `ruff check` clean on the
script; `--emit-pgadmin-sql` reproduces the hand-verified pgAdmin file of
the sketch round byte-for-byte apart from its header; `--from-csv` run on
the 3 October export. Not run here: `--db` (no database in this
environment) — it wraps each section exactly as the pgAdmin variant does,
so the first local run is the test.

## Rollout

From the repository root (Windows PowerShell):

```powershell
Expand-Archive -Path .\launch-report-docs.zip -DestinationPath . -Force; Remove-Item .\launch-report-docs.zip
cd docs-site; npm run ci; cd ..
cd backend; uv run ruff format --check scripts\crowdsourcing_report.py; uv run ruff check scripts\crowdsourcing_report.py; cd ..
cd frontend; npm run ci; npx vite build; cd ..
```

## Commit split

```powershell
git add backend\scripts\crowdsourcing_report.py backend\scripts\sql\crowdsourcing_report_export.sql backend\scripts\sql\crowdsourcing_report_export_pgadmin.sql
git commit -m "feat(scripts): crowdsourcing report generator and export SQL" -m "Figures, chart series, corridor dedup and map positions for the docs-site launch report; pgAdmin variant generated from the psql source." -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01Vj2ut8KHNkNvk8U516cJ7w"
git add docs-site\reports docs-site\updates docs-site\.vitepress docs-site\.prettierignore docs-site\demand.md docs-site\views.md .pre-commit-config.yaml
git commit -m "docs(site): launch report, September product update, Costs & revenues" -m "New sidebar group Product and development updates with the two pages, Report*/ChangelogEntry/ActionDock components, feedback topic feature; Costs renamed to Costs & revenues, Demand and fares, Breakdown views." -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01Vj2ut8KHNkNvk8U516cJ7w"
git add frontend\src\lib\galleryEntry.ts frontend\src\lib\galleryEntry.test.ts frontend\src\components\Gallery.vue frontend\src\components\ProposalWorkspace.vue frontend\src\router\index.ts
git commit -m "feat(gallery): open at the gallery proper when linked with a filter or #gallery" -m "A plain entry at the site root keeps the landing pitch; filter links, the docs site's buttons and the proposal page's back pill land on the search bar and map." -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01Vj2ut8KHNkNvk8U516cJ7w"
git add AGENTS.md docs\DEPLOY_HANDOVER.md docs\2026-10-04_launch_report_manifest.md
git commit -m "docs: launch report manifest, deploy note, key files" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01Vj2ut8KHNkNvk8U516cJ7w"
git status --short
```
