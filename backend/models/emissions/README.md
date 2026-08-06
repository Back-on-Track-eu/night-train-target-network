# Emissions Model

Flat per-mode GHG intensity factors (g CO2e per passenger-km) — the
single source for the night-train, air, and car values across the
platform (`docs/PROPOSALS_DESIGN.md` decision 24).

**Related documentation:** model layer overview —
[`../README.md`](../README.md) · evaluation model (summary KPI
derivation) — [`../evaluation/README.md`](../evaluation/README.md) · API
reference — [`../../api/README.md`](../../api/README.md)

---

## What lives here

| File | Content |
|---|---|
| `factors.py` | `EMISSION_FACTORS` (per-mode `EmissionFactor(g_per_pax_km, source)`), `MODE_SHIFT_SHARES`, `EMISSIONS_MODEL_VERSION` / `EMISSIONS_MODEL_DESCRIPTION` |

There is no calculation pipeline: the model is a set of sourced
constants (EEA TERM 2020, EU-average 2018 figures). Correspondingly, the
`evaluation.models.emissions` entry of `POST /api/proposal/calc` carries
`factors` where the other models carry `formulas`.

## Consumers

- `models/evaluation/summary.py` — `co2_g_per_pax_km` on every §5.4
  summary row (the flat night-train factor) and the placeholder
  CO2-savings derivation (`shifted_km × (mode − night_train)`, combined
  with `MODE_SHIFT_SHARES`).
- `api/helpers/evaluation_serialize.py` — the `evaluation.models.emissions`
  documentation entry, so every calc/publish/load response carries the
  per-mode reference values the frontend renders next to a proposal's
  night-train figure.

**Not** a consumer: the ONTD side. Existing routes carry their own
per-route value from `ontd.trips.co2_per_km` (decision 27 — every
existing-route KPI comes from ONTD itself).

## Roadmap

- The night-train value is a flat European average until an energy-based,
  country-resolved model replaces it (`energy_kwh` per segment × country
  grid intensity ÷ sold places).
- `MODE_SHIFT_SHARES` are §8.1 demand placeholders hosted here only
  because their sole consumer is the emissions-savings placeholder — they
  move to `models/demand/` when the real demand model lands.
- The factors migrate into a scenario-versioned params table with the
  WP16 schema split; until then these constants are the single source.
