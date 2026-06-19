# Night Train Test Database — Setup Guide

This spins up a local Postgres instance with the three project schemas (`admin`, `input_params`, `proposals`), seeded with illustrative test data, plus two ways to browse it: pgAdmin and Mathesar.

## Prerequisites

- Docker Desktop installed and running
- The project's `docker-compose.yml`, `Dockerfile`, `.env`, `seed_database.py`, `sql_loader.py`, and `sql/` folder (containing `create_admin_schema.sql`, `create_input_params_schema.sql`, `create_proposal_schema.sql`) all in the same directory

## Starting the database

From that directory:

```powershell
docker-compose up --build
```

This starts three services:

- **postgres** — Postgres 16, with seeded data persisted in the `pgdata` volume
- **seeder** — runs once, drops and recreates all three schemas, loads test data, then exits
- **mathesar** — Mathesar's web UI, starts once Postgres is healthy

On success, `seeder` exits with code 0 and prints row counts for every table. `postgres` and `mathesar` keep running afterward.

To reset everything and start from a clean slate:

```powershell
docker-compose down -v
docker-compose up --build
```

## Schema overview

### `admin`

| Table | Description |
|---|---|
| `users` | Platform users (email-based, placeholder for OTP/magic-link auth) |
| `feedback` | User feedback submissions with optional notification tracking |

### `input_params`

| Table | Description |
|---|---|
| `sources` | Reusable registry of data sources. Referenced by all versioned parameter tables via `source_id` (row-level default) and `column_sources` JSONB (per-column overrides where a column comes from a different source than the rest of the row) |
| `stops` | Night train stopping points, versioned |
| `stop_defaults` | Fallback station access charge when a stop has no explicit value, versioned |
| `infrastructure` | Country-level infrastructure parameters (TAC, energy price, terrain, boarding times etc.), versioned |
| `infrastructure_defaults` | EU-average fallback infrastructure parameters, versioned |
| `classes` | Stable accommodation class taxonomy (Seat, Couchette, Sleeper, Capsule, Catering) |
| `operators` | Train operating companies bearing costs — driver/crew rates, overhead quotas, shunting costs etc. Distinct from a GTFS agency (the passenger-facing booking brand); maps to `agency_id` on GTFS export |
| `operator_class_costs` | Service & stockings cost per place, per operator per accommodation class |
| `coachtypes` | Individual railcar types with physical attributes and crew factor, versioned |
| `coachtype_classes` | Places per accommodation class within a coach type (replaces the wide slot columns from the Excel source) |
| `compositions` | Train formations: operational and cost parameters. Capacity is derived from `composition_coaches` → `coachtype_classes`, not stored directly |
| `composition_coaches` | Ordered coach slots per composition (replaces the wide `coach_01_type`…`coach_14_type` columns) |

### `proposals`

GTFS-compatible tables (`services` through `stop_times`) plus a project-specific `proposals` table for cost/revenue/climate evaluations.

| Table | Description |
|---|---|
| `services` | GTFS service registry — the entity that `calendar` and `calendar_dates` attach active dates to |
| `calendar` | GTFS `calendar.txt` — regular weekly service pattern with start/end dates |
| `calendar_dates` | GTFS `calendar_dates.txt` — per-date exceptions, or a fully enumerated irregular schedule when used without `calendar` |
| `shapes` | Route geometry stored as a GeoJSON LineString in JSONB (one row per shape, not the GTFS per-point format). On GTFS export, explode coordinates into one row per point |
| `routes` | GTFS `routes.txt` — one row per named night train line. `route_type` 105 = Sleeper Rail Service. `agency_id` nullable for now, populated on GTFS export from `input_params.operators` |
| `trips` | GTFS `trips.txt` — one scheduled run of a route. `composition_id` is a project extension linking to the rolling stock |
| `stop_times` | GTFS `stop_times.txt` — ordered stop sequence per trip. Times stored as `INTERVAL` to support GTFS overnight convention (values above `24:00:00`) |
| `proposals` | Project-specific: one versioned row per saved cost/revenue/climate evaluation of a route. Carries a `parameter_snapshot` JSONB recording the exact model version, parameter row IDs, versions, sources, and column comments used — making every evaluation fully reproducible |

## Connection details

Whichever tool you use to browse the data, the database itself is:

| | |
|---|---|
| Database | `target_network_test_db` |
| Username | `bot_admin` |
| Password | see `.env` → `POSTGRES_PASSWORD` |
| Port | `5432` |

## Access via pgAdmin

pgAdmin runs directly on your machine (not in Docker), so it reaches Postgres through the port Docker published to the host.

1. Download and install pgAdmin: https://www.pgadmin.org/download/pgadmin-4-windows/
2. In pgAdmin, right-click **Servers** → **Register** → **Server...**
3. **General** tab: give it any name, e.g. `Night Train Test DB`
4. **Connection** tab:
   - Host: `localhost`
   - Port: `5432`
   - Maintenance database: `target_network_test_db`
   - Username: `bot_admin`
   - Password: from `.env`
5. Save. The server should appear in the tree with `admin`, `input_params`, and `proposals` schemas underneath.

## Access via Mathesar

Mathesar runs as a container on the same Docker network as Postgres, so it connects by service name rather than `localhost`.

1. With the stack running, open `http://localhost:8000/`
2. First visit prompts you to create a Mathesar admin account
3. Add a new database connection with:
   - Host: `postgres`
   - Port: `5432`
   - Database: `target_network_test_db`
   - Username: `bot_admin`
   - Password: from `.env`

Mathesar also manages its own separate internal database for its app state (accounts, saved connections) — that's unrelated to `target_network_test_db` and needs no configuration.

## Verifying the parameter snapshot

After seeding, the `proposals.proposals` table contains one demo evaluation of the Berlin–Wien route. To verify the snapshot was assembled correctly:

```sql
SELECT
    proposal_id,
    parameter_snapshot->>'model_version'                                                        AS model_version,
    parameter_snapshot->>'generated_at'                                                         AS generated_at,
    ARRAY(SELECT jsonb_array_elements(parameter_snapshot->'infrastructure')->>'country_code')   AS infra_countries,
    ARRAY(SELECT jsonb_array_elements(parameter_snapshot->'coachtypes')->>'coachtype_id')       AS coachtype_ids,
    ARRAY(SELECT jsonb_array_elements(parameter_snapshot->'stops')->>'stop_id')                 AS stop_ids
FROM proposals.proposals;
```

Expected result: `model_version = v1.0.0`, `infra_countries = {DE,AT}`, `coachtype_ids = {type2}`, `stop_ids = {DE_BERLIN_HBF, DE_DRESDEN_HBF, AT_WIEN_HBF}`.