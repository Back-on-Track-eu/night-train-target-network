# Night Train — Demand Model

All demand-related code lives here. Today that is exactly one thing: the
**stopgap uniform-distribution proxy** (`stopgap.py`), which populates a
`Route`'s OD pairs from a flat target utilization and per-km fares — see
`model.py` for the standard values and the open TODO describing the real
model that will replace it.

**Related documentation:** domain model & pipeline —
[`../README.md`](../README.md) · evaluation model —
[`../evaluation/README.md`](../evaluation/README.md)

## Structure

```
demand/
├── stopgap.py    # distribute_demand() — the uniform-distribution proxy
├── model.py      # DEMAND_MODEL_VERSION + stopgap standard values + open TODOs
├── docu/         # concept, implementation log, source register
└── calib/        # data acquisition and preparation for the real model
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
`adapters/proposal/README.md` §8.1).

Design and progress are tracked in [`docu/`](docu/):

- [`DEMAND_MODEL_CONCEPT.md`](docu/DEMAND_MODEL_CONCEPT.md) — what the model
  is and why it is specified that way, including the acquisition-ordered data
  inventory (§3) and the decisions taken so far (§5)
- [`IMPLEMENTATION_DOCU.md`](docu/IMPLEMENTATION_DOCU.md) — what exists, what
  was learned building it, what is next
- [`SOURCES.md`](docu/SOURCES.md) — per-file provenance and licence for every
  external input

Data work happens in [`calib/`](calib/), which separates exploration
notebooks from the ETL pipelines they produce; see
[`calib/README.md`](calib/README.md).

**Zone frame (DM1a) is complete.** `calib/out/01_zones.parquet` holds 1 514
NUTS-3 zones with identity, membership, tier, geometry, population-weighted
centroid, centroid source and the NUTS 2021↔2024 crosswalk. Batch 2 (zone
attributes) is next.
