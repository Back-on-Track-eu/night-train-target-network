"""
version.py
==========
Version constant, standard values, and open TODOs for the demand model —
same single-place convention as models/route/version.py and
models/evaluation/version.py: every standard assumption the model makes
lives here, and modules using a value import it from here.

The demand model is currently the stopgap uniform-distribution proxy
(stopgap.py) — DEMAND_MODEL_VERSION stays 0.0.x until the real model
(OPEN_TODOS["demand_model"] below) replaces it. The version is not yet
reported in API responses; that wiring lands with the real model.
"""

DEMAND_MODEL_VERSION: str = "0.0.1"


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
        "projection.py (_PLACEHOLDER_* constants, PROPOSALS_DESIGN.md §8.1) "
        "are the second replacement site once this lands."
    ),
}
