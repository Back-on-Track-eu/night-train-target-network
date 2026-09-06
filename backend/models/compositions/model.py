"""
model.py
========
Version anchor for the composition cost model — the calibrated
parameter set describing what a night train composition costs to buy
and operate: per-metre coach purchase model, maintenance, cleaning,
crew, availability, and the new/refurbished material strategy families.

The model's parameters live in the input_params tables (db/schema.py)
and their derivation in calib/CALIBRATION.md and the calibration
notebooks. The rolling-stock catalog the notebook prices — locomotive
and coach types, class sections, standard compositions — is data in
calib/catalog/*.csv, read and validated by catalog.py (the only code
here). The cost formulas consuming the parameters surface in the
evaluation model's CALC_FORMULAS (models/evaluation/model.py), keyed by
output field.

Bump COMPOSITIONS_MODEL_VERSION when the calibration itself changes —
parameter derivation, per-metre purchase model, allocation bases. A
reseeded value alone is a data change and follows the DB versioning
rules instead (see db/dev/seed.py).
"""

COMPOSITIONS_MODEL_VERSION: str = "0.9.5"

COMPOSITIONS_MODEL_DESCRIPTION: str = (
    "Composition cost model: calibrated purchase, maintenance, cleaning, "
    "crew, and availability parameters per train composition, in a 'new' "
    "and a 'refurbished' rolling stock family, at 2032 prices."
)

CHANGELOG: dict = {
    "0.9.5": {
        "date": "2026-09-06",
        "author": "david",
        "changes": "Calibration review against operator evidence (Juri, "
        "Josua; interviews S57-S59, RIC KeV S60, Newrest pay offer S61, "
        "Ramboll S07 re-read). Rates: maintenance 1.30/1.00 -> 0.70/0.60 "
        "EUR/coach-km at a 2026 basis (the KeV all-in usage rate is a "
        "ceiling; Ramboll 2.5%-of-invest and Italo actuals sit far lower); "
        "availability 0.80/0.909 -> 0.87/0.92; cleaning 364 -> 180 "
        "EUR/coach/day (S07 Tab. 11 operator billing); fixed overhead 0.12 "
        "-> 0.08; target EBIT 0.10 -> 0.05 (ES's own target). Onboard crew "
        "priced per hour on board at 40 EUR/h (2032, from the Nightjet "
        "contractor's advertised pay) with no roster division "
        "(crew_roster_eff_ref 1.0, no duty cap; driver unchanged); staffing "
        "seat 0, couchette/capsule 0.25, sleeper 0.5, catering coach 1, one "
        "Zugchef per train (the >=10-coach doubling is dropped; catalog crew "
        "factors updated). Benchmark section corrected: the Ramboll base "
        "case is a 14-coach 696-place train (S07 p. 46, Tab. 17), so the "
        "peer is NEW-BAL-14, not NEW-BAL-7. New-stock purchase rate 145 -> "
        "128 kEUR/m (25th percentile of the five contract anchors = the OeBB "
        "Nightjet contract); refurbished 53 -> 45 kEUR/m (older acquisition, "
        "SJ-scope refit) amortised over 15 instead of 12 years, the KeV "
        "all-in usage rate staying the documented ceiling for used stock. "
        "Fleet average 40.1 -> 21.7 "
        "EUR/train-km; "
        "required-revenue gross-up 1.220 -> 1.149. No formula change; "
        "CALC_VERSION untouched, but every evaluation result moves - reseed. "
        "Calibration declared reviewed and released for Release 1; the "
        "review section of CALIBRATION.md is replaced by a release status.",
    },
    "0.9.4": {
        "date": "2026-09-06",
        "author": "david",
        "changes": "The rolling-stock catalog becomes data: calib/catalog/"
        "*.csv (loco types, coach types, class sections, compositions, "
        "formations) replace the literals in 02_calibration.ipynb; "
        "catalog.py loads and validates them (id convention "
        "<REF|NEW>-<CONCEPT>-<N>, single-family coach use, sections "
        "inside the revenue space, Zugchef and locomotive-by-family "
        "rules, source references) and the seed fails on a defect. Batch "
        "2026-09 adds four refurbished-family compositions: REF-NOR-7 "
        "(Norwegian Class 5 / WLAB2 consist), REF-ROOM-14 (all-private-"
        "room train after the Nox concept, 14 x 36 capsule places on "
        "converted IC coaches), REF-POD-7/14 (Luna Rail Seat Pod and "
        "Hotel Pod on converted coaches). max_speed_kmh stays at the "
        "family's routing-profile speed (200) for all four: per-coach "
        "physical limits below that (the WLAB2 sleeper is rated 150 "
        "km/h) are a modelling judgement documented in the composition's "
        "notes, not a catalog field or a new routing profile — see "
        "calib/catalog/README.md. Sub-categories within a class_main "
        "(the WLAB2 reclining-seat variant, the Nox/Luna Rail pod "
        "concepts) are carried in section_label rather than a new "
        "column, e.g. 'Capsule (Luna Rail Seat Pod)'. Per-coach places "
        "and crew of the two startup concepts are TO_VERIFY. Existing "
        "eight compositions unchanged (seed rows identical apart from "
        "coach remarks now carrying the description and sources, and "
        "the Bcmz_5291 section lengths written at two decimals). No "
        "formula change; CALC_VERSION untouched.",
    },
    "0.9.3": {
        "date": "2026-08-13",
        "author": "david",
        "changes": "Locomotives become first-class catalog entities. "
        "input_params.loco_types holds the machine (mass, design speed, "
        "traction); operator_loco_costs holds the rental rate per "
        "(operator, machine); composition_type_locos wires machines to "
        "compositions in position order. Two types are seeded from the "
        "existing lease derivation, which already distinguished the "
        "230 km/h Vectron (CD class 384) from the standard 200 km/h "
        "Vectron MS — a distinction material_strategy was carrying "
        "implicitly while also standing for the business model. "
        "composition_type_n_locos is dropped: the count is now the number "
        "of wiring rows, so the two cannot disagree. operators."
        "operator_loco_lease_eur_h is dropped. LOCOMOTIVE MASS REMAINS AN "
        "ASSUMPTION: 90 t is the Vectron-class figure the traction model "
        "always used as a hardcoded constant; it has no source in this "
        "calibration and is carried here so it lives in one place rather "
        "than two. A sourced per-type mass is an open question.",
    },
    "0.9.2": {
        "date": "2026-07-21",
        "author": "david",
        "changes": "Cost calibration v2 (calib/CALIBRATION.md): per-metre "
        "coach purchase model (new 145 / refurbished 53 k€ per metre, "
        "double-deck ×1.12); material strategy families new/refurbished "
        "driving amortisation (30y/12y), availability (0.909/0.80), and "
        "the 200/230 km/h speed cap; material-tiered loco lease operator "
        "rows (STD-REF/STD-NEW); class-main cost allocation bases "
        "(length/weight blend on revenue space, service areas per "
        "place); seeded indicative KPIs per composition (€/train-km, "
        "ct/place-km on the S41 reference route); driver/crew overhead "
        "hours retired (roster inefficiency embedded in the deployment-"
        "hour rates). 2032 price basis. Consumed by evaluation 0.9.7/"
        "0.9.8 and route builder 0.9.12.",
    },
    "0.9.1": {
        "date": "2026-06-25",
        "author": "david",
        "changes": "Initial parameter set: coach and composition catalogs "
        "with places per class, weights, lengths, purchase and "
        "maintenance rates — consumed by the initial evaluation model.",
    },
}
