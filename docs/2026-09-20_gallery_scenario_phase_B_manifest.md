# Gallery on a chosen scenario — phase B manifest (2026-09-20)

The creator's last selection reaches the stored proposal. **Frontend only**
— no API change, no migration, no version bump; the write is the existing
`POST /api/proposal/publish` in `overwrite` mode. Plan:
`docs/2026-09-20_gallery_scenario_plan.md` §3.

## What changes for a user

On their **own** already-published proposal, switching composition — which
the family serves without a compute — now saves. The save is debounced
(1.5 s of quiet), so stepping through the catalogue is one publish, not one
per step, and it is silent: the inline "saved" line under the results says
it happened, no toast per step.

Not saved this way, on purpose:

- **Someone else's proposal** — recomputing it to look at another
  composition stays a private what-if (the backend refuses the write).
- **An unpublished draft** — a first publish carries the name and the
  identity gate; that is the Evaluate button's job.
- **The scenario** — a published proposal always represents the current
  base (§2.2's base rule). Which scenario a _reader_ sees is phase C's
  gallery panel, not the author's last click.
- **Prices, demand, schedule, expert timetable** — they already reach the
  store through the Recalculate that computes them.

## Files touched

### `frontend/src/lib/selectionSave.ts` (new)

`SELECTION_SAVE_DELAY_MS` and `selectionSaveNeeded(state)` — the whole rule
as a pure function (owned, published, not dirty, not busy, composition
differs from the stored one), so it can be tested without mounting a
component, as the rest of the frontend suite is.

### `frontend/src/lib/selectionSave.test.ts` (new)

7 cases: saves a changed composition; does not when the selection is back
where it was saved; never someone else's proposal; never creates one; waits
while dirty or busy; needs a composition; the delay is a debounce, not
perceptible lag.

### `frontend/src/components/ProposalViewport.vue`

- `savedCompositionId` — what the STORED proposal carries, set on load and
  after every successful publish; the thing the rule compares against.
- `scheduleSelectionSave()` / `cancelSelectionSave()` and the timer.
  `applyMemberFromFamily()` schedules; the rule is re-checked when the
  timer fires, not only when it is set.
- Cancelled by: an itinerary edit (`isDirty` watcher), `recomputeWithSelection()`
  (it publishes on its own path), and unmount.
- `doPublish(silent = false)` — a selection save passes `true`: no toast,
  everything else identical.
- The "switching is a look, not an edit" comment replaced by what is now
  true.

### `frontend/README.md`

New "The creator's last selection" section: the rule, what cancels it, and
why only the composition is saved.

### `docs/2026-09-20_gallery_scenario_phase_B_manifest.md`

This file.

## Gates

| Gate                   | Result                                                                          |
| ---------------------- | ------------------------------------------------------------------------------- |
| `npm run format:check` | clean                                                                           |
| `npm run lint`         | clean                                                                           |
| `npm run type-check`   | clean                                                                           |
| `npm test`             | 28 files, 332 cases green (7 new)                                               |
| `npm run build`        | green (locally with stub font files — the fonts are not in the snapshot export) |

## Your run

1. Extract, delete the zip, `cd frontend && npm run ci && npm run build`.
2. Open one of your own published proposals, arrow through three or four
   compositions, stop. After ~1.5 s exactly one publish should appear in
   `admin.request_log` (`proposal_publish.publish`), and the api log should
   show `scenario rows from family document` for it — the A.1 cheap path.
3. Reload the proposal: it opens on the composition you left it on.
4. Counter-checks: switching on someone else's proposal writes nothing;
   switching back to the stored composition within the debounce writes
   nothing; an itinerary edit mid-debounce cancels the save.

## Open

- **1.5 s** is a guess at your reading pace — trivially changed in
  `SELECTION_SAVE_DELAY_MS` if it fires too eagerly or too late.
- If the A.1 re-measurement is not where we expect, this is the feature
  that suffers first (one publish per pause). The fallback remains the
  `PATCH …/selection` endpoint from the plan's §3; nothing here would have
  to change but the call inside `doPublish`.
