# AGENTS.md — AI Assistant Guide for night-train-target-network

## Project Overview

Economic model for a future European Night Train Network.
This is a **monorepo** with two independently deployable parts:

| Part         | Location    | Language                 | Entry point             |
| ------------ | ----------- | ------------------------ | ------------------------ |
| Backend API  | `backend/`  | Python 3.12 (Flask, uv)  | `backend/main.py`       |
| Frontend SPA | `frontend/` | TypeScript (Vue 3, Vite) | `frontend/src/main.ts`  |
| Server deploy | `deploy/`  | Compose + bash           | `deploy/bot-server-app/README.md` |

Data lives in PostgreSQL 16/PostGIS. Routing is served by a self-hosted
OpenRailRouting (GraphHopper fork) container. There are two Docker Compose
files describing the same three backend services, kept manually in sync:

- `backend/docker/docker-compose.yml` — canonical backend stack (`postgres`,
  `openrailrouting`, `api`). Used by backend developers and CI.
- `.devcontainer/docker-compose.yml` — self-contained duplicate for VS Code
  / frontend developers, adding a fourth `frontend` service. See that file's
  header comment: it must be updated by hand whenever the canonical file's
  service definitions change.

---

## Key Conventions

### Python (backend)

- Style: **`ruff format`** (`ruff==0.15.21`, enforced in CI and pre-commit);
  config is the single `[tool.ruff]` section in `backend/pyproject.toml`
- Dependencies: managed with `uv` (`pyproject.toml` + `uv.lock`); never run
  `pip install` directly in the project — use `uv add`/`uv sync`
- Domain objects in `models/` carry **no serialization methods** — all
  `to_dict`/`from_dict` logic lives exclusively in `api/helpers/*_serialize.py`,
  split by domain (`route_serialize.py`, `evaluation_serialize.py`,
  `params_serialize.py`, `proposal_serialize.py`, `feedback_serialize.py`,
  `scenario_serialize.py`)
- No dict-shaping or SQL in blueprint files (`api/*.py`) — blueprints are
  thin delegation only
- Meaningful but sparse comments; longer explanations go in module
  docstrings or READMEs, not inline blocks

### TypeScript / Vue (frontend)

- **All** components use `<script setup lang="ts">` — no Options API, no
  `defineComponent`
- ESLint rule `vue/component-api-style: ['error', ['script-setup']]`
  enforces this
- Pinia stores: Composition API form (function-form `defineStore`), not
  Options API stores
- No `any` types — use `unknown` and narrow; ESLint warns on
  `@typescript-eslint/no-explicit-any`
- HTTP: native `fetch` only — no axios or other HTTP libraries
- Translations: all user-facing strings through `vue-i18n`'s `t()` — no
  hardcoded strings in templates
- File naming: components `PascalCase.vue`, stores `camelCaseStore.ts`,
  composables `useFoo.ts`
- Block order in `.vue` files: `<script>` → `<template>` → `<style>`
  (enforced by ESLint)

### CSS / Styling

- Tailwind CSS v4 (no `tailwind.config.js` — uses `@tailwindcss/vite` plugin)
- PrimeVue 4 in styled mode with Lara theme preset (`@primeuix/themes/lara`)
- CSS layer order declared in `frontend/src/style.css` and
  `frontend/src/main.ts` must stay in sync:
  `tailwind-base → primevue → tailwind-utilities`
- Use PrimeVue design tokens (`text-primary-700`, `bg-surface-50`) for brand
  colours; Tailwind for layout/spacing
- Icons: use `<AppIcon :path="mdiXxx" />` from `@/components/AppIcon.vue`
  with path constants imported from `@mdi/js` — never use
  `<i class="mdi mdi-*">` CSS font classes
- Math/LaTeX: render backend-provided LaTeX (e.g. `models.evaluation.formulas`)
  with **KaTeX** (`katex.renderToString` + `katex/dist/katex.min.css`) — no
  other math renderer is bundled

---

## How to Run

### Full stack (recommended, VS Code / frontend work)

```bash
docker compose -f .devcontainer/docker-compose.yml up --build
```

- Frontend: http://localhost:5173 (Vite HMR — edits reflect instantly)
- Backend API: http://localhost:5000
- OpenRailRouting: http://localhost:8989 (admin/metrics on 8990)

### Backend stack only (PyCharm / backend work)

```bash
cd backend/docker
cp .env.example .env   # first time only
docker-compose up -d   # postgres, openrailrouting, api
```

See `backend/DEVELOPMENT.md` for the full backend workflow, including
running Flask outside Docker for step-through debugging.

### Frontend only (backend running separately)

```bash
cd frontend
npm install
npm run dev
```

### Backend tests

```bash
cd backend
uv run --extra dev pytest tests/ -v
```

Requires the full Docker stack (`postgres` + `openrailrouting` + `api`)
running — these are integration tests against a live stack, not mocks. See
`backend/tests/README.md` for the full test layout.

### Deploy stack rehearsal (validate a deploy without a server)

```bash
cd deploy/bot-server-app && ./local.sh    # → http://localhost:8090
```

Runs the same compose stack the servers run (no routing engine — route
planning fails, everything else works). See `deploy/bot-server-app/README.md`.

---

## Branches, environments & deployment

There is **no `main` branch**. Two protected branches map to two server
environments; all work lands via pull request:

| Branch | Role | Deploys to (on merge) |
| ------ | ---- | --------------------- |
| `staging` | Integration — every PR targets this | staging env, `targetnetwork.65.109.137.97.sslip.io` (basic-auth) |
| `production` | Released — receives `staging` merges once tested | `targetnetwork.back-on-track.eu` |

A merged PR triggers `.github/workflows/deploy-staging.yml` /
`deploy-production.yml`: SSH to bot-server → `deploy/bot-server-app/deploy.sh`
(pull, build, **apply pending DB migrations before the api starts**, health
check). A failed deploy is a red X on the merge commit.

---

## Database changes — the migrations contract

Server databases are **never reseeded**. Every schema change ships twice:

1. folded into `backend/db/dev/sql/create_*.sql` (fresh local seeds are
   always at the latest state), **and**
2. as a dated migration `backend/db/dev/sql/migrations/YYYY-MM-DD_name.sql`
   (how the server databases move forward — applied automatically at deploy
   by `backend/db/migrate.py`).

Migration files must **not** contain their own `BEGIN;`/`COMMIT;` — the
runner wraps each file in one transaction together with its tracking record.
Full contract, `--baseline` semantics, and editorial rules:
`backend/db/README.md`.

---

## Important Files

| File | Purpose |
| ---- | ------- |
| `backend/main.py` | Flask app factory, blueprint registration, global JSON error handlers — endpoint list is in its module docstring |
| `backend/api/helpers/dependencies.py` | Singleton state: `DBDataLoader`, `CountryIndex`, `ProposalRepository`, `FeedbackRepository`, all built once at startup; `get_loader()` etc. for route handlers |
| `backend/api/*.py` | One blueprint file per domain: `health.py`, `params.py`, `route.py`, `evaluation.py`, `auth.py`, `feedback.py`, `proposals.py`, `scenarios.py` |
| `backend/api/helpers/*_serialize.py` | All `to_dict`/`from_dict` logic, split by domain — see Python conventions above |
| `backend/models/` | Domain layer (routing, energy, evaluation) — no serialization, no monetary values outside `models/evaluation/calc.py`. See `backend/models/README.md` |
| `backend/db/dev/sql/` | Schema DDL, source of truth for all environments. See `backend/db/README.md` |
| `backend/tests/` | Integration test suite, numbered by layer. See `backend/tests/README.md` |
| `frontend/src/main.ts` | App bootstrap — plugin registration order matters |
| `frontend/src/style.css` | Tailwind v4 import + CSS layer order declaration |
| `frontend/src/stores/store.ts` | Pinia store — currently containing everything but might have more in the future |
| `frontend/src/i18n/index.ts` | i18n setup; add new locales here |
| `frontend/src/i18n/locales/en.json` | English translation strings |
| `frontend/src/types/api.ts` | TypeScript types for backend responses |
| `backend/docker/docker-compose.yml` | Canonical backend Docker stack |
| `.devcontainer/docker-compose.yml` | Self-contained VS Code devcontainer stack — duplicates the above, plus `frontend` |
| `.github/workflows/ci.yml` | Frontend/backend formatting + frontend type-check (see CI/CD below) |
| `.github/workflows/backend-tests.yml` | Version-bump enforcement + full backend integration test run |
| `.pre-commit-config.yaml` | Pre-commit: ruff-format (`backend/`) + prettier (`frontend/`) |

---

## Current API Surface

Authoritative list lives in `backend/main.py`'s module docstring; kept here
for quick reference (all under `/api`):

```
GET  /api/health
GET  /api/data/status
POST /api/auth/request-code        OTP mail (rate-limited 5/h per IP)
POST /api/auth/verify              OTP → JWT; merges guest work into the account
POST /api/auth/guest               anonymous JWT (rate-limited 20/h per IP)
POST /api/feedback
GET  /api/feedback/categories
POST /api/proposal
GET  /api/proposals
POST /api/proposals
GET  /api/proposal/<id>
GET  /api/params/StopInfrastructures
GET  /api/params/compositions
GET  /api/params/TrackInfrastructures
GET  /api/scenarios
POST /api/route/plan               @optional_auth — persists on calc
POST /api/evaluation/calc          @optional_auth — persists on calc
```

Auth has two planes: the OTP/guest plane above (always on; needs
`JWT_SECRET` at boot, `SMTP_*` or `AUTH_EMAIL_DEV_MODE=true` for mail) and
a dormant Keycloak/OIDC plane that activates when `KEYCLOAK_ISSUER_URL` +
`KEYCLOAK_CLIENT_ID` are set. Details: `backend/api/README.md`.

Full request/response documentation: `backend/api/README.md`.

---

## Adding New Features

### New API endpoint

1. Add the route to the relevant existing blueprint file in `backend/api/`
   (`health.py`, `params.py`, `route.py`, `evaluation.py`, `auth.py`,
   `feedback.py`, `proposals.py`, `scenarios.py`) or create a new blueprint file
2. Register the blueprint in `backend/main.py` if it is a new file
3. Add serialization logic to the matching `api/helpers/*_serialize.py` file
   — never inline dict-shaping in the blueprint
4. Add TypeScript types in `frontend/src/types/api.ts`
5. Add a Pinia action in the relevant store under `frontend/src/stores/`
6. Add i18n strings for any new UI messages
7. Update `backend/api/README.md` and `backend/main.py`'s docstring endpoint
   list

### New Pinia store

Follow the Composition API pattern in `frontend/src/stores/store.ts`.
Name the file `<name>Store.ts`.

---

## CI/CD

Four workflows:

**`.github/workflows/ci.yml`** — runs on every push/PR to `staging`/`production`:

| Job | What it checks |
| --- | -------------- |
| `prettier-check` | Frontend formatting (`npm run format:check`) |
| `ruff-check` | Backend Python formatting (`ruff format --check backend/`) |
| `type-check` | Frontend TypeScript (`npm run type-check` via `vue-tsc`) |

**`.github/workflows/deploy-staging.yml` / `deploy-production.yml`** — on
push to the matching branch, deploy to the matching server environment (see
"Branches, environments & deployment" above).

**`.github/workflows/backend-tests.yml`** — runs on push to
`staging`/`production`/`backend-dev`, only when `backend/**` or
`.devcontainer/**` changed:

| Job | What it checks |
| --- | -------------- |
| `version-check` | Fails if a model file (route builder, energy, or evaluation) changed without a matching version-constant bump in its `version.py` |
| `test` | Builds and starts the full Docker stack (with `GIT_SHA` injected into `version.py` files), then runs `uv run --extra dev pytest tests/ -v --timeout=60` against it |

### Pre-commit hooks

Mirrors CI formatting locally. Install once per machine:

```bash
pip install pre-commit
pre-commit install
```

Run manually: `pre-commit run --all-files`

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
