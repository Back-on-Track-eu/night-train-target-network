# Handover to Josua — compositions batch and how to add more (2026-09-06)

Your four concepts are in the catalog and seeded. This note says what happened
to them, what changed on the way, what is still open from your side, and how
the next batch works — the workspace folder is gone, the catalog itself is now
the place to contribute.

## 1. Your four compositions, as seeded

| yours | seeded as | places | €/train-km | ct/place-km | note |
|---|---|---|---|---|---|
| Norwegian-7 | **REF-NOR-7** | 266 (206 seat · 60 sleeper) | 16.4 | 6.18 | B5-7 · 2× B5-3 · FR5-1 · BC5-3 · 2× WLAB-2 |
| NOX-14 | **REF-ROOM-14** | 504 (all capsule) | 27.8 | 5.52 | 14× NOX-36 |
| LR-7 | **REF-POD-7** | 379 (264 capsule · 115 sleeper) | 17.1 | 4.52 | 4× Seat Pod · 1 Hotel Pod single · 2 Hotel Pod 2–3 pax |
| LR-14 | **REF-POD-14** | 758 | 29.2 | 3.85 | two REF-POD-7 rakes |

Costs are operator-only on the 1,000 km / 14.5 h reference route, after the
2026-09-06 cost re-calibration (fleet average is now 21.7 €/train-km, was
40.1). REF-POD-14 is the cheapest train per place in the whole catalog — which
rests entirely on your 66-places-per-coach Seat Pod figure, see §3.

## 2. What changed against your CSVs, and why

- **All four are `refurbished`, not `new`.** Class 5 / WLAB2 are 1977–87 stock;
  Nox and Luna Rail both launch on converted used coaches (sources S51, S55,
  S56 in the register). That drives refit price, 15-year amortisation,
  availability and the 200 km/h Vectron. A new-build variant of a pod concept
  would be a second composition with its own coach types, not a flag.
- **Real geometry replaced the placeholder rows.** Every coach carried the
  example row's 26.4 m / 54.0 t / crew 0.5. Norske tog's own data sheets give
  Class 5 = 25.3 m, tare 42–44 t, 68 seats (B5-3), 40 seats (BC5-3 — you had
  32), 30 reclining seats (B5-7); WLAB2 = 27.0 m, tare 50 t, 15 compartments,
  150 km/h. Weight convention in the catalog: tare + 0.1 t per place.
- **Sections must fit inside the revenue space.** Your rows declared 2.0 m of
  service space and then used the full 26.4 m for the class section; the
  validator now rejects that.
- **The bistro is a service coach, not a class.** FR5-1 has no places; its cost
  is spread per passenger, like the catalog's dining car.
- **Nox = 14 identical coaches × 36 places = 504.** Nox says every coach is the
  same; ~500 per full train and the 36-per-coach layout estimate agree. Your
  NOX-2 (29 places) had no source and was dropped.
- **Class assignment:** Nox rooms and Seat Pods → `capsule` (private, no
  en-suite, couchette-level price); Hotel Pods → `sleeper`; B5-7 reclining
  seats → `seat`. Each keeps its concept name as a sub-category in the section
  label, e.g. `Capsule (Luna Rail Seat Pod)`, `Seat (reclining seat)` — that
  string becomes the class id in the database, no new column.
- **Ids follow `<REF|NEW>-<CONCEPT>-<N>`** and never carry a brand; the brand
  goes into the description as "similar to". Slugs used: NOR, ROOM, POD.
- **Speed:** REF-NOR-7 is catalogued at 200 km/h although the WLAB2 is rated
  150. The catalog carries one speed per material family because routing has
  one profile per family; the real limit is a note on the composition.
- **Crew** now follows one rule for the whole catalog (seat 0, couchette and
  capsule 0.25, sleeper 0.5, catering coach 1, one Zugchef per train), so your
  crew columns were overwritten.
- **Your Schmierzettel numbers:** availability is now 0.87 refurbished / 0.92
  new (lessor interview + BVWP); maintenance 0.70 / 0.60 €/coach-km. The RIC
  document you meant is the UIC KeV 2026 sheet (S60): 0.83 €/coach-km × class
  coefficient — the 1.15 / 0.75 you noted are the a/c and non-a/c couchette
  coefficients, not euros; 0.83 × 1.15 = 0.95 happens to land on your midpoint.
  The Sweden Talgo consist never became a composition (see §3).

## 3. Still open from your side

Numbers I could not source. Each is marked `TO_VERIFY` in the CSV `notes`;
the validator lists them until the note is removed.

1. **Luna Rail places per coach** — 66 / 31 / 42 are your figures; Luna Rail
   publishes none. Where are they from (talk, deck, mock-up)? And the cabin
   mix behind the 42.
2. **Nox room mix and service space** — 36 assumes no crew or luggage
   compartment in the coach.
3. **Tare weights after conversion** for Nox and Luna Rail coaches — I used
   the catalog Apm tare (48.8 t) plus passengers; pod structures add weight.
4. **Norwegian consist** — which real SJ Nord / Vy train did you model (number
   of WLAB2, position of the bistro)? A real consist would drop the TO_VERIFY.
5. **Amenities** (wifi / bikes / aircon / plugs) were taken over as-is; bikes
   = False everywhere — right for the Norwegian day/night coaches?
6. **Sweden Talgo** (9 night + 9 day coaches, 252 places): do you want it in?
   Talgo cars are ~13 m, which the per-coach model handles once we have
   lengths and tare per car and a source for the consist.

## 4. How the next batch works

There is no workspace folder any more. The catalog is five CSVs in
`backend/models/compositions/calib/catalog/` — `loco_types`, `coach_types`,
`coach_type_sections`, `composition_types`, `composition_formations` — with a
`README.md` next to them that documents every column and convention. The
calibration notebook reads these files directly, so a row you add is a row
that gets priced and seeded; nothing is transferred by hand any more.

1. Register your sources first in `01_source_extraction.ipynb` (register
   block at the end, next free `S` id — the 2026-09 batch is the pattern).
   Coach geometry and capacities need a source like cost figures do.
2. Add coach types only for coaches not already in the catalog, with their
   sections. Reusing catalog coaches is the normal case.
3. One row per composition, plus its ordered coach list.
4. From `backend/`: `uv run python scripts/validate_composition_catalog.py`.
   Errors block the seed (bad ids, coach used in both material families,
   sections outside the revenue space, wrong loco or Zugchef, unregistered
   source); warnings are review notes. Fix, read, repeat until clean.
5. Push on the branch and hand over. Re-running the notebooks, the version
   bump and the docs are on David's side.

Conventions worth knowing before you start: ids are permanent; a coach type
belongs to one material family; `material_strategy` is what the operator will
actually run (converted used coaches = `refurbished`); weight = tare + 0.1 t
per place; a coach without sections is a service coach and its service section
must be the whole coach; sub-categories go into the section label, not into a
new class. Anything the format cannot express (multiple units, coaches shared
across families, a traction change en route) the cost model cannot price
either — note it and raise it rather than bending a column.
