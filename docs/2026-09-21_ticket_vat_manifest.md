# VAT on tickets: calibration, table, endpoint, gross fares — manifest and handover

Date: 2026-09-21 · Scope: **backend `0.5.7 → 0.5.8` + frontend + docs-site.**
No model version bump: nothing in the evaluation reads a VAT rate.

## The rule

Passenger transport is taxed where it takes place, in proportion to the
distance covered in each country (VAT Directive Art. 48). Most countries
exempt the domestic leg of an **international** rail ticket while taxing a
domestic one, so each country carries two rates. A route's effective rate:

    effective = Σ_c distance_share_c × rate_c
    rate_c    = vat_international_per if the route crosses a border
                else vat_domestic_per

VAT is **display only**: the fares, the ticket revenue and every cost or
subsidy figure stay net; the gross figures appear beside them.

Member states still taxing their section of an international ticket
(T&E 2025, EC 2017): DE 7 %, NL 9 %, BE 6 %, ES 10 %, HR 25 %, GR 13 %, and
AT 10 % (kept from the 2017 study and ÖBB's invoices; T&E's 2025 list omits
it — flagged for review in the calibration).

## Backend

| File | Change |
|---|---|
| **new** `backend/models/demand/calib/vat/vat_calibration.py` | Stdlib calibration (opt-tt pattern): 41-country table with domestic and international rates, status (`sourced` 23 / `assumed` 14 / `no_railway` 2 / `blocked` 2), note, source id; writes `seed/ticket_vat_rates.csv`, `seed/sources.csv` and the document. |
| **new** `backend/models/demand/calib/vat/VAT_CALIBRATION.md` | Generated: rule, table, sources (T&E 2025, EC/CE Delft 2017, TEDB, ESTV, HMRC, Skatteetaten). |
| `backend/db/schema.py` | `input_params.ticket_vat_rates` — unversioned catalogue, one row per country, FK to sources. |
| **new** `backend/db/dev/sql/migrations/2026-09-21_ticket_vat_rates.sql` | Idempotent: create-if-absent, source rows matched by description, 41 rows `ON CONFLICT DO NOTHING`. Generated from the calibration's own table. |
| `backend/db/dev/seed.py` | Regenerates the VAT seed CSVs every seed (like opt-tt), merges the source register, `seed_ticket_vat_rates()` asserts the CSV covers `COUNTRIES` exactly. |
| `backend/.dockerignore` | `!models/demand/calib/vat/` — the whole demand calib tree was excluded, and the seeder runs the script inside the container. |
| `.gitignore` (repo root) | `backend/models/demand/calib/vat/seed/`. |
| `backend/models/params.py` | `TicketVatRate`, `TicketVatCollection`. |
| `backend/adapters/data_loader_from_db.py` | `build_all_ticket_vat()` with provenance under `ticket_vat:{cc}:{field}`. |
| `backend/api/params.py`, `api/helpers/params_serialize.py` | `GET /api/params/TicketVat` → `{rule, sources, count, rates}`. |
| `backend/tests/test_10_params_api.py` | `TestTicketVat`: layout, one row per track country, fractions with provenance, DE 7 % / FR 0 % international pinned. |
| `backend/api/README.md`, `backend/models/demand/README.md`, `backend/pyproject.toml` | Endpoint, the display-only rule, `0.5.8`. |

## Frontend

| File | Change |
|---|---|
| **new** `frontend/src/lib/ticketVat.ts` (+ test, 6 cases) | `ticketVat(legs, rates)` → `{ratePer, international, shares, missing}`; `gross()`; `vatBreakdown()` for the tooltip. A country the table lacks counts at 0 % and is reported. |
| `frontend/src/stores/store.ts`, `App.vue` | `ticketVatRates` fetched once per session (`fetchTicketVat`, silent on failure — no rates means no gross line). |
| `frontend/src/types/api.ts` | `TicketVatRate`, `TicketVatResponse`. |
| `frontend/src/components/ProposalViewport.vue` | `ticketVat` computed from the outbound segments' `distance_m` × `country_distance_shares`; passed to the Details card. Contains today's earlier changes — extract after those zips. |
| `frontend/src/components/DetailsSection.vue` | `ticketVat` prop, handed to the two panels. |
| `frontend/src/components/details/PlacesPricesPanel.vue` | Each example fare (every class and the all-classes average) gets a muted line with the gross amount; the example headers carry *incl. VAT 7.7 %*, with the per-country make-up as hover title (*DE 7 % on 62 % of the distance · NL 9 % on 38 %*). |
| `frontend/src/components/details/WhatFollowsPanel.vue` | Muted row *Ticket revenue incl. VAT* under the net revenue, noted *7.7 %, not in the cost and revenue calculation*; outside the total. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `prices.inclVat`, `prices.vatShare`, `follows.ticketRevenueGross`, `follows.vatRate`. 914 keys each, in parity. |
| `docs-site/demand.md` | VAT paragraph under *Places and prices*; a sentence under *What follows*. |

## Pipeline

1. `docker compose down -v && up -d --build` in `backend/docker/` (new table + seed), or on a live DB `uv run python db/migrate.py`.
2. `uv run --extra dev python -m pytest tests/test_10_params_api.py -v` — and `test_04_versioning.py` / `test_03_loader.py` as the seed changed.
3. `uv run ruff format --check` / `ruff check` on `backend/` — clean here.
4. Frontend: `vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean · `vitest run` **382 passed** (376 + 6) · `vite build` OK. Docs: `prettier --check` clean.
5. Deploy: migration runs before the API starts (existing deploy flow); API image and frontend image. An older frontend ignores the endpoint; an older backend leaves the gross lines away.

## Open

- Austria's international treatment (see above) — worth a look at a current ÖBB invoice.
- Station charges and the assumed domestic rates for EE, HU, RO, SK are the weak spots of the table; they only price a route inside that one country.

## Commit split

- `feat(demand): VAT on tickets — calibration, ticket_vat_rates table, GET /api/params/TicketVat` — backend app files, migration, ignore rules.
- `feat(builder): gross fares and gross ticket revenue, distance-weighted VAT` — frontend + docs-site.
- `test: ticket VAT endpoint and rule` — the two test files.
- `docs: VAT manifest and READMEs` — READMEs, calibration document, this file.
