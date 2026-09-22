# Migration audit before the first post-manual-demand deploy — 2026-09-22

What `db/migrate.py` will apply on staging and production, checked against
`db/schema.py` / `db/dev/sql/create_proposal_schema.sql` (the dev truth), and
what those environments can only get from a reseed.

## How migrate.py behaves

Files in `db/dev/sql/migrations/` run in filename order, each in one
transaction together with its `admin.schema_migrations` row; already-recorded
files are skipped, a recorded file missing from the folder aborts. All 19
files from `2026-09-05` on parse (pglast). The deploy runs `migrate` before
the api starts, asserts `--check`, waits for health, then
`scripts/refresh_proposals.py`.

## The four files a post-2026-09-14 database gets

| File | What it does | Checked |
|---|---|---|
| `2026-09-19_schedule_frequency.sql` | Folds `seasonal_schedules` into `routes.schedule_months`, sets it NOT NULL, drops the table; strips `schedule_mode` from every stored `compute_request` (flat seven for `alwaysDaily`); one `update_log` row per rewritten proposal. | `schedule_months` exists since `2026-09-10_route_schedule_months`; `seasonal_schedules` since `2026-08-03`; `update_log.event` is free TEXT, `user_id` nullable — the `migrated` event inserts. **Fails loudly by design** if a route has neither a map nor a projection; none should exist. |
| `2026-09-19b_manual_demand.sql` | `od_pairs.places_sold` → DOUBLE PRECISION; `shift_car_*` → `shift_other_*` (guarded); `demand_kpis_placeholder` default FALSE. | Column names and types match the dev schema. |
| `2026-09-20_proposal_scenario_summaries.sql` | New table + two indexes. | Column list and order identical to `create_proposal_schema.sql`. No backfill flag needed on this deploy: every proposal is outdated by the 09-19 version bumps, and a refresh writes the scenario rows the way a publish does. |
| `2026-09-21_ticket_vat_rates.sql` | New catalogue table, six source rows (matched by description), 41 rate rows. | **Hardened today**: rates are inserted only for country codes the database's `countries` table carries; a missing code is skipped with a NOTICE instead of failing the deploy on the FK. |

## What no migration carries — verify on staging before deploying

Two groups of columns were only ever created by `db/schema.py` (a reseed),
never by a migration:

- `input_params.stop_infrastructures` catalogue enrichment: `stop_timezone`,
  `stop_charge_vat_rate_per`, `stop_charge_incl_vat_eur`, `stop_charge_basis`,
  `stop_charge_price_basis_year`, `stop_charge_class`, `stop_charge_source`,
  `stop_provenance`, `name_latin`, `name_ascii`, `country_en…country_pl`,
  `city`, `city_osm_id`, `city_en…city_pl`, `gauges_mm`, `gauge_evidence`.
- `input_params.track_infrastructures` / `_defaults`: `track_terrain_*`,
  `track_hsr_*`, `track_min_boarding_*`, `track_min_alighting_*`,
  `track_buffer_*` and the `*_src` columns.

The loader reads these by name (`row["gauges_mm"]` …), so an environment last
reseeded before they existed would fail on the first catalogue load. The
stop catalogue's *content* (1,214 stops, gauges, charges) also arrives only
by reseed — a migration cannot carry Drive-hosted data.

Run this on staging (pgAdmin) and compare with the 41 expected names:

    SELECT column_name FROM information_schema.columns
    WHERE table_schema = 'input_params' AND table_name = 'stop_infrastructures'
    ORDER BY ordinal_position;

Expected: stop_infra_row_id, stop_id, stop_name, country_code, stop_timezone,
stop_lat, stop_lon, stop_loc_src, stop_charge_eur, stop_charge_per_tonne_eur,
stop_charge_src, stop_charge_vat_rate_per, stop_charge_incl_vat_eur,
stop_charge_basis, stop_charge_price_basis_year, stop_charge_class,
stop_charge_source, stop_provenance, name_latin, name_ascii, uic_ref,
country_en, country_de, country_fr, country_nl, country_it, country_es,
country_pl, city, city_osm_id, city_en, city_de, city_fr, city_nl, city_it,
city_es, city_pl, gauges_mm, gauge_evidence, change_log, stop_infra_version.

And the countries the VAT rows join against:

    SELECT count(*) FROM input_params.countries;   -- 41 on a current seed

If either differs, that environment needs the `reseed-staging` workflow (or
its production equivalent) once more before this deploy, not a migration —
after which every migration file is recorded as applied by the seed's
`--baseline` step.

## Migrations vs. seed on a reseeded database

A freshly seeded database already has every change; `migrate.py --baseline`
records the files without executing them. Both paths end at the same schema —
which is exactly what the two parity checks above confirm for the new tables.
