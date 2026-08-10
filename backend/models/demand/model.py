"""
model.py
========
Version constant, description, changelog, standard values, and open
TODOs for the demand model — same single-anchor convention as every
other model.py under models/: every standard assumption the model makes
lives here, and modules using a value import it from here.

The demand model is currently the stopgap uniform-distribution proxy
(stopgap.py) — DEMAND_MODEL_VERSION stays 0.0.x until the real model
(OPEN_TODOS["demand_model"] below) replaces it. The version is not yet
reported in API responses; that wiring lands with the real model.
"""

DEMAND_MODEL_VERSION: str = "0.0.2"

DEMAND_MODEL_DESCRIPTION: str = (
    "Demand model (placeholder): assumes every accommodation class is "
    "70% booked at a flat per-kilometre fare, spread evenly across all "
    "connections — a stand-in until a real demand model with directional "
    "demand, price sensitivity, and competition from other modes "
    "replaces it."
)

CHANGELOG: dict = {
    "0.0.2": {
        "date": "2026-08-10",
        "author": "david",
        "changes": "version.py renamed to model.py (every model now anchors "
        "version, description, and changelog in a model.py); "
        "DEMAND_MODEL_DESCRIPTION and CHANGELOG added. Standard values "
        "and behaviour unchanged.",
    },
    "0.0.1": {
        "date": "2026-08-03",
        "author": "david",
        "changes": "Stopgap demand model moved out of models/route/ into its "
        "own models/demand/ package (route builder 0.9.13): "
        "distribute_demand() uniform-distribution proxy plus the "
        "STOPGAP_* standard values, ahead of the real demand model "
        "landing here.",
    },
}


# =============================================================================
# STANDARD VALUES — stopgap demand (stopgap.distribute_demand() inputs)
# =============================================================================

STOPGAP_UTILIZATION_PER: float = 0.7
"""Placeholder scalar utilization applied uniformly to every class until a
real demand model lands."""

STOPGAP_FARE_PER_KM_BY_CLASS: dict[str, float] = {
    "Seat": 0.10,
    "Couchette": 0.13,
    "Sleeper": 0.18,
    "Capsule": 0.12,
    "Catering": 0.0,
}
"""Placeholder flat per-km fares by class_main — same caveat as above."""


# =============================================================================
# OPEN TODOS
# =============================================================================

OPEN_TODOS: dict[str, str] = {
    "demand_model": (
        "Replace stopgap.distribute_demand()'s inputs (STOPGAP_UTILIZATION_"
        "PER, STOPGAP_FARE_PER_KM_BY_CLASS above) and its uniform-"
        "distribution proxy with a real demand model accounting for "
        "asymmetric directional demand, price elasticity, and competition "
        "from other modes — likely with per-scenario parameters. Candidate "
        "structure identified: the French open-source night train shift "
        "model's log-additive factor form (compatible with the existing "
        "test suite). The placeholder demand KPIs in adapters/proposal/"
        "projection.py (_PLACEHOLDER_* constants, adapters/proposal/README.md §8.1) "
        "are the second replacement site once this lands."
    ),
}
