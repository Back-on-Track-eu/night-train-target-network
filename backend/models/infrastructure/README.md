# Infrastructure parameters

Everything a country charges a night train, and everything about a country
that shapes how the train runs. Four calibrated domains, each a self-contained
package with its own source register, notebooks, seed export and published
calibration document.

| Package | What it calibrates | Priced by | Document |
|---|---|---|---|
| `tac/` | Track access charges — the minimum access package | `calc_tac.py` | `TAC_CALIBRATION.md` |
| `energy_pricing/` | Traction electricity, day and night, plus catenary charges | `calc_energy_price.py` | `ENERGY_PRICING_CALIBRATION.md` |
| `facility/` | Shunting, stabling, hotel power | `calc_facility.py` | `FACILITY_CALIBRATION.md` |
| `route_context/` | Terrain, schedule supplement, dwell floor, HSR access | — no calc module | `ROUTE_CONTEXT_CALIBRATION.md` |

Route context has no calc module because nothing in it is a charge: its values
are read directly by the energy model (terrain), the router (schedule
supplement) and the timetable (dwell floor, high-speed access).

`model.py` holds `INFRA_MODEL_VERSION`, the changelog and the standard values
that belong to no single domain. `STOP_CLASSIFICATION.md` documents the stop
catalog pipeline; `stops/` is reserved for the station-charge calibration that
does not exist yet.

## The contract every package follows

**Notebooks are the source of truth.** `01_source_extraction.ipynb` writes the
domain's source register; `02_<domain>_calibration.ipynb` writes every value,
the seed CSVs and the calibration document. Everything under `data/` and
`seed/` is generated and gitignored — never hand-edit it, the next run
overwrites the change silently. The documents and figures are committed,
following the `docs/MODEL.md` precedent for generated-but-published files.

**Seeding regenerates what is missing.** `db/dev/seed.py` runs a domain's
notebooks itself when its `seed/*.csv` are absent, executing only the cells
that are stdlib-only — which is why compute and export cells must not import
pandas, and why display, figure and live-database cells must. A fresh
container therefore needs no manual step and no router.

**Provenance is columns, not a framework.** One row per document in
`data/sources_register.csv` with a semantic id (`AT-SNNB-2026`); one row per
value in `data/*.csv` with `source_id`, `locator` and a status
(`sourced`, `derived`, `benchmark`, `assumed`, `not_levied`, `missing`,
`no_railway`); and `_src` foreign keys carrying it into
`input_params.sources` so it survives into the database. `assumed` carries a
mandatory low/high band, `derived` a formula, and `missing` is always explicit
— a gap must never look like a zero.

**Money is converted once.** Currency at a pinned ECB snapshot and price basis
carried to the 2032 evaluation year, both inside the calibration notebook,
before anything is seeded. No calc module, adapter or seed script ever sees a
currency or a price basis. Escalation rates differ by domain and each states
its reasoning: track access 3 %/yr, energy 2 %, shunting 2.5 %, stabling 2 %.
Route context is the exception with no monetary value at all.

## Reading a calibrated number honestly

Each document opens with a provenance count, and they differ sharply. TAC is
mostly sourced from network statements. Energy pricing is a benchmark plus
documented overrides. Facility is dominated by one assumption — the market
top-up — with seventeen of twenty-eight countries on a European default.
Route context has no `sourced` values at all, because no document publishes a
timetable supplement.

Two consequences worth carrying: a country figure is not automatically a
national tariff (in facility and route context it is frequently the European
average, tier-adjusted), and the calibration documents say which is which per
country rather than leaving it to be inferred.

## Open

- **Stop charges** (`stops/`) are still a flat seeded value per stop with no
  calibration behind them.
- **Route context is the weakest domain** and its own document says so: the
  schedule supplement is measured against a router whose speed model is
  optimistic, and the two cannot be separated by that measurement. Since
  2026-09-05 it is calibrated as a *minimum driving time* (lower quartile of
  the leg-level residual; France a documented exception) with arrival-hour
  stretching left to the timetable layer — the Wien–Paris check that forced
  the change is in `ROUTE_CONTEXT_CALIBRATION.md` §3. The utilisation and
  punctuality inputs are calibrated and unused, waiting for a
  night-train-priority scenario.
- **The energy consumption model** (`models/energy/`) is still a flat
  28 kWh/train-km placeholder. Its `f_terrain` coefficient must be fitted
  against the seeded 1–100 terrain score, not the 1.0–1.8 values that
  preceded it.
