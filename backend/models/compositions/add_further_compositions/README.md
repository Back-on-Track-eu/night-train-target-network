# Add Further Compositions — Workspace

Staging area for proposing **new train compositions** (train concepts) for the
target-network model. Everything you author here is plain CSV + this README —
no code changes needed on your side. Once a batch is reviewed, David transfers
it into the calibration notebook
([`../calib/02_calibration.ipynb`](../calib/02_calibration.ipynb)), which is
the single source of truth that seeds the database.

**Related documentation:** composition cost model —
[`../model.py`](../model.py) · parameter derivations & existing catalog —
[`../calib/CALIBRATION.md`](../calib/CALIBRATION.md) · model layer overview —
[`../../README.md`](../../README.md)

---

## Workflow

1. **Register your sources** in `sources.csv` (one row per document, id `J01`,
   `J02`, …).
2. **Record the values you extracted** in `parameter_observations.csv` — one
   row per number per source, exactly as published (original currency, price
   year). *Never* convert or inflate here; conversion to the 2032 EUR basis
   happens exactly once, in the calibration notebook, at integration.
3. **Define new coach types** (only if your concept needs coaches not in the
   existing catalog) in `coach_types.csv` + `coach_type_sections.csv`.
4. **Define the compositions** in `compositions.csv` and their ordered coach
   list in `formations.csv`. Reusing existing catalog coaches is encouraged.
5. **Validate**: from this folder, run

   ```
   python validate.py
   ```

   (stdlib-only — any Python ≥ 3.10 works, no dependencies). Fix errors,
   read the warnings, repeat until clean.
6. **Commit and push** on the `add-further-compositions` branch, then hand
   over for review. Keep the worked `EXAMPLE-*` rows around while you learn
   the format; delete them before the final handoff (the validator reminds
   you).

Anything that doesn't fit the format — EMU/multiple-unit concepts, coaches
shared across the new/refurbished families, traction changes en route —
doesn't fit the current model either. Flag it in `notes` and raise it with
David instead of bending a column.

---

## Conventions

- **IDs are permanent natural keys.** A changed parameter set means a *new*
  `composition_type_id`, never editing an already-integrated one. Follow the
  existing naming style: `<FAMILY>-<CONCEPT>-<N_COACHES>`, e.g. `REF-BAL-9`,
  `NEW-BAL-14` (`REF` = refurbished stock, `NEW` = new-build).
- **Source ids** are `J`-prefixed here (`J01`, …) so they can never collide
  with the calibration register (`S01`, …). You may *reference* existing
  `S`-ids in `source_ids` columns when a value comes from a document already
  in the register (see `../calib/CALIBRATION.md` for the list).
- **`source_ids` columns** hold a `;`-separated list, e.g. `J01;S03`. Every
  parameter you fill should be traceable to at least one source; use
  `TO_VERIFY` in `notes` where it isn't yet, not an invented id.
- **Booleans** are literal `True` / `False`. **Decimal separator** is `.`
  (period). **Units** are in the column names.
- **Source documents** (PDFs, spreadsheets) are *not* committed to this
  public repository — put them in the shared Drive folder and reference the
  filename in `url_or_file`.

---

## File reference

### `sources.csv`

Mirrors the calibration source register, one row per document.

| column | meaning |
|---|---|
| `source_id` | `J01`, `J02`, … |
| `short_id` | short slug used in prose, e.g. `oebb_nj_fleet` |
| `title` | full document title |
| `publisher` | issuing organisation |
| `pub_year` | publication year |
| `price_basis_year` | which year's prices the document states (often ≠ pub year) |
| `currency` | currency of the stated values |
| `kind` | `study` / `operator_disclosure` / `press` / `manufacturer` / `operator_model` / … |
| `url_or_file` | URL, or Drive filename for offline documents |
| `date_accessed` | ISO date you retrieved it |
| `reliability_note` | your judgement: projections vs. actuals, known biases, caveats |

### `parameter_observations.csv`

One row per extracted number. `parameter` is free-form but be consistent
(reuse names from `../calib/CALIBRATION.md` where they exist, e.g.
`coach_purchase_keur_m`, `coach_maint_eur_km`, `cleaning_eur_coach_day`).
`condition` narrows applicability (`new`, `refurbished`, `sleeper only`,
`any`). `confidence` ∈ `high` / `medium` / `low`. `conversion_note` is where
you *state* what conversion would be needed (currency, inflation) — without
performing it.

### `coach_types.csv`

Only for coach types **not** in the existing catalog (the validator knows the
catalog and rejects collisions). Dimensions describe the whole coach; the
`svc_*` columns carry the on-board service section (bistro corner, crew
compartment) so that revenue space can be separated — `0` when there is none.
`crew` is the coach's total attendant factor including any service staff.

| column | unit / values |
|---|---|
| `coach_type_id` | catalog-style id, e.g. `Bcmz_FAM` |
| `description` | one line: what this coach is, which real design it follows |
| `length_m`, `weight_t` | full coach, m / t |
| `svc_length_m`, `svc_weight_t` | service section share, m / t (`0` if none) |
| `crew` | attendants per coach (0.25 steps; dining car = 2.0) |
| `wifi`, `bikes`, `aircon`, `plugs` | `True` / `False` |
| `source_ids` | `;`-separated |
| `notes` | anything the columns can't say |

### `coach_type_sections.csv`

The class breakdown of each **new** coach: one row per section, `position`
starting at 1 per coach. `class_main` ∈ `seat` / `couchette` / `capsule` /
`sleeper`. `section_label` becomes the DB `class_id` as
`"<coach_type_id> - <section_label>"`, so keep it descriptive
(`couchette (4-berth)`, `Sleeper (2-berth) with shower & WC`). Per-section
`length_m` / `weight_t` are that section's share of the coach (basis of the
class cost allocation) and must sum to at most the coach's revenue space.
A coach with **no** section rows is treated as a pure service coach
(restaurant) — the validator warns so you can confirm that's intended.

### `compositions.csv`

One row per new train concept.

| column | unit / values |
|---|---|
| `composition_type_id` | `<FAMILY>-<CONCEPT>-<N>`, permanent |
| `description` | one line incl. the real-world consist it resembles |
| `material_strategy` | `new` / `refurbished` — drives purchase rate, amortisation, availability, maintenance |
| `max_speed_kmh` | composition cap (coaches; the loco has its own) |
| `hsr_allowed` | `True` / `False` — may use high-speed lines |
| `zugchef_crew_factor` | `1.19` below ten coaches, `2.38` from ten (current convention — deviations need a note) |
| `length_cost_prop` | X in the class cost allocation: X on length, 1−X on weight; catalog uses `0.7` |
| `food_and_beverages` | free-text concept, e.g. `kiosk/ trolley service/ morning service` |
| `loco_type_ids` | `;`-separated in position order; `VECTRON-MS-200` (refurbished family) / `VECTRON-MS-230` (new family); two entries = double heading |
| `source_ids` | `;`-separated — what grounds this concept |
| `notes` | open questions, TO_VERIFY items |

### `formations.csv`

The ordered coach list: `composition_type_id`, `position` (1, 2, …
contiguous), `coach_type_id`. Coaches may come from the existing catalog or
from your `coach_types.csv`. Repeat a coach id for every physical coach of
that type. Mind the family rule: a coach type belongs to exactly one material
family — don't put an existing `REF`-family coach into a `new`-strategy
composition (the validator checks this where it can).

---

## What happens after handoff

David transfers reviewed rows into `02_calibration.ipynb` (`COACH_TYPES` /
`STANDARD_COMPOSITIONS`), merges your `J`-sources into the register, re-runs
the notebook (which recomputes indicative KPIs, regenerates
`CALIBRATION.md` and the seed CSVs) and bumps `COMPOSITIONS_MODEL_VERSION`.
Your CSVs stay in this folder as the provenance record of the batch.
