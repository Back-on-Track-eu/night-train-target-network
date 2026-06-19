# Night Train — Backend API: Developer Setup Guide

This guide is for **frontend developers** who need the backend API running locally.  
You do not need Python or any other backend tooling — just Docker.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- A Google service account JSON key file with read access to the `B-o-T_targetnetwork_DB` spreadsheet

> **Don't have a service account yet?** See [Setting up Google Credentials](#setting-up-google-credentials) below before continuing.

---

## Quickstart

**1. Clone the repository**
```bash
git clone https://github.com/Back-on-Track-eu/night-train-target-network.git
cd night-train-target-network
```

**2. Create your `.env` file**

Create `.devcontainer/.env` and set the path to your Google service account JSON file:
```bash
echo "GOOGLE_APPLICATION_CREDENTIALS=/Users/yourname/keys/service_account.json" > .devcontainer/.env
```

Or create the file manually with the following content:
```
GOOGLE_APPLICATION_CREDENTIALS=/Users/yourname/keys/service_account.json
```

> - Use the **absolute path** on your machine to the JSON file.
> - Use **forward slashes** on all platforms, including Windows (`C:/Users/...` not `C:\Users\...`).
> - The file must exist at that path before you start the containers.

**3. Start the backend**
```bash
docker compose -f .devcontainer/docker-compose.yml up --build
```

This starts two services:
- **OpenRailRouting** — loads the European rail graph (~1–2 min on first run)
- **API** — waits for OpenRailRouting to be healthy, then loads data from Google Sheets

Watch the terminal for progress. When you see:
```json
{"loaded": true, "loaded_at": "...", "message": "Data loaded successfully."}
```
the backend is ready.

**4. Verify everything works**
```bash
curl http://localhost:5000/api/health
curl http://localhost:5000/api/compositions
```

---

## Stopping the backend

```bash
docker compose -f .devcontainer/docker-compose.yml down
```

---

## Rebuilding after changes to `.env`

If you change `.devcontainer/.env` (e.g. new credentials path), bring the stack down and back up:
```bash
docker compose -f .devcontainer/docker-compose.yml down
docker compose -f .devcontainer/docker-compose.yml up --build
```

---

## VS Code Dev Container

If you use VS Code with the Dev Containers extension, you can open the repo and choose **Reopen in Container** — it uses the same Docker setup automatically.

---

## API Endpoints

Base URL: `http://localhost:5000`

### Health & Data

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Liveness check |
| `GET` | `/api/data/status` | Data loading state (`loaded`, `loaded_at`, `error`) |
| `POST` | `/api/data/load` | Load data from Google Sheets — call once after startup |
| `POST` | `/api/data/reload` | Force reload of data during runtime |

### Parameters

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/compositions` | All train compositions with full parameters |
| `GET` | `/api/stops` | All stops with `stop_id`, name, country, lat/lon |
| `GET` | `/api/infrastructure` | Per-country infrastructure parameters |

### Evaluate

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/evaluate` | Run full pipeline — route + cost model |

#### POST /api/evaluate — Request body

```json
{
  "stops": [
    {"stop_id": "Wien Hbf",     "stop_type": "boarding"},
    {"stop_id": "Salzburg Hbf", "stop_type": "both"},
    {"stop_id": "München Hbf",  "stop_type": "both"},
    {"stop_id": "Paris Est",    "stop_type": "alighting"}
  ],
  "composition_id":        "NJ-5.1",
  "departure_time_h":      21.0,
  "utilization_seat":      0.7,
  "utilization_couchette": 0.6,
  "utilization_sleeper":   0.5,
  "avg_fare_seat":         49.0,
  "avg_fare_couchette":    79.0,
  "avg_fare_sleeper":      129.0,
  "operating_days_year":   360
}
```

| Field | Type | Description |
|-------|------|-------------|
| `stops` | array | Ordered list of stops. `stop_type`: `boarding`, `alighting`, or `both` |
| `composition_id` | string | Train composition key from `/api/compositions` |
| `departure_time_h` | float | Departure time in decimal hours (e.g. `21.5` = 21:30) |
| `utilization_*` | float | Fraction of capacity filled, `0.0`–`1.0` |
| `avg_fare_*` | float | Average ticket price in EUR |
| `operating_days_year` | int | Operating days per year, `1`–`366` |

#### POST /api/evaluate — Response

```json
{
  "result": {
    "composition_id": "NJ-5.1",
    "total_distance_km": 2749.5,
    "total_driving_time_h": 20.51,
    "total_time_h": 22.56,
    "operating_days_year": 360,
    "revenue": {
      "revenue_seat": 2744,
      "revenue_couchette": 6826,
      "revenue_sleeper": 1548,
      "total": 11118
    },
    "cost": {
      "fixed_day_total": 18063,
      "variable_km_total": 15782,
      "variable_hour_total": 12904,
      "variable_ticket_total": 1635,
      "infra_total": 15831,
      "ebit_margin": 334,
      "total": 64549
    },
    "margin": -53431,
    "margin_pct": -4.806,
    "annual_margin": -19235256,
    "cost_per_seat_km": 0.0947
  }
}
```

### Error Responses

| Status | `error` key | Meaning |
|--------|-------------|---------|
| `503` | `data_not_loaded` | Call `POST /api/data/load` first |
| `400` | `validation_error` | Invalid request body — see `details` array |
| `422` | `domain_error` | Valid request but pipeline failed (e.g. unknown stop) |
| `500` | `pipeline_error` | Unexpected server error |

---

## Setting up Google Credentials

You need a Google service account with read access to the spreadsheet. Do this once.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and select or create a project.
2. Enable the **Google Sheets API**: APIs & Services → Enable APIs → search "Google Sheets API" → Enable.
3. Enable the **Google Drive API** the same way (needed to open the spreadsheet by ID).
4. Go to **IAM & Admin → Service Accounts → Create Service Account**.
   - Name it something like `night-train-dev`. No special roles needed.
5. On the service account page, go to **Keys → Add Key → Create new key → JSON**.
   - A JSON file downloads automatically. Save it somewhere outside the repository (e.g. `~/keys/`).
6. Share the `B-o-T_targetnetwork_DB` spreadsheet with the service account email address (shown on the service account page). Viewer access is sufficient.
7. Set the path to the JSON file in `.devcontainer/.env`:
   ```
   GOOGLE_APPLICATION_CREDENTIALS=/Users/yourname/keys/service_account.json
   ```

---

## Troubleshooting

**Data load fails with `Expecting value: line 1 column 1`**  
The credentials file is missing or not mounted. Check that:
- `.devcontainer/.env` exists and `GOOGLE_APPLICATION_CREDENTIALS` points to a real file
- The file exists at that exact path on your machine
- You restarted the containers after creating or changing `.env`

**API returns `503 data_not_loaded`**  
The startup data load failed silently. Check `GET /api/data/status` for the error message, then call `POST /api/data/load` manually.

**`docker compose` fails with volume mount error**  
The path in `GOOGLE_APPLICATION_CREDENTIALS` doesn't exist. Verify the path and use forward slashes.

**OpenRailRouting takes a long time to start**  
Normal — it loads the full European rail graph (~1–2 min). The API container waits for it automatically via a health check.

**Container is stuck or in a bad state**  
```bash
docker compose -f .devcontainer/docker-compose.yml down
docker compose -f .devcontainer/docker-compose.yml up --build
```
