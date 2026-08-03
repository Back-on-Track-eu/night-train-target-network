# Night Train — Demand Model

All demand-related code lives here. Today that is exactly one thing: the
**stopgap uniform-distribution proxy** (`stopgap.py`), which populates a
`Route`'s OD pairs from a flat target utilization and per-km fares — see
`version.py` for the standard values and the open TODO describing the real
model that will replace it.

**Related documentation:** domain model & pipeline —
[`../README.md`](../README.md) · evaluation model —
[`../evaluation/README.md`](../evaluation/README.md)

## Structure

```
demand/
├── stopgap.py    # distribute_demand() — the uniform-distribution proxy
└── version.py    # DEMAND_MODEL_VERSION + stopgap standard values + open TODOs
```

## Callers

- `models/pipeline.py::run_compute()` — every compute pass
  (`POST /api/proposal/calc`, publish) runs the stopgap after `plan_route()`.
- `db/dev/seed.py` — the seeded example proposal runs the same stopgap on
  its hand-crafted route.

Tests that need *controlled* demand (formula-correctness testing) bypass
this module entirely and set OD pairs directly
(`tests/helpers.py::add_directional_domain_demand()`).

## Incoming design

The real model's candidate structure is the French open-source night train
shift model's **log-additive factor form**, analyzed and found compatible
with the existing test suite. When it lands here, the second replacement
site is the placeholder demand KPIs in
`adapters/proposal/projection.py` (`_PLACEHOLDER_*` constants,
`docs/PROPOSALS_DESIGN.md` §8.1).
