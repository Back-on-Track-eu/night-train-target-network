# Composition catalog

The rolling-stock catalog of the cost model, as data: locomotive types,
real coach types with their class sections, and the standard compositions
built from them. `02_calibration.ipynb` loads these files through
`models/compositions/catalog.py`, prices every composition, and exports the
seed CSVs that `db/dev/seed.py` turns into the `input_params` catalog
tables. Nothing here is a cost rate — rates are derived in the notebook
and documented in [`../CALIBRATION.md`](../CALIBRATION.md).

**Related:** cost model anchor — [`../../model.py`](../../model.py) · loader
and rules — [`../../catalog.py`](../../catalog.py) · model layer overview —
[`../../../README.md`](../../../README.md)

## Adding a composition

1. **Sources first.** Register every document you take a number from in
   `01_source_extraction.ipynb` (register block at the end, next free `S`
   id; the catalog batch of 2026-09 is the pattern). Coach geometry and
   capacities are grounded there just like cost observations; a row without
   a source is a warning that stays until it has one.
2. **Coach types.** Add rows to `coach_types.csv` and their class breakdown
   to `coach_type_sections.csv` only for coaches not already in the catalog.
   Reusing catalog coaches is the normal case.
3. **Composition.** One row in `composition_types.csv`, the ordered coach
   list in `composition_formations.csv`.
4. **Validate** from `backend/`:

   ```
   uv run python scripts/validate_composition_catalog.py
   ```

   Errors block the seed; warnings are review notes. Fix the errors, read
   the warnings, repeat until clean.
5. **Re-run** `01_source_extraction.ipynb` then `02_calibration.ipynb` top
   to bottom. That regenerates the seed CSVs, the fleet figures and
   `CALIBRATION.md`; commit the two notebooks, the CSVs here, the figures and
   the document. Bump `COMPOSITIONS_MODEL_VERSION` (`../../model.py`) with a
   changelog entry, then `uv run python scripts/generate_model_docs.py` so
   `docs/MODEL.md` stays in step (CI checks it).

What the format cannot express — multiple units, coaches shared across the
two material families, a traction change en route — the model cannot price
either. Note it in `notes` and raise it instead of bending a column.

## Conventions

- **Ids are permanent natural keys.** A changed parameter set is a *new*
  id, never an edit of a seeded one: the compute cache keys on composition
  ids, and published proposals reference them.
- **Composition ids** are `<REF|NEW>-<CONCEPT>-<N_COACHES>`. The family
  prefix must match `material_strategy`, the number the formation length.
  Concept slugs are synthetic; the real operation a concept resembles goes
  in `description` ("similar to …"), never in the id.
- **Coach types belong to exactly one material family.** A coach used in a
  `refurbished` composition cannot appear in a `new` one.
- **Material strategy** is what the operator runs, not what the concept
  aspires to: a startup launching on converted used coaches is
  `refurbished` (53 k€/m refit, 12-year amortisation, 0.80 availability,
  1.30 €/coach-km, 200 km/h Vectron). `new` is a new-build order (145 k€/m,
  30 years, 0.909, 1.00 €/coach-km, 230 km/h Vectron).
- **Locomotive** follows the family: `VECTRON-MS-200` for refurbished,
  `VECTRON-MS-230` for new. The lease rate is derived per family, so a
  deviation needs its own rate before it can be used. Two ids
  (`;`-separated) mean double heading.
- **Zugchef factor** 1.19 for every composition (one train manager per
  train, any length — S07 Tab. 9). Expressed in attendant-equivalents so
  the seed prices it at the manager rate.
- **Weight** is gross at full load: tare + 0.1 t per place (the convention
  the energy calibration checks its mass basis against).
- **Service space.** `svc_length_m` / `svc_weight_t` carry the on-board
  service section (dining, bistro, crew compartment, luggage). A coach
  with no section rows is a pure service coach and its service section must
  be the whole coach. Section length must fit inside the revenue space
  (coach minus service); section weights should, but the 2026-07-22
  workbook's NEW-family sections exceed it slightly, so weight is advisory.
- **Class mains** are `seat`, `couchette`, `capsule`, `sleeper` — the coarse
  taxonomy the cost/stockings model and the frontend key on. A bistro or
  restaurant is service space, not a class. Private pods and rooms without
  en-suite at a couchette-level price point are `capsule`; private cabins
  sold as a premium product are `sleeper`.
- **Sub-categories live in `section_label`, not in a new column.** A
  distinct product under one of the four mains (a reclining-seat variant of
  `seat`, a branded pod concept under `capsule` or `sleeper`) gets its own
  descriptive label rather than a new `class_main` or a schema field —
  `section_label` becomes the DB `class_id` as
  `"<coach_type_id> - <section_label>"`, so the sub-category is visible
  end to end without touching the schema. Pattern:
  `"<Class main> (<what makes it distinct>)"`, e.g.
  `"Seat (reclining seat)"`, `"Capsule (Luna Rail Seat Pod)"`,
  `"Sleeper (Luna Rail Hotel Pod, single)"`. Keep it descriptive and stable —
  it is a permanent id once seeded.
- **Per-coach speed limits are not modelled.** `composition_types.csv`
  carries one `max_speed_kmh` per composition — the routing profile speed
  the material family already supports (200 refurbished, 230 new), not a
  literal cap derived from the slowest coach. A coach rated below the
  family speed (e.g. a legacy sleeper limited to 150 km/h) is a real-world
  constraint to weigh by eye when building the composition, not a catalog
  field — adding a coach-level speed would mean a matching GraphHopper
  routing profile for every speed tier, which the routing setup does not
  carry today. Note the discrepancy in the composition's `notes` instead.
- **Crew** per coach is the sum of its section crew factors. Staffing
  rule (project decision 2026-09-06, one step leaner than the S07 Tab. 9
  operator rule): seat 0, couchette 0.25, capsule 0.25, sleeper 0.5,
  dining or bistro coach 1.0, plus one Zugchef per train.
- **Booleans** are literal `True` / `False`; decimal separator `.`; units in
  the column names. `source_ids` is a `;`-separated list of register ids;
  `TO_VERIFY` in `notes` marks a value that still needs one.

## Files

| file | one row per |
|---|---|
| `loco_types.csv` | locomotive type: id, description, traction, weight_t, max_speed_kmh |
| `coach_types.csv` | coach type: id, description, length_m, weight_t, svc_length_m, svc_weight_t, crew, wifi, bikes, aircon, plugs, source_ids, notes |
| `coach_type_sections.csv` | class section of a coach: coach_type_id, position (1..n), class_main, section_label, places, length_m, weight_t, crew, source_ids |
| `composition_types.csv` | composition: id, description, material_strategy, max_speed_kmh, hsr_allowed, zugchef_crew_factor, length_cost_prop, food_and_beverages, loco_type_ids, source_ids, notes |
| `composition_formations.csv` | coach position of a composition: composition_type_id, position (1..n), coach_type_id |

`max_speed_kmh` is the composition's cap (the slowest coach); the
locomotive has its own and the validator rejects a composition faster than
its machine. `length_cost_prop` is X in the class cost allocation — X on
length, 1−X on weight; the catalog uses 0.7.
