# Energy pricing calibration

The price of the electricity a night train draws **while driving**, and the
charges an infrastructure manager levies for supplying it, calibrated per
country from Eurostat, network statements, tariff lists and tax law.

Same contract as `models/infrastructure/tac/calib/`: the notebooks are the
single source of truth, everything else here is a generated artifact.

## Layout

```
energy_pricing/calib/
├── 01_source_extraction.ipynb        the source register
├── 02_energy_pricing_calibration.ipynb  the values, and the document generator
├── ENERGY_PRICING_CALIBRATION.md     generated — the calibration document
├── energy_price_by_country.svg       generated — Figure 1 of that document
├── data/                             generated — gitignored
│   ├── sources_register.csv
│   ├── energy_prices.csv             every component, native currency and basis
│   └── energy_price_modes.csv        the resolved result, one row per country
└── seed/                             generated — gitignored
    ├── track_energy.csv
    ├── track_energy_default.csv
    └── sources.csv
```

`data/` is the calibration record and `seed/` is what the database reads — the
same values, converted, pivoted one row per country, and reduced to the columns
`db/dev/seed.py` inserts. Keeping them apart is what lets a reviewer check
`data/` line by line against a source document while the seed step handles a
plain number and no units.

## Regenerating

Run `01` then `02`, top to bottom. Both are stdlib-only except the final
figure cell; `02` reads the register `01` writes, so the order matters.
Everything under `data/` and `seed/`, plus `ENERGY_PRICING_CALIBRATION.md` and
the SVG, is generated — **never hand-edit them**, the next run overwrites the
change silently. To change a value, change the notebook.

`data/` and `seed/` are gitignored; the document and the figure are committed,
following the `docs/MODEL.md` precedent for generated-but-published documents.

Nothing has to be run by hand for a fresh stack: `db/dev/seed.py` regenerates
the seed CSVs itself when they are absent, executing both notebooks in order
and stopping as soon as the three files exist. That stop is what keeps the
committed document from being rewritten on every container start — the figure
cell also imports matplotlib, which the seed executor skips.

## What belongs here, and what does not

Driving energy only:

- the traction electricity price in EUR/kWh, day and — for AT, CH and HR —
  night;
- the charge for using the catenary and the traction power-supply
  installations, in the unit the infrastructure manager publishes.

Not here, each for a stated reason (the document's scope table says it in
full): consumption in kWh belongs to `models/energy/`; stabling and
pre-heating energy belong to the facility domain, since they are drawn
standing and priced two to three times higher; the minimum access package
belongs to `models/infrastructure/tac/`.

The TAC boundary is the load-bearing one. `TAC_CALIBRATION.md` records an
"excluded (energy)" line for eighteen countries, and `02` asserts that every
one of them has a position here — priced, documented as not levied, or MISSING
with the document named. That assertion is what stops a charge falling between
the two domains, or being counted in both.

## Two conversions, both here

A calibrated value is what the source says: native currency, at the document's
own price basis. Both conversions happen once, in `02`:

1. **Currency** — ECB reference rates, snapshot pinned in the notebook. The
   same snapshot the TAC calibration pins, deliberately, so a scenario repins
   one date rather than two.
2. **Price basis → evaluation year** — 2 %/yr, nominal HICP.

The 2 % is where this domain parts company with TAC's 3 %. Track access rises
in real terms because Directive 2012/34 pushes infrastructure managers towards
full cost recovery; a traded commodity has no such mechanism, and European
power forwards run flat to falling in real terms beyond 2027. Two documented
deviations apply, and a parameter-level deviation outranks a country-level one:
statutory electricity excise does not escalate at all (Germany's rail rate is
unchanged 2016 → 2027, which is the evidence), and Slovakia's frozen Measure
2/2018 rates carry the same 0 %/yr as its track charges.

## What the seed export adds

Two things the calibration record does not carry, because they are database
concerns rather than tariff facts:

- **The fallback row.** A country the model routes through but the register has
  no price for is priced from the European **median** day price
  (`track_energy_default.csv`), not the mean — the spread runs from 0.06 to
  0.33 EUR/kWh and a mean over that lands on a figure no market charges. Only
  the day price is defaulted: a night band and a supply-equipment charge are
  national particularities, and handing one to every uncalibrated country
  would invent tariff structure rather than fill a gap.
- **The source register, reduced.** Only documents an actual value cites are
  seeded; an unused register row is a research note, not provenance. Documents
  cited by both this domain and TAC produce an identical description row, so
  `db/dev/seed.py` de-duplicates on the description rather than inserting the
  same source twice.
