# Suggest mode: tick own stops off and on, route once on Continue — manifest and handover

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump. One new i18n key. Supersedes the "remove → reroute at once" behaviour
of the two earlier suggest-mode zips today.

## What changed

Taking one of your own stops off the route in *Add stops along the way?* no
longer triggers a calculation. It is a **choice like a candidate pick**:

- The stop stays in the timeline, dimmed like an unpicked candidate, with a
  plus to tick it back on; on the map its marker becomes the same plus
  marker a candidate has.
- The map cuts the two legs that touched the stop and **bridges the gap with
  a straight line**, drawn on the dimmed layer so it reads as "not routed
  yet". Several stops can be ticked off and on; adjacent removals merge into
  one bridge; a removed terminus just drops its leg.
- **Continue** recomputes once (`auto_stop_addition: "off"`) on the remaining
  stops plus the chosen candidates. With nothing picked and nothing removed
  the base response is reused as before. The button reads *Continue with the
  changed route* when stops were removed but none picked.
- Floor: more than two of your own stops must remain; the last two cannot be
  ticked off. Reload mid-flow restores the removals with the picks.

## Updates by file

| File | Change |
|---|---|
| **new** `frontend/src/lib/suggestShape.ts` (+ test, 6 cases) | `bridgeRemovedStops(legs, removed)` → routed runs + bridge lines. Pure geometry. |
| `frontend/src/components/ProposalViewport.vue` | `suggestRemoved` set; `toggleConfirmed()` / `toggleSuggestRow()` replace `removeConfirmedStop()`; `suggestConfirmed` / `suggestActive` / `suggestShape` computeds; rows keep removed stops dimmed; endpoints = first/last stop still on; removed stops ride on `mapSuggested`; `mapShape` is a MultiLineString of the routed runs, `mapBridges` the beelines; `confirmStopSelection()` settles on the remaining stops and treats a removal as a change; draft persists `suggestRemovedIds`; `stopRemovable` counts own stops still on the route in suggest mode. Shape types narrowed to `'LineString'`. |
| `frontend/src/components/MapView.vue` | `shape` accepts a MultiLineString; new `bridges` prop drawn on the dim route source beside it; both in the redraw watch. |
| `frontend/src/lib/proposalDraftStorage.ts` | Optional `suggestRemovedIds`. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.suggestions.continueChanged`. 896 keys each, in parity. |
| `frontend/README.md` | *Stop suggestions* and *Removing stops from the map* rewritten to the deferred behaviour. Contains all of today's README changes — extract after the earlier zips. |

## Behaviour to check on your stack

- Amsterdam → Milano Centrale → Roma with candidates: tick Milano Centrale
  off → its legs vanish, a dimmed straight line Stresa-side → Piacenza-side,
  no scrim; tick it back on → real geometry returns; tick two adjacent own
  stops off → one bridge. Continue → one calculation on the remaining stops.
- Three own stops: after one removal the other two show no close icon.
- Reload mid-flow: removals and picks restored.

## Known, accepted

The map refits when a removed stop's marker moves between the route and the
candidate set (the marker set changed), the same as for any stop change.

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **376 passed** (370 + 6) · `vite build` OK.

## Commit split

- `feat(builder): tick own stops off in suggest mode, bridge the map, route on Continue` — components, lib, storage, locales.
- `test(builder): bridged suggest shape` — the test file.
- `docs: deferred reroute manifest and README` — README + this file.
