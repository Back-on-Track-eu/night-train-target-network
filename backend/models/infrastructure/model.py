"""
model.py
========
Version anchor for the infrastructure parameter model — the per-country
track and station parameters (track access charges, station charges,
energy prices, terrain, HSR permission, schedule buffer quotas, minimum
dwell times) and the stop catalog with its classification pipeline.

Its parameters live in the input_params tables (db/schema.py), versioned
as full-table snapshots pinned by scenarios; the stop classification
pipeline is documented in STOP_CLASSIFICATION.md. The formulas consuming
the parameters surface in the route builder's ROUTE_FORMULAS
(models/route/model.py) and the evaluation model's CALC_FORMULAS
(models/evaluation/model.py).

The one piece of code the domain owns is calc_tac.py, which prices the
calibrated track access charge components for one segment. The standard
values that calculation assumes — rather than reads from a parameter
table — live here, so docs/MODEL.md can link them like any other.

Bump INFRA_MODEL_VERSION when the parameter model itself changes —
which parameters exist, how they resolve against defaults, how the
stop catalog is classified. A changed value alone is a data change and
follows the DB full-snapshot versioning rules instead.
"""

INFRA_MODEL_VERSION: str = "0.9.2"

INFRA_MODEL_DESCRIPTION: str = (
    "Infrastructure parameter model: per-country track access charges, "
    "station charges, electricity prices, terrain, schedule buffers, and "
    "minimum stopping times, with EU-average fallbacks — plus the "
    "catalog of possible night train stops."
)

# =============================================================================
# STANDARD VALUES
# =============================================================================

WEEKDAY_BLEND: float = 5.0 / 7.0
"""Share of departures assumed to fall on a weekday. Austria and
Switzerland levy their congestion surcharge and peak multiplier Monday to
Friday only, but a Segment carries clock minutes and no service date, so
a weekday-only tariff window is priced at five sevenths of its overlap
rather than all or nothing — see calc_tac.py and
OPEN_TODOS['tac_weekday_blend']."""


CHANGELOG: dict = {
    "0.9.2": {
        "date": "2026-08-13",
        "author": "david",
        "changes": "Track access charges become a calibrated component "
        "model instead of one flat rate per country. Both track tables "
        "gain the day/night train-km rates, the gross-tonne-km, seat-km, "
        "per-stop, flat per-train-km and revenue-share terms, the peak "
        "multiplier and congestion surcharge, and the night and peak "
        "band definitions; input_params.passage_charges joins them as "
        "the fifth scenario-versioned table, carrying the separately "
        "billed crossings and their polygons. Values are seeded from "
        "tac/calib in EUR at 2032 — currency and price basis are "
        "converted once, in the calibration notebook, so no code "
        "downstream sees either. RESOLUTION RULE: the component group "
        "resolves as a whole, not field by field — the EU-median default "
        "group substitutes only where a country has no distance-based "
        "rate term at all, so a lone empty component keeps its meaning "
        "of 'not levied here'. The flat track_tac_eur_train_km column "
        "survives as a display value and is no longer read by any cost "
        "path.",
    },
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
    "tac_weekday_blend": (
        "WEEKDAY_BLEND prices a Mon-Fri peak tariff at its expected "
        "value because a Segment carries clock minutes but no service "
        "date. Once a route knows which days it runs (Schedule already "
        "holds the frequency, just not the weekday pattern), the peak "
        "share should be evaluated against the real operating days "
        "instead of 5/7."
    ),
    "stop_classification_steps_4_7": (
        "Stop classification pipeline steps 4–7 "
        "(see STOP_CLASSIFICATION.md) — Johanna's ownership."
    ),
}
