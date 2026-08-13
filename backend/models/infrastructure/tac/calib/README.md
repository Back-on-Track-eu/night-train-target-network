# TAC calibration

Track access charges for the **minimum access package (MAP)** on a
passenger night train, calibrated per country from official network
statements, tariff lists and legal texts.

## Layout

```
tac/calib/
├── 01_source_extraction.ipynb   the source register
├── 02_tac_calibration.ipynb     the values, and the document generator
├── TAC_CALIBRATION.md           generated — the calibration document
├── data/                        generated — gitignored
│   ├── sources_register.csv
│   ├── tac_components.csv
│   ├── tac_night_mode.csv
│   ├── tac_peak_bands.csv
│   ├── passage_charges.csv
│   └── passage_geometries.geojson
└── seed/                        generated — gitignored
    ├── track_tac.csv
    ├── track_tac_default.csv
    ├── passage_charges.csv
    └── sources.csv
```

`data/` is the calibration record and `seed/` is what the database
reads — the same values, but converted, pivoted one row per country, and
reduced to the columns `db/dev/seed.py` inserts. Keeping them apart is
what lets a reviewer check `data/` line by line against a source document
while the seed step handles a plain number and no units.

## Regenerating

Run `01` then `02`, top to bottom. Both are stdlib-only and take no
arguments; `02` reads the register `01` writes, so the order matters.
Everything under `data/` and `seed/`, and `TAC_CALIBRATION.md` itself, is
a generated artifact — **never hand-edit them**, the next run overwrites
the change silently. To change a value, change the notebook.

`data/` and `seed/` are gitignored; `TAC_CALIBRATION.md` is committed,
following the `docs/MODEL.md` precedent for generated-but-published
documents.

Nothing has to be run by hand for a fresh stack: `db/dev/seed.py`
regenerates the seed CSVs itself when they are absent, executing both
notebooks in order and stopping as soon as the four files exist. That
stop matters — every cell here is stdlib-only, so unlike the compositions
notebook there is no pandas import to mark where the document generator
begins, and without it a committed calibration document would be rewritten
on every container start.

## What belongs here, and what does not

The MAP only. Energy (traction current, catenary access), station and
stop charges, shunting, parking and service facilities are calibrated in
their own domains and are excluded here **even where a national tariff
bundles them into one charge** — the country sections record each
exclusion so nothing is silently dropped or double-counted.

The one deliberate exception is the Swiss *Haltezuschlag*: it is a
capacity element of the path price rather than a station-usage fee, and
Switzerland levies no separate station charge for platform provision, so
it belongs to TAC. That reasoning is set out in the CH section.

## Two conversions, both here

A calibrated value is what the source document says: native currency, at
the document's own price basis. Two conversions stand between that and a
number the cost model can use, and both happen once, in `02`:

1. **Currency** — ECB reference rates, snapshot pinned in the notebook.
   Nine countries publish in a non-euro currency.
2. **Price basis → evaluation year** — 3 %/yr by default, the IRG-Rail
   European passenger average over a decade. Without it the
   infrastructure share of cost is understated against a compositions
   calibration that already sits at nominal 2032.

The database receives one plain EUR number per component, already at the
evaluation year — that conversion is what the `seed/` export applies and
`data/` deliberately does not. `calc_tac.py` never sees a currency or a
price basis, and neither does `seed.py`.

A national tariff that demonstrably does not move with the European
average takes an explicit rate of its own via `ESCALATION_OVERRIDE`, with
a mandatory reason. Slovakia is the current case: rates set by Measure
2/2018 have not changed since 2019. The override carries its own
counter-argument — a fourteen-year freeze is implausible and a revision
would likely catch up at once — so the deviation is as challengeable as
the average it replaces.

## Provenance discipline

Every value carries a status: `sourced` (named document, named locator),
`derived` (arithmetic on other values, formula in the note), `assumed`
(judgement, and then a low/high band is mandatory), `missing`, or
`no_railway`. A NULL is a statement — *this country does not levy this
term* — not an absence, which is why every country carries every
parameter. Notebook `02` fails rather than writing a citation that does
not resolve against the register.

## What the seed export adds

Three things the calibration record itself does not carry, because they
are database concerns rather than tariff facts:

- **The fallback group.** A country the model routes through but the
  register has no rate term for is priced from the European median of
  `b_day`, `b_night` and `gamma` (`track_tac_default.csv`). Median rather
  than mean: the calibrated spread runs from 0.21 to 6.94 EUR/train-km,
  and an average over that lands on a figure no network actually charges.
  Only those three terms are defaulted — a seat surcharge or a per-stop
  charge is a national particularity, and handing one to every
  uncalibrated country would invent tariff structure rather than fill a
  gap. The substitution itself happens in the loader, as a group: a
  country levying any rate term keeps its own empty components, which
  mean *not levied here*.
- **Crossing names and polygons per charge row.** Øresund is one polygon
  behind two charge rows, so the geometry is duplicated onto each — the
  database keys on the charge, not the crossing.
- **The source register, reduced.** Only documents an actual value cites
  are seeded; an unused register row is a research note, not provenance.
