# Calculation wait: expected-duration escalation — manifest and handover

Date: 2026-09-21 · Scope: **frontend**, plus the bench script's fit.
No backend change, no version bump, nothing to migrate.

## Why

The builder said *"This is taking longer than usual. Our servers seem to be
experiencing heightened demand."* at a fixed 8 s. Measured on the dev stack
(`backend/scripts/bench_family_wait.py`), a **new** proposal takes 9–14 s for
4–11 stops and a recalculation with cached legs 5–10.5 s — so the message
appeared on nearly every new proposal and blamed server load that was not
there. The loading facts flipped every 9 s though they run 22–38 words, and a
document-cache hit (0.2–0.4 s) flashed the whole scrim on and off.

## The model

A family evaluates every member over every leg, so:

    expected = 2.1 s + 15 ms·members + 6.8 ms·members·legs  (+ 5 s for a new route)

fitted over HTTP (worst residual 0.8 s). "New route" = any leg this browser
has never received a family for, or suggest mode. The prediction is then
scaled by the median of the last 8 actual ÷ predicted ratios (clamped
0.5–4×), so it adapts to the production server by itself. Escalation:

| Phase | When | Copy (EN) |
|---|---|---|
| slow | max(10 s, 1.5 × expected) | This is taking longer than usual. |
| verySlow | max(slow + 15 s, 3 × expected) | This is taking much longer than usual — our servers may be busy. |

On the dev stack that puts "longer than usual" at ~16 s for a new 4-stop
proposal and ~23 s for 11 stops, against real waits of 9–14 s.

## Updates by file

| File | Change |
|---|---|
| **new** `frontend/src/lib/calcExpectation.ts` | The model (`FAMILY_WAIT_MODEL`), thresholds, correction factor, direction-free leg keys, and the two localStorage-backed functions `expectFamilyWait()` / `recordFamilyWait()`. Storage failures fall back to the uncorrected model. |
| **new** `frontend/src/lib/calcExpectation.test.ts` | 18 cases: the model against the bench's own measurements, median/clamp, thresholds, new-leg memory (incl. reversed routes), suggest mode, learning a slower server, ignoring cache hits, the ratio window, no storage. |
| **new** `frontend/src/lib/readingTime.ts` (+ test) | `readingDwellMs()` — 3 s + 250 ms per word, floor 10 s. |
| **new** `frontend/src/composables/useDeferredFlag.ts` (+ test) | A flag that turns on only after a delay and then stays a minimum time. |
| `frontend/src/lib/apiClient.ts` (+ test) | `SlowThresholds` and a per-call `slowThresholds` option; the dev overrides (`api.slowAt`, `api.verySlowAt`) still win. Defaults unchanged for every other caller, publish included. |
| `frontend/src/lib/proposalsApi.ts` | `postFamily()` passes thresholds through. |
| `frontend/src/composables/useProposalFamily.ts` | `run()` asks for the expectation, posts with its thresholds, measures wall time and records the outcome. Member count from the posted axes, else the last document's axis sizes (kept across `reset()`), else 96. |
| `frontend/src/components/ProposalViewport.vue` | The map scrim renders from `useDeferredFlag` (500 ms delay, 700 ms minimum); Cancel only while a calc is actually running, since the scrim can outlive it by the minimum. Stale "8s / 30s" comment replaced. |
| `frontend/src/components/LoadingFunFact.vue` | Per-fact dwell from `readingDwellMs()` instead of a fixed 9 s; hover or focus holds the fact, leaving gives it a fresh dwell. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `errors.stillWorking`, `errors.highDemand` — no server-load claim in the first stage, a hedged one in the second. |
| `backend/scripts/bench_family_wait.py` | Fits the members × legs model the frontend uses and prints the constants in `FAMILY_WAIT_MODEL`'s units, plus a `newRouteMs` candidate. |

## Frontend handover

- **Refitting.** After any change to family build performance, run
  `uv run python -m scripts.bench_family_wait` (backend/) on a stack and copy
  the printed `FAMILY_WAIT_MODEL` line into `calcExpectation.ts`. `newRouteMs`
  is only meaningful on a stack that has not routed the bench's legs yet.
- **Persistence.** Two localStorage keys per browser: `calc.familyWaitRatios`
  (≤ 8 numbers) and `calc.knownLegs` (≤ 2,000 stop-pair keys). Clearing them
  just resets the learning.
- **Seeing the escalation by hand.** Unchanged: `localStorage.setItem('api.slowAt', '2000')`
  and `api.verySlowAt` in a dev build override every threshold.
- **Publish** keeps the fixed 8 s / 30 s — its cost does not scale the same
  way, and the new copy is honest there too.

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.
Users' learned correction starts at 1 and adapts to production within a few
calculations.

## Verification (Node 22)

`vue-tsc` clean · `eslint` clean · `prettier --check` clean · `vitest run`
**363 passed** (26 new) · `vite build` OK · `ruff format` / `ruff check` clean
on the script, and replaying the 2026-09-21 measurements through the new fit
reproduces the shipped constants (2123 ms, 15.2 ms, 6.84 ms).

## Commit split

- `feat(builder): size-aware "longer than usual", readable facts, no scrim flash` — all non-test frontend files and the bench script.
- `test(builder): wait model, deferred flag, reading time, per-call thresholds` — the four test files.
- `docs: calculation wait manifest and handover` — this file.
