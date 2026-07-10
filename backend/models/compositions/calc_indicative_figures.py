"""
calc_indicative_figures.py
===========================
Computes indicative comparison KPIs for a Composition — a summary cost
profile used to compare compositions against each other, independent of
any specific route (unlike models/evaluation/calc.py, which computes
exact costs for a concrete Route).

PLACEHOLDER MODULE: models/compositions/ doesn't have a real cost model
yet. compute_indicative_figures() below returns dummy, zero-valued
figures so that composition_references provenance and the
GET /api/params/compositions response shape can be built, wired up, and
tested end-to-end ahead of the real calculation landing. Replace the body
of compute_indicative_figures() when that happens — its signature and the
IndicativeFigures shape it returns are meant to stay stable across that
change; callers (DBDataLoader.build_all_compositions()) shouldn't need to
change.

Target KPIs (see IndicativeFigures in models/params.py):
  cost_eur_per_train_km          : total composition cost ÷ reference
                                    distance, for the reference trip
                                    profile (ref) — same cost basis as
                                    models/evaluation/calc.py's
                                    evaluate_route() (track access
                                    charges, energy, staff, coach costs,
                                    etc.), just applied to a reference
                                    profile instead of a concrete route.
  cost_eur_per_place_km_by_class : that same total cost allocated to
                                    each class present in the composition
                                    (keyed by class_main, not class_id —
                                    see Composition.places_by_class), divided
                                    by that class's density-weighted
                                    place-km.
"""

from __future__ import annotations

from models.params import (
    Composition,
    CompositionReference,
    IndicativeFigures,
    StopInfraCollection,
    TrackInfraCollection,
)

# Hand-picked, order-of-magnitude illustrative placeholders — NOT derived
# from any cost model. Same flat value for every composition and every
# class, so the API/frontend have something non-null to render while the
# real compositions cost model doesn't exist yet. Round numbers on
# purpose, so they read as obviously provisional rather than as real
# figures. Replace both together with the real calculation.
_PLACEHOLDER_COST_EUR_PER_TRAIN_KM = 10.0
_PLACEHOLDER_COST_EUR_PER_PLACE_KM = 0.05


def compute_indicative_figures(
    comp: Composition,
    ref: CompositionReference,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
) -> IndicativeFigures:
    """
    PLACEHOLDER — returns the same flat, hand-picked illustrative figures
    (see the module-level constants above) for every composition and
    every class present in `comp`, regardless of comp/ref/tracks/
    stop_infra. Real implementation is planned for a dedicated
    compositions cost model (this module is its first file), applying
    the same cost logic as models/evaluation/calc.py's evaluate_route()
    to the reference trip profile (`ref`) instead of a concrete Route.

    tracks/stop_infra are accepted but unused for now, so the signature
    won't need to change once the real calculation actually needs them
    (e.g. to price the reference trip's track access charges per the
    countries it would cross).
    """
    return IndicativeFigures(
        cost_eur_per_train_km=_PLACEHOLDER_COST_EUR_PER_TRAIN_KM,
        cost_eur_per_place_km_by_class={
            class_main: _PLACEHOLDER_COST_EUR_PER_PLACE_KM
            for class_main in comp.places_by_class
        },
    )
