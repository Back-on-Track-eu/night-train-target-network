# Gallery polish — phase 1 manifest (2026-09-20)

Frontend-only round on `/gallery`, covering David's feedback items 1–5.
**No backend change, no API change, no migration, no version bump** — every
field and filter used here was already served by `POST /api/proposals`.

## Items and how they were solved

| #   | Feedback                                | Solution                                                                                                     |
| --- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 1   | Map too tall to fit a standard screen   | Map height = viewport − the gallery's measured chrome; result count moved into the result column             |
| 2   | Proposals above existing on the map     | Corridors drawn in two passes over one source, existing first, proposals on top, each at its own count       |
| 3   | Composition irrelevant on existing rows | Composition stat is proposal-only                                                                            |
| 4   | "Only my proposals" filter              | Toggle in the result column sending `filter.user_ids` + `filter.sources: ["proposal"]`                       |
| 5   | Show likes, comments and demand         | Comment count beside the like button, both always rendered; passenger trips per year added to the stat strip |

## Files touched

### `frontend/src/components/Gallery.vue`

- **Map height budget.** New `measureMap()` + `resultsRow` ref:
  `height: max(MAP_MIN_HEIGHT_PX, calc(100vh − chrome − 2×24px))`, where
  `chrome` is measured between the top of the gallery block and the top of the
  results row. Re-measured by a `ResizeObserver` on `document.body` and on
  `window.resize` (attached in `onMounted` / `onActivated`, released in
  `teardown()` alongside the existing `IntersectionObserver`). Replaces the
  fixed `h-[calc(100vh-3rem)]`; the sticky `top-6` and the root `-mb-6` are
  unchanged.
- **Chrome trimmed** so the budget leaves a usable map: section heading
  `text-4xl → text-3xl`, `pt-12 → pt-8`, `mt-6 → mt-2`, search block
  `gap-4 → gap-3`.
- **Result count moved** out of the search block into the result column, on one
  row with the new toggle (`min-h-7` so the row does not appear only once the
  first query lands).
- **"Only mine" filter.** `mineOnly` + `canFilterMine` (any signed-in identity,
  guests included); `buildFilter()` adds `user_ids: [store.userId]` and pins
  `sources: ['proposal']`; released when the source switch goes to existing-only
  or the user signs out; round-trips through the query string as `mine=1`
  (written only when on, hydrated against the current identity).

### `frontend/src/components/GalleryMap.vue`

- Corridor layers generated per kind (`CORRIDOR_KINDS` order = draw order), two
  per kind for the routed/unrouted split — four layer ids from
  `corridorLayerId()`, collected in `CORRIDOR_LAYER_IDS` for the
  hover-isolation visibility toggle.
- Each layer: flat colour, `line-width` over its own count, `line-sort-key` over
  its own count, `line-opacity` from `CORRIDOR_OPACITY` (existing 0.65 so the
  proposal line over it stays legible; proposals 0.95).
- Legend re-ordered to match the stacking (suggested first).
- Root element's `min-height: 480px` dropped — the gallery now owns the height.

### `frontend/src/lib/galleryMap.ts`

- Added `CORRIDOR_KINDS` / `CorridorKind`, `CORRIDOR_COUNT_PROPERTIES`,
  `CORRIDOR_OPACITY`, `corridorPresenceFilter()`.
- `CORRIDOR_COLORS` re-typed per kind; `corridorWidthExpression(kind)` now reads
  the kind's own count instead of `total_count`.
- Removed `corridorColorExpression()` (each layer has a flat colour now) and
  `corridorState()` (a corridor no longer resolves to one state).
- `total_count` is consequently unused on the client; it stays in the API and in
  `types/api.ts` untouched.

### `frontend/src/lib/galleryMap.test.ts`

- `corridorState` cases replaced by a draw-order case on `CORRIDOR_KINDS` and a
  presence-filter case; width-expression case now pins both kinds. 20 cases in
  the file, all green.

### `frontend/src/components/ProposalCard.vue`

- `compositionLabel` is proposal-only (item 3).
- New `demand` stat (`demand_trips_per_year`, `mdiAccountGroupOutline`) and
  `commentCount` (`mdiCommentOutline`), the comment chip reusing the existing
  stat popover.
- Footer restructured: stats as one wrapping strip (they would otherwise stack
  five rows deep beside the flags), then one line of flags + proposer/ONTD badge
  on the left and comments + likes on the right. Like count no longer hides at
  zero.

### `frontend/src/i18n/locales/en.json`, `de.json`

- Added `gallery.filter.mineOnly`, `gallery.card.demandPerYear`,
  `gallery.card.stat.demand.*`, `gallery.card.stat.comments.*`.

### `frontend/README.md`

- New "Gallery" section: the one-screen height budget, the two map grains and
  their layering, the filters, and what a card shows.

### `docs/2026-09-20_gallery_polish_phase1_manifest.md`

- This file.

## Gates run

| Gate                   | Result                                                                          |
| ---------------------- | ------------------------------------------------------------------------------- |
| `npm run format:check` | clean                                                                           |
| `npm run lint`         | clean                                                                           |
| `npm run type-check`   | clean                                                                           |
| `npm test`             | 27 files, 325 cases green                                                       |
| `npm run build`        | green (locally with stub font files — the fonts are not in the snapshot export) |

Backend untouched, so no integration-test run and no CI version bump is
required for this phase.

## Rollout

1. Extract over the repository root, delete the zip.
2. `cd frontend && npm run ci && npm run build`.
3. Nothing to deploy beyond the usual frontend image rebuild; no
   `deploy/`-side change, no `.env` key, no migration.

## Open for David

- Item 2 changes what a corridor carrying **both** proposals and trains looks
  like: it used to resolve to orange ("a train already runs here wins"), and now
  draws orange underneath with the blue proposal line over it. Widths are per
  kind, so where the corridor is better served than proposed an orange casing
  stays visible around the blue.
- Passenger demand is `demand_trips_per_year` — say if you meant
  `demand_trip_km_per_year` (passenger-km) instead.
- Sorting still offers distance, stops, CO₂, likes, comments, created, updated.
  Demand is now displayed but not sortable; adding it is a one-line change if
  you want it.
- Unrelated drift spotted: `frontend/README.md`'s "Landing Page Copy" section
  describes a two-band intro with `gallery.audience.*` / `gallery.story.*`
  keys that neither `LandingIntro.vue` nor the locale files carry. Left alone
  in this phase.
