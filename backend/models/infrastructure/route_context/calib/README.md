# Route context calibration

Terrain, timetable buffer, dwell floor and high-speed line access, calibrated
per country. The parameters that shape how a train **runs** — as opposed to
what it pays, which is the other three infrastructure domains.

Same contract as `tac/calib/`, `energy_pricing/calib/` and `facility/calib/`:
the notebooks are the single source of truth, everything else here is
generated.

## Layout

```
route_context/calib/
├── 01_source_extraction.ipynb        the source register, and the ONTD extraction
├── 02_route_context_calibration.ipynb  the values, and the document generator
├── ROUTE_CONTEXT_CALIBRATION.md      generated — the calibration document
├── sources/                          COMMITTED — the ONTD observation set
│   ├── ontd_buffer_legs.csv
│   └── ontd_buffer_by_country.csv
├── data/                             generated — gitignored
│   ├── sources_register.csv
│   ├── route_context.csv
│   └── route_context_summary.csv
└── seed/                             generated — gitignored
    ├── track_route_context.csv
    ├── track_route_context_default.csv
    └── sources.csv
```

`sources/` is the one directory in any of the four calibration packages that is
**committed rather than gitignored**, and the reason is worth stating: it holds
an extraction from a live database, not a derivation. `01`'s last cell reads
`ontd.route_legs` and writes it; `02` then reads it like a source document. So
the calibration reproduces on a machine with no ONTD snapshot and no router —
the document simply reports the buffer check as pending instead of silently
omitting it.

## Regenerating

Run `01` then `02`, top to bottom. To refresh the ONTD observation set you need
a reachable database with a loaded snapshot and a rebuilt `ontd.route_legs`
(`db/ontd/projection.py` writes it); without one, `01`'s last cell says so and
leaves `sources/` untouched.

`db/dev/seed.py` never runs the extraction cell — it imports pandas, and the
seed executor skips pandas cells by contract. Seeding a fresh container must
not depend on a router pass.

## No money in this domain

The only infrastructure package with no monetary value: no FX table, no price
basis, no escalation to the evaluation year. What replaces that discipline is
unit discipline — m/km, per mille, per cent of running time and minutes per
stop are four different things, and cumulative ascent versus ruling gradient is
the easiest pair in this repository to confuse. Ascent drives energy; ruling
gradient drives traction requirement and reaches no database column at all.

## The two things to know before changing a value

**Terrain is judgement, and stays per country deliberately.** The figures are a
corridor-by-corridor assessment, right in ranking and band, ±1 m/km within a
band. The within-country spread often exceeds the between-country spread
(Norway's Oslo–Göteborg is T1 and Oslo–Bergen is T4), so the obvious fix is
per-segment terrain from routed geometry — which the router cannot supply,
because it carries no elevation. The alternative is therefore not finer
terrain, it is dropping the terrain term entirely. A national average feeding
one term of a model that is itself a flat 28 kWh/train-km placeholder is the
right precision for now.

**The dwell floor and the high-speed flag are uniform, and stay per-country
columns anyway.** 2 minutes and `false` for all 28. The column is not leftover
detail: a scenario overrides per country, so it is what lets one ask *what if
Spanish high-speed access opened* without a schema change. The uniform value is
the calibration; the column is the lever.

## Buffer, and why the ONTD check matters more here than elsewhere

There is no tariff document for a timetable supplement, so nothing in this
package is `sourced` the way a network statement sources a charge. The buffer
comes from a formula over two RMMS indicators, and its delay coefficient was
chosen to land the output inside published practice — which is honest but
circular. `ontd.route_legs` breaks the circle: real night-train timetables
against the router's own passage times, per leg, attributed per country.

Read the two correlations in §3 of the document before the levels. If implied
buffer rises with utilisation and falls with punctuality, the residual is
mostly buffer and the coefficients can be refitted. If it does not, the
residual is mostly router speed error — and the answer is to fix the router's
line-speed model, not to move the quotas.
