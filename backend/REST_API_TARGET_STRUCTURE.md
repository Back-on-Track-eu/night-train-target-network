# Night Train — Backend API

V.901.2

---

## API Endpoints

Base URL: `http://localhost:5000`

### Health

| Method | Endpoint      | Description     |
|--------|---------------|-----------------|
| `GET`  | `/api/health` | Liveness check  |

### Auth

| Method | Endpoint                 | Description                                                     |
|--------|--------------------------|-----------------------------------------------------------------|
| `POST` | `/api/auth/request-code` | {email} → sends OTP, no response body data (just success/error) |
| `POST` | `/api/auth/verify`       | {email, code} → {token} (JWT for subsequent requests)           |

### Feedback

| Method | Endpoint        | Description                                                                     |
|--------|-----------------|---------------------------------------------------------------------------------|
| `POST` | `/api/feedback` | submit feedback on a specific model parameter incl. potential data attachements |

### Scenarios

| Method   | Endpoint             | Description                                                          |
|----------|----------------------|----------------------------------------------------------------------|
| `POST`   | `/api/scenario`      | tag with {user} no response body data (just success/error)           |
| `GET`    | `/api/scenarios`     | list ALL user's saved scenarios (id, name, summary metrics)          |
| `POST`   | `/api/scenarios`     | list filter saved scenarios (id, name, summary metrics) with limiter |
| `GET`    | `/api/scenario/{id}` | full saved scenario (input + result), 404/403 if not owner           |
| `PUT`    | `/api/scenario/{id}` | update name/input/result for an owned scenario                       |


### Trip Schedule Builder

| Method | Endpoint                              | Description                                                                              |
|--------|---------------------------------------|------------------------------------------------------------------------------------------|
| `GET`  | `/api/tsbuilder/stops`                | Load relevant stop data with stop_id, name, country, lat/lon                             |
| `POST` | `/api/tsbuilder/build-schedule`       | Post a stop list and composition and get a fully optimized route and timetable in return |
| `GET`  | `/api/tsbuilder/get-existing-network` | ???? Receive the existing night train network ????                                       |
| `GET`  | `/api/compositions/`                  | Load all compositions                                                                    |


### Evaluate

| Method | Endpoint                            | Description                                                 |
|--------|-------------------------------------|-------------------------------------------------------------|
| `POST` | `/api/model/evaluate/{scenario_id}` | Run first cost evaluation                                   |


### Error Responses

tbd