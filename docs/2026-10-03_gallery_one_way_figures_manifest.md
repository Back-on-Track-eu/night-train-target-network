# Gallery — distance and time are one way (2026-10-03)

Backend 0.5.13, no migration, no frontend change.

## What was wrong

A proposal card read "Madrid – Oslo 7,622 km", "Berlin – Barcelona 3,904 km":
the stored summary (`models/evaluation/summary.py` `_route_metrics`) sums
**both trips of the pair** — distance and time of the full cycle — while the
existing (ONTD) side of the gallery is per direction. The card's own hover
text already said "Total one-way length of the route"; the data did not.
Sorting by distance put a 1,500 km proposal above a 2,500 km real train,
and the new typical-night-train sieve (500–2 000 km, 7–16 h) was being
asked of doubled figures.

## What changes

The gallery union halves the proposal side once, where the two sources meet
(`repository.py` `_GALLERY_PROPOSAL_BRANCH`:
`round(total_distance_km / 2, 1)`, `round(total_time_h / 2, 2)`). Every
gallery reader — list rows, range filters, sort, `map_lines`' filtered set,
the stats endpoints — sees one direction on both sides. `avg_speed_kmh` is
a ratio and unchanged.

The **stored** figure stays the cycle on purpose: `train_km_per_year`, the
supply figures (`lib/detailsScope.ts`, one operating day = one cycle) and
the builder's own KPIs (`lib/compareKpis.ts` halves journey time itself)
are built on it, `GET /api/proposal/<id>` and the family responses keep
returning it, and changing `summary.py` would be a CALC_VERSION bump that
marks every stored proposal outdated. The two trips of a pair are the same
stops in reverse, so half the cycle is one direction up to the stored
rounding.

## Mind the launch report

`GET /api/proposals/stats` and the gallery figures the report was built on
were cycle figures until now. "2.1 M km of night train route, one way",
"the typical route is 1 470 km and takes 16 hours", "286 longer than
2 000 km", "627 would take more than 16 hours one way" and the 622 /
48 % qualifying count all need to be re-run against the one-way figures
before the report goes out — the shares will move noticeably (the qualifying
share up, the too-long counts down).

## Compare keeps the cycle

`POST /api/proposals/compare` built its stored side from the gallery list
and its computed side from the calc summary, so after the halving the two
disagreed by a factor of two (test_54
`test_override_equal_to_stored_is_computed_but_identical`). The stored side
now reads the row as stored through a new `repository.stored_summary()` —
same column shape as the list, engagement counts included, no halving — so
the diff is zero again where nothing changed. The gallery list was the only
other consumer.

## Files

- `backend/adapters/proposal/repository.py` — the two halved columns in
  `_GALLERY_PROPOSAL_BRANCH`, with the rationale; `stored_summary()`.
- `backend/api/helpers/proposal_compare.py` — stored side via `stored_summary()`.
- `backend/tests/test_52_proposals_gallery_api.py` —
  `test_gallery_distance_and_time_are_one_way`.
- `backend/tests/test_56_proposal_scenario_summaries.py` — the variant row
  comparison expects the halved time.
- `backend/pyproject.toml` — 0.5.12 → 0.5.13 (`uv lock` moves `uv.lock`).
- `backend/api/README.md` §7.1, `backend/adapters/proposal/README.md` §7.1.

## Gates

ruff format + check clean (0.15.21); the union rendered through both
scenario paths and parsed. Integration tests not run here.

## Your run

```powershell
docker-compose -f backend\docker\docker-compose.yml -f .devcontainer\docker-compose.yml up --build --force-recreate -d api
cd backend; uv lock; uv run ruff format; uv run ruff check; uv run pytest tests/test_52_proposals_gallery_api.py tests/test_56_proposal_scenario_summaries.py -q; cd ..
```

Then `/gallery`: Berlin – Barcelona reads ~1,950 km; sorting by distance
interleaves proposals and existing trains sensibly; the typical toggle keeps
the proposals it should.
