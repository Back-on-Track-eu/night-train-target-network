# Builder errors: toasts at the top only — manifest and handover

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump, no i18n change.

## Why

A failed save or calculation showed twice: once as the toast at the top and
once as a red box under the route stats (and, for calc failures, a third
time in *Compare across scenarios*). Decision (David, 2026-09-21): builder
messages appear **only at the top**.

## What changed

- **Calculation failures** — the backend's own text (gauge clash, unroutable
  pair, error member) and systemic failures alike — raise one sticky error
  toast under the key `proposal:calc`, with *Try again* when the failure is
  retryable. The next calculation, retry or recalculation dismisses it.
- **Save failures** raise one sticky toast under `proposal:publish`; the next
  save attempt (or a new calculation) dismisses it. Same copy as before
  (`errors.publishFailed` + the classified reason).
- **Views fetch failures** are now always toasted (`force: 'toast'`); a
  timeout previously showed nothing at all.
- **Compare across scenarios** no longer repeats the family failure inline.
  Its Retry (`family.retry()`) re-ran the family without applying the result
  to the builder; the toast's *Try again* replays the full calculation instead.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/ProposalViewport.vue` | `calcFailure`, `calcFailureMsg`, `publishError`, `retryFamily` and both inline alerts removed; new `showCalcFailure()` / `clearCalcFailure()` and the two toast keys beside `retryCalc()`; publish failure toasted with its key; views failure forced to toast; stale comments fixed. |
| `frontend/src/components/CompareSection.vue` | Inline alert, `errorMessage` prop and `retry` emit removed. |
| `frontend/src/components/ProposalResults.vue` | `familyError`, the `messageKey` import and the `retryFamily` emit removed. |
| `frontend/src/composables/useProposalFamily.ts` | `retry()` and `lastRequest` removed — no caller left. |
| **deleted** `frontend/src/components/InlineAlert.vue` | No user left (removed by the extract command, not by the zip). |
| `frontend/README.md` | New *Errors in the builder* section; the stale "inline saved line" sentence fixed. Includes the landing-intro README change of the same day. |

## Still inline, deliberately (outside the builder panel)

Form errors in the auth modal and the comment box, the stop-search dropdown's
load error, the gallery's list-load error, and the full-page panel that
replaces the builder when a stored proposal cannot be loaded.

## Frontend handover

- New builder failures go through `toastStore.addToast('error', …)` with a
  merge key, or `report(err, { force: 'toast' })` — not inline.
- `lib/apiError.ts` `treatment()` still distinguishes inline vs toast for the
  gallery and comments; the builder simply no longer uses the inline branch.

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **370 passed** · `vite build` OK.

## Commit split

- `fix(builder): show calc and save failures only as toasts at the top` — components, composable, deletion.
- `docs: builder errors manifest and README` — README + this file.
