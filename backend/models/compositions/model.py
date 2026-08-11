"""
model.py
========
Version anchor for the composition cost model — the calibrated
parameter set describing what a night train composition costs to buy
and operate: per-metre coach purchase model, maintenance, cleaning,
crew, availability, and the new/refurbished material strategy families.

The model has no code of its own: its parameters live in the
input_params tables (db/schema.py) and its derivation in
calib/CALIBRATION.md and the calibration notebooks. The cost formulas
consuming the parameters surface in the evaluation model's
CALC_FORMULAS (models/evaluation/model.py), keyed by output field.

Bump COMPOSITIONS_MODEL_VERSION when the calibration itself changes —
parameter derivation, per-metre purchase model, allocation bases. A
reseeded value alone is a data change and follows the DB versioning
rules instead (see db/dev/seed.py).
"""

COMPOSITIONS_MODEL_VERSION: str = "0.9.2"

COMPOSITIONS_MODEL_DESCRIPTION: str = (
    "Composition cost model: calibrated purchase, maintenance, cleaning, "
    "crew, and availability parameters per train composition, in a 'new' "
    "and a 'refurbished' rolling stock family, at 2032 prices."
)

CHANGELOG: dict = {
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
