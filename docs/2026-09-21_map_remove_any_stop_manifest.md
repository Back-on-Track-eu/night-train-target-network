# Remove any stop from the map, in every mode — manifest and handover

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump, no i18n change. Supersedes the "endpoints are fixed" rule of the
suggest-mode removal delivered earlier today.

## One rule

A route marker can be removed from the map (hover → close icon → click)
whenever the route has **more than two stops** — termini included, the
neighbour becomes the new end. `stopRemovable` in `ProposalViewport.vue` is
the single floor shared by the table's trash icon, the map in every mode and
the suggest timeline.

| Mode | Before | Now |
|---|---|---|
| Edit | any stop, > 2 stops | unchanged |
| Display (computed route, incl. a stored proposal) | not removable — Edit first | removable; the click opens re-edit with the stop already gone, as *Edit* + trash would |
| Suggest (*Add stops along the way?*) | middle stops only | any confirmed stop, incl. termini; reroutes and refreshes the candidates as before |

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/ProposalViewport.vue` | `isRemovableConfirmed()` replaced by the `stopRemovable` computed; display-mode markers carry `stopId` + `removable`; `onMapRemoveStop()` calls `startEdit()` first in display mode; suggest timeline renders the removable button for endpoints too (endpoint dot size kept); comments updated. |
| `frontend/README.md` | *Stop suggestions* adjusted; new *Removing stops from the map* section. Includes the day's earlier README changes — extract after those zips. |

## Behaviour to check on your stack

- Open a stored three-stop proposal, hover a terminus marker, click: the
  builder is in edit mode, the stop is gone, available stops appear as plus
  markers; *Cancel* restores the stored route.
- Two-stop route in any mode: markers keep their popup, no close icon.
- Suggest mode: removing a terminus reroutes from the new terminus and
  refreshes the candidate list.

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **370 passed** · `vite build` OK.

## Commit split

- `feat(map): remove any stop, termini included, from the map in every mode` — component.
- `docs: map removal manifest and README` — README + this file.
