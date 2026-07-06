# Night Train — Database Layer

This folder contains everything database-related for the Night Train backend.

---

## Structure

```
db/
├── dev/                        # Dev/test database — not used in production
│   ├── sql/                    # Schema DDL — source of truth for all environments
│   │   ├── create_admin_schema.sql
│   │   ├── create_input_params_schema.sql
│   │   └── create_proposal_schema.sql
│   ├── seed.py                 # Seeds the database with illustrative test data
│   ├── sql_loader.py           # Loads .sql files from the sql/ folder
│   ├── Dockerfile              # Builds the seeder image
│   ├── docker-compose.yml      # Standalone stack: postgres + seeder + Mathesar
│   └── .env.example            # Default credentials for local use (POSTGRES_* only)
└── README.md                   # This file
```

---

## For database architects — standalone stack

The standalone stack in `db/dev/` lets you spin up postgres, seed it with
illustrative test data, and inspect the full schema via Mathesar — independently
of the backend API.

**Quickstart:**
```bash
cd backend/db/dev
cp .env.example .env        # default values work out of the box
docker-compose up --build
```

This starts three services:

- **postgres** — PostgreSQL 16, seeded data persisted in the `pgdata` volume
- **seeder** — runs once, drops and recreates all three schemas, loads test data, then exits
- **mathesar** — web UI for schema inspection, starts once Postgres is healthy

On success, `seeder` exits with code 0 and prints row counts for every table.

**Resetting to a clean slate:**
```bash
docker-compose down -v      # -v removes the postgres volume
docker-compose build --no-cache seeder
docker-compose up -d
```

---

## For backend developers

Backend developers do not use this stack directly. The database starts automatically
as part of the main backend Docker stack — seeding runs via the API container's
entrypoint before Flask starts.

```bash
cd backend/docker
docker-compose up -d        # starts postgres, openrailrouting, and api
```

See `backend/DEVELOPMENT.md` for the full backend developer setup guide.

---

## The SQL schemas

The files in `db/dev/sql/` are the **source of truth** for the database structure
across all environments — dev, test, and production.

When setting up the production database, run these files once manually
(without the seed data in `seed.py`). Migration tooling will be added in a later phase.

---

## Schema overview

Three schemas: `admin`, `input_params`, `proposals`.

### `admin`

| Table | Description |
|---|---|
| `users` | Platform users (email-based, placeholder for OTP/magic-link auth) |
| `feedback` | User feedback submissions |

### `input_params`

| Table | Description |
|---|---|
| `sources` | Reusable registry of data sources referenced by all parameter tables |
| `countries` | ISO 3166-1 alpha-2 country reference table |
| `service_classes` | Accommodation class taxonomy (Seat, Couchette, Sleeper, Capsule, Catering) with density |
| `operators` | Train operating companies — driver/crew rates, overhead quotas, shunting costs |
| `operator_class_costs` | Service & stockings cost per place, per operator per service class |
| `coach_types` | Individual railcar types with physical attributes and crew factor. Not versioned — a changed spec means a new coach_type_id |
| `coach_type_classes` | Places per service class within a coach type |
| `composition_types` | Train formation blueprints: operational and cost parameters. Not versioned — a changed setting means a new composition_type_id |
| `composition_type_coaches` | Ordered coach slots per composition type |
| `track_infrastructure_defaults` | EU-average fallback track parameters, versioned |
| `track_infrastructures` | Country-level track parameters (TAC, energy price, terrain etc.), versioned, with per-field `_src` columns |
| `stop_infrastructure_defaults` | Fallback station access charge per country (NULL = global), versioned |
| `stop_infrastructures` | Night train stopping points with coordinates and charges, versioned |

### `proposals`

GTFS-compatible tables plus a project-specific `proposals` evaluation table.
All GTFS IDs follow the convention `P{proposal_id}_V{version}_R1[_D{dir}_T{idx}]`.

| Table | Description |
|---|---|
| `services` | GTFS service registry |
| `calendar` | GTFS calendar.txt — regular weekly service pattern |
| `calendar_dates` | GTFS calendar_dates.txt — per-date exceptions |
| `shapes` | Route geometry as GeoJSON LineString in JSONB |
| `routes` | GTFS routes.txt — one row per proposal version route |
| `trips` | GTFS trips.txt — one scheduled run per proposal version |
| `stop_times` | GTFS stop_times.txt — ordered stop sequence per trip (times as INTERVAL) |
| `proposals` | Project-specific versioned evaluation table. `proposal_id` is stable across versions; `proposal_version` increments on every change. `parameter_snapshot` JSONB records the exact ParamVersions used |

---

## Connection details

| | |
|---|---|
| Database | `target_network_test_db` |
| Username | `bot_admin` |
| Password | see `POSTGRES_PASSWORD` in your `.env` |
| Port | `5432` |

## Access via Mathesar

Mathesar runs as a container on the same Docker network as Postgres.

1. With the stack running, open `http://localhost:8000/`
2. First visit prompts you to create a Mathesar admin account
3. Add a new database connection:
   - Host: `postgres`
   - Port: `5432`
   - Database: `target_network_test_db`
   - Username: `bot_admin`
   - Password: from `.env`

## Access via pgAdmin

pgAdmin runs on your machine and connects via the published host port.

1. Download pgAdmin: https://www.pgadmin.org/download/
2. Register a new server:
   - Host: `localhost`
   - Port: `5432`
   - Database: `target_network_test_db`
   - Username: `bot_admin`
   - Password: from `.env`