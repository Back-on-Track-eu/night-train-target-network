# Night Train — Backend Developer Setup Guide

This guide is for **backend developers** working in PyCharm with manual Docker control.

For frontend developers using VS Code, see `.devcontainer/` instead.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [PyCharm](https://www.jetbrains.com/pycharm/) (Professional recommended)
- [uv](https://docs.astral.sh/uv/) installed

---

## First-time setup

**1. Clone the repository**
```bash
git clone https://github.com/Back-on-Track-eu/night-train-target-network.git
cd night-train-target-network
```

**2. Set up the Python environment**

Run from the `backend/` directory:
```bash
cd backend
uv sync
```

**3. Create your `.env` file**

`backend/docker/.env` is the single source of truth for all backend configuration —
it is used by both `backend/docker/docker-compose.yml` and `.devcontainer/docker-compose.yml`.

```bash
cp backend/docker/.env.example backend/docker/.env
```

The default values in `.env.example` work out of the box for local development.
Edit `backend/docker/.env` if you need to change ports or paths.

---

## Starting the services

```bash
cd backend/docker
docker-compose up -d
```

On first run Docker builds the images — this takes a few minutes.
Check status with:
```bash
docker-compose ps
```

Wait until all three containers (`night_train_postgres`, `openrailrouting`, `night-train-api`) show as healthy before testing.

---

## Verifying the setup

```powershell
Invoke-RestMethod -Uri http://localhost:5000/api/health
Invoke-RestMethod -Uri http://localhost:5000/api/params/StopInfrastructures
Invoke-RestMethod -Uri http://localhost:5000/api/params/compositions
```

---

## Running tests

From `backend/`:
```bash
uv run --extra dev pytest tests/ -v
```

Tests require the full Docker stack to be running (`postgres` + `openrailrouting` + `api`).

The suite is organised by layer (stack health → DB seed → loader → versioning →
params API → route/plan → evaluation/calc → pipeline). See `tests/README.md`
for a complete list of every test file and test, with purpose, input, and
expected outcome.

---

## Stopping the services

```bash
cd backend/docker
docker-compose down
```

To also wipe the database volume (full reset):
```bash
docker-compose down -v
```

---

## Running the API outside Docker (for debugging)

To run Flask directly in PyCharm (e.g. for step-through debugging),
start only the dependencies in Docker and run the API from your venv:

```bash
# Start postgres and routing engine only
cd backend/docker
docker-compose up -d postgres openrailrouting

# Run the API from PyCharm or the terminal
cd backend
uv run python main.py
```

When running outside Docker, set these in your PyCharm run configuration
(or shell) to match your local `.env` values:
```
POSTGRES_HOST=localhost
OPENRAILROUTING_URL=http://localhost:8989
```

---

## Database (standalone inspection)

To inspect or edit the database schema independently of the full stack,
use the standalone DB stack with Mathesar:

```bash
cd backend/db/dev
cp .env.example .env   # already has working defaults
docker-compose up -d
open http://localhost:8000   # Mathesar UI
```

The standalone DB stack has its own `.env` — only `POSTGRES_*` variables are needed there.

---

## Project structure

```
night-train-target-network/
├── .devcontainer/          # VS Code Dev Container setup (frontend devs)
│   ├── docker-compose.yml  # extends backend/docker/docker-compose.yml
│   └── devcontainer.json
├── backend/
│   ├── docker/             # Main Docker stack (backend dev workflow)
│   │   ├── docker-compose.yml
│   │   ├── Dockerfile
│   │   └── .env.example    ← single source of truth for all env vars
│   ├── db/dev/             # Standalone DB stack (schema inspection)
│   ├── api/                # Flask API blueprints
│   │   └── helpers/        # serialize.py and dependencies.py
│   ├── models/             # Domain model, routing, energy, evaluation
│   ├── adapters/           # DB data loader
│   ├── tests/              # Integration tests
│   ├── main.py
│   └── pyproject.toml
```

---

## Troubleshooting

**`docker-compose up` fails with a missing env variable**
The `.env` file is missing or incomplete.
Copy `backend/docker/.env.example` to `backend/docker/.env`.

**OpenRailRouting takes a long time to start**
Normal on first run — it loads the European rail graph from the graph cache.
Subsequent starts use the cached graph and are much faster (~30s).

**Container stuck in a bad state**
```bash
cd backend/docker
docker-compose down
docker-compose up -d
```

**Full reset (wipes database)**
```bash
docker-compose down -v
docker-compose up -d --build
```