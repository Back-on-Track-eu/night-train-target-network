# Night Train — Backend API: Developer Setup Guide

This guide is for **frontend developers** who need the backend API running locally.  
You do not need Python or any other backend tooling — just Docker.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Access to the `B-o-T_targetnetwork_DB` Google Spreadsheet
- A Google service account JSON key file with read access to the spreadsheet

> **Don't have a service account yet?** See [Setting up Google credentials](#setting-up-google-credentials) below.

---

## Quickstart

**1. Clone the repository**
```bash
git clone https://github.com/Back-on-Track-eu/night-train-target-network.git
cd night-train-target-network/backend/docker
```

**2. Create your `.env` file**
```bash
cp .env.example .env
```

Open `.env` and set the path to your Google service account JSON:
```
GOOGLE_APPLICATION_CREDENTIALS=C:/Users/yourname/keys/service_account.json
```

> Use forward slashes on all platforms, including Windows.

**3. Start the backend**
```bash
docker-compose up -d
```

This starts two services:
- `openrailrouting` — the rail routing engine (port `8989`)
- `night-train-api` — the Flask REST API (port `5000`)

> **First startup takes 1–2 minutes** — OpenRailRouting loads the full European rail graph into memory. The API will not accept requests until routing is ready.

**4. Load the data**

Once both services are running, trigger the initial data load from Google Sheets:
```bash
curl -X POST http://localhost:5000/api/data/load
```

You should see:
```json
{"loaded": true, "loaded_at": "...", "message": "Data loaded successfully."}
```

**5. Verify everything works**
```bash
curl http://localhost:5000/api/health
curl http://localhost:5000/api/compositions
```

---

## Stopping the backend

```bash
docker-compose down
```

> Always stop cleanly before shutting down your machine to avoid Docker startup issues next time.

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

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select or create a project
3. Enable the **Google Sheets API**
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Give it a name (e.g. `night-train-dev`)
6. On the service account page, go to **Keys → Add Key → Create new key → JSON**
7. Save the downloaded JSON file somewhere safe (outside the repo)
8. Share the `B-o-T_targetnetwork_DB` spreadsheet with the service account email (viewer access is sufficient)
9. Set the path to the JSON file in your `.env` file

---

## Troubleshooting

**API returns `503 data_not_loaded`**  
Call `POST /api/data/load` after startup.

**`docker-compose up` fails with volume mount error**  
Check that `GOOGLE_APPLICATION_CREDENTIALS` in your `.env` points to an existing file and uses forward slashes.

**OpenRailRouting takes a long time to start**  
This is normal — it loads the full European rail graph (~1–2 min). The API container waits for it automatically.

**Docker Desktop shows "lingering processes"**  
Always stop services with `docker-compose down` before shutting down. If stuck, restart Docker Desktop.