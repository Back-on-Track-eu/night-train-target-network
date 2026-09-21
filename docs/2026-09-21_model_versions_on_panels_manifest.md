# Model versions beside every panel — manifest and handover

Date: 2026-09-21 · Scope: **backend `0.5.5 → 0.5.6` + frontend.** No model
version bump: `evaluation_serialize.py` is not a gated model file, no
formula, schema or member shape changed — `GET /api/models` gains two
entries.

## What changed

Only the cost model's version was on screen (under the breakdown). Now every
model that produces figures is named where its figures show, as one muted
line in the panel's foot:

| Where | Line |
|---|---|
| Route stats (top of the builder) | *Route builder 0.9.40* — the result's own `route_builder_version` |
| Scenario and main figures | *Demand model 0.1.0 · Emissions model 0.2.0* — the result's demand block, and the registry |
| Costs and revenue | *Cost model 0.9.34* (as before, new wording) |
| Details › Demand | *Demand model* |
| Details › Supply | *Composition model 0.9.5 · Demand model* |
| Details › Train operation | *Cost model · Composition model* |
| Details › Infrastructure | *Infrastructure model 0.9.7 · Energy model 1.1.2* |
| Details › Overhead | *Cost model* |

Per-result versions (route builder, cost, demand) are read from the result
on screen, so a stored proposal names what it was computed with; the
parameter and factor models (compositions, infrastructure, energy,
emissions) come from the registry the store fetches once per session.

## Backend

| File | Change |
|---|---|
| `backend/api/helpers/evaluation_serialize.py` | `models_to_dict()` lists `compositions` (`COMPOSITIONS_MODEL_VERSION`) and `infrastructure` (`INFRA_MODEL_VERSION`) with version and description only; docstring says why they carry no formulas. |
| `backend/tests/test_10_params_api.py` | The "exactly one of formulas / factors / defaults" rule becomes "at most one"; new `test_every_pipeline_model_is_listed` pins the seven entries. |
| `backend/api/README.md` | Models section lists the two entries. |
| `backend/pyproject.toml` | `0.5.6`. |

## Frontend

| File | Change |
|---|---|
| **new** `frontend/src/components/ModelVersions.vue` | One line from `{ label, version }[]`, skipping missing versions. |
| `frontend/src/types/api.ts` | `ModelVersionSection`; `EvaluationModels` gains optional `emissions`, `compositions`, `infrastructure`; `EvaluationResponse` gains `route_builder_version`. |
| `frontend/src/components/ProposalViewport.vue` | Fills `route_builder_version` into `calcResult`; the line under the route stats. Contains today's earlier changes — extract after those zips. |
| `frontend/src/components/ProposalResults.vue` | Line under the KPI grid. |
| `frontend/src/components/CostRevenueBreakdown.vue` | The old version line replaced. |
| `frontend/src/components/DetailsSection.vue` | `tabModels` per tab, one line at the foot of the open tab. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.models.*` (7 labels); `proposal.evaluation.calcVersion` removed. 908 keys each, in parity. |

## Pipeline

1. Rebuild the API image and run `uv run --extra dev python -m pytest tests/test_10_params_api.py -v` against the stack (the registry tests need the live endpoint).
2. `uv run ruff format --check` / `ruff check` on `backend/` — clean here with the project's default rule set.
3. Frontend: `vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean · `vitest run` **376 passed** · `vite build` OK.

## Deployment handover

API image and frontend image. No environment variable, no migration, no
cache flush — an older frontend ignores the two new registry entries, an
older backend leaves those lines empty rather than wrong.

## Commit split

- `feat(api): list the compositions and infrastructure models in GET /api/models` — backend files.
- `feat(builder): name every model version beside the panel that reads it` — frontend files.
- `docs: model versions manifest` — this file.
