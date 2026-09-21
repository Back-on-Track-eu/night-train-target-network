# Suggest mode: take your own stops off the route — manifest and handover

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump, no i18n change (existing keys reused).

## What changed

In *Add stops along the way?* the user's own stops between the endpoints
can now be removed — from the timeline (hovering the dot shows a close icon)
and from the map marker (same gesture as in edit mode). Because that
changes the route structurally, the removal:

1. takes the stop off the itinerary (`removeStop()`, the same edit as the
   table's trash icon),
2. drops the suggest state and shows the loading scrim,
3. runs the **suggest pass again** on the shorter itinerary
   (`requestPlan(ids, 'suggest')`) — the two neighbours are routed directly
   and the candidates come from the new geometry,
4. keeps the candidate picks that reappear in the new list, drops the rest
   with the leg they sat on,
5. on zero candidates ends the step as Evaluate would (`applyPlan`).

The endpoints stay fixed in suggest mode: they define what "along the way"
means, and changing them is *Back to edit*. A calculation failure lands the
user in edit mode with the stop already removed, the failure as a toast.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/ProposalViewport.vue` | `resetSuggestState()` (replaces three copies of the same four lines), `isRemovableConfirmed()`, `removeConfirmedStop()`; suggest-mode map markers carry `stopId` + `removable` for the middle stops; `onMapRemoveStop()` routes to the suggest path in suggest mode; timeline dot for a removable confirmed stop is a button with hover/focus close icon (`proposal.suggestions.removeAria`, `proposal.map.removeStop` as title); comments updated. |
| `frontend/README.md` | New *Stop suggestions* section. Includes the day's earlier README changes (landing intro, builder errors) — extract after those zips. |

## Behaviour to check on your stack

- Amsterdam → Milano Centrale → Roma: remove Milano Centrale in suggest mode
  → scrim, new route Stresa/Milano region direct, candidate list refreshed,
  earlier picks north of Milano still ticked if still listed.
- Two-stop route: no removable dot or marker (only endpoints).
- Reversed view (↕ pill): removal works by stop id, unaffected by the flip.
- Reload mid-flow: draft restore (`restoreSuggestState`) unchanged.

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **370 passed** · `vite build` OK.

## Commit split

- `feat(builder): remove own stops in suggest mode, rerouting the suggestions` — component.
- `docs: suggest-mode removal manifest and README` — README + this file.
