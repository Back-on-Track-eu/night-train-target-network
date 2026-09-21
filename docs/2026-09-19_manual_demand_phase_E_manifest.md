# Manual demand inputs — Phase E delivery manifest

Date: 2026-09-20 · Guide: `docs/2026-09-18_manual_demand_guide.md` §6 Phase E ·
Scope: **Pipeline** — gates, version bumps verified, the deploy refresh step, handover docs.

## Gates (all run on the full A–D result)

| Gate | Result |
|---|---|
| `uv run ruff format --check .` / `ruff check .` | clean |
| `uv run python scripts/generate_model_docs.py --check` | current |
| Backend standalone units (`test_21`, `test_7x`, `test_83`, …) | green |
| Backend integration against the Docker stack | **991 passed** on your machine after Phase B (Phases C–E change no backend code) |
| CI version gate (simulated against the snapshot: every gated file that changed has its constant moved) | ROUTE_BUILDER 0.9.39 → 0.9.40 · CALC 0.9.32 → 0.9.34 · DEMAND 0.0.5 → 0.1.0 · EMISSIONS 0.1.2 → 0.2.0 (self-gated) |
| `vue-tsc --noEmit` · `eslint .` · `prettier --check .` | clean |
| `vitest run` | 325 passed |
| `vite build` | OK (with the local Mark Pro fonts) |

## What changed

| # | File | Change |
|---|---|---|
| 1 | `deploy/bot-server-app/deploy.sh` | Step 5: after the health check, `docker compose exec -T api python -m scripts.refresh_proposals --concurrency ${REFRESH_CONCURRENCY:-2}`; a failure is a WARNING with the rerun command, never a failed deploy (the on-load fallback covers it). Health loop restructured so the script can continue past it. |
| 2 | `deploy/bot-server-app/.env.example` | `REFRESH_CONCURRENCY=2`. |
| 3 | `deploy/bot-server-app/README.md` | The deploy chain now ends in the refresh. |
| 4 | `docs/DEPLOY_HANDOVER.md` | Top update note, table row, **§4f**: the two migrations (what they rewrite, the `places_sold` type change lock, the dropped table, the new `migrated` event), the three model bumps, the refresh step and its duration, what an un-refreshed row shows, the new-default-3-days note, rollback (schedule migration needs a DB restore). |
| 5 | **new** `docs/FRONTEND_HANDOVER_DEMAND.md` | The card after A–D: scopes and the dot map, state ↔ request ↔ echo, the components, the ports and the parity-fixture rule, display rules, known limits and the two improvement rounds. |
| 6 | `docs/FRONTEND_HANDOVER_SUPPLY_SETTINGS.md` | Supersession note points at the new handover. |
| 7 | `docs-site/demand.md`, `docs-site/not-modelled.md` | The public "Demand and revenue" page describes DEMAND 0.1.0; the known-gaps entry says demand is a manual input, not a placeholder. |

## Rollout, whole work package (A–E)

1. Merge to staging; `deploy.sh` applies `2026-09-19_schedule_frequency.sql` then `2026-09-19b_manual_demand.sql`, starts the api, asserts `migrate.py --check`, waits for health, runs the refresh (one to two seconds per proposal at concurrency 2 — this deploy recomputes every proposal on the environment).
2. `TRUNCATE proposals.compute_cache;` as after any model bump (§3 of the deploy handover).
3. Check: the gallery shows no `demand_kpis_placeholder = TRUE` rows after the refresh; a stored daily proposal still reads daily; a new proposal opens on Demand at Medium / 3 days a week.
4. Production: identical, from its own migration state.

## Commit split

- `chore(deploy): refresh outdated proposals after every deploy; REFRESH_CONCURRENCY knob` — files 1–3.
- `docs: deploy handover §4f, frontend handover for the manual demand inputs, public demand page` — files 4–7 and this manifest.
