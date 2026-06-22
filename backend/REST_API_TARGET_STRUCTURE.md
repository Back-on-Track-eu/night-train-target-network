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

| Method | Endpoint             | Description                                                                                                  |
|--------|----------------------|--------------------------------------------------------------------------------------------------------------|
| `POST` | `/api/scenario`      | save scenario to database (always a new scenario, never update, then in scenarios table tag via 'is_current' |
| `GET`  | `/api/scenarios`     | get a list of saved scenarios with limiter (only with tag 'is_current' (id, name, summary metrics)           |
| `POST` | `/api/scenarios`     | get a filtered list of saved scenarios with limiter (10, 20, 50 etc. results)                                |
| `GET`  | `/api/scenario/{id}` | load a scenario                                                                                              |


### Route Builder

| Method | Endpoint                   | Description                                                                                              |
|--------|----------------------------|----------------------------------------------------------------------------------------------------------|
| `GET`  | `/api/params/stops`        | Load relevant stop data (stop list)                                                                      |
| `GET`  | `/api/params/compositions` | Load relevant compositions data (compositions list)                                                      |
| `POST` | `/api/route-builder/build` | Post a stop list, composition and departure time and get a fully optimized route and timetable in return |




### Evaluate

| Method | Endpoint                  | Description             |
|--------|---------------------------|-------------------------|
| `POST` | `/api/cost-rev-calc/calc` | Run cost/rev evaluation |


### Error Responses

tbd