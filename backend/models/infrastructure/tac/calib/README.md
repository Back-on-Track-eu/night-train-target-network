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
└── data/                        generated — gitignored
    ├── sources_register.csv
    ├── tac_components.csv
    ├── tac_night_mode.csv
    ├── tac_peak_bands.csv
    ├── passage_charges.csv
    └── passage_geometries.geojson
```

## Regenerating

Run `01` then `02`, top to bottom. Both are stdlib-only and take no
arguments; `02` reads the register `01` writes, so the order matters.
Everything under `data/`, and `TAC_CALIBRATION.md` itself, is a generated
artifact — **never hand-edit them**, the next run overwrites the change
silently. To change a value, change the notebook.

`data/` is gitignored; `TAC_CALIBRATION.md` is committed, following the
`docs/MODEL.md` precedent for generated-but-published documents.

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
evaluation year. `calc_tac.py` never sees a currency or a price basis.

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
