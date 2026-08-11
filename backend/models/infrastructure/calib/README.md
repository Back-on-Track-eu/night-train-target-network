# Track Infrastructure Calibration

Per-country track infrastructure parameters for the 2032 target network:
track access charges, traction electricity price, shunting and parking, and
the route-context values (terrain, timetable buffer, dwell).

Mirrors `models/compositions/calib/` in structure and contract, split
further into one folder per calibration domain — see **Layout** below.

---

## Layout

```
calib/
├── 01_source_extraction.ipynb   sources_register.csv — nothing calibrated, shared
├── 06_seed_export.ipynb         reads every domain's data/ -> seed/, STDLIB-ONLY
├── resolution.py                directory anchor + (unused) resolution-ladder utility
├── README.md                    this file
├── data/
│   └── sources_register.csv     shared source register — the only file outside
│                                 a domain folder; every domain and 06 read it
├── seed/                        derived, NOT committed — read by db/dev/seed.py
│   └── ...                      (sources.csv, track_tac.csv, passage_charges.csv, ...)
│
├── tac/                          track access charges
│   ├── 02_tac_calibration.ipynb
│   ├── TAC_MODEL.md              per-country tariff narrative
│   ├── TAC_CALC_DESIGN.md        implemented-calculation decisions
│   └── data/                     tac_components.csv, tac_night_mode.csv,
│                                  tac_peak_bands.csv, passage_charges.csv,
│                                  passage_geometries.geojson
│
├── electricity_pricing/          traction electricity price per kWh
│   ├── 03_electricity_pricing_calibration.ipynb
│   ├── ELECTRICITY_PRICING.md
│   └── data/                     electricity_price_modes.csv, electricity_prices.csv
│
├── facility_calibration/         shunting and parking per event
│   ├── 04_facility_calibration.ipynb
│   ├── SHUNTING_PARKING.md
│   └── data/                     facility_charges.csv, facility_reference_rotation.csv
│
├── route_context/                terrain, buffer quota, dwell
│   ├── 05_route_context_calibration.ipynb
│   ├── TERRAIN_AND_BUFFER.md
│   └── data/                     route_context.csv, route_context_summary.csv
│
└── stops/                        RESERVED — stop/station charge calibration (later)
    └── README.md
```

Each domain folder is self-contained: its own notebook, its own narrative
`.md`, its own `data/`. The only things that cross domain boundaries are
`data/sources_register.csv` at the root (every domain cites into it) and
`06_seed_export.ipynb`, which reads across all four domains' `data/` to
assemble the unified per-country seed rows — a country's track access
charge, electricity price, facility costs and terrain/buffer figures all
end up as columns on the *same* `track_infrastructures` row downstream.

The implemented TAC calculation lives in
`backend/models/infrastructure/calc_tac.py`; its unit suite
(`tests/test_72_calc_tac_units.py`) pins the calibration reference numbers
from `tac/02_tac_calibration.ipynb` / `tac/TAC_MODEL.md`.

Run order: `01` first (writes the shared source register), then `tac/02`,
`electricity_pricing/03`, `facility_calibration/04`, `route_context/05` in
any order, then `06` last. `06` depends on the other four having produced
their `data/` output, not on their kernel state — each notebook re-reads
its own domain's `data/` files from disk, so any subset can be re-run
independently as long as `01` has run at least once.

---

## Provenance

There is no provenance framework. Provenance is **columns**, in three places
that already existed in this repo:

1. **`data/sources_register.csv`** (root, shared) — one row per document.
   Semantic ids (`FR-DRR-2027-A52`, not `I23`), because a pointer is read far
   more often than it is written and a semantic id tells a reviewer what to
   open. Ids are stable: a superseded document keeps its id and gains a note
   rather than being renumbered.

2. **`<domain>/data/*.csv`** — one row per value, long format, with
   `source_id` and `locator`. Every calibration notebook carries a small
   stdlib `SV` dataclass that enforces the invariants at construction, so a
   bad value cannot reach a CSV:

   | status | means | enforced |
   |---|---|---|
   | `sourced` | a named document at a named locator says so | needs `source_id` **and** `locator` |
   | `not_levied` | positively documented as zero | same; distinct from `missing` on purpose |
   | `derived` | arithmetic on other values | must state the formula in `note` |
   | `benchmark` | a pan-European statistic standing in for a country | — |
   | `assumed` | a judgement | must carry `low`/`high` **and** a rationale |
   | `missing` | nothing read yet — never an estimate | must have no value |
   | `no_railway` | CY, MT | must have no value |

   `locator` is what makes an extraction re-checkable a year later. A
   `source_id` alone is not enough: network statements run to hundreds of pages
   and their tariff tables move between editions.

3. **`_src` columns in `seed/`** → `input_params.sources` FKs. Provenance
   survives into the database rather than stopping at the notebook.

The status vocabulary is a claim about *evidence*, not about quality. A
well-argued `assumed` and a mis-transcribed `sourced` are both possible; the
status tells the reader which kind of thing they are looking at, and
`assumed` rows are exactly the filter for a sensitivity sweep.

---

## The stdlib-only contract

`db/dev/seed.py` regenerates missing seed CSVs by exec'ing the
pandas/matplotlib-free cells of `06_seed_export.ipynb`, and the API container
has no dev extras. So in `06`:

- no `import pandas`, no `plt.`
- **no local-module import either** — `resolution.py` is not on the path
  under that exec (see below: it's unused as a mechanism anyway)

`01` and every domain's `0N_*_calibration.ipynb` may use pandas, but only in
display and validation cells. Their compute and write paths are stdlib
`csv`, so the same fallback would work for them too.

## `resolution.py`

Defines a resolution-ladder mechanism (`EXTRACTED` > `ANCHORED` > `DEFAULT`,
`Observation`/`Resolved` dataclasses, escalation-to-2032 helpers) that **no
notebook currently imports** — each domain ended up with its own inline `SV`
dataclass instead (see Provenance above), which is what actually runs. Its
one live job today is as the **directory anchor**: every notebook's helper
cell walks up from `cwd` looking for a file literally named `resolution.py`
to find the calib root, regardless of which domain subfolder the notebook
lives in:

```python
for cand in (cwd, *cwd.parents):
    if (cand / "resolution.py").exists():
        return cand
```

This is why it stays at the `calib/` root rather than moving into a domain
folder — moving it would break that anchor for every notebook. If nothing
ever imports the ladder mechanism itself, it's a candidate for removal or
revival, but that's a separate decision from the folder layout.

---

## Seed contract (what seed.py consumes)

The TAC component model is fully in the schema
(migration `db/dev/sql/migrations/2026-07-28_tac_calibration.sql`).
`db/dev/seed.py` reads three files from `seed/` — and regenerates them by
exec'ing `06`'s stdlib cells when absent, same contract as the
compositions calibration:

- **`seed/sources.csv`** — the full register, inserted into
  `input_params.sources` with the `source_key` prefixed into the
  description (that prefix is how per-country `track_tac_src` FKs get
  resolved).
- **`seed/track_tac.csv`** — DB-ready TAC columns per country
  (`track_tac_night_mode` … `track_tac_peak_weekdays_only` plus the flat
  indicative `track_tac_eur_train_km`), **EUR-converted** — `06` is the
  single place FX happens. Merged onto seed.py's canonical country rows;
  SE keeps its flat NULL on purpose (test fixture — the flat is
  display-only, SE's component group is seeded normally).
- **`seed/passage_charges.csv`** — crossing charges with the polygon from
  `tac/data/passage_geometries.geojson` as a GeoJSON string per row,
  inserted via `ST_GeomFromGeoJSON` into `input_params.passage_charges`
  (the fifth scenario-versioned table).

`seed/track_infrastructures.csv` / `_defaults.csv` are still exported for
the wider infra columns (parking, shunting, energy, terrain, buffer) but
not yet consumed — those parameters stay hardcoded in seed.py until their
models are implemented.

Remaining schema flattening, flagged not papered over:

- **`track_terrain_category` is constrained** to Flat/Hilly/Mountainous, so
  the five model bands map down and T2/T3 both become Hilly.

---

## Reference night train

Charging formulas are train-specific, so comparing countries needs one fixed
consist — the same role the reference route plays in the composition
calibration. NT-REF is 600 t gross, 300 m, 500 places, 1 electric locomotive,
non-PSO open access, night band, conventional line.

Documented in `tac/TAC_MODEL.md`, `electricity_pricing/ELECTRICITY_PRICING.md`,
`facility_calibration/SHUNTING_PARKING.md` and
`route_context/TERRAIN_AND_BUFFER.md` alongside the per-country reasoning.
Those documents carry the narrative; the notebooks carry the numbers and
their pointers, so a tariff revision touches one line of code rather than a
paragraph of prose.
