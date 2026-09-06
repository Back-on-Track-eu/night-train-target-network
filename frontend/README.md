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
    │   ├── compositionFormation.ts  # Composition → drawable formation; class colours/glyphs
    │   ├── costFactorRates.ts  # Cost factor → per-unit-rate resolution (popover)
    │   ├── ctaButtonClass.ts   # Shared "Suggest a new route" pill styling
    │   ├── feedbackApi.ts      # Thin client for POST /api/feedback
    │   └── selectPillPt.ts     # Shared PrimeVue Select pass-through styling
    ├── utils/
    │   └── octilinear.ts    # Octilinear map-line layout helpers
    └── components/
        ├── AppIcon.vue                    # Tree-shakeable @mdi/js icon wrapper
        ├── CompositionDetailOverlay.vue   # Composition detail popover — facts + formation
        ├── CompositionFormation.vue       # Formation drawing (Wagenstandsanzeiger)
        ├── CompositionPanel.vue           # Composition of the computed route
        ├── ComputeInputsPanel.vue         # Scenario + composition — the two recompute inputs
        ├── EvaluationPanel.vue            # Cost/revenue evaluation cube explorer
        ├── Gallery.vue                    # Landing page: intro, search bar, result list + map
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
and composition therefore only appear once a route exists, together in
`ComputeInputsPanel` above the results.

Changing either does **not** recompute on the spot: `ProposalViewport` marks
the results stale (`paramsStale`) and covers them with a recompute control, so
the catalogue can be browsed without firing a calc per arrow click. Reverting
to the selection the results were computed with clears the flag on its own. A
diverged itinerary takes precedence — that is the Evaluate button's path,
which also re-prompts for stop suggestions.

---

## Landing Page Copy

The pitch a first-time visitor reads on `/gallery` lives entirely in
`en.json` under `gallery.heading`, `gallery.welcome.*`, `gallery.audience.*`
and `gallery.story.*` — `LandingIntro.vue` holds only layout, so editing the
text never means touching a component.

The intro is two bands, both above the fold. The first carries the headline,
the two calls to action and the argument, split into three headed blocks; the
two columns are top-aligned inside a vertically centred row, so the lead-in
above the headline shares a line with the first block heading. Its
height is measured at runtime rather than fixed: the site header carries a
background image and the API status banner comes and goes, so the offset above
it is not a constant, and the collapsed row below it is subtracted so that row
stays visible without scrolling.

That second band — who the tool is for, and what happens to a submission — is a
panel collapsed by default, so the pitch stays the whole first impression. It
opens by animating `grid-template-rows` from `0fr` to `1fr`, which needs no
height measurement: copy can grow freely without re-tuning a `max-height`.
Toggling it scrolls the panel's bottom edge onto the fold, so opening reveals
the whole panel, closing returns the page to where it started, and neither
exposes the gallery below. A rule above the gallery heading keeps the two halves
of the page apart.

`LandingIntro` emits rather than navigates — `create` opens the builder,
`browse` scrolls to the gallery — because what follows the intro on the page is
`Gallery.vue`'s business, not the intro's.

---

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
