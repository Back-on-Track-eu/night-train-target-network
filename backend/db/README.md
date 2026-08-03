# Night Train — Database Layer

This folder contains everything database-related for the Night Train backend.

**Related documentation:** API endpoints reading these tables —
[`../api/README.md`](../api/README.md) · loader consuming the seed
(`DBDataLoader`) — [`../models/README.md`](../models/README.md) · seed
assertions in the test suite — [`../tests/README.md`](../tests/README.md)

---

## Structure

```
db/
├── dev/                        # Dev/test database — not used in production
│   ├── sql/                    # Schema DDL — source of truth for all environments
│   │   ├── create_admin_schema.sql
│   │   ├── create_input_params_schema.sql
│   │   ├── create_scenario_schema.sql
│   │   ├── create_proposal_schema.sql
│   │   └── create_ontd_schema.sql     # separate/optional — see "ontd schema" below
│   ├── seed.py                 # Seeds admin/input_params/scenario/proposals; operational
│   │                           # parameters come from models/compositions/calib/seed/*.csv
│   ├── sql_loader.py           # Loads .sql files from the sql/ folder
│   ├── ontd_loader.py          # Separate script: loads the ontd schema from the ONTD GitHub snapshot
│   ├── Dockerfile              # Builds the seeder image
│   ├── docker-compose.yml      # Standalone stack: postgres + seeder + Mathesar
│   └── .env.example            # Default credentials for local use (POSTGRES_* only)
└── README.md                   # This file
```

---

## Calibration seed CSVs (derived artifacts)

`seed.py` reads the operational parameters (operators, coach types with
per-class sections, the eight standard compositions, class cost
allocation) from `models/compositions/calib/seed/*.csv`. These CSVs are
**derived artifacts and not committed** — the calibration notebook
`models/compositions/calib/02_calibration.ipynb` is the source of truth,
and its derivations are documented in `calib/CALIBRATION.md`.

When the CSVs are absent, `seed.py` regenerates them automatically by
executing the notebook's compute + export cells directly from the
`.ipynb` JSON (no jupyter needed). That path is **stdlib-only by
contract** — the notebook's export cell documents the constraint — so it
works inside the API container and in CI, where dev extras (pandas,
matplotlib) are not installed; display/validation/chart cells are
skipped by code-token detection. To update values: re-run the notebook,
never edit seed.py or the CSVs by hand.

The 2026-07-22 schema redesign (real coach types, per-section class
entries with geometry, composition crew/loco/allocation columns,
retirement of `service_class_density`) is documented column-by-column in
the DDL comments (`sql/create_input_params_schema.sql`) and in the
migration `sql/migrations/2026-07-22_composition_redesign.sql`.

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
- **seeder** — runs once, drops and recreates all four core schemas, loads test data, then exits
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

`create_*.sql` + `seed.py` always represent the **latest** schema and are for
**local databases only** (the seeder drops and recreates). Server databases
(staging, production) are never reseeded — they move forward exclusively
through `db/dev/sql/migrations/*.sql`, applied by `db/migrate.py`.

### Migrations (`db/migrate.py`)

Every schema change ships twice: folded into the `create_*.sql` files (so a
fresh local seed is already current) **and** as a dated migration file
`migrations/YYYY-MM-DD_name.sql` (so server databases with existing data can
move forward). The date prefix defines execution order.

`migrate.py` records applied filenames in `admin.schema_migrations` (created
on first contact) and applies each pending file **in one transaction together
with its tracking row** — a crash can't leave a migration applied-but-
unrecorded. Because the runner owns the transaction, **new migration files
must not contain their own `BEGIN;`/`COMMIT;`** (standalone transaction-control
lines are stripped for older files that predate this rule).

```
python db/migrate.py              # apply pending migrations
python db/migrate.py --dry-run    # list pending, change nothing
python db/migrate.py --check      # exit 2 if pending (deploy assertion)
python db/migrate.py --baseline   # record all as applied, execute nothing
```

`--baseline` exists for databases whose schema already contains the changes
(a fresh seed, or a server DB that received the files by hand): run it exactly
once, then never again. Deploys run `migrate.py` before starting the API, so
a deployed backend can never meet a database missing its schema changes.

Editorial rule for the stop tables: base and HSR lineages stay identical only
by construction — a stop-charge correction must **fan out to every current
scenario lineage**, and a partial reseed of `input_params`/`scenario` that
preserves `proposals` would dangle pinned `scenario_id`s. Reseed = everything
or nothing.

### The proposals redesign — two-phase migration (in progress)

The `proposals` schema is mid-redesign per
[`docs/PROPOSALS_DESIGN.md`](../../docs/PROPOSALS_DESIGN.md); see that
doc's §10 for the full work-package plan. The migration is deliberately
**two-phase** so the full test suite stays green after every single work
package instead of only at the end:

- **Phase 1** (`migrations/2026-08-03_proposal_schema_phase1.sql`, WP1) —
  strictly additive: new sidecar tables, `update_log`,
  `proposal_summaries`, and the compute cache land alongside the
  existing persist-on-calc tables/columns, which keep running untouched.
  Nothing dropped, no constraint the old code violates.
- **Phase 1b** (`migrations/2026-08-03_proposal_schema_phase1b_auto_added.sql`,
  WP3) — one additional nullable column (`stop_times.auto_added`) phase 1
  missed; see the `proposals` schema section below for why. WP3 also
  landed the sidecar tables' write/read path
  (`api/helpers/route_gtfs_serialize.py`), round-trip-tested but not yet
  wired into any live endpoint.
- **Phase 2** (WP5) — the single cutover migration: drops
  `route_body`/`evaluation_body`/`is_current`/`change_log`, enforces the
  final `NOT NULL`s, and lands in the same PR as the code that requires
  the new shape. Decided data strategy: **drop and recreate, no row
  migration** — current stored proposals are pre-launch test artifacts,
  and `update_log`/`likes`/`comments` survive structurally since they
  already use soft references.

---

## Schema overview

Four core schemas, all created and seeded by `seed.py`: `admin`, `input_params`,
`scenario`, `proposals`. A fifth, `ontd`, exists separately — see below.

### `admin`

| Table | Description |
|---|---|
| `users` | Platform users — `user_id` identity, `user_name` display name, `email` login identity (placeholder for OTP/magic-link auth) |
| `feedback` | User feedback submissions — `user_id` (logged-in) or `email` (anonymous) identifies the author, `category`/`sub_category` are free text, `notified_at` is set once the notification mail to the working group succeeds |

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

### `scenario`

| Table | Description |
|---|---|
| `scenarios` | Container pinning one version of each of the four versioned `input_params` infrastructure tables (`track_infrastructures`, `track_infrastructure_defaults`, `stop_infrastructures`, `stop_infrastructure_defaults`). Every read of infrastructure data goes through a scenario — there's no other notion of "current" for those four tables. Exactly one row has `is_current_base = TRUE` (the live default used when an API call omits `scenario_id`); exactly one row per `scenario_key` has `is_current_scenario = TRUE` (the head of that what-if lineage). `scenario_id` is a surrogate key that changes on every edit; `scenario_key` (e.g. `"base"`, `"2032-baseline-hsr-allowed"`) is the stable identifier for one lineage. Compositions, coach types, operators, and composition references are catalogs, not scenario-versioned — see `input_params` above. |

A version bump on any of the four pinned tables is a **full-table snapshot**,
never a per-row diff: editing one stop's charge duplicates every other row of
`stop_infrastructures` forward into the new version too, so resolution is
always an exact match (never "highest version ≤ N") and a version number is
never reinterpreted differently depending on which scenario is asking. This
is what makes two scenarios branching off the same table in incompatible
directions safe, and what makes re-evaluating a scenario next year return
the same numbers even if the base has since moved on — nothing on a
`scenarios` row is resolved at read time. `seed.py` seeds three scenarios,
each pinning its own version number (in lockstep, across all four tables —
every scenario owns a complete, independent snapshot rather than sharing
rows with another scenario):

- `"2026-baseline"` (version 1) — **2026 Base Line**, a deprecated historical
  reference (`is_current_base = FALSE`, `is_current_scenario = FALSE`). Only
  `track_infrastructures`/`track_infrastructure_defaults` carry genuinely
  different figures (DE's pre-correction rates, a slightly lower EU-average
  default); the stop-side tables are duplicated with identical values.
- `"base"` (version 2) — **2032 Base Line**, the live default
  (`is_current_base = TRUE`). `track_hsr_allowed = FALSE` everywhere.
- `"2032-baseline-hsr-allowed"` (version 3) — **2032 Base Line + Night
  Trains on HSR allowed**, a second current lineage head
  (`is_current_scenario = TRUE`, `is_current_base = FALSE`). Identical to
  `"base"` in every field except `track_hsr_allowed = TRUE` everywhere.

See `create_scenario_schema.sql` for the full column-level rationale.

### `proposals`

GTFS-compatible tables plus a thin project-specific `proposals` version
container. All GTFS IDs follow the convention
`P{proposal_id}_V{version}_R1[_D{dir}_T{idx}]`.

The route — and, once evaluated, its evaluation — is stored twice: once
verbatim as JSON (`route_body` / `evaluation_body`, the names `GET
/api/proposal/<id>` returns, see `api/README.md`), once decomposed into
the GTFS tables below (the route only — evaluation results have no GTFS
equivalent). Since persist-on-calc (2026-07-16) both are written by the
pipelines themselves: `POST /api/route/plan` persists its own response as
`route_body`, `POST /api/evaluation/calc` persists its own response as
`evaluation_body`. These two columns are `JSON`,
deliberately not `JSONB` — `JSONB`'s decomposed binary storage does not
preserve original key order (confirmed empirically: a value round-tripped
through `JSONB` comes back with keys in a different order than it went
in), which defeats the point of a column that exists specifically to
hand back the exact bytes originally posted to `/api/route/plan` and
`/api/evaluation/calc`. `JSON` (the text-based type) preserves an exact
copy of the input, key order included. The tradeoff: `JSONB`-only
operators (`-`, `#-`, `@>`, `<@`, `?`, `?|`, `?&`, `||`) and GIN indexing
aren't available directly on these two columns — queries needing them
cast explicitly with `::jsonb` (see `list_current()` in
`adapters/proposal_repository.py`), a read-only cast with no effect on
what's stored. Neither column is trimmed before storing, so
`evaluation_body`'s `input.route` ends up holding a full second copy of
the same route already in `route_body.route` — a deliberate simplicity
tradeoff (see the schema comments in `create_proposal_schema.sql`), not
an oversight: since persist-on-calc both bodies are produced by the
pipelines themselves, so they agree by construction (`POST
/api/evaluation/calc` refuses to persist against a version whose stored
route no longer matches the posted one — `route_mismatch`), and this
table can never hold two disagreeing versions of one proposal's route. `evaluation_body` is a
point-in-time snapshot of a `POST /api/evaluation/calc` response — not
re-derived — so it can drift from a fresh call if parameters change
later, the same tradeoff scenario pinning already makes elsewhere. List
summaries read `total_revenue_eur`/`total_cost_eur`/`net_eur` out of
`evaluation_body -> views -> route -> data -> per_year`.

| Table | Description |
|---|---|
| `services` | GTFS service registry |
| `calendar` | GTFS calendar.txt — regular weekly service pattern |
| `calendar_dates` | GTFS calendar_dates.txt — per-date exceptions |
| `shapes` | Route geometry as GeoJSON LineString in JSONB |
| `routes` | GTFS routes.txt — one row per proposal version route |
| `trips` | GTFS trips.txt — one scheduled run per proposal version |
| `stop_times` | GTFS stop_times.txt — ordered stop sequence per trip (times as INTERVAL) |
| `proposals` | Version container. `proposal_id` is stable across versions; `proposal_version` increments on every persisted change (append-only — the single exception is `evaluation_body`, filled in place on the version it was computed for while still NULL, see the 2026-07-16 migration); `is_current` flags the latest version per `proposal_id`. `route_body` JSON holds the exact `POST /api/route/plan` response the version was saved from, key order preserved; `evaluation_body` JSON (nullable) holds the `POST /api/evaluation/calc` response, if one was saved, same guarantee |
| `likes` | Thumbs-up on a proposal, one per user (`UNIQUE(proposal_id, user_id)`), no down-vote. Keys on the stable `proposal_id`, not a specific version — see below |
| `comments` | Flat (non-threaded) discussion per proposal. Soft-deleted (`is_deleted`, body cleared server-side) rather than removed, so the thread stays chronologically intact |

`likes`/`comments` (2026-07-29, `api/proposal_engagement.py`) key on
`proposal_id` alone rather than `(proposal_id, proposal_version)` — a like
or a comment is about the proposal as an ongoing discussion, not one
snapshot of it, and survives the proposal being edited into a new
version. Because `proposal_id` alone isn't unique on `proposals.proposals`
(the primary key is the composite pair), it can't be an FK target there;
both tables carry it as a **soft reference**, the same convention already
used for `stop_times.stop_id` and `trips.composition_type_id` —
existence is checked at the API layer
(`adapters/proposal_engagement_repository.py`) instead of by a DB
constraint. Each row also stamps the `proposal_version` that was current
at the moment of the like/comment, as read-only context — it is never
re-derived if the proposal is later versioned.

Both tables' `user_id` is reassigned on a guest→registered merge
(`adapters/auth_repository.py: merge_guest_into()`, see `api/README.md`'s
Auth section), same as `proposals.proposals.user_id` and
`admin.feedback.user_id` — a guest's likes and comments follow them into
their verified account. `likes` needs one extra step the others don't:
its `UNIQUE(proposal_id, user_id)` means the guest and the target account
could already both have liked the same proposal, so the guest's copy is
dropped in that case (the target's own like already counts) before the
rest are reassigned — the merge never fails on this, it just avoids a
constraint violation.

**Proposals redesign, schema phase 1 (2026-08-03, additive-only — see the
two-phase migration note above).** `proposals.proposals` gained two
nullable columns ahead of the WP5 cutover: `route_fingerprint` (route
identity fingerprint, informational only) and `compute_request` (resolved
`POST /api/proposal/calc` request, verbatim — mirrors `route_body`'s
JSON-not-JSONB key-order rationale). `stop_times` gained a nullable
`stop_type` column (lossless boarding/alighting/night/both
classification). None of the three is populated by the current
persist-on-calc write path (`adapters/proposal_repository.py`'s
`_insert_gtfs()`, still unchanged) — that stays true until WP5's cutover
replaces it.

**Phase 1b (`migrations/2026-08-03_proposal_schema_phase1b_auto_added.sql`,
WP3).** `stop_times` gained a third nullable-in-name-only column,
`auto_added BOOLEAN NOT NULL DEFAULT FALSE` — mirrors
`Stop.auto_added` (`models/route/trip.py`). Phase 1 missed this one: it's
not derivable after the fact (a record of what the one-time
`auto_stop_addition` candidate search decided, not something
recomputable from stored physics), so WP3 added it alongside the sidecar
write path below rather than silently losing the field on every
reconstruction.

The phase 1 migration adds ten new tables. As of WP3
(`api/helpers/route_gtfs_serialize.py`, `insert_route_gtfs()`/
`route_dict_from_gtfs()`), they're no longer empty in principle — that
module is a **complete, standalone GTFS+sidecar write/read path**,
round-trip-tested end to end (`tests/test_36_proposal_gtfs_roundtrip.py`)
against real `POST /api/proposal/calc` (WP2) responses. It is
deliberately **not** wired into the live persist-on-calc pipeline yet
(`adapters/proposal_repository.py`'s `_insert_gtfs()` stays untouched and
is what every current endpoint still uses) — WP5 is what retires the old
write path and switches the real `POST /api/proposal/publish` endpoint
over to this one. Until then, rows only exist here during test runs:

| Table | Description |
|---|---|
| `segments` | One row per `Segment` (`models/route/trip.py`) — the atomic per-stop-pair physics unit of a trip (distance, driving/dynamics/buffer/slack time, energy, per-country shares). Composite PK `(trip_id, segment_sequence)`. Geometry stored per-segment on `shapes` (`{trip_id}_L{i}_SHAPE`, mirroring `route_to_dict()`'s own `geometry_id` convention) — WP3's write path deliberately doesn't also write a concatenated per-trip shape the way the old `_insert_gtfs()` does; `trips.shape_id` is left `NULL` |
| `od_pairs` | One row per `ODPair` (`models/params.py`) — demand for one origin-destination pair, one accommodation class, one trip. `avg_price NUMERIC(10,2)` genuinely rounds the stopgap demand model's raw output (`distribute_demand()`'s flat per-km fare × distance, e.g. `77.38690000000001`) to the cent — correct precision for a EUR column, not a bug; the round-trip tests round the expected side the same way rather than asserting exact equality against a value that was never going to survive real storage |
| `parkings` | One row per `Parking` (`models/route/route.py`) — overnight parking location, deduplicated by `stop_id` within the route; `trip_ids` lists every trip that parks there |
| `shuntings` | One row per `Shunting` (`models/route/route.py`) — one shunting event at a trip terminal; not deduplicated, up to 4 rows per round trip |
| `timetable_warnings` | One row per `TimetableWarning` (`models/route/trip.py`) — a derived timetable quality annotation, informational only |
| `seasonal_schedules` | One row per `SeasonalSchedule` (`models/route/route.py`) — operating frequency (daily/three_per_week) per season on a route |
| `update_log` | Append-only timeline event log (published/overwritten/recalculated/branched_from/branched_to) — preserves state transitions that `proposals.proposals` itself prunes on overwrite. Still unpopulated — lands with WP5 |
| `proposal_summaries` | Derived projection over `proposals.proposals` for the gallery/map — route metrics, financial KPIs, placeholder demand KPIs, simplified PostGIS geometry. Not a source of truth; rebuildable at any time. The row-building logic (`adapters/proposal_projection.py`'s `build_summary_row()`, WP4) is complete and round-trip-tested against this table's schema (`tests/test_37_proposal_projection.py`), but nothing writes here from a real endpoint yet — still unpopulated in practice until WP5 wires the publish handler |
| `compute_cache_pointer` | Compute cache, pointer side — `request_hash` → which result it resolves to, plus request-specific response parts. `UNLOGGED`. Still unpopulated — lands with WP13 |
| `compute_cache_result` | Compute cache, result side — `(route_fingerprint, scenario_id, composition_id)` → the shared route + evaluation payload, stored once per distinct result. `UNLOGGED`. Still unpopulated — lands with WP13 |

Segments/od_pairs/timetable_warnings key off `trip_id`; parkings/shuntings/
seasonal_schedules key off `route_id` — matching where each field lives on
the `Route`/`Trip` domain objects (route-level vs. trip-level), same
soft-reference convention as `stop_times.stop_id`. See
`docs/PROPOSALS_DESIGN.md` §5.2/§4.1/§5.4/§2.3 for the full rationale and
`migrations/2026-08-03_proposal_schema_phase1.sql` for the DDL and
column-level comments.

**Seed data.** `db/dev/seed.py` seeds exactly one proposal (`proposal_id=1`
— the natural first-insert outcome on a fresh DB, no reservation needed —
Berlin Hbf → Dresden Hbf → Wien Hbf, owned by David) — saved through
`adapters.proposal_repository.ProposalRepository.save()`, the same code
path the persist-on-calc pipelines use, so the seeded GTFS rows and the
`proposals.proposals` row that owns them are structurally identical to a
real persisted plan rather than a hand-maintained parallel representation. This
keeps the "every GTFS row is linked to a real proposal" invariant true
with no exception, including at seed time. It's saved without an
evaluation, so its financial fields are null until someone evaluates and
re-saves it. `proposal_id=1` is collision-free because
`tests/conftest.py`'s route-fixture draft placeholders live at `100`+
(see that file's range-convention comment) and
`tests/test_50_proposals_api.py`'s own sequence floor is `1000`+. Every
saved proposal's GTFS service, seeded or live, is pinned to the project's
target 2032 timetable year (`ProposalRepository._SERVICE_START`/
`_SERVICE_END`).

---

## The `ontd` schema (separate, optional)

`ontd` mirrors the [Open Night Train Database](https://github.com/Back-on-Track-eu)
— a community-maintained Google Sheet of real-world night train agencies,
stops, and trips (source of truth: the Sheet, owned by Juri Maier). It is
**not** created or seeded by `seed.py` — it's a separate concern, loaded on
demand with:

```bash
python db/dev/ontd_loader.py                  # fetch the latest snapshot from GitHub
python db/dev/ontd_loader.py --local /path     # load from a local data/latest/ export
```

`ontd_loader.py` is idempotent (`TRUNCATE ... CASCADE`s all `ontd` tables
before each load) and never touches `admin`/`input_params`/`scenario`/`proposals`.
`ontd.stops.stop_id`/`stop_uic_code` are aligned with `input_params.stops.stop_id`
by convention (agreed Giovanni ↔ David, 2026-06-22), but there's no FK between
the schemas — `ontd` is reference data for comparison/import tooling, not a
live dependency of the API.

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