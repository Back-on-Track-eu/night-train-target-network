# Night Train — Frontend

Vue 3 SPA for the Night Train Target Network economic model.

**Related documentation:** backend API this SPA consumes —
[`../backend/api/README.md`](../backend/api/README.md) · what each evaluation
view displays and which filter selection maps to which view —
[`../backend/models/evaluation/README.md`](../backend/models/evaluation/README.md#views-explained-for-display)
· dev-container setup — [`../.devcontainer/DEVELOPMENT.md`](../.devcontainer/DEVELOPMENT.md)
· conventions — [`../AGENTS.md`](../AGENTS.md)

---

## Tech Stack

| Tool         | Version         | Role                                            |
| ------------ | --------------- | ----------------------------------------------- |
| Vue 3        | ^3.5            | UI framework (`<script setup>` Composition API) |
| Vite         | ^8.0            | Dev server + bundler                            |
| TypeScript   | ^5.8 (strict)   | Type safety                                     |
| Pinia        | ^2.3            | State management                                |
| PrimeVue     | ^4.3            | UI component library (Lara theme)               |
| Tailwind CSS | v4              | Utility-first CSS (`@tailwindcss/vite` plugin)  |
| vue-i18n     | ^11             | Internationalisation                            |
| ESLint       | 9 (flat config) | Linting                                         |
| Prettier     | ^3.5            | Formatting                                      |

---

## Dev Setup

### Docker (recommended)

All three services start together:

```bash
# from repo root
docker compose -f .devcontainer/docker-compose.yml up --build
```

- **Frontend**: http://localhost:5173 — Vite HMR, edits reflect instantly without rebuild
- **Backend API**: http://localhost:5050
- **OpenRailRouting**: http://localhost:8989

### Without Docker

Requires Node 22+ and the backend running separately.

```bash
cd frontend
npm install
npm run dev
```

---

## Project Structure

```
frontend/
├── index.html               # Vite entry HTML
├── package.json
├── tsconfig.json            # Reference aggregator
├── tsconfig.app.json        # src/ TypeScript config (strict)
├── tsconfig.node.json       # Config files (vite.config.ts etc.)
├── vite.config.ts
├── eslint.config.ts         # ESLint 9 flat config
├── .prettierrc
└── src/
    ├── main.ts              # App bootstrap — plugin order matters
    ├── App.vue              # Root component
    ├── style.css            # Tailwind + CSS layer declarations
    ├── env.d.ts             # Vite env type shims
    ├── types/
    │   └── api.ts           # TypeScript types for backend responses
    ├── i18n/
    │   ├── index.ts         # vue-i18n setup
    │   └── locales/
    │       └── en.json      # English strings
    ├── stores/
    │   └── store.ts         # Pinia store
    ├── lib/
    │   ├── apiClient.ts       # One classified HTTP boundary for every backend call
    │   ├── apiError.ts        # Failure classification shared by every consumer
    │   ├── proposalFamily.ts  # the family document on the client: inflateRoute, member keys, error mapping
    │   ├── compareKpis.ts     # The comparison KPIs, deltas and the surplus rule
    │   ├── scenarioAxes.ts    # Scenario switches (network / HSR / opt. tt) ↔ scenario_id
    │   ├── compositionFormation.ts  # Composition → drawable formation; class colours/glyphs
    │   ├── costFactorRates.ts  # Cost factor → per-unit-rate resolution (popover)
    │   ├── ctaButtonClass.ts   # Shared "Suggest a new route" pill styling
    │   ├── feedbackApi.ts      # Thin client for POST /api/feedback
    │   ├── selectPillPt.ts     # Shared PrimeVue Select pass-through styling
    │   └── uiLanguages.ts      # Language bar: order + which locales are live
    ├── utils/
    │   └── octilinear.ts    # Octilinear map-line layout helpers
    └── components/
        ├── AppIcon.vue                    # Tree-shakeable @mdi/js icon wrapper
        ├── CompositionDetailOverlay.vue   # Composition detail popover — facts + formation
        ├── CompositionFormation.vue       # Formation drawing (Wagenstandsanzeiger)
        ├── CompareSection.vue             # Zone B: KPI picker, scenario bars, scenario × composition grid
        ├── CostRevenueBreakdown.vue       # Zone E: cost/revenue bars + the cube explorer (collapsible)
        ├── Gallery.vue                    # Landing page: intro, search bar, result list + map
        ├── InfoHint.vue                   # A single ⓘ with one sentence behind it
        ├── InfoPopover.vue                # The hover-intent info overlay both ⓘ users share
        ├── MainKpiGrid.vue                # Zone A: the eight headline KPIs with deltas vs. baseline
        ├── ProposalResults.vue            # Everything below the map, zones A–E
        ├── ScenarioSwitches.vue           # Zone A: the scenario as three switches (+ measures, disabled)
        ├── SettingsSection.vue            # Zone D: supply table / demand notes (collapsible)
        ├── SupplyTable.vue                # Compositions compared on the current route + scenario
        ├── LandingIntro.vue               # Landing pitch above the gallery (copy lives in en.json)
        ├── MapView.vue                    # MapLibre route/stop map
        ├── ProposalViewport.vue           # Proposal build/evaluate workspace
        ├── RouteSectionSlider.vue         # OD-range slider for the evaluation panel
        └── StopSelect.vue                 # Stop search/select control
```

Only the components above are listed; the tree is a map of the main pieces,
not a complete file listing.

**Recompute inputs.** The first evaluation posts no `composition_id` at all —
the backend computes it with its standard composition (`DEFAULT_COMPOSITION_ID`,
`backend/models/route/model.py`) and reports back which one that was. Scenario
and composition therefore only appear once a route exists: the scenario as
switches at the top of `ProposalResults` (zone A), the composition in the
supply table of the collapsible settings (zone D).

**The family.** Every evaluation is one `POST /api/proposal/family`
(`composables/useProposalFamily.ts`): the stops and HOW fields under every
offered scenario × every composition, returned as one document — a summary
per member, a compact route per (scenario, composition), the geometry once.
`ProposalViewport` puts the presented member on screen (its compact route
inflated back into the full shape by `lib/proposalFamily.ts`, so the map,
the itinerary and the expert timetable read what they always read), and a
scenario or composition switch afterwards is a lookup in the document, not a
request. The comparisons (zone A's deltas, B's bars and grid, D's table) read
the other members. A member's six evaluation views are not in the document:
zone E fetches the member on screen's from
`GET /api/proposal/family/<key>/members/<sv>/<comp>/views` and shows a
skeleton until they arrive. Editing the itinerary resets the family. A
loaded proposal arrives with its full route and views inline
(`GET /api/proposal/<id>`) and builds its family in the background so that
switching on it is just as instant.

A member the backend could not compute (a gauge clash, an unroutable pair, a
graph this deployment does not run) is not a failed request but a member with
`status: 'error'` and a code — `lib/proposalFamily.ts` turns the presented
one into the same `ApiFailure` a 422 used to be, and the grid renders the
others as `cellErrors.<code>`.

**Coming-soon surfaces.** Three things are shown but disabled, each for a
different reason: the "price & regulatory measures" toggles (the backend
does not model them — `docs/PARKED_WORK.md` §3), the "fit to demand" column
(the demand stopgap gives every composition the same utilisation), and the
**Infra 2032** network (the routing instance runs and the backend evaluates
it fine, but its infrastructure data is not at publishable quality yet).
Only the last one is a release switch rather than missing code:
`PREVIEW_NETWORKS` in `lib/scenarioAxes.ts`, overridable per deployment with
`VITE_PREVIEW_NETWORKS` (comma-separated; empty string releases every
network). A held-back network is also left out of the comparison views and
of the family request's `scenario_variant_ids`, so nothing is computed for it.

Changing either does **not** recompute on the spot: `ProposalViewport` marks
the results stale (`paramsStale`) and covers them with a recompute control, so
the catalogue can be browsed without firing a calc per arrow click. Reverting
to the selection the results were computed with clears the flag on its own. A
diverged itinerary takes precedence — that is the Evaluate button's path,
which also re-prompts for stop suggestions.

## Stop suggestions

Evaluate first runs the family with `auto_stop_addition: "suggest"`: the
backend routes exactly the user's stops and returns the candidates along the
way, which the builder shows interleaved with the user's own stops (suggest
mode, `lib/suggestPlacement.ts` for the ordering). Candidates toggle in and
out from the timeline bubble or the map marker. A user's own stop — a
terminus included — can be ticked off the route from the same two places
while more than two remain, and ticked back on: like a pick, that is a
choice, not an edit. Nothing is routed per click; the timeline dims the stop
like an unpicked candidate and the map cuts its legs, bridging the gap with a
dimmed beeline (`lib/suggestShape.ts`). Continue then recomputes once with
`"off"` on the remaining stops, the chosen candidates placed on the leg they
were listed on; with nothing picked and nothing removed it reuses the base
response as is.

## Removing stops from the map

Every mode that shows the user's stops as route markers lets a marker be
removed by hovering it (close icon) and clicking — under one floor,
`stopRemovable` in `ProposalViewport.vue`: more than two stops, termini
included. In edit mode it is the table's trash icon by other means; on a
computed route (display mode) it opens re-edit with the stop already gone,
exactly as _Edit_ followed by the trash icon would; in suggest mode it is
the choice described above, routed on Continue.

---

## Landing Page Copy

The pitch a first-time visitor reads on `/gallery` lives entirely in
`en.json` / `de.json` under `gallery.heading` and `gallery.welcome.*` —
`LandingIntro.vue` holds only layout, so editing the text never means touching
a component.

The intro is one band that fills the viewport below the header. Its left
column holds the headline and every way onward (the filled "suggest a route"
call to action on its own line, the quieter "see other suggestions",
"suggest a new composition" (the feedback form, opened on the catalogue's
fields) and "About" beneath it); the right column holds the pitch as three
paragraphs —
`gallery.welcome.pitch.network`, `.contribute` and `.study`. Only the last
carries the `{source}` link to Back-on-Track's reports; adding a paragraph
means a new key there and an entry in `PITCH_PARAGRAPHS`. The band's height is
measured at runtime rather than fixed: the site header carries a background
image and the API status banner comes and goes, so the offset above it is not
a constant.

`LandingIntro` emits rather than navigates — `create` opens the builder,
`browse` scrolls to the gallery — because what follows the intro on the page is
`Gallery.vue`'s business, not the intro's.

---

## The creator's last selection

A composition switch in the builder is served from the family document, so
it puts a member on screen without computing anything. That used to store
nothing: the proposal kept the composition of the last **Recalculate**, and
the gallery then described a train the creator had moved on from.

`lib/selectionSave.ts` holds the rule, `ProposalViewport` the timer. On the
user's **own** already-published proposal, a family-served switch schedules
a publish-overwrite `SELECTION_SAVE_DELAY_MS` after the last one, so
arrowing through the catalogue costs one publish rather than one per step.
The rule is re-checked when the timer fires, not only when it is set: a
switch back to the stored composition, an itinerary edit, a Recalculate (it
publishes on its own) and leaving the page all cancel it.

Only the composition is saved this way. Prices, demand, schedule and expert
edits reach the store through the Recalculate that computes them, and the
scenario is deliberately not stored at all — a published proposal always
represents the current base, and which scenario a _reader_ sees is the
gallery's scenario panel, not the author's last click. The save is silent:
no toast per step. A failed save is not — it raises a sticky error toast.

## Errors in the builder

Every failure in the proposal builder — a calculation (including the
backend's own validation text, such as a gauge clash), a save, a views fetch
— shows in the toast stack at the top of the page, never as an inline box
under the controls. Calc and save failures each hold one merge key
(`proposal:calc`, `proposal:publish` in `ProposalViewport.vue`), so the next
attempt clears the old message instead of stacking a second one; a retryable
calc failure carries a _Try again_ action on its toast.

---

## Gallery

`Gallery.vue` is one screen with three parts: the search bar, the result
column and the map beside it.

**One screenful.** The results row — card column AND map — is exactly the
viewport minus the gallery's own chrome, measured at runtime (`measureRow`, the
same technique `LandingIntro` uses for its band) because the heading wraps and
the search pill changes height with the active mode. Two things follow, and both
are the point: the search bar stays on screen beside the map at 100% zoom, so
changing a filter and seeing the result costs no scrolling; and the two columns
are the same height, so the card list ends at the map's bottom edge instead of
running past its corner. The cards scroll inside their own column, not down the
page, which is also why the infinite-scroll sentinel is observed against that
box (`root: cardScroller`) rather than the viewport. Anything added above the
results row comes straight off the row's height — that is why the result count
and the ownership switch live in the result column. `ROW_MIN_HEIGHT_PX` is the
floor for short windows: it keeps room for roughly three cards, and below it the
page scrolls again.

**Two grains on the map** (`GalleryMap.vue`, helpers in `lib/galleryMap.ts`).
The overview is `map_lines`: one line per stop-pair corridor across the whole
filtered set. It is drawn in two passes over the same features — existing
trains first, proposals over the top — so a corridor carrying both shows the
suggestion in front of the train already running there, each in its own colour
and at its own count's thickness (`proposal_count` / `existing_count`, absolute
ramp, never scaled to the current result set). Hovering a card swaps the
corridors for that one row's route from `map_routes`, which follows the list's
own pagination. A corridor or route the ONTD catalogue could not route is
dashed, at either grain.

**The scenario the figures are read on.** Every suggestion is stored once per
scenario variant on the backend (§5.4a), so `GalleryScenarioPanel.vue` — the
builder's own `ScenarioSwitches` behind a one-line collapsible header — picks
which projection the list reads: figures, sort order, per-card geometry and
the corridor map all follow it. Existing (ONTD) trains are
scenario-independent and unaffected. Two details that are load-bearing:

- The request sends `scenario_variant_id` only when the reader has moved
  off the base, so the base view stays the pre-§5.4a request. Either way the
  **result set is the same**: the backend joins the scenario's figures onto
  the base projection, so a filter returns the same proposals on every
  scenario. A scenario changes what a card says, never which cards are
  listed.
- A proposal the chosen scenario has no figures for — not evaluable on that
  network (`status: "error"`) or not yet backfilled (`"missing"`) — stays in
  the list with its identity and stops, and `ProposalCard` shows one line
  saying why in place of the figure grid. The panel header counts them.

When the source switch shows existing trains alone, the panel and the
ownership switch grey out and close rather than hide: nothing in either
applies to an ONTD row, and a control that vanished with the source would be
a control nobody could find again. The panel header carries a permanent
"proposals only" chip for the same reason — which rows a scenario reaches is
the one thing a reader can get wrong here.

The panel is collapsed by default because the results row is sized to the
viewport minus everything above it — an always-open panel would cost the map
its height for a control most readers never touch. The URL carries the
`scenario` id (not the variant: variant ids are materialised and
rebuildable). Opening a card hands the scenario to the proposal view through
`store.pendingScenarioId`, which `ProposalViewport` applies once the
proposal's family is there — a stored proposal always loads on the base,
because that is what it is stored on.

**Filters.** Source ("all" / proposals / existing) and sort round-trip through
the query string, as does the ownership switch (`?mine=1`). "Mine" adds the
signed-in account's `user_ids` and pins `sources` to proposals, since an
existing row has no owner — picking it while the list shows existing trains
alone moves the source switch with it. The switch is always on screen whatever
the sign-in state: signed out or a guest, "mine" opens the login /
registration modal and applies itself the moment the account exists (the
click meant "show mine", not "show me a form"); dismissing the modal drops
that intent. Registered accounts only, on purpose: a guest session carries a
user id too, so on identity alone the switch would silently filter to an
anonymous user and never ask — and registering merges the guest's proposals
into the account, so nothing is lost by asking. It releases itself on
sign-out. The account is
deliberately not part of the shared link: `?mine=1` resolves against whoever
opens it. Signing in also reloads the list (or marks it stale if the gallery is
in its keep-alive cache), because the guest merge changes who published what
and the "proposed by" lines would otherwise keep naming the guest.

**What a card shows** (`ProposalCard.vue`). Three blocks, each behind a
hairline, ranked so the eye has somewhere to land: the route in bold at the top
with the country flags heading it (they say what the route crosses, so they
belong to the itinerary rather than to the proposer), the figures in a fixed
two-column grid, and the metadata foot — proposer, authoring dates, comments,
likes. Only the route is bold; below it, hierarchy is carried by colour and
size, because a card that sets the itinerary, every figure and both counts in
semibold ranks nothing.

The grid is filled in a fixed order — distance | average speed, composition |
passenger trips per year, CO₂ saved | subsidy per tonne of CO₂ — so the same
fact sits in the same corner on every card and a list can be read down a
column: the route's physics, then what runs and who rides, then climate and
its price.
Every value stays on one line (`whitespace-nowrap`, and the labels are kept
short for it): a figure that wraps breaks the alignment the grid exists for.
Everything past average speed is proposal-only and appears once the proposal has
an evaluation snapshot; composition is proposal-only on purpose, since an
existing train carries whatever the catalogue names but nothing in the app can
pick, show or change it.

The foot carries "proposed by" and the authoring dates ("Created 12 Sep 2026 ·
updated 14 Sep 2026", the updated half dropped when it would repeat the creation
date). Dates come from `useLocaleFormat`'s `formatDate`, shared with the comment
thread so both print the same short form in the active locale; euro figures go
through `lib/money.ts` like everywhere else. Comments and likes are two
identically built icon-then-count buttons — count always to the right of its
icon, same box, one baseline. The like button toggles; the comment count opens
the proposal AT its discussion, via `/proposal/<id>#comments`.
`ProposalWorkspace` turns that hash into `ProposalViewport`'s `focusSection`
prop, which scrolls to the thread once it mounts — the discussion only renders
after the results do, so a plain browser anchor would resolve against nothing.

**One vocabulary.** The two kinds of row are called the same thing wherever they
appear — source switch, map legend and card badge all say "Proposals" and
"Existing" (German: "Vorschläge" / "Bestehend"). Keep them in step: they are
three separate keys under `gallery.source.*`, `gallery.map.legend.*` and
`gallery.card.existing`.

## Available Scripts

| Command                | Description                          |
| ---------------------- | ------------------------------------ |
| `npm run dev`          | Start Vite dev server with HMR       |
| `npm run build`        | Type-check then build for production |
| `npm run type-check`   | `vue-tsc --noEmit` (used in CI)      |
| `npm run lint`         | ESLint report                        |
| `npm run lint:fix`     | ESLint auto-fix                      |
| `npm run format`       | Prettier write                       |
| `npm run format:check` | Prettier check (used in CI)          |

---

## Pre-commit Hooks

Hooks run `ruff format` (backend) and Prettier (frontend) automatically on every `git commit`.

**Install once per machine:**

```bash
pip install pre-commit
pre-commit install
```

**Run manually on all files:**

```bash
pre-commit run --all-files
```

Hooks are defined in `/.pre-commit-config.yaml` at the repo root. They mirror the
`prettier-check` and `ruff-check` CI jobs — if CI fails on formatting, run
`npm run format` (frontend) or `ruff format backend/` (backend) and recommit.

---

## Icons

Use the `AppIcon` component with path constants from `@mdi/js`:

```vue
<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import { mdiMagnify } from '@mdi/js'
</script>

<template>
  <AppIcon :path="mdiMagnify" :size="20" color="white" />
</template>
```

Props: `path` (required), `size` (px, default `24`), `color` (default `currentColor`).

Do **not** use `<i class="mdi mdi-*">` CSS font classes — `@mdi/js` is tree-shakeable and avoids loading the full icon font.

---

## CSS Layer Architecture

PrimeVue 4 and Tailwind v4 coexist via CSS cascade layers. The layer order is declared
in two places that must stay in sync:

- `src/style.css`: `@layer tailwind-base, primevue, tailwind-utilities;`
- `src/main.ts` PrimeVue config: `cssLayer.order: 'tailwind-base, primevue, tailwind-utilities'`

This ensures Tailwind utility classes always win over PrimeVue component styles.
