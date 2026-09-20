# Gallery on a chosen scenario — phase C.1 manifest (2026-09-20)

Correction after David's review of phase C: **the scenario panel must never
change which proposals are listed — only what their figures say.** Two
places broke that, both introduced by phases A and C. Backend 0.5.2 →
0.5.3 (contract change on the variant read path, no schema change, no
migration) plus the matching frontend.

## What was wrong

1. Backend: with a `scenario_variant_id`, the gallery read the proposal side
   _from_ `proposal_scenario_summaries` — so a proposal without a row for
   that variant (published before the backfill) vanished, and the filterable
   columns came from the variant row. A scenario could change the result
   set.
2. Frontend: rows with `status: "error"` were filtered out of the card list
   and only counted. A scenario could remove cards.

## What it is now

**Backend.** The variant path LEFT JOINs the scenario row onto the base
projection: identity, name, `countries`, `stop_ids`, `country_relations`,
composition and timestamps always come from `proposal_summaries`; the
figures (`_SCENARIO_FIGURE_COLUMNS`) come from the variant row when its
status is ok and are null otherwise. Three statuses: `"ok"`, `"error"`
(not evaluable on that variant), `"missing"` (rows not yet backfilled —
keeps the base geometry so the map still draws it). Corridors in
`map_lines` come only from ok rows. Same filter → same proposals on every
scenario, by construction.

**Frontend.** Every row stays a card. A card the scenario has no figures for
shows one line in place of the figure grid — "Cannot be evaluated on this
scenario." / "Not yet evaluated on this scenario." — and the panel header
counts them ("N routes without figures here").

## Files touched

### Backend

- `backend/adapters/proposal/repository.py` — `_SCENARIO_ENGAGEMENT_CTE`
  rebuilt as a LEFT JOIN from `proposal_summaries`; `_SCENARIO_FIGURE_COLUMNS`
  (the figure subset of the metric columns) rendered as
  `CASE WHEN sv.status = 'ok' THEN sv.<col> END`; `status` =
  `COALESCE(sv.status, 'missing')`; geometry from the variant when ok, the
  base when missing, none on error; `map_lines`' variant branch joins
  `status = 'ok'` rows only.
- `backend/api/proposals.py`, `api/helpers/proposal_serialize.py` — docstrings
  for the revised semantics (`"missing"`).
- `backend/tests/test_56_proposal_scenario_summaries.py` — the error-variant
  case now asserts the row keeps `stop_ids`/`name`; new
  `test_a_scenario_never_changes_the_result_set` (same filter, base vs HSR,
  same ids and total) and `test_a_proposal_without_rows_is_listed_as_missing`
  (rows deleted → `"missing"`, base geometry, back on the backfill queue;
  last in the module because it is destructive). 14 cases.
- `backend/pyproject.toml` — 0.5.3.
- `backend/adapters/proposal/README.md` §5.4a / §7.1, `backend/api/README.md`.

### Frontend

- `frontend/src/components/Gallery.vue` — no row filtering; `withoutFigures`
  count for the panel; comment on the request field corrected.
- `frontend/src/components/GalleryScenarioPanel.vue` — prop renamed
  `withoutFigures`; header text.
- `frontend/src/components/ProposalCard.vue` — `withoutFigures` /
  `noFiguresKey`: the figure grid gives way to one line on a non-ok row;
  everything else on the card unchanged.
- `frontend/src/types/api.ts` — `status: 'ok' | 'error' | 'missing'`, comments
  aligned with the contract.
- i18n `gallery.scenario.withoutFigures` (replaces `notComputable`),
  `gallery.card.notEvaluable` / `notYetEvaluated` (en/de).
- `frontend/README.md` — Gallery section corrected.

### Docs

- `docs/FRONTEND_HANDOVER.md` §24, `docs/DEPLOY_HANDOVER.md` §21 — the
  revised rule and the `"missing"` status.
- `docs/2026-09-20_gallery_scenario_plan.md` §4 — the correction recorded.

## Gates

Backend: `ruff format --check`, `ruff check` clean. Frontend: prettier,
eslint, vue-tsc, 332 vitest cases, `vite build` green. Integration tests need
the live stack.

## Your run

1. Extract, delete the zip.
2. `docker compose -f backend\\docker\\docker-compose.yml up -d --build api`,
   then `uv run pytest tests/test_56_proposal_scenario_summaries.py -v`.
3. `cd frontend && npm run ci && npm run build`.
4. In the gallery: note the count and the cards on the base; switch to
   HSR — same count, same cards, other figures; switch to a scenario your
   stack cannot compute (if any) — same cards, each with the note instead of
   figures.
