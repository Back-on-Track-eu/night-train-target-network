# Night Train — Backend Developer Setup Guide

This guide is for **backend developers** working in PyCharm with manual Docker control.

For frontend developers using VS Code, see `.devcontainer/DEVELOPMENT.md` instead.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [PyCharm](https://www.jetbrains.com/pycharm/) (Professional recommended)
- [uv](https://docs.astral.sh/uv/) installed
- A Google service account JSON key file with read access to the `B-o-T_targetnetwork_DB` spreadsheet

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

```bash
cp backend/docker/.env.example backend/docker/.env
```

Then open `backend/docker/.env` and set the path to your Google service account JSON file:
```
GOOGLE_APPLICATION_CREDENTIALS=C:/Users/yourname/keys/service_account.json
```

> - Use the **absolute path** on your machine to the JSON file.
> - Use **forward slashes** on all platforms, including Windows (`C:/Users/...` not `C:\Users\...`).
> - Docker Compose will refuse to start with a clear error if this variable is not set.

---

## Starting the services

```bash
cd backend/docker
docker-compose up -d
```

On first run, the `openrailrouting` container downloads its graph cache (~600 MB). Check status with:
```bash
docker-compose ps
```

Wait until both containers show as healthy before loading data.

---

## Loading data

Once both services are healthy, load the data from Google Sheets.

**PowerShell:**
```powershell
Invoke-RestMethod -Method POST -Uri http://localhost:5000/api/data/load
```

**bash / WSL:**
```bash
curl -X POST http://localhost:5000/api/data/load
```

You need to do this once after each fresh container start. The data is held in memory and does not persist between restarts.

---

## Verifying the setup

```powershell
Invoke-RestMethod -Uri http://localhost:5000/api/health
Invoke-RestMethod -Uri http://localhost:5000/api/stops
```

---

## Stopping the services

```bash
cd backend/docker
docker-compose down
```

---

## Running the API outside Docker (for debugging)

To run the Flask API directly in PyCharm (e.g. for step-through debugging), start only the routing engine in Docker and run the API from your venv:

```bash
# Start only the routing engine
cd backend/docker
docker-compose up -d openrailrouting

# Run the API from PyCharm or the terminal
cd backend
uv run python main.py
```

`OPENRAILROUTING_URL` defaults to `http://localhost:8989` when running outside Docker, so no extra configuration is needed.

---

## Project structure

```
night-train-target-network/
├── .devcontainer/          # VS Code Dev Container setup (for frontend devs)
│   ├── docker-compose.yml
│   ├── devcontainer.json
│   ├── setup.sh
│   └── env.example
├── backend/                # All Python source code
│   ├── docker/             # Your Docker setup (PyCharm workflow)
│   │   ├── docker-compose.yml
│   │   ├── Dockerfile
│   │   └── .env.example
│   ├── api/                # Flask API and routes
│   ├── models/             # Route evaluation model and routing
│   ├── main.py
│   └── pyproject.toml
└── test_data/              # Postgres/seeder (not yet wired in)
```

Both `.devcontainer/` and `backend/docker/` build from `backend/` as their Docker context — the `Dockerfile` and `pyproject.toml` are shared.

---

## Coming soon

The PostgreSQL database and seeder container are not yet part of the Docker setup — data is currently loaded from Google Sheets on startup. Both setups will be updated when the database migration is complete.

---

## Troubleshooting

**`docker-compose up` fails with `Set GOOGLE_APPLICATION_CREDENTIALS in .env`**  
The `.env` file is missing or the variable is empty. Copy `backend/docker/.env.example` to `backend/docker/.env` and set the path.

**API returns `503 data_not_loaded`**  
The data load hasn't been called yet. Run `Invoke-RestMethod -Method POST -Uri http://localhost:5000/api/data/load`.

**`Invoke-RestMethod` returns a credentials error**  
The path in `GOOGLE_APPLICATION_CREDENTIALS` doesn't exist or points to a wrong file. Verify the path and use forward slashes.

**OpenRailRouting takes a long time to start**  
Normal on first run — it downloads and loads the full European rail graph (~600 MB, ~1–2 min). Subsequent starts use the cached graph and are much faster.

**Container is stuck or in a bad state**  
```bash
cd backend/docker
docker-compose down
docker-compose up -d
```
