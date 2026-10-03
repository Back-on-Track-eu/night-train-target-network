# Proposal builder on a phone — expert timetable off, stickers inside their boxes (2026-10-03)

Frontend only. No backend change, no version bump, no new i18n keys.

## What the screenshots showed (iPhone, 393 px)

1. The itinerary tool row (Edit · swap · Expert timetable · night · lock …)
   ran past the right edge — the lock pill was cut off — and with expert mode
   on, the per-leg stepper column floated beside stop names four lines tall.
2. On the KPI tiles the "2032 prices" sticker sat outside the tile, and
   "227.73 M km / year" broke between "km /" and "year".

## What changes

- **Expert timetable is not offered below `lg`** (`ProposalViewport.vue`:
  `expertAvailable` from `useMediaQuery(LG_MEDIA_QUERY)`, the gallery's
  composable). A session that was in expert mode when the viewport narrowed
  (rotation, a resized window) leaves it through `toggleExpertMode()` —
  overrides dropped, not hidden, the night back to what the results were
  computed with — so nothing invisible reaches the next Recalculate. The
  stepper column, departure strip, night and pin/mirror pills all hang off
  `expertMode`, so they go with it.
- **The tool row wraps** (`flex-wrap`, centred) instead of overflowing; the
  tools group wraps too.
- **Sticker rows wrap**: the KPI tile label (`MainKpiGrid.vue`), the finance
  heading (`CostRevenueBreakdown.vue`), the details summary
  (`DetailsSection.vue`) and the compare title (`CompareSection.vue`) are
  `flex-wrap`, so the "2032 prices" / "stale" chips drop to the next line
  rather than leave their box. KPI tiles are `min-w-0`; their unit text is
  `whitespace-nowrap`, so "km / year" wraps as a whole after the number.

Not changed: endpoint stop names stay `text-2xl` — long station names wrap
inside the column (`break-words`), which is correct, just tall.

## Files

- `frontend/src/components/ProposalViewport.vue` — `expertAvailable` + watcher; expert button `v-if`; tool row wraps.
- `frontend/src/components/MainKpiGrid.vue` — label row wraps, `min-w-0`, nowrap units.
- `frontend/src/components/CostRevenueBreakdown.vue`, `DetailsSection.vue`, `CompareSection.vue` — heading rows wrap.
- `frontend/README.md` — "The builder on a phone".

## Gates

eslint, prettier, vue-tsc, vitest 388/388, `vite build` — green.

## Your run

```powershell
cd frontend; npm run ci; npm run build; cd ..
```

Then on the phone: the tool row shows Edit and the swap only (no Expert
timetable); every KPI tile keeps its sticker inside; turn a desktop window
narrow while in expert mode and the mode switches off. I could not render the
builder here (it needs the api), so a second screenshot round is welcome —
anything else that leaves its box, send it.
