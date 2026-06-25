# Night train target wetwork — Routing Infrastructure

This folder contains the OpenRailRouting server used to calculate rail travel times
and distances between stations. It runs as a Docker container and exposes a REST API on the host port configured in `backend/docker/.env`
(`OPENRAILROUTING_HOST_PORT`, default 8989). With this setup, the limits on requesting routes do 
only depend on the properties of your local machine but not on request limits of 
https://routing.openrailrouting.org/maps/ and also routing setting can be adjusted individually.



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
│   └── night_train.json        # custom routing profile for night trains
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
models/routing/docker/data/europe-latest.osm.pbf
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
> The import takes **20–40 minutes** for full Europe.

Success looks like:
```
INFO  com.graphhopper.GraphHopper - flushed graph
```

The built graph is stored in `graph-cache/` (~5–10 GB).

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

## Night Train Profile

The routing uses a custom `night_train` profile defined in
`custom_models/night_train.json`. It is configured for:

| Parameter | Value | Reason |
|---|---|---|
| Max speed | 200 km/h | Siemens Vectron MS top speed |
| Gauge | 1435 mm only | Standard gauge — all European mainlines |
| Electrification | All tracks | Vectron Dual Mode supports diesel fallback |
| Service tracks | Blocked | No routing via yards or spurs |
| Routing objective | 80% time / 20% distance | Balanced for night train economics |
| U-turn penalty | 300 seconds (5 min) | Locomotive reversal time |

---

## API Reference

### Route Request

```
GET http://localhost:8989/route
```

| Parameter | Example | Description |
|---|---|---|
| `point` | `48.2082,16.3738` | lat,lon — repeat for each waypoint |
| `profile` | `night_train` | routing profile to use |
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
- `config.yml` profiles are changed
- `night_train.json` custom model is changed
- The OSM data file is updated

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