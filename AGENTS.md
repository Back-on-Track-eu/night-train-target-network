# AGENTS.md — AI Assistant Guide for night-train-target-network

## Project Overview

Economic model for a future European Night Train Network.
This is a **monorepo** with two independently deployable parts:

| Part       | Location              | Language                      | Entry point              |
| ---------- | --------------------- | ----------------------------- | ------------------------ |
| Backend API | `backend/`           | Python 3.12 (Flask, uv)       | `backend/main.py`        |
| Frontend SPA | `frontend/`         | TypeScript (Vue 3, Vite)      | `frontend/src/main.ts`   |

Infrastructure: Docker Compose at `.devcontainer/docker-compose.yml` with three services —
`openrailrouting` (Java/GraphHopper, ports 8989/8990), `api` (Flask, port 5000), `frontend` (Vite, port 5173).

---

## Key Conventions

### Python (backend)

- Style: **Black** (line length 88, configured in `backend/pyproject.toml`)
- Type hints: required on all public function signatures
- Imports: stdlib → third-party → local, separated by blank lines
- Logging: module-level `logger = logging.getLogger(__name__)`; use `%s` lazy interpolation, not f-strings
- Dependencies: managed with `uv` (`pyproject.toml` + `uv.lock`); never run `pip install` directly in the project

### TypeScript / Vue (frontend)

- **All** components use `<script setup lang="ts">` — no Options API, no `defineComponent`
- ESLint rule `vue/component-api-style: ['error', ['script-setup']]` enforces this
- Pinia stores: Composition API form (function-form `defineStore`), not Options API stores
- No `any` types — use `unknown` and narrow; ESLint warns on `@typescript-eslint/no-explicit-any`
- HTTP: native `fetch` only — no axios or other HTTP libraries
- Translations: all user-facing strings through `vue-i18n`'s `t()` — no hardcoded strings in templates
- File naming: components `PascalCase.vue`, stores `camelCaseStore.ts`, composables `useFoo.ts`
- Block order in `.vue` files: `<script>` → `<template>` → `<style>` (enforced by ESLint)

### CSS / Styling

- Tailwind CSS v4 (no `tailwind.config.js` — uses `@tailwindcss/vite` plugin)
- PrimeVue 4 in styled mode with Lara theme preset (`@primeuix/themes/lara`)
- CSS layer order declared in `frontend/src/style.css` and `frontend/src/main.ts` must stay in sync:
  `tailwind-base → primevue → tailwind-utilities`
- Use PrimeVue design tokens (`text-primary-700`, `bg-surface-50`) for brand colours; Tailwind for layout/spacing
- Icons: use `<AppIcon :path="mdiXxx" />` from `@/components/AppIcon.vue` with path constants imported from `@mdi/js` — never use `<i class="mdi mdi-*">` CSS font classes

---

## How to Run

### Full stack (recommended)

```bash
docker compose -f .devcontainer/docker-compose.yml up --build
```

- Frontend: http://localhost:5173 (Vite HMR — edits reflect instantly)
- Backend API: http://localhost:5000
- OpenRailRouting: http://localhost:8989

### Backend only

```bash
cd backend
uv run python main.py
```

### Frontend only (backend running separately)

```bash
cd frontend
npm install
npm run dev
```

---

## Important Files

| File | Purpose |
| ---- | ------- |
| `backend/main.py` | Flask app factory, blueprints, error handlers |
| `backend/api/dependencies.py` | Singleton data-loader state; `require_data()` guard |
| `backend/api/routes/data.py` | `POST /api/data/load`, `POST /api/data/reload`, `GET /api/data/status` |
| `backend/tests/test_health.py` | Smoke tests that run in CI without Google credentials |
| `frontend/src/main.ts` | App bootstrap — plugin registration order matters |
| `frontend/src/style.css` | Tailwind v4 import + CSS layer order declaration |
| `frontend/src/stores/store.ts` | Pinia store — currently containing everything but might have more in the future |
| `frontend/src/i18n/index.ts` | i18n setup; add new locales here |
| `frontend/src/i18n/locales/en.json` | English translation strings |
| `.devcontainer/docker-compose.yml` | Three-service Docker setup |
| `.github/workflows/ci.yml` | CI: prettier, black, pytest, vue-tsc |
| `.pre-commit-config.yaml` | Pre-commit: black (backend) + prettier (frontend) |

---

## Adding New Features

### New API endpoint

1. Add route to an existing file in `backend/api/routes/` or create a new file
2. Register the blueprint in `backend/main.py` if it is a new file
3. Add TypeScript types in `frontend/src/types/api.ts`
4. Add a Pinia action in the relevant store under `frontend/src/stores/`
5. Add i18n strings for any new UI messages

### New Pinia store

Follow the Composition API pattern in `frontend/src/stores/store.ts`.
Name the file `<name>Store.ts`.

---

## CI/CD

GitHub Actions at `.github/workflows/ci.yml` — four jobs, all triggered on push/PR to `main`:

| Job | What it checks |
| --- | -------------- |
| `prettier-check` | Frontend formatting (`npm run format:check`) |
| `black-check` | Backend Python formatting (`black --check backend/`) |
| `test` | Backend unit tests (`uv run pytest tests/ -v`) — no Google credentials needed |
| `type-check` | Frontend TypeScript (`npm run type-check` via vue-tsc) |

### Pre-commit hooks

Mirrors CI formatting locally. Install once per machine:

```bash
pip install pre-commit
pre-commit install
```

Run manually: `pre-commit run --all-files`
