# Night Train — Frontend Developer Setup Guide

This guide is for **frontend developers** who need the backend API running locally.
You do not need Python or any other backend tooling — just Docker.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running

---

## Quickstart

**1. Clone the repository**
```bash
git clone https://github.com/Back-on-Track-eu/night-train-target-network.git
cd night-train-target-network
```

**2. Create your `.env` file**

The single `.env` for the entire backend lives at `backend/docker/.env`:
```bash
cp backend/docker/.env.example backend/docker/.env
```

The default values work out of the box for local development — no changes needed.

**3. Start the backend**

**Option A — VS Code Dev Container (recommended)**

Open the repo in VS Code. When prompted, click **Reopen in Container**.
If the prompt does not appear, open the command palette (`Ctrl+Shift+P`) and run
**Dev Containers: Reopen in Container**.

VS Code will build the images and start all containers automatically.

**Option B — plain Docker Compose**

```bash
docker compose -f .devcontainer/docker-compose.yml up --build
```

**4. Verify everything works**
```bash
curl http://localhost:5000/api/health
curl http://localhost:5000/api/params/stops
curl http://localhost:5000/api/params/compositions
```

---

## Stopping the backend

```bash
docker compose -f .devcontainer/docker-compose.yml down
```

Or use **Dev Containers: Stop Container** from the VS Code command palette.

---

## API Endpoints

Base URL: `http://localhost:5000`

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Liveness check |

### Parameters

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/params/stops` | All stops with stop_id, name, country, lat/lon |
| `GET` | `/api/params/compositions` | All composition types with full parameters |

### Route Builder

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/route-builder/build` | Build a route from a stop list, composition and departure time |

#### POST /api/route-builder/build — Request body

```json
{
  "stops": [
    {"stop_id": "DE_BERLIN_HBF",  "stop_type": "boarding"},
    {"stop_id": "AT_WIEN_HBF",    "stop_type": "alighting"}
  ],
  "composition_id":   "STD-7.1",
  "departure_time":   "21:00"
}
```

### Cost/Revenue Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/cost-rev-calc/calc` | Run cost/revenue evaluation on a built route |

### Error Responses

| Status | `error` key | Meaning |
|--------|-------------|---------|
| `400` | `validation_error` | Invalid request body — see `details` array |
| `422` | `domain_error` | Valid request but pipeline failed (e.g. unknown stop) |
| `500` | `pipeline_error` | Unexpected server error |

---

## Troubleshooting

**OpenRailRouting takes a long time to start**
Normal on first run — it loads the European rail graph from the graph cache (~30s–2min).
The API container waits for it automatically via a health check.

**Container stuck in a bad state**
```bash
docker compose -f .devcontainer/docker-compose.yml down
docker compose -f .devcontainer/docker-compose.yml up --build
```

**Full reset (wipes database)**
```bash
docker compose -f .devcontainer/docker-compose.yml down -v
docker compose -f .devcontainer/docker-compose.yml up --build
```