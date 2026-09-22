# Deselect stops on the map — delivery manifest

Date: 2026-09-21 · Scope: **frontend only**, no backend change, no version bump.

A route stop could be added from the map but only removed from the itinerary
table. The map now carries both directions of the same gesture: an available
stop reveals a plus, a stop already on the route reveals a close icon.

## What changed

| # | File | Change |
|---|---|---|
| 1 | `frontend/src/components/MapView.vue` | `MarkerStop` gains `stopId` and `removable`; new `remove-stop` emit. `makeDotEl()` factored out of `makeMarkerEl()` and reused by the new `makeRemovableMarkerEl()`: an 18 px transparent wrapper (constant, so growing the dot never moves the marker's centre) around the normal 10/14 px dot, which grows to hold a close icon on hover and returns on leave. `syncMarkers()` builds the removable element only where `removable` and a `stopId` are both present, and then sets no name popup — the click is the removal, and the stop's name is already a permanent map label (`STOPS_LABEL_LAYER`). The comment on `makeAvailableMarkerEl()` saying removal lives only in the table is corrected. |
| 2 | `frontend/src/components/ProposalViewport.vue` | `mapStops` passes `stopId` and `removable` on the edit-mode branch only, under the same floor as the table's delete control (`itinerary.length > 2`). New `onMapRemoveStop()` beside `onMapAddStop()`: finds the row **by stop id**, not by marker index — `mapStops` drops rows with no stop chosen yet, so the two orders can differ — and delegates to the existing `removeStop()`. Template wires `@remove-stop`. |
| 3 | `frontend/src/i18n/locales/en.json` | `proposal.map.removeStop` — the marker's hover title. |
| 4 | `frontend/src/i18n/locales/de.json` | Same key, **plus the locale gap this round uncovered**: the whole `proposal.night.*` block (fixed-night hints, legend, slack hint, the four stop types) and the four `proposal.expert.*Aria` labels were missing in German, so the night tool and the expert pills rendered raw keys; ten dead `proposal.expert.*` keys left over from the rejected separate expert panel (`pinned`, `follows`, `automatic`, `pinnedHint`, `followsHint`, `nudgeAria`, `mirrored`, `editSeparately`, `ownTimes`, `relink`) are removed. EN and DE are now at 871 keys each, in parity. |

## Behaviour

- **Edit mode, three or more stops**: hovering a route marker grows it and shows
  a close icon; clicking takes that stop off the itinerary, exactly as the
  table's trash icon does. Re-adding it is the plus on the same spot.
- **Edit mode, two stops**: markers behave as before (plain dot, name popup on
  click) — two stops are a route, one is not, which is the same rule that
  disables the table's delete control.
- **Display and suggest modes**: unchanged.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **332 passed** · `vite build` OK.

No test was added: the change is marker DOM and one lookup, and the frontend
suite deliberately mounts nothing (`AGENTS.md`). The lookup's one real trap —
index-by-marker vs index-by-row — is avoided by keying on the stop id instead.

## Commit split

- `feat(map): remove a stop from the map, not only add one` — files 1–3.
- `fix(i18n): German night-tool and expert labels, drop the dead expert keys` — file 4.
- `docs: map deselect manifest` — this file.
