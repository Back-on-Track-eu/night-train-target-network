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
  dict↔domain `to_dict`/`from_dict` logic lives in
  `api/helpers/*_serialize.py`, split by domain (`route_serialize.py`,
  `evaluation_serialize.py`, `params_serialize.py`,
  `proposal_serialize.py`, `feedback_serialize.py`,
  `scenario_serialize.py`)
- Layering: `api/*.py` (blueprints, thin delegation only — no dict-shaping,
  no SQL) → `api/helpers/` (validation + serialization, Flask-free apart
  from `dependencies.py`) → `adapters/` (**all** DB access — repositories,
  loaders, and the GTFS store) → `models/` (pure domain; pipeline
  *sequencing* lives in `models/pipeline.py`). Direction rules: `adapters/`
  may import the pure serializers from `api/helpers/` (they are Flask-free
  by design) but never blueprint files or `dependencies.py`; `models/`
  imports nothing from `api/` or `adapters/`. Proposal persistence is
  grouped in the `adapters/proposal/` package (`repository.py`,
  `gtfs_store.py`, `projection.py`, `engagement_repository.py`,
  `id_prefix.py`)
- Every parameter has exactly ONE home — see the "Parameter placement"
  section below for the full ruleset. Never restate a value outside its
  home; documentation names the variable and its home, not the value
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

### Routing (frontend)

- `frontend/src/router/index.ts` — `vue-router` in HTML5 history mode.
  Four routes: `/` (redirect to `/gallery`), `/gallery` (`Gallery.vue`),
  `/proposal-builder` and `/proposal/:id` (both `ProposalWorkspace.vue`).
  `App.vue` is just `<AppHeader/><router-view/><AuthModal/><ToastContainer/>`.
- `/proposal-builder` and `/proposal/:id` deliberately share **one**
  component (`ProposalWorkspace.vue`, a thin wrapper deriving
  `mode`/`proposalId` from `route.params.id` and passing them to
  `ProposalViewport`) instead of two separate route components. This is
  load-bearing, not incidental: after publishing a new proposal, the app
  does `router.replace({ name: 'proposal', params: { id } })` and relies on
  Vue Router patching the existing instance rather than remounting it —
  splitting this into two components would remount `ProposalViewport` and
  discard the just-computed state.
- Gallery's search bar (mode/from/to/station/country/sort/dir) round-trips
  through `/gallery`'s query string — it owns that sync itself
  (`useRoute`/`useRouter` inside `Gallery.vue`), reflecting its defaults into
  the URL right after mount too, via `seedToQuery`/`seedFromQuery`
  (`frontend/src/lib/proposalPrefill.ts`). `/proposal-builder`'s prefill seed
  deliberately does *not* go through the URL: `Gallery.vue`'s
  `createProposal()` stashes it in `store.pendingProposalSeed`
  (`frontend/src/stores/store.ts`) just before the push, and
  `ProposalWorkspace.vue` reads it once on mount — keeping arbitrary stop
  picks out of the address bar at the cost of not surviving a reload.
- The deployed (nginx) frontend image needs `frontend/nginx.conf`'s
  `try_files ... /index.html` fallback for history-mode routes to survive a
  direct load/refresh — keep it if `Dockerfile.demo`'s base image changes.

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


## Parameter placement

Two axes decide where a value lives: its **home** (five questions, first
"yes" wins) and its **lifecycle** (may it have a default at all).

**Gate first — parameter or contract?** If changing the value would break
a caller, invalidate stored data, or redefine a vocabulary (regexes, SQL,
column maps, enum vocabularies, trust levels, `_JWT_ALGORITHM`,
`_NAME_MAX_LEN` on persisted keys), it is a contract: it stays beside its
use, and none of the below applies. Only tunables continue.

1. **Differs between laptop / CI / staging / production?** → `.env`, read
   via `os.environ` at the point of use.
   - *Secrets and wiring* (`JWT_SECRET`, `POSTGRES_*`, `SMTP_PASSWORD`,
     URLs, ports, container names): **no code default** — missing means a
     loud failure. A default here cannot rescue a misconfiguration, only
     turn a startup crash into a silent wrong answer. Dev-side exception:
     `backend/dev_env.py` is the ONE place host-run tooling defaults are
     defined.
   - *Mode switches and data identity* (`AUTH_EMAIL_DEV_MODE`,
     `ONTD_BOOTSTRAP`, `TESTING`, Drive file ids): one code default, the
     safe/canonical value. Dev opts in to the unsafe one.
2. **Calibrated from real-world data, needs provenance + versioning?** →
   DB tables (`input_params`, `scenario`).
3. **Changing it changes model output?** → the owning model's
   `version.py` STANDARD VALUES — because changing it must bump that
   model's version. Request-body defaults applied at the API boundary
   (`DEFAULT_TIMETABLE_MODE` etc.) and the persisted-GTFS calendar window
   live here.
4. **Only shapes the HTTP request/response cycle?** → `backend/api/config.py`
   (rate limits, body/subject caps, page sizes, session TTLs). For caps
   on user input the tiebreak is: relaxing it invalidates stored data →
   contract, stays local; otherwise → `api/config.py`.
5. **Otherwise** → module constant beside the one implementation that
   uses it (`COMPUTE_CACHE_TTL_HOURS`, `ONTD_ROUTING_WORKERS`).

**One home per value.** `backend/docker/.env.example` lists every
per-environment variable; variables whose default lives in code appear
there commented out, name-only. The single sanctioned restatement:
compose files may mirror port defaults as `${VAR:-value}` fallbacks,
which must stay equal to `.env.example`.

**One dev-side `.env`.** `backend/docker/.env` configures the main stack,
the devcontainer overlay, the standalone db/dev stack, and (via
`backend/dev_env.py`) all host-run scripts, tests, and ontd loaders.
Server deployments in `deploy/` intentionally do NOT read it — they
enumerate their environment explicitly.

At boot, `api/config.py::log_effective_config()` logs every resolved
non-secret setting, so a deployment's effective configuration is
answered by `docker logs`.

## How to Run

### Full stack (recommended, VS Code / frontend work)

```bash
docker compose -f backend/docker/docker-compose.yml \
               -f .devcontainer/docker-compose.yml up --build
```

(The devcontainer file is an overlay on the backend stack — ports and all
other wiring come from `backend/docker/.env`; values below are the
defaults.)

- Frontend: http://localhost:5173 (`FRONTEND_HOST_PORT`; Vite HMR — edits reflect instantly)
- Backend API: http://localhost:5050 (`API_HOST_PORT` — host side moved off 5000, macOS AirPlay Receiver squats there; container binds `API_CONTAINER_PORT`, 5000)
- OpenRailRouting: http://localhost:8989 (`OPENRAILROUTING_HOST_PORT`; admin/metrics on `OPENRAILROUTING_ADMIN_HOST_PORT`, 8990)

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

### Frontend tests

```bash
cd frontend
npm test
```

Vitest, node environment, `src/**/*.test.ts` — pure logic in `src/lib` only.
Components are never mounted (no jsdom, no `@vue/test-utils`), so logic worth
testing gets extracted out of the SFC first. Not wired into CI.

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
| `backend/api/helpers/dependencies.py` | Singleton state: `DBDataLoader`, `CountryIndex`, `RailRouter`, `ProposalRepository`, `FeedbackRepository`, all built once at startup; `get_loader()` etc. for route handlers |
| `backend/api/*.py` | One blueprint file per domain: `health.py`, `params.py`, `proposal_calc.py`, `proposal_publish.py`, `proposals.py`, `proposal_compare.py`, `proposal_engagement.py`, `auth.py`, `feedback.py`, `scenarios.py` |
| `backend/api/helpers/*_serialize.py` | All `to_dict`/`from_dict` logic, split by domain — see Python conventions above |
| `backend/api/config.py` | API-layer operational limits (rate limits, body caps), env-overridable. Not secrets (env at point of use), not domain parameters (DB or `models/*/version.py`) |
| `backend/models/` | Domain layer (routing, demand, energy, evaluation, pipeline) — no serialization, no monetary values outside `models/evaluation/calc.py`. See `backend/models/README.md` |
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
POST /api/proposal/calc            merged compute (route + evaluation), stateless
POST /api/proposal/publish         @require_auth — the only user write path
GET  /api/proposals
POST /api/proposals
GET  /api/proposal/<id>
POST /api/proposals/compare        two sides, stored or what-if overrides, stateless
GET  /api/proposal/<id>/share      Open Graph link-preview stub (HTML, not JSON)
GET  /api/proposal/<id>/engagements likes + comments + event timeline
POST/DELETE /api/proposal/<id>/like
POST /api/proposal/<id>/comment
PATCH/DELETE /api/proposal/<id>/comment/<cid>
GET  /api/params/StopInfrastructures
GET  /api/params/compositions
GET  /api/params/TrackInfrastructures
GET  /api/scenarios
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
   (see the blueprint list in Important Files above) or create a new
   blueprint file
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
