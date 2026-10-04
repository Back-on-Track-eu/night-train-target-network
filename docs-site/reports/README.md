# Reports and product updates

Maintainer notes for the two page families under _Product and development
updates_ in the sidebar. Not built as a page (`srcExclude` in
`.vitepress/config.ts`).

| Family         | Folder     | Cadence                                       | Shape                                                                                                     |
| -------------- | ---------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Report         | `reports/` | Per milestone (launch; later e.g. a month in) | Story cards, one big number and one chart each; every figure read from `reports/data/<edition>.json`      |
| Product update | `updates/` | Monthly, `updates/YYYY-MM.md`                 | Changelog: Launched / Shipped this month, Fixed and improved, What we are building next, Read next; prose |

Both end with `<ActionDock />` (suggest a route · visit the gallery · provide
feedback), fixed to the bottom of the viewport, which is why neither page
carries in-text buttons for those three. Every link into the tool (dock, map, bars) opens a **new tab** — the docs stay where the reader was, and VitePress's client router only leaves anchors with a `target` alone — and lands **on the gallery proper**, past the landing pitch: `/gallery#gallery`, or any `/gallery?…` link that names a filter (`frontend/src/lib/galleryEntry.ts`). Links in the report page carry no underline (`.report-page .vp-doc a` in `custom.css`). The only in-text button is _Suggest
a feature_ on the update page (`/feedback?topic=feature`, which preselects
the category in `GeneralFeedbackForm.vue`).

## Building blocks

Global components, registered in `.vitepress/theme/index.ts`:

| Component                     | Use                                                                                                                                                              |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ReportCard`                  | One story card: `kicker`, `big`, `title`, prose in the default slot, chart in `#viz`; `wide` for a full-row card                                                 |
| `ReportTiles`                 | Row of number tiles, `items: {value, label}[]` — values arrive formatted                                                                                         |
| `ReportBars`                  | Inline-SVG bars. `rows` (label \| bar \| value, optional `href`) or `direction="v"` with `values` + `labels`; `highlight`, `unit`, `percent-of`, `caption`       |
| `ReportMap`                   | Europe map: `basemap` (shared file) + `data` (the edition's `where.map`)                                                                                         |
| `ReportQuotes`, `ReportChips` | Comment quotes by route (never by author); station chips                                                                                                         |
| `ChangelogEntry`              | One update entry inside `<ul class="changelog">`: `tag` (Launched / Shipped / Fixed / Improved / Next), `title`, prose in the slot; `index` numbers a Next entry |
| `ActionDock`                  | The sticky action bar                                                                                                                                            |

Number formatting lives in `.vitepress/theme/lib/format.ts`
(`formatNumber`, `formatPercent`, `formatCompact`); pages import it
relatively (`../.vitepress/theme/lib/format`) and interpolate with
`{{ n(…) }}` in the prose.

Markdown gotchas in these pages: a component's opening tag must sit on one
line, surrounded by blank lines, for VitePress to render the markdown
inside it; consecutive component lines inside `<template #viz>` must have
no blank line between them; no backticks inside `{{ }}` in prose (markdown
sees inline code first) — put such expressions in `<script setup>`.

## Where the numbers come from

```
production DB ─ pgAdmin, backend/scripts/sql/crowdsourcing_report_export_pgadmin.sql ─▶ grid → CSV
CSV ─ uv run python scripts/crowdsourcing_report.py --from-csv <csv> --edition <e> --window <a>..<b> ─▶ reports/data/<e>.json
```

- The script owns `reports/data/` (prettier ignores it). Re-running with
  the same edition overwrites the JSON; the page re-renders, the prose stays.
- The window is inclusive and in the database's time zone; the proposal
  side is filtered on `created_at`, the usage side (request log) reaches
  back `REQUEST_LOG_RETENTION_DAYS` only.
- `reports/data/europe-basemap.json` is shared by every edition and
  rebuilt only with `--basemap-source <Natural Earth 50m admin-0 GeoJSON>`.
- The "typical night train" envelope, the corridor clustering thresholds and
  the map window are constants at the top of the script; the envelope must
  equal the gallery's preset (`frontend/src/lib/typicalNightTrain.ts`),
  and the page reads it from the JSON so it cannot say otherwise.
- Hand-picked content — comment quotes, the missing-station list — lives in
  the page's `<script setup>`, next to the prose that refers to it. Nothing
  else in a report page is typed by hand.
- Privacy: the export carries no e-mail, no client hash, no OTP rows;
  display names are in it (public in the gallery) but never rendered.

## Adding an edition

1. Run the export in pgAdmin, save the grid as CSV, run the script with a
   new `--edition` and `--window`.
2. Copy the newest report page, point its imports at the new JSON, rewrite
   the prose around the numbers (the sentences are built on the figures but
   their emphasis — "a start", "most likely tests" — is editorial).
3. For an update page: copy the newest one, rename _Launched_ to _Shipped
   this month_, and keep the four sections.
4. Add both to the sidebar group in `.vitepress/config.ts`, newest first;
   link the two pages to each other; `npm run ci` (prettier + build with the
   dead-link check).
