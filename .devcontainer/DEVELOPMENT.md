# Night Train — Frontend Developer Setup Guide

This guide is for **frontend developers** who need the backend API running
locally. You do not need Python or any other backend tooling — just Docker
(and VS Code, if you use the Dev Container option).

For backend developers working in PyCharm, see `backend/DEVELOPMENT.md` instead.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [VS Code](https://code.visualstudio.com/) with the
  [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
  — only needed for Option A below

---

## Quickstart

**1. Clone the repository**
```bash
git clone https://github.com/Back-on-Track-eu/night-train-target-network.git
cd night-train-target-network
```

**2. Create your `.env` file**

The single `.env` for the entire backend lives at `backend/docker/.env` —
it's shared by `backend/docker/docker-compose.yml` and
`.devcontainer/docker-compose.yml`:

```bash
cp backend/docker/.env.example backend/docker/.env
```

The default values work out of the box for local development — no changes needed.

**3. Start the stack**

**Option A — VS Code Dev Container (recommended)**

Open the repo in VS Code. When prompted, click **Reopen in Container**.
If the prompt does not appear, open the command palette (`Ctrl+Shift+P`) and run
**Dev Containers: Reopen in Container**.

VS Code builds all four images and starts them automatically, then runs
`.devcontainer/setup.sh` inside the `backend-api` container (`uv sync`,
`pre-commit install`, `npm install` for the frontend, then waits for the
API health check to pass).

**Option B — plain Docker Compose**

```bash
docker compose -f .devcontainer/docker-compose.yml up --build
```

**4. Verify everything works**
```bash
curl http://localhost:5000/api/health
curl http://localhost:5000/api/params/StopInfrastructures
curl http://localhost:5000/api/params/compositions
```

---

## Stopping the stack

```bash
docker compose -f .devcontainer/docker-compose.yml down
```

Or use **Dev Containers: Stop Container** from the VS Code command palette.

To also wipe the database volume (full reset):
```bash
docker compose -f .devcontainer/docker-compose.yml down -v
```

---

## What's running

Four services, defined in `.devcontainer/docker-compose.yml` (a
self-contained duplicate of `backend/docker/docker-compose.yml`'s
`postgres`/`openrailrouting`/`api` services, plus `frontend`):

| Service | Container | Port(s) |
|---|---|---|
| `postgres` | `night_train_postgres` | `5432` |
| `openrailrouting` | `openrailrouting` | `8989` (routing), `8990` (admin/metrics) |
| `backend-api` | `backend-api` | `5000` |
| `frontend` | `night-train-frontend` | `5173` (Vite HMR — edits reflect instantly) |

The `backend-api` service seeds the database (via its entrypoint) and
starts Flask under gunicorn on every start — no separate seed step needed.

---

## API Reference

Base URL: `http://localhost:5000`. Full request/response documentation is
in `backend/api/README.md`; the endpoints below are current as of this guide:

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Liveness check |
| `GET` | `/api/data/status` | DB loader status (`loaded`, `loaded_at`, `error`) |

### Parameters

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/params/StopInfrastructures` | Night train stopping points, versioned |
| `GET` | `/api/params/TrackInfrastructures` | Country-level track parameters, versioned |
| `GET` | `/api/params/compositions` | All composition types with full cost/physics parameters |

### Route planning

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/route/plan` | Build a full route (both directions) from a stop list, composition, and mode selections — no monetary values |

#### POST /api/route/plan — Request body

```json
{
  "stops": ["DE_BERLIN_HBF", "AT_WIEN_HBF"],
  "composition_id": "STD-7.1"
}
```

`timetable_mode`, `schedule_mode`, `routing_mode`, and `auto_stop_addition`
are optional — see `backend/api/README.md` for the full field list and defaults.

### Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/evaluation/calc` | Run cost/revenue evaluation on a route returned by `/api/route/plan` |

### Proposals

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/proposal` | Save a new proposal version (route + optional evaluation) |
| `GET`/`POST` | `/api/proposals` | List saved proposals |
| `GET` | `/api/proposal/<id>` | Load a saved proposal |

### Feedback

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/feedback` | Submit user feedback |
| `GET` | `/api/feedback/categories` | List feedback categories/sub-categories |

### Auth ⚠️ not yet implemented

`POST /api/auth/request-code` and `POST /api/auth/verify` exist as stubs and
currently return `501 Not Implemented`.

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

**`docker compose up` fails with a missing env variable**
The `.env` file is missing or incomplete. Copy `backend/docker/.env.example`
to `backend/docker/.env`.