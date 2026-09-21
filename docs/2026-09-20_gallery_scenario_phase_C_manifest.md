# Gallery on a chosen scenario — phase C manifest (2026-09-20)

The gallery's scenario panel. **Frontend only** — consumes the
`scenario_variant_id` field phase A added; no API change, no migration, no
version bump. Completes the plan
(`docs/2026-09-20_gallery_scenario_plan.md` §4).

## What a reader gets

A collapsible "Scenario" row between the search bar and the results, whose
header states the scenario in one line ("Infra 2026 · Base") and whose body
is the builder's own `ScenarioSwitches` — network, high-speed lines,
optimised timetables; measures still coming-soon, Infra 2032 still preview.
Pick another scenario and the whole gallery follows it: the card figures,
the sort order, each card's route on hover and the corridor map. Existing
(ONTD) connections are scenario-independent and shown as they run today.

Three decisions worth knowing:

1. **The base sends nothing.** `scenario_variant_id` rides the request only
   when the reader has moved off the base, because the default path is also
   the only one that lists proposals whose §5.4a rows have not been
   backfilled yet.
2. **Error rows are counted, not listed.** A proposal the chosen scenario
   cannot evaluate comes back with `status: "error"` and null figures; the
   panel header says "N routes not evaluable here" and the card list leaves
   them out.
3. **Collapsed by default** — the results row is sized to the viewport minus
   everything above it (`measureRow`), so an open panel costs the map its
   height. The header line answers "which figures am I looking at?" without
   opening anything.

## Files touched

### `frontend/src/components/GalleryScenarioPanel.vue` (new)

Header (icon, "Scenario", the summary line, the not-evaluable count, a
chevron) plus the collapsed body: one explanatory line and
`ScenarioSwitches`. `v-model` is the scenario id; labels come from the
existing `proposal.compare.*` keys, so the gallery and the builder name the
scenarios identically.

### `frontend/src/components/Gallery.vue`

- `galleryScenarioId` (defaults to the base once the scenarios load) and the
  derived `scenarioVariantId`, deliberately separate from
  `store.selectedScenarioId`, which is the builder's selection.
- `loadPage()` sends `scenario_variant_id` when it is non-null; the
  URL/reload watcher now includes the scenario, and the query string carries
  `scenario=<scenario_id>` (not the variant — variant ids are materialised
  and rebuildable).
- `isComputable` / `listedProposals` / `notComputable`: error rows leave the
  card list and become the panel's count.
- `openProposal()` / `openDiscussion()` hand the browsed scenario over via
  `store.pendingScenarioId`.

### `frontend/src/components/ProposalViewport.vue`

A watcher on the family document: when the gallery handed over a scenario,
it moves `store.selectedScenarioId` there once the family exists (a stored
proposal always loads on the base, which is what it is stored on), and the
existing scenario watcher turns that into the member switch. Read once.

### `frontend/src/stores/store.ts`

`pendingScenarioId`, beside `pendingProposalSeed` — the same off-URL
hand-over pattern.

### `frontend/src/types/api.ts`

`ProposalsRequest.scenario_variant_id`,
`ProposalsSummariesSection.scenario_variant_id`, and `status` / `error_code`
/ `scenario_variant_id` on a proposal summary row, each documented with when
it is null and why the figures stay non-nullable (the gallery filters error
rows out before a card sees one).

### `frontend/src/i18n/locales/en.json`, `de.json`

`gallery.scenario.label` / `applied` / `hint` / `notComputable`.

### `frontend/README.md`

New "The scenario the figures are read on" section in the Gallery chapter.

## Gates

| Gate                   | Result                                                                          |
| ---------------------- | ------------------------------------------------------------------------------- |
| `npm run format:check` | clean                                                                           |
| `npm run lint`         | clean                                                                           |
| `npm run type-check`   | clean                                                                           |
| `npm test`             | 28 files, 332 cases green                                                       |
| `npm run build`        | green (locally with stub font files — the fonts are not in the snapshot export) |

## Your run

Backend 0.5.2 and the `--scenario-summaries` backfill must have run, or a
non-base scenario lists nothing.

1. Extract, delete the zip, `cd frontend && npm run ci && npm run build`.
2. Open the panel, switch to HSR: the figures on the cards change, the
   corridor map redraws, and the URL gains `?scenario=<id>`. Reload the URL
   — same view.
3. Without the Infra 2032 routing instance, 2032 stays disabled (preview),
   as in the builder.
4. Open a card while on HSR: the proposal view should settle on the HSR
   member once its family arrives.
5. Back to the base: the request drops the field, and any proposal without
   backfilled rows is listed again.

## Open

- Sorting still offers the phase-1 key set. Now that the figures are
  per-scenario, a sort by subsidy per tonne would be a reasonable addition —
  say the word.
- The not-evaluable count is per loaded page, not per result set (`total`
  comes from the backend and counts every row). If that reads oddly with a
  long list, the alternative is a backend count per status — a small
  addition to the summaries section.
