# Facility calibration

What a **service facility** charges for handling a train that is not carrying
passengers: one shunting movement, one stabling occupation, and the power drawn
while the train stands. Calibrated per country from network statements and
facility price lists, and cross-checked against an operator-side cost model.

Same contract as `tac/calib/` and `energy_pricing/calib/`: the notebooks are
the single source of truth, everything else here is generated.

## Layout

```
facility/calib/
├── 01_source_extraction.ipynb        the source register
├── 02_facility_calibration.ipynb     the values, and the document generator
├── FACILITY_CALIBRATION.md           generated — the calibration document
├── data/                             generated — gitignored
│   ├── sources_register.csv
│   ├── facility_charges.csv          every value, native currency and basis
│   └── facility_reference_rotation.csv   the resolved result per country
└── seed/                             generated — gitignored
    ├── track_facility.csv
    ├── track_facility_default.csv
    └── sources.csv
```

## Regenerating

Run `01` then `02`, top to bottom. Both are stdlib-only except the final
display cell; `02` reads the register `01` writes, so the order matters. To
change a value, change the notebook — the next run overwrites a hand edit
silently. `db/dev/seed.py` regenerates the seed CSVs itself on a fresh
container, stopping as soon as the three files exist.

## Read this before trusting a per-country figure

This is the most assumption-heavy of the three infrastructure domains, and the
document is explicit about where:

| | sourced or derived | European default |
|---|---|---|
| Shunting IM tariff | 11 countries | 17 |
| Stabling basis | 11 countries | 17 |
| Scope class | 5 inferred from tariff wording | 23 assumed `track` |

The seventeen default countries all carry the **same** IM tariff and the same
stabling rate. Their figures differ from one another only through the labour
index — which is deliberate: that index is the one piece of per-country
variation with evidence behind it (Ramboll prices a driver-hour at 62–104 EUR/h
across fifteen countries), where inventing per-country tariffs would not be.
Read a default country's number as *the European average, tier-adjusted*.

This matters less than it looks: the market top-up dominates every all-in
figure, so a real price list for a default country moves its total by
single-digit per cents. Read a price list for the countries a chosen route set
actually touches, and skip the rest.

## The one structural idea

Raw tariffs span a factor of **150** for the same physical movement — Hungary
263 EUR, Poland 1.72, Denmark nothing — because they differ in **scope**, not
in price level. MÁV bundles the shunting locomotive; DB InfraGO sells the track
and nothing else; Adif sells the whole operation; OSE says explicitly that its
charge covers the team but not the locomotive or driver. So the model prices
what the infrastructure manager does *not* sell:

```
shunting_event = IM_tariff + market_topup(scope) × labour_index
```

That collapses the spread to 2.8× and reproduces the nox operator model's
infrastructure-access line for the German rotation to within a per cent.
Pricing from published tariffs alone books about a sixth of it.

## Four stabling bases, all carried

Europe prices an occupation per metre per started 24 h, per started hour
(Germany, length-independent by design), flat per occupation, or not at all.
All four are seeded as a basis plus one rate, and `calc_facility.py` selects
the arithmetic — reducing them to one would misprice the two that are
structurally different rather than merely differently priced.

A free allowance is subtracted before the started period rounds, and an
allowance longer than the layover zeroes the siding charge entirely (Norway
48 h, Croatia 24 h). **Hotel power is charged on the actual stabled hours
regardless** — the electricity flows whether or not the siding is free.

## Two conversions and two escalation rates

Currency at the ECB snapshot pinned in the notebook, shared with the other two
infrastructure domains. Price basis to 2032 at **two** rates, because the cost
drivers differ: shunting at 2.5 %/yr (labour, which has outrun HICP for a
decade) and stabling plus hotel power at 2.0 %/yr (land and track, and the
sourced rates carry no wage signal at all). The document records the
counter-argument — the split is worth 3–7 % on the shunting line, well inside
the ±35 % the market top-up itself carries.

## What is deliberately not modelled

- **German disponent facilities** price stabling ten times higher on a 12 h
  stay (722 EUR against 72). Which facility a route is given is published per
  facility and not knowable from a route, so the model prices the plain rate.
  This is the largest unpriced risk in the domain.
- **Pre-heating energy** — 157.828 EUR/h flat, implying 428 kW and about
  316 EUR for a winter conditioning. Real money, but seasonal, and the model
  carries no season.
- **Cleaning and interior servicing**, which are operator-side, and which is
  why the Ramboll study's *Reinigung/Abstellung* block cannot be used here
  directly.
