# Expert timetable — mirrored departures, strip controls, fixed night in the builder

Route builder `0.9.36 → 0.9.37`. No schema change, no migration, no reseed,
no `FAMILY_DOCUMENT_FORMAT` bump (the family key carries the route builder
version, so cached documents rebuild themselves).

## What was there, what was not

| Mode | Before | Now |
|---|---|---|
| Automatic (no expert block) | each direction centred on 02:30 | unchanged |
| Expert, mirrored (`return: {mirror_outbound: true}`) | add-ons mirrored, **departure not** — the return stayed at its automatic value | departure displaced the opposite way by however far outbound actually moved, `absolute` and `shift` alike |
| Expert, own times (explicit `return` block) | independent | unchanged |
| Switching back to mirror | mirrors the direction on screen | unchanged (already by construction: the on-screen direction always occupies the posted slot) |

## Files

### Backend

- `backend/models/route/timetable.py` — `mirror_overrides(overrides, departure_shift_min=0)` emits a `shift` of the negated amount for the mirrored direction; module/class docstrings say so.
- `backend/models/route/route_factory.py` — `_build_trip()` records `departure_time_min − auto_departure_time_min` on the trip; `_build_trip_pair()` passes `outbound.departure_shift_min` to `mirror_overrides()`; pipeline docstring step 6b and the pair comment updated.
- `backend/models/route/trip.py` — `Trip.departure_shift_min: int = 0` (+ `_create`).
- `backend/api/helpers/route_serialize.py` — `general_parameters.departure_shift_min` written and read back (default 0 for older payloads); comment on the two non-derivable general_parameters entries.
- `backend/models/route/model.py` — `ROUTE_BUILDER_VERSION` 0.9.37 with changelog.
- `backend/tests/test_22_expert_timetable.py` — `test_return_departure_is_never_mirrored` replaced by: mirrored pin, mirrored shift, explicit return keeps its own departure, `departure_shift_min` zero on automatic trips, `departure_shift_min` round-trips through `route_from_dict`.
- `backend/api/README.md` — the "Expert timetable" section FRONTEND_HANDOVER §9 pointed at (it was missing) — block shape, rules, mirroring semantics, the new field.
- `backend/models/README.md` — pipeline sketch: shift recorded per trip, mirror step on the return direction.

### Generated docs (`generate_model_docs.py`, CI job 0 green)

- `docs/MODEL.md`, `docs-site/reference/changelog.md`, `docs-site/reference/versions.md` — version and changelog entry only.

### Frontend

- `frontend/src/lib/expertTimetable.ts` — `AutoDepartures`, `mirrorAddons()`, `mirrorDeparture()` (shift negated; pin mirrored by its distance from the automatic value, mode kept), `mirrorDirection(direction, autos)`, `swapDirections(state, autos)` keeps a mirroring return mirroring across a flip; `shiftDeparture()` removed.
- `frontend/src/lib/expertTimetable.test.ts` — tests follow (incl. mirror-twice-is-identity with the autos exchanged, `clockToServiceMinute`, `resolveTimetable`, `materialiseSlack`).
- `frontend/src/components/ExpertTimetableControls.vue` — **deleted** (round 4: no panel). Delete it by hand — the zip cannot remove files.
- `frontend/src/components/ProposalViewport.vue` — `rememberAutoDeparture()` reads `departure_shift_min` (the "pinned hides the auto value" workaround is gone); `autosOnScreen()`; `setMirrored()` replaces `unlinkReturn`/`relinkReturn`; `expertChanged` flips the committed state with the autos; `BackendGeneralParameters.departure_shift_min`. Expert UI now lives in the strip: the first row's departure is a time input (`onDepartureInput`, `currentDepartureClock`), and 🔒/🔓, ⧉/⇄ and ↺ are icon pills next to the direction switch (`expert-pill-on` = gold when on); those four icons drive one shared `InfoPopover` (`toolHint`, `showToolHint()`) with their aria sentence as hover text (`pinHintText`/`mirrorHintText` computeds).
- `frontend/src/i18n/locales/en.json` — `proposal.expert` reduced to `toggle`, `firstDeparture`, `pinnedAria`/`followsAria`/`mirroredAria`/`ownTimesAria`, `reset`, the per-leg strings and `droppedAddons`.
- `frontend/src/lib/expertTimetable.ts` (also) — `clockToServiceMinute()` extracted from the deleted component; `resolveTimetable(state, autos)` (each slot as departure minute + sorted add-ons) with `sortedAddons()` shared with `toRequest()`; tests for both.
- `frontend/src/components/ProposalViewport.vue` (also) — `expertChanged` compares `resolveTimetable()` per route direction instead of request JSON, so pin-at-auto / pin↔follows / mirror↔own-copy are not stale; while `paramsStale && timetableChanged` the route-stats panel greys out and carries the Recalculate button (no scrim over the timetable — its inputs stay live until the explicit click), the map dims, and `ProposalResults` gets `dimmed` instead of `paramsStale` so it greys without a second button.

### Fixed night (frontend only, same zip)

- `frontend/src/lib/nightInterval.ts` + `nightInterval.test.ts` — the interval's pure logic (prune, reverse, same-in-either-order, two-click selection, membership, night-leg rule) with 8 cases.
- `frontend/src/components/ProposalViewport.vue` (also) — `nightMode` + `nightToolOn` (🌙 pill in the tool row, expert mode only, `night-pill-on` blue; leaving expert mode restores the committed night), `nightSelection`/`committedNightInterval`; `familyRequest()` posts `timetable_mode` + pruned `fixed_night_interval`; restored from the echo in `applyPlan`; reversed in `swapDirection`; `nightChanged` + `timetableChanged` drive `paramsStale`, the route-stats Recalculate and the results' `dimmed`; restored in `cancelEdit`; display table gains one stop-type icon column (times → icon → band; walk / sleep / exit-run icons) that doubles as the night marker while the tool is on, blue night legs, legend + status line; `StopTimeFmt`/`ViewRow` carry `stop_type`, the night flags and `slack_in`; the expert stepper shows add-on + night stretch (`legSlack`/`legExtra`, blue when stretch only; the first manual touch of a stretched leg calls `materialiseNight()` → `materialiseSlack()` in the lib: stretch → add-ons on every leg, departure pinned, night dropped, tool off, then the step/typed value applies to a plain add-on field; band/icons/legend fade while `nightOnScreenStale`).
- `frontend/src/components/ProposalViewport.vue` (also) — `applyMemberFromFamily()` captures pending expert state, night selection/tool state and the on-screen direction before `applyPlan(plan, false, look=true)` and restores them after (re-flipping the itinerary when needed); `look` suppresses the dropped-add-ons toast.
- `frontend/src/lib/proposalDraftStorage.ts` — `nightIntervalIds` in the draft.
- `frontend/src/i18n/locales/en.json` — `proposal.night.*`.

### Handover

- `docs/FRONTEND_HANDOVER.md` §21 (expert) and §22 (fixed night), `docs/DEPLOY_HANDOVER.md` §19.

## Decisions taken

- Pinned/follows and reset stay, as icons; only the nudge buttons and the panel went.
- Flipping direction while mirrored shows the mirrored departure on the direction now on screen (mode kept, flip back restores the original). After a reroute the pin holds on the direction on screen.

## Verified here

- `ruff format --check` / `ruff check` on the whole backend; `generate_model_docs.py --check` clean.
- Frontend: `vue-tsc --noEmit`, `eslint` + `prettier --check` on touched files, `vitest run` (23 files, 300 tests), `vite build` (with the snapshot's excluded Mark Pro fonts stubbed).
- Not run here (needs the Docker stack): `tests/test_22_expert_timetable.py` — please run it locally.

## Rollout

1. `uv run pytest tests/test_22_expert_timetable.py` (then the full suite) against the local stack — api image rebuilt.
2. Commit as `feat` / `test` / `docs`; CI gates: version bump (0.9.37), model-docs check (regenerated), ruff.
3. Deploy the api image; nothing else. Cached family documents rebuild on first request.
