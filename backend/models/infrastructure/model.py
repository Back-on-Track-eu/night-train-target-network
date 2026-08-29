"""
model.py
========
Version anchor for the infrastructure parameter model — the per-country
track and station parameters (track access charges, station charges,
energy prices, terrain, HSR permission, schedule buffer quotas, minimum
dwell times) and the stop catalog with its classification pipeline.

The model has no code of its own: its parameters live in the
input_params tables (db/schema.py), versioned as full-table snapshots
pinned by scenarios; the stop classification pipeline is documented in
STOP_CLASSIFICATION.md. The formulas consuming the parameters surface
in the route builder's ROUTE_FORMULAS (models/route/model.py) and the
evaluation model's CALC_FORMULAS (models/evaluation/model.py).

Bump INFRA_MODEL_VERSION when the parameter model itself changes —
which parameters exist, how they resolve against defaults, how the
stop catalog is classified. A changed value alone is a data change and
follows the DB full-snapshot versioning rules instead.
"""

INFRA_MODEL_VERSION: str = "0.9.1"

INFRA_MODEL_DESCRIPTION: str = (
    "Infrastructure parameter model: per-country track access charges, "
    "station charges, electricity prices, terrain, schedule buffers, and "
    "minimum stopping times, with EU-average fallbacks — plus the "
    "catalog of possible night train stops."
)

CHANGELOG: dict = {
    "0.9.1": {
        "date": "2026-08-10",
        "author": "david",
        "changes": "Initial consolidation as its own model anchor: "
        "per-country track parameters (TAC €/train-km, parking, "
        "shunting, energy price, terrain, HSR permission, buffer quota, "
        "minimum dwell) and station charges with EU-average defaults, "
        "versioned as full-table snapshots pinned by scenarios; "
        "ONTD-derived stop catalog seeded from Drive (stop "
        "classification steps 1–3, STOP_CLASSIFICATION.md).",
    },
}


# =============================================================================
# OPEN TODOS
# =============================================================================

OPEN_TODOS: dict[str, str] = {
    "segment_tac": (
        "Replace the flat per-country track access charge with the "
        "segment-resolved passage-charge model from the infrastructure "
        "calibration (calib-infra branch): per-country TAC components "
        "with NULL = 'not levied' semantics, PassageCharge resolution "
        "per routed segment, and calc_segment_tac() in evaluation."
    ),
    "stop_classification_steps_4_7": (
        "Stop classification pipeline steps 4–7 "
        "(see STOP_CLASSIFICATION.md) — Johanna's ownership."
    ),
}
