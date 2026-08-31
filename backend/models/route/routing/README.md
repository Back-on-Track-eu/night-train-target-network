# Night Train Target Network — Routing Infrastructure

This folder contains the OpenRailRouting server used to calculate rail travel times
and distances between stations. It runs as a Docker container and exposes a REST API on the host port configured in `backend/docker/.env`
(`OPENRAILROUTING_HOST_PORT_INFRA_2026`, default 8989). With this self-hosted setup,
request limits depend only on your local machine — not on the public
https://routing.openrailrouting.org/maps/ instance — and routing settings can
be adjusted individually.

How the backend consumes this server (`rail_router.py`, routing modes) is
documented in [`../../README.md`](../../README.md); the day-to-day backend
workflow that assumes this graph already exists is in
[`../../../DEVELOPMENT.md`](../../../DEVELOPMENT.md).



---

## Prerequisites

Install the following tools before starting:

| Tool | Download | Notes |
|---|---|---|
| Docker Desktop | https://www.docker.com/products/docker-desktop | Make sure the engine is running |
| Git | https://git-scm.com/download/win | Add to system PATH during install |

No Java, Maven, or Node.js required — everything runs inside Docker.

---

## Folder Structure

```
models/route/routing/docker/
├── Dockerfile                  # builds the routing server image
├── docker-compose.yml          # standalone routing-only stack (for graph import)
├── config.yml                  # GraphHopper / OpenRailRouting configuration
├── custom_models/
│   ├── night_train.json        # shared base model for every gauge profile
│   └── nt_gauge_<mm>.json      # one per gauge family: 1435, 1520 (+1524), 1600, 1668
├── data-infra-2026/            # ← NOT in git — place OSM file here
│                               #    (one data-<key>/ dir per routing graph)
│   └── europe-latest.osm.pbf
└── graph-cache-infra-2026/     # ← NOT in git — generated during import
                                #    (one graph-cache-<key>/ dir per graph)
```

---

## Multiple Graphs (Infrastructure Scenarios)

A GraphHopper process serves many profiles but exactly **one graph** — a
second OSM base (e.g. the 2032 upgraded-network file) is therefore a second
container, not a second profile. The backend stack is prepared for this:

* Each graph has a **key** (`infra_2026` = today's network, `infra_2032` =
  the upgrade). Scenarios pin their graph via
  `scenario.scenarios.routing_graph_key`; the backend holds one `RailRouter`
  per configured key (`api/helpers/dependencies.py`).
* The second instance lives in `backend/docker/docker-compose.yml` as
  service `openrailrouting-infra-2032`, gated behind compose profile
  `infra-2032` and **off by default**. It reuses this folder's image,
  `config.yml` and `custom_models/` unchanged (identical gauge profiles on
  every instance). Every instance mounts its own `data-<key>/` and
  `graph-cache-<key>/` host directories (none in git — the repo
  `.gitignore` wildcards cover them; keep `graph-cache-*/` in
  `.git/info/exclude` for branch-suffixed copies).
* Enabling it is three lines in `backend/docker/.env` —
  `COMPOSE_PROFILES=infra-2032`, `OPENRAILROUTING_URL_INFRA_2032`,
  `GRAPH_CACHE_FILE_ID_INFRA_2032` — see `.env.example`.
* **Every per-graph setting is suffixed with the graph key**, the
  default graph included: `OPENRAILROUTING_URL_<KEY>`,
  `OPENRAILROUTING_HOST_PORT_<KEY>`,
  `OPENRAILROUTING_ADMIN_HOST_PORT_<KEY>`, `GRAPH_CACHE_FILE_ID_<KEY>`.
  No instance is implicitly "the" router. `OPENRAILROUTING_CONTAINER_PORT`
  is the one exception — all instances share `config.yml`, so they bind
  the same port internally. The contract lives in `rail_router.py`.

### Bringing up a second graph

The worked example is `infra_2032`, but nothing below is specific to it —
the same six steps apply to any new graph key.

**The OSM filename is a contract.** `config.yml` reads
`datareader.file: /app/data/europe-latest.osm.pbf`, and that config is
baked into the image every instance shares, so each graph's `data-<key>/`
directory must present its extract under exactly that name. A file called
anything else is silently not read. Renaming `datareader.file` to
something more honest is not worth it: CI keys its graph cache on
`hashFiles(config.yml)`, and GraphHopper validates a cache against the
config it was built with, so the edit costs a re-import and re-upload of
every existing graph for a cosmetic gain.

```powershell
# 1. Place the extract under the contract name, clear any stale one
cd backend\models\route\routing\docker
Move-Item -Force <source>.osm.pbf .\data-infra-2032\europe-latest.osm.pbf

# 2. The import must start from an EMPTY cache — over a populated one it
#    loads the existing graph and reports success without reading the new
#    extract. entrypoint.sh refuses the run rather than let that happen.
Remove-Item -Recurse -Force .\graph-cache-infra-2032 -ErrorAction SilentlyContinue

# 3. Import (~30-45 min, needs 24 GB free to the Docker VM — on Windows
#    that is a .wslconfig memory setting, not host RAM)
cd ..\..\..\..\docker
docker compose --profile infra-2032 run --rm openrailrouting-infra-2032 `
  java -Xmx24g -Xms1g -jar railway_routing.jar import config.yml

# 4. Start the instance and verify it (next section) BEFORE uploading
docker compose --profile infra-2032 up -d openrailrouting-infra-2032
uv run python scripts/verify_routing_graph.py --graph infra_2032 --against infra_2026
```

Only once that passes: zip `graph-cache-infra-2032/`, upload to Drive, and
put the file id into `GRAPH_CACHE_FILE_ID_INFRA_2032` so servers download
it exactly like the base graph. Then uncomment the three `_INFRA_2032`
lines in `backend/docker/.env` and restart the stack; the API logs
`Routing graphs configured: ...` with every registered key at startup.

Do NOT compare OSM file sizes as a coverage check. An extract prepared for
this stack is filtered down to railway data and is orders of magnitude
smaller than a full Geofabrik `europe-latest.osm.pbf` — the comparison
that carries information is between graph caches, after the import.

### Verifying a newly imported graph

`scripts/verify_routing_graph.py` is the acceptance gate. It talks HTTP to
the routing engines only — no API, no database, no seeded scenario — so it
runs before the graph is registered anywhere:

```powershell
uv run python scripts/verify_routing_graph.py --graph infra_2032 --against infra_2026
```

| Check | What a failure means |
|---|---|
| `/info` profile lists identical across instances | The image or the cache is out of step with this source tree |
| `/info` bounding boxes side by side | Coverage lost — the extract does not span the same area |
| Gauge matrix, should-route rows | Missing network for that gauge |
| Gauge matrix, should-block rows | **The gauge tags did not survive into the graph** |
| Corridor delta against the reference graph | Near-identical numbers mean the upgrade is not in this OSM file |
| Graph cache size on disk | Reported, not asserted — a bulk sanity number |

The should-block rows are the ones that matter on a pre-filtered extract.
Untagged track (`gauge == 0`) is permitted by every profile by design, so
a graph that lost its `gauge` tags routes everything on every profile and
looks perfectly healthy — until a Spanish trip is planned on standard
gauge. The same reasoning applies to `voltage`, `electrified` and
`railway_service`: confirm with whoever prepared the extract which tags
their filter kept, against `graph.encoded_values` in `config.yml`.

One more thing a filtered extract loses: anything hand-patched into the
previous `.pbf`. If a link was ever added by hand (see the re-import
warning below), it is in that file and not in a freshly filtered one.

---

## First Time Setup

Follow these steps exactly in order. Steps 1 and 2 only need to be done once.

### Step 1 — Download Europe OSM Data

Download the OpenStreetMap Europe extract (~30 GB) from Geofabrik:

```
https://download.geofabrik.de/europe-latest.osm.pbf
```

Save it to:
```
backend/models/route/routing/docker/data-infra-2026/europe-latest.osm.pbf
```

> **Note:** This file is large and will take 1–3 hours to download depending on
> your connection. If the download is interrupted, resume it with:
> ```powershell
> curl -L -C - -o data-infra-2026\europe-latest.osm.pbf https://download.geofabrik.de/europe-latest.osm.pbf
> ```

### Step 2 — Build the Docker Image

Open PowerShell and navigate to the docker folder:

```powershell
cd backend\models\route\routing\docker
docker compose build
```

This clones OpenRailRouting from GitHub, builds the JAR with Maven, and packages
everything into a Docker image. Takes approximately **5–10 minutes**.

Success looks like:
```
✔ Image docker-openrailrouting Built
```

### Step 3 — Import the Routing Graph (one-time, ~30 minutes)

This step processes the OSM data and builds the routing graph. Only needed once,
or when the OSM data is updated.

```powershell
docker compose run --rm openrailrouting-infra-2026 `
  java -Xmx24g -Xms1g -jar railway_routing.jar import config.yml
```

> **Requirements:** At least 24 GB of free RAM during import.
> The import takes **20–40 minutes** for full Europe, longer since the graph
> carries four gauge profiles (each with its own CH and LM preparation).
>
> Any argument overrides the default server start, so `entrypoint.sh` runs
> this import and skips the graph-cache download. Without that override the
> command would have started the server and pulled the prebuilt cache over
> the very directory the import is meant to rebuild.

Success looks like:
```
INFO  com.graphhopper.GraphHopper - flushed graph
```

The built graph is stored in `graph-cache-infra-2026/`. Rail-only Europe is far smaller than a road graph: **213 MB zipped** for the four-profile cache (2026-08-29), against ~190 MB for the single-profile one — the three extra gauge networks are a small fraction of European rail, so four profiles cost about 12% more than one, not four times.

### Step 4 — Start the local Server

```powershell
docker compose up -d
```

The server starts in the background. Wait ~30 seconds, then verify it is running:

```powershell
docker compose ps
```

Expected status: `running`

### Step 5 — Test the API

Test a route from Vienna to Munich:

```powershell
(curl "http://localhost:8989/route?point=48.2082,16.3738&point=48.1351,11.5820&profile=night_train&calc_points=false" -UseBasicParsing).Content
```

Expected response contains:
```json
{
  "paths": [{
    "distance": 420232.605,
    "time": 11762168
  }]
}
```

- `distance` — route length in metres (~420 km Vienna→Munich)
- `time` — travel time in milliseconds (~196 min)

---

## Day-to-Day Usage

> **Note:** In normal development, the routing engine starts automatically as part
> of the main backend stack (`backend/docker/docker-compose.yml`). Use the standalone
> compose here only for graph import or isolated routing testing.

```powershell
# Start the server (standalone)
docker compose up -d

# Stop the server
docker compose down

# Check if running
docker compose ps

# View live logs
docker compose logs -f
```

---

## Night Train Profiles

There is one profile per track gauge. They share `custom_models/night_train.json`
and differ only in which `custom_models/nt_gauge_<mm>.json` they add:

| Profile | Gauge | Network |
|---|---|---|
| `night_train` | 1435 mm | Standard gauge — the European mainline network |
| `night_train_1520` | 1520 + 1524 mm (one family, 0.9.28) | Baltics, Ukraine, Moldova, Finland, broad-gauge border sidings in PL/RO |
| `night_train_1600` | 1600 mm | Ireland and Northern Ireland (island network, intra-island only) |
| `night_train_1668` | 1668 mm | Spain, Portugal, and the French break-of-gauge stations |

The `nt_` prefix is not cosmetic: OpenRailRouting ships built-in custom
models called `gauge_<mm>.json`, and GraphHopper rejects any file in
`custom_models.directory` that shadows a built-in name.

**The profile name is a contract.** `rail_router.py` derives it as
`<OPENRAILROUTING_PROFILE>` for standard gauge and
`<OPENRAILROUTING_PROFILE>_<gauge_mm>` for the rest; renaming a profile in
`config.yml` breaks routing for that gauge.

Baking the gauge into the profile rather than sending it in the request is
what keeps stop *snapping* gauge-correct. 36 catalog stops carry two gauges,
24 of them in Spain — a request-time rule would let the CH snapping pass land
a standard-gauge trip on an Iberian platform.

Shared settings, from `night_train.json` and `config.yml`:

| Parameter | Value | Reason |
|---|---|---|
| Speed ceiling | 230 km/h | Graph-level bound, not a per-trip speed — see below |
| Electrification | All tracks | Vectron Dual Mode supports diesel fallback |
| Service tracks | Blocked | No routing via yards or spurs |
| Belarus, Russia | Blocked at request time | Project decision — see note below |
| Routing objective | 80% time / 20% distance | Balanced for night train economics |
| U-turn penalty | 300 seconds (5 min) | Locomotive reversal time |

The 230 km/h ceiling bounds only the paths that send no composition:
`route_geometry()` (ONTD map lines, which have no composition by design) and
`simpleRouting`. `fullRouting` caps every trip at its own
`composition.max_speed_kmh` in the request custom model, and GraphHopper
resolves two `limit_to` rules by minimum, so the baked value never binds
there. It mirrors `MAX_COMPOSITION_SPEED_KMH` in `models/route/model.py`;
keep the two equal, and remember that changing either needs a re-import.

Untagged track (`gauge == 0`) is permitted by every gauge profile, as it has
been since the first import: OSM tags gauge only where it differs from the
local norm, so blocking it would strand large parts of the network. That
permissiveness is the filter's known weak point — the pre-check in
`models/route/route_factory.py` is the primary defence, these rules the
secondary one.

---

## API Reference

### Route Request

```
GET http://localhost:8989/route
```

| Parameter | Example | Description |
|---|---|---|
| `point` | `48.2082,16.3738` | lat,lon — repeat for each waypoint |
| `profile` | `night_train` | routing profile — see the gauge table above |
| `calc_points` | `true` / `false` | include route geometry in response |
| `instructions` | `false` | exclude turn-by-turn instructions |
| `details` | `distance` | request per-segment details |
| `points_encoded` | `false` | return geometry as plain GeoJSON |

### Full Example with Geometry

```powershell
(curl "http://localhost:8989/route?point=48.2082,16.3738&point=48.1351,11.5820&profile=night_train&calc_points=true&points_encoded=false&instructions=false" -UseBasicParsing).Content
```

### Admin API

Available at `http://localhost:8990` — shows server health and metrics.

---

## Re-importing the Graph

Re-import is needed when:
- `config.yml` profiles or `graph.encoded_values` are changed
- any file in `custom_models/` is changed
- The OSM data file is updated

> **A re-import destroys anything hand-applied to the graph-cache directory.** Patch the
> OSM `.pbf` instead of the cache when a link is missing from OSM (e.g. the
> Sicily train ferry), so the change survives every later import.

GraphHopper validates the graph cache against `config.yml` at startup and
refuses to start on a mismatch, so the config and the cache must ship
together. After a re-import: zip `graph-cache-infra-2026/`, upload it to Drive, set the
new id as `GRAPH_CACHE_FILE_ID_INFRA_2026` in `backend/docker/.env`, and rebuild the
image (`custom_models/` is `COPY`d at build time, so `docker compose build`
is required — not just `up`).

Steps:
```powershell
# Stop the server
docker compose down

# Delete old graph cache
Remove-Item -Recurse -Force graph-cache-infra-2026\

# Re-run import
docker compose run --rm openrailrouting-infra-2026 `
  java -Xmx24g -Xms1g -jar railway_routing.jar import config.yml

# Start server again
docker compose up -d
```

---

## Profile Selection (backend side)

Since 0.9.27 the backend chooses among these profiles per trip:
`models/route/routing/gauge.py` resolves ONE gauge from the trip's stops
(set intersection of `gauges_mm`, each set first normalized through
`GAUGE_FAMILY_MM` — 1524 folds into 1520; unknown does not constrain; ties
prefer 1435) and `rail_router._profile_for_gauge()` maps it onto the naming
contract above. **1520 and 1524 are one family** (0.9.28): interoperable in
practice, tagged separately in OSM, and as separate profiles the Estonian
seam — tagged both ways — was impassable. `night_train_1520` accepts both
tags; there is no separate Finnish-gauge profile, and family trips report
`track_gauge_mm: 1520`. Stop pairings no single gauge serves fail before any router
call as `422 gauge_mismatch`. `SUPPORTED_GAUGES_MM` in
`models/route/model.py` is the sanctioned mirror of the profile list here —
adding a gauge means a new profile in `config.yml`, a re-import, and that
tuple.

## Route Segment Cache (backend side)

Routing is served **per stop pair** from `route_cache.route_segments`
(`adapters/route_segment_repository.py`); only misses reach GraphHopper,
and every miss is stored back — the cache grows with traffic. Keyed by
`(routing_graph_key, stop_lo, stop_hi, variant_key)`: each graph has its own
snapped points and HSR resolution, so nothing is shared across graphs.

`rail_router.py` is split in two layers for this:

- **Layer 1 — `RailRouter.route(stops, max_speed_kmh, avoid_hsr, gauge_mm,
  routing_mode)`** returns *raw* physics only (geometry, distance, unrounded
  per-country distance/time, countries, passages). Its inputs are exactly
  what shapes the geometry, which is what makes the cache key honest:
  `route_variant_key(profile, custom_model)` = gauge profile + hash of the
  resolved custom model (speed cap, HSR vector, blocked-country areas).
- **Layer 2 — `route_trip(router, stops, composition, tracks, routing_mode)`**
  is what every call site uses (`route_factory`, `timetable`'s reroutes,
  `routing_context`). It resolves layer-1 inputs from the domain pair, then
  applies the scenario-dependent physics — country buffer quotas and
  traction dynamics — on top. Cached rows therefore stay scenario-free: a
  TAC or buffer-quota recalibration invalidates nothing.

Per-pair stitching is output-identical to one multi-point call (via-points
are hard constraints; snapping is per-point deterministic). The one known
caveat — terminus/reversal stations where the arrival track constrains the
departure — is unchanged from live routing. Note the gauge is resolved over
the *whole trip's* stops, so a dual-gauge border pair pulled broad by its
co-stops misses under the standard-gauge row and self-populates under the
broad one.

**Invalidation is per graph and automatic:** `route_cache.graph_state`
remembers each graph's GraphHopper `import_date`; at API start the live
`/info` is compared and a changed graph has its rows purged. A re-import
empties exactly the graph it touched. Neither `ROUTE_BUILDER_VERSION` nor
scenario ids are in the key — nothing they change is stored.

Front-loading: `scripts/precompute_route_segments.py --graph <key>` routes
every pair under a distance cap once and bulk-loads the CSV (`--load`, or
`db/dev/seed.py` picking up `db/dev/data/route_segments_<key>.csv.gz` on a
dev reseed). Deploy and run notes: `docs/DEPLOY_HANDOVER.md` §7a.

## Verifying the Gauge Profiles

After a re-import, check that each profile routes its own gauge and
refuses the others. `scripts/verify_routing_graph.py` runs this whole
table for you (see "Verifying a newly imported graph" below); the raw
calls are:

```powershell
# four profiles must be listed
(curl "http://localhost:8989/info" -UseBasicParsing).Content
```

| Profile | Should route | Should fail |
|---|---|---|
| `night_train` | Berlin → Wien | Helsinki → Tampere |
| `night_train_1520` | Kyiv → Lviv | Kyiv → Warszawa |
| `night_train_1520` (Finnish 1524 tag) | Helsinki → Tampere | Helsinki → Stockholm |
| `night_train_1600` | Dublin → Cork | Dublin → London |
| `night_train_1668` | Madrid → Sevilla | Madrid → Perpignan |

A failing pair should return a "connection between locations not found"
message, not a route.

**The Belarus/Russia exclusion is not in the graph.** GraphHopper's `country`
encoded value is not registered by this fork (`Unknown encoded value:
country` at import), so the block cannot be baked in. Since 0.9.27 it is
applied per request instead (`BLOCKED_COUNTRIES` in `models/route/model.py`):
`rail_router._blocked_country_rules()` builds a speed-0 area rule over EVERY
component polygon of each blocked country — every component, because
Russia's largest polygon is the western mainland and a block built from it
alone would leave the Kaliningrad exclave open — and those rules ride in the
custom model of every routing request, all modes (`route_geometry()` and
`simpleRouting` included, which therefore run LM rather than CH). A bare
`/route` call against this server, like the smoke tests above, carries no
custom model and is NOT blocked — the exclusion lives in the backend's
requests, not in the graph. Re-check whether the fork has gained `country`
before adding it back to `graph.encoded_values`; that would be the better
mechanism, since it follows real borders rather than a simplified ring.

---

## Updating the OSM Data

Geofabrik updates the Europe extract weekly. To update:

```powershell
# Download new file
curl -L -o data-infra-2026\europe-latest.osm.pbf `
  https://download.geofabrik.de/europe-latest.osm.pbf

# Re-import (see above)
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `docker: command not found` | Docker not on PATH | Restart PowerShell after installing Docker Desktop |
| `Cannot connect to Docker daemon` | Docker Desktop not running | Open Docker Desktop, wait for "Engine running" |
| `port 8989 already in use` | Another service on that port | Change `OPENRAILROUTING_HOST_PORT_INFRA_2026` in `backend/docker/.env` |
| `No route found` | Station coordinates snap to non-rail | Check lat/lon are correct and near a rail station |
| `OutOfMemoryError` during import | Not enough RAM | Close other applications, ensure 24 GB free |
| Server starts but returns 503 | Graph still loading | Wait 30–60 seconds after `docker compose up` |

---

## Architecture Notes

The Docker setup uses a **two-stage build**:

1. **Builder stage** — Maven + Java 21, clones and compiles OpenRailRouting
2. **Runtime stage** — JRE only, copies the JAR — keeps the image lean (~300 MB vs ~1.5 GB)

The OSM data (`data-<key>/`) and routing graph (`graph-cache-<key>/`) are mounted as volumes
outside the container so they survive image rebuilds.

The `config.yml` and `custom_models/` are baked into the image. Changes to these
files require `docker compose build` followed by a re-import.