# Station charges — your task list

**Owner:** Josua · **Handed over:** 2026-08-25

Every stop in the catalog currently costs the same **11.28 EUR per call**,
because only Germany has real figures. Your job is the rest of Europe:
one CSV per country, all in the same shape.

**Germany is finished — use it as your worked example, don't touch it.**

---

## How it works

```
network statement / station price list  (per country, PDF or XLSX)
        │  transcribe into the template
        ▼
charges/sources/<cc>_station_charges.csv      ← your deliverable
        │  02_station_charges.ipynb reads every file the same way
        ▼
charges/data/station_charges.csv
        │  step10_export_seed_stops.py joins it onto the catalog
        ▼
the seeded stop catalog → the cost model
```

The template is `sources/TEMPLATE.md` — eleven columns, read it first.
`sources/de_station_charges.csv` is a complete example of a country done right.

---

## Your list

Do them in this order — biggest catalog coverage first.

### 1. Countries with stations to price

| # | Country | Catalog stops | Notes |
|---|---|---|---|
| 1 | IT | 85 | |
| 2 | RO | 56 | |
| 3 | GB | 56 | Network Rail station long-term charge |
| 4 | ES | 55 | |
| 5 | NL | 30 | |
| 6 | AT | 26 | Johanna had figures — **no source**, re-do from the ÖBB document |
| 7 | BG | 23 | |
| 8 | CH | 23 | |
| 9 | HU | 23 | |
| 10 | SK | 16 | Johanna had figures — **no source**, re-do from the ŽSR document |
| 11 | FI | 14 | |
| 12 | PT | 11 | Johanna had figures — **no source**, re-do from the IP document |
| 13 | RS | 7 | |
| 14 | LT | 6 | |
| 15 | SI | 5 | |
| 16 | BA | 4 | |
| 17 | ME | 3 | |
| 18 | AL | 2 | |

### 2. Countries Johanna listed as levying no station charge

**BE, CZ, DK, EE, FR, GR, HR, IE, LU, LV, NO, PL, SE** (13 countries,
286 catalog stops — FR and PL alone are 169).

**This list is unsourced.** It came from a notebook of Johanna's that has since
been deleted, and it cites no documents. Treat it as a hypothesis, not a
finding: check each country's network statement yourself. If a country really
levies nothing, that is a *result* and gets a file too — same template, empty
`charge_eur`, and a `note` plus `source_ref` recording which document says so.
A missing file cannot be told apart from a country nobody has looked at.

France and Poland are worth doing early despite being on this list: 169 stops
ride on whether it is true.

### 3. Not needed

TR, UA, MD, MK, XK — the model does not seed these countries, so their stops
never reach the cost model. Skip them.

---

## For each country

1. Find the document — the network statement (annex on station charges) or a
   separate station price list. Download it into `charges/sources/`.
2. Register it in `01_source_extraction.ipynb`: one tuple, same column order as
   the others, `downloaded` = `x`. Use the German entry as the pattern.
3. Transcribe into `sources/<cc>_station_charges.csv` per `TEMPLATE.md`.
   Look up each catalog `stop_id` yourself while transcribing — that is what
   makes the reader trivial. `stop_seed_catalog.csv` has the ids, filtered by
   `country_code`.
4. Add the country to `CHARGE_FILES` in `02_station_charges.ipynb` — one line.
5. Run `02_station_charges.ipynb`, then from `charges/`:
   `python ../step10_export_seed_stops.py`.
6. `uv run ruff format .` from `backend/`.

The reader **raises** rather than skipping: a wrong `stop_id`, a header that
doesn't match the template, or a foreign `country_code` stops the run. That is
deliberate — a skipped row is a station quietly falling back to 11.28 EUR,
which looks exactly like a station nobody has priced.

---

## Rules

- **Only sourced values.** No estimates, no interpolating between a country's
  tariff classes for a station the document doesn't list. A stop with no
  defensible figure is left out and resolves through the default.
- **One charge per stop**, for one night train calling once. Where a document
  publishes several figures, take the one a night train pays and say which in
  `note`. (Germany: the SPFV long-distance share, not SPNV.)
- **Both money figures, plus the rate.** `charge_excl_vat_eur`,
  `vat_rate_per` (as a percentage: `19.0`) and `charge_incl_vat_eur`. Fill in
  whichever the document prints and compute the other. The reader checks that
  the three agree to the cent and raises if they don't — that check is what
  catches a mistyped digit or a gross figure entered as net. The cost model
  prices from the net column.
- **Published year as printed** in `price_basis_year`. Escalation to 2032
  prices happens once, later, across all countries — never per row.
- The notebooks are the source of truth; `data/station_charges.csv` is
  generated and gitignored. Never hand-edit it.

---

## When your first country lands

Two integration tests currently **skip** for want of a single sourced charge
outside Germany. They start running as soon as one lands — that is your signal
that the whole path works:

- `test_04_versioning.py::test_stop_explicit_charge_is_not_default`
- `test_10_params_api.py::test_is_default_flags_via_api`

---

## What Germany looks like (your example)

105 of 105 catalog stops priced from *Stationspreisliste 2026* (DB InfraGO,
valid from 01.01.2026), extracted from the published PDF and matched to the
catalog. Charges 6.59–107.52 EUR per call net (7.84–127.95 gross at 19% VAT),
the SPFV long-distance share. Registered as `DE-DB-SPL-2026`. Nothing
outstanding.
