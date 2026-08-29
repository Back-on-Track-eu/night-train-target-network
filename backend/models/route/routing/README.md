# Night Train Target Network — Routing Infrastructure

This folder contains the OpenRailRouting server used to calculate rail travel times
and distances between stations. It runs as a Docker container and exposes a REST API on the host port configured in `backend/docker/.env`
(`OPENRAILROUTING_HOST_PORT`, default 8989). With this self-hosted setup,
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
│   └── nt_gauge_<mm>.json      # one per gauge: 1435, 1520, 1524, 1600, 1668
├── data/                       # ← NOT in git — place OSM file here
│   └── europe-latest.osm.pbf
└── graph-cache/                # ← NOT in git — generated during import
```

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
backend/models/route/routing/docker/data/europe-latest.osm.pbf
```

> **Note:** This file is large and will take 1–3 hours to download depending on
> your connection. If the download is interrupted, resume it with:
> ```powershell
> curl -L -C - -o data\europe-latest.osm.pbf https://download.geofabrik.de/europe-latest.osm.pbf
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
docker compose run --rm openrailrouting `
  java -Xmx24g -Xms1g -jar railway_routing.jar import config.yml
```

> **Requirements:** At least 24 GB of free RAM during import.
> The import takes **20–40 minutes** for full Europe, longer since the graph
> carries five gauge profiles (each with its own CH and LM preparation).
>
> Any argument overrides the default server start, so `entrypoint.sh` runs
> this import and skips the graph-cache download. Without that override the
> command would have started the server and pulled the prebuilt cache over
> the very directory the import is meant to rebuild.

Success looks like:
```
INFO  com.graphhopper.GraphHopper - flushed graph
```

The built graph is stored in `graph-cache/`. Rail-only Europe is far smaller than a road graph: the single-profile cache was ~190 MB zipped. Re-measure after adding the gauge profiles.

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
| `night_train_1520` | 1520 mm | Baltics, Ukraine, Moldova, broad-gauge border sidings in PL/RO |
| `night_train_1524` | 1524 mm | Finland |
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

> **A re-import destroys anything hand-applied to `graph-cache/`.** Patch the
> OSM `.pbf` instead of the cache when a link is missing from OSM (e.g. the
> Sicily train ferry), so the change survives every later import.

GraphHopper validates `graph-cache/` against `config.yml` at startup and
refuses to start on a mismatch, so the config and the cache must ship
together. After a re-import: zip `graph-cache/`, upload it to Drive, set the
new id as `GRAPH_CACHE_FILE_ID` in `backend/docker/.env`, and rebuild the
image (`custom_models/` is `COPY`d at build time, so `docker compose build`
is required — not just `up`).

Steps:
```powershell
# Stop the server
docker compose down

# Delete old graph cache
Remove-Item -Recurse -Force graph-cache\

# Re-run import
docker compose run --rm openrailrouting `
  java -Xmx24g -Xms1g -jar railway_routing.jar import config.yml

# Start server again
docker compose up -d
```

---

## Profile Selection (backend side)

Since 0.9.27 the backend chooses among these profiles per trip:
`models/route/routing/gauge.py` resolves ONE gauge from the trip's stops
(set intersection of `gauges_mm`; unknown does not constrain; ties prefer
1435) and `rail_router._profile_for_gauge()` maps it onto the naming
contract above. Stop pairings no single gauge serves fail before any router
call as `422 gauge_mismatch`. `SUPPORTED_GAUGES_MM` in
`models/route/model.py` is the sanctioned mirror of the profile list here —
adding a gauge means a new profile in `config.yml`, a re-import, and that
tuple.

## Verifying the Gauge Profiles

After a re-import, check that `country` reached the graph and that each
profile routes its own gauge and refuses the others:

```powershell
# five profiles must be listed
(curl "http://localhost:8989/info" -UseBasicParsing).Content
```

| Profile | Should route | Should fail |
|---|---|---|
| `night_train` | Berlin → Wien | Helsinki → Tampere |
| `night_train_1520` | Kyiv → Lviv | Kyiv → Warszawa |
| `night_train_1524` | Helsinki → Tampere | Helsinki → Stockholm |
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
curl -L -o data\europe-latest.osm.pbf `
  https://download.geofabrik.de/europe-latest.osm.pbf

# Re-import (see above)
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `docker: command not found` | Docker not on PATH | Restart PowerShell after installing Docker Desktop |
| `Cannot connect to Docker daemon` | Docker Desktop not running | Open Docker Desktop, wait for "Engine running" |
| `port 8989 already in use` | Another service on that port | Change `OPENRAILROUTING_HOST_PORT` in `backend/docker/.env` |
| `No route found` | Station coordinates snap to non-rail | Check lat/lon are correct and near a rail station |
| `OutOfMemoryError` during import | Not enough RAM | Close other applications, ensure 24 GB free |
| Server starts but returns 503 | Graph still loading | Wait 30–60 seconds after `docker compose up` |

---

## Architecture Notes

The Docker setup uses a **two-stage build**:

1. **Builder stage** — Maven + Java 21, clones and compiles OpenRailRouting
2. **Runtime stage** — JRE only, copies the JAR — keeps the image lean (~300 MB vs ~1.5 GB)

The OSM data (`data/`) and routing graph (`graph-cache/`) are mounted as volumes
outside the container so they survive image rebuilds.

The `config.yml` and `custom_models/` are baked into the image. Changes to these
files require `docker compose build` followed by a re-import.