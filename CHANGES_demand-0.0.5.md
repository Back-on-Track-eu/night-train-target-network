# DEMAND 0.0.5 — benchmarked stopgap tariff defaults

Unzip over the repo root (paths are relative to it). 11 files, all edits in place.

## What changed

| File | Change |
|---|---|
| `backend/models/demand/model.py` | Version 0.0.5 + changelog entry. New defaults: fare_per_pax 30/55/110/75, fare_per_km 0.025/0.035/0.060/0.040, services 1.5/2.5/4.0/2.5, catering +1.5/+2.0/+1.0/+2.0 (Seat/Couchette/Sleeper/Capsule). Docstrings carry the basis (operators, VAT/price-year conversion, implied fares at 300/700/1,200 km, staff-excluded catering, stockings flag). Description now says "two-part fare". |
| `backend/models/demand/README.md` | "per-km fares" → "two-part fare". |
| `backend/tests/test_21_schedule_and_trainsets.py` | `test_spellings_that_mean_the_same_hash_the_same` spells the new defaults. |
| `frontend/src/components/details/PlacesPricesPanel.vue` | Per-part precision: €/km kept and shown at 3 decimals (was rounded to the cent — 0.025 would have become 0.03), stepper moves €/km by 0.005. Per-pax parts stay at 2 decimals. Weighted-average row shows €/km at 3 decimals. |
| `frontend/src/composables/useCompareFormat.ts` | `dec3` formatter added. |
| `frontend/src/components/ProposalResults.vue` | Fare-span label uses `dec3` for €/km. |
| `docs/MODEL.md`, `docs-site/reference/{standard-values,changelog,versions}.md` | Regenerated with `scripts/generate_model_docs.py`. |
| `docs-site/cost/ticket-revenue.md` | Hand-written prose: two-part fare, benchmarked defaults. |

## Backend already fine
`normalize_fares()` rounds `fares_eur_per_km` to 4 decimals (the per-pax maps to 2), so 0.025 survives the request → echo → family-key round trip unchanged. No API change.

## Verified here
- `ruff check` + `ruff format --check` clean on the Python files.
- `pytest tests/test_21_schedule_and_trainsets.py` — 35 passed (no DB needed).
- `prettier --check` clean on the three frontend files.
- `generate_model_docs.py` ran clean.

## Not verified here (needs your environment)
- Postgres-backed suites (`test_30`, `test_39`) — the fixtures need a live DB.
- `vue-tsc`, `eslint`, `vitest` — no node_modules in the sandbox.
- One visual check of the Places & prices panel: the €/km input is `w-16`; "0.025" fits, but confirm it does not clip in the mobile card.

Every evaluation that does not override fares changes with this. Published proposals keep their committed request, so their numbers are stable; the family cache keys on the resolved fares, so new computes miss and reprime as intended.
