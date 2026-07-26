"""
evaluation_serialize.py
========================
Serialization (domain → dict) for the cost/revenue evaluation pipeline —
Breakdown trees, matrix views, and the "models" / "input" documentation
sections of POST /api/evaluation/calc's response.

Split out of the former serialize.py (2026-07-06) into two domain files —
this one for evaluation output, route_serialize.py for Route (de)serialization
— mirroring the existing params_serialize.py split for the params endpoints.

EUR values are NOT rounded here — every leaf on a Breakdown is already
rounded by the time it reaches this file, at a precision scaled to its
normalisation (2dp for annual EUR, finer for per-unit views — see
models/evaluation/views.py: _round_breakdown() and NORMALISATION_NDIGITS /
BREAKDOWN_TOTAL_NDIGITS in models/evaluation/version.py). This file only
shapes dicts, it never re-formats numbers.

Public interface:
  breakdown_to_dict(breakdown)                    → dict  (one Breakdown, all 5 normalisations already applied by the caller)
  normalise_all_to_dict(breakdown, route, pair, scope, class_split_override)
                                                    → dict  (all normalisations of one Breakdown, each class-keyed with 'all' —
                                                             CALC 0.9.9; scope = a cell's own annual denominators for
                                                             route-section cells, None otherwise)
  views_to_dict(bd_all, bd_per_pair, matrix_country, matrix_od, matrix_section,
                section_scopes, matrix_stop, route, trip_pair_by_key)
                                                    → dict  (the full "views" section: description + normalisations +
                                                             data per view, views_meta merged in — see views_to_dict())
  models_to_dict()                                 → dict  (version + description + formulas for route_builder / energy / evaluation)
  input_to_dict(route_dict, tracks, stop_infra, compositions) → dict  (the posted route + every parameter actually used to cost it)
"""

from __future__ import annotations

from models.route.route import Route, TripPair
from models.evaluation.views import (
    Breakdown,
    NormalisationScope,
    build_class_keyed_normalisations,
    build_class_main_shares,
    revenue_by_class_main,
    VIEW_META,
)
from models.evaluation.version import (
    CALC_VERSION,
    CALC_MODEL_DESCRIPTION,
    CALC_FORMULAS,
)
from models.energy.version import (
    ENERGY_CALC_VERSION,
    ENERGY_MODEL_DESCRIPTION,
    ENERGY_FORMULAS,
)
from models.route.version import (
    ROUTE_BUILDER_VERSION,
    ROUTE_BUILDER_DESCRIPTION,
    ROUTE_FORMULAS,
)
from models.params import (
    StopInfraCollection,
    TrackInfraCollection,
    CompositionCollection,
)
from api.helpers.params_serialize import (
    stop_infra_to_dict,
    track_infra_to_dict,
    composition_collection_to_dict,
)

# =============================================================================
# BREAKDOWN — serialize
# =============================================================================


def breakdown_to_dict(b: Breakdown) -> dict:
    """Serialize a Breakdown tree to a nested JSON-compatible dict.
    Includes computed summary fields (total_cost_eur, net_eur) at the top."""
    return {
        "cost": {
            "operator": {
                "variable": {
                    "driver_eur": b.cost.operator.variable.driver_eur,
                    "crew_eur": b.cost.operator.variable.crew_eur,
                    "coach_maintenance_eur": b.cost.operator.variable.coach_maintenance_eur,
                    "loco_eur": b.cost.operator.variable.loco_eur,
                    "svc_stockings_eur": b.cost.operator.variable.svc_stockings_eur,
                    "var_overhead_eur": b.cost.operator.variable.var_overhead_eur,
                    "total_eur": b.cost.operator.variable.total_eur,
                },
                "fixed": {
                    "coach_amortisation_eur": b.cost.operator.fixed.coach_amortisation_eur,
                    "financing_eur": b.cost.operator.fixed.financing_eur,
                    "fix_overhead_eur": b.cost.operator.fixed.fix_overhead_eur,
                    "cleaning_eur": b.cost.operator.fixed.cleaning_eur,
                    "shunting_eur": b.cost.operator.fixed.shunting_eur,
                    "total_eur": b.cost.operator.fixed.total_eur,
                },
                "total_eur": b.cost.operator.total_eur,
            },
            "infrastructure": {
                "tac_eur": b.cost.infrastructure.tac_eur,
                "energy_eur": b.cost.infrastructure.energy_eur,
                "station_charge_eur": b.cost.infrastructure.station_charge_eur,
                "parking_eur": b.cost.infrastructure.parking_eur,
                "total_eur": b.cost.infrastructure.total_eur,
            },
            "total_eur": b.cost.total_eur,
        },
        "revenue": {
            "ticket_revenue_eur": b.revenue.ticket_revenue_eur,
            "total_eur": b.revenue.total_eur,
        },
        "margin": {
            "ebit_margin_eur": b.margin.ebit_margin_eur,
            "total_eur": b.margin.total_eur,
        },
        "total_cost_eur": b.total_cost_eur,
        "total_revenue_eur": b.total_revenue_eur,
        "net_eur": b.net_eur,
    }


def normalise_all_to_dict(
    breakdown: Breakdown,
    route: Route,
    trip_pair: TripPair | None = None,
    scope: NormalisationScope | None = None,
    class_split_override: dict[str, Breakdown] | None = None,
) -> dict:
    """All normalisations of a Breakdown as a serialized dict.
    Combines computation (normalisers) and serialization in one step
    since the result is always destined for JSON output.
    scope carries a cell's own annual physical denominators (route
    sections) — None means the normalisers derive them from
    route/trip_pair as before.

    CALC_VERSION 0.9.9: class_main is an orthogonal axis on EVERY
    normalisation — each norm key maps to {"all" | class_main: breakdown
    dict}. Shares are built from the pair's composition (route level: the
    first pair's — exact while all pairs share one composition) with
    class revenue from its OD demand; class_split_override passes an
    exact per-class split through to build_class_keyed_normalisations
    where the view has one (section/OD class cells). The former
    by_class_main view is retired — it equals per_year's class cells."""
    pairs = [trip_pair] if trip_pair is not None else route.trip_pairs
    shares = build_class_main_shares(pairs[0].composition, revenue_by_class_main(pairs))
    keyed = build_class_keyed_normalisations(
        breakdown, route, shares, trip_pair, scope, class_split_override
    )
    return {
        norm: {cls: breakdown_to_dict(b) for cls, b in cells.items()}
        for norm, cells in keyed.items()
    }


# =============================================================================
# VIEWS — human-readable filter labels
# =============================================================================


def _label_context(
    route: Route,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Precompute, once per request:
    stop_names  — stop_id → stop_name
    trip_labels — trip_id → 'Origin → Destination (outbound|return)', for a
                  SINGLE direction. Covers every trip in every pair —
                  outbound AND return_trip — since
                  build_breakdown_per_trip_per_stop() keys its matrix by
                  whichever direction a stop call actually happened on.
    pair_labels — outbound trip_id → 'Origin ↔ Destination', for a whole
                  TRIP PAIR (outbound + return together). Deliberately a
                  different arrow (↔, not →) from trip_labels — a trip
                  pair view covers both directions, and a one-way arrow
                  there would misrepresent it as outbound-only.
    """
    stop_names: dict[str, str] = {}
    trip_labels: dict[str, str] = {}
    pair_labels: dict[str, str] = {}
    for pair in route.trip_pairs:
        for trip in pair.trips:
            stops = trip.stops
            for s in stops:
                stop_names[s.stop_id] = s.stop_name
            if stops:
                direction_text = "outbound" if trip.direction == 0 else "return"
                trip_labels[trip.trip_id] = (
                    f"{stops[0].stop_name} \u2192 {stops[-1].stop_name} ({direction_text})"
                )
        outbound_stops = pair.outbound.stops
        if outbound_stops:
            pair_labels[pair.outbound.trip_id] = (
                f"{outbound_stops[0].stop_name} \u2194 {outbound_stops[-1].stop_name}"
            )
    return stop_names, trip_labels, pair_labels


def _pair_value(pair_labels: dict[str, str], pair_key: str) -> str:
    """pair_key is always an outbound trip_id (or 'all')."""
    return "all" if pair_key == "all" else pair_labels.get(pair_key, pair_key)


def _trip_value(trip_labels: dict[str, str], trip_key: str) -> str:
    return "all" if trip_key == "all" else trip_labels.get(trip_key, trip_key)


def _country_value(country_key: str) -> str:
    return "all" if country_key == "all" else country_key


def _stop_value(stop_names: dict[str, str], stop_key: str) -> str:
    return "all" if stop_key == "all" else stop_names.get(stop_key, stop_key)


def _od_value(stop_names: dict[str, str], od_key: str) -> str:
    """od_key is 'origin_stop_id__destination_stop_id__class_main' (see
    views.py: build_breakdown_per_trip_pair_per_od's od_key()), or 'all'.
    Uses → (not ↔) — an OD pair is a genuinely one-way ticket, unlike a
    trip pair which always runs both directions."""
    if od_key == "all":
        return "all"
    parts = od_key.split("__")
    if len(parts) != 3:
        return od_key
    origin_id, destination_id, class_main = parts
    origin = stop_names.get(origin_id, origin_id)
    destination = stop_names.get(destination_id, destination_id)
    return f"{origin} \u2192 {destination} ({class_main})"


def _section_parts(section_key: str) -> tuple[str, str, str] | None:
    """section_key is 'origin_stop_id__destination_stop_id__{class_main|all}'
    (see views.py: build_breakdown_per_trip_pair_per_section), or 'all'.
    Returns (origin_id, destination_id, class_part) or None for 'all' /
    malformed keys."""
    if section_key == "all":
        return None
    parts = section_key.split("__")
    return tuple(parts) if len(parts) == 3 else None


def _section_value(stop_names: dict[str, str], section_key: str) -> str:
    """Human-readable section label — → like a single trip, since a section
    is directional (the opposite direction is its own key)."""
    parts = _section_parts(section_key)
    if parts is None:
        return "all" if section_key == "all" else section_key
    origin_id, destination_id, class_part = parts
    origin = stop_names.get(origin_id, origin_id)
    destination = stop_names.get(destination_id, destination_id)
    class_text = "all classes" if class_part == "all" else class_part
    return f"{origin} \u2192 {destination} ({class_text})"


# =============================================================================
# VIEWS — per-view builders (views_meta merged in, one description +
# normalisations block per view, plus a "filter" label per data point for
# every view with a dimension to filter on)
# =============================================================================


def _route_view_to_dict(bd_all: Breakdown, route: Route) -> dict:
    """The whole-route view has nothing to filter by — a single Breakdown,
    no "filter" label needed."""
    meta = VIEW_META["route"]
    return {
        "description": meta["description"],
        "normalisations": meta["normalisations"],
        "data": normalise_all_to_dict(bd_all, route),
    }


def _per_trip_pair_view_to_dict(
    bd_per_pair: dict[str, Breakdown],
    route: Route,
    trip_pair_by_key: dict[str, TripPair],
) -> dict:
    meta = VIEW_META["per_trip_pair"]
    _, _, pair_labels = _label_context(route)
    data = {
        pair_key: {
            "filter": {"trip_pair": _pair_value(pair_labels, pair_key)},
            "values": normalise_all_to_dict(bd, route, trip_pair_by_key.get(pair_key)),
        }
        for pair_key, bd in bd_per_pair.items()
    }
    return {
        "description": meta["description"],
        "normalisations": meta["normalisations"],
        "data": data,
    }


def _per_trip_pair_per_country_view_to_dict(
    matrix: dict[tuple[str, str], Breakdown],
    route: Route,
    trip_pair_by_key: dict[str, TripPair],
) -> dict:
    meta = VIEW_META["per_trip_pair_per_country"]
    _, _, pair_labels = _label_context(route)
    data: dict[str, dict[str, dict]] = {}
    for (pair_key, country_key), b in matrix.items():
        trip_pair = trip_pair_by_key.get(pair_key) if pair_key != "all" else None
        filter_dict = {
            "trip_pair": _pair_value(pair_labels, pair_key),
            "country": _country_value(country_key),
        }
        data.setdefault(pair_key, {})[country_key] = {
            "filter": filter_dict,
            "values": normalise_all_to_dict(b, route, trip_pair),
        }
    return {
        "description": meta["description"],
        "normalisations": meta["normalisations"],
        "data": data,
    }


def _per_trip_pair_per_od_view_to_dict(
    matrix: dict[tuple[str, str], Breakdown],
    route: Route,
    trip_pair_by_key: dict[str, TripPair],
) -> dict:
    """OD cells are class-scoped (od_key carries one class_main), so their
    class axis is the identity — {cls: the cell itself} — never a shares
    re-split; the 'all' wildcard cells get the default shares split."""
    meta = VIEW_META["per_trip_pair_per_od"]
    stop_names, _, pair_labels = _label_context(route)
    data: dict[str, dict[str, dict]] = {}
    for (pair_key, od_key), b in matrix.items():
        trip_pair = trip_pair_by_key.get(pair_key) if pair_key != "all" else None
        od_parts = od_key.split("__") if od_key != "all" else None
        class_override = (
            {od_parts[2]: b} if od_parts is not None and len(od_parts) == 3 else None
        )
        filter_dict = {
            "trip_pair": _pair_value(pair_labels, pair_key),
            "od_pair": _od_value(stop_names, od_key),
        }
        data.setdefault(pair_key, {})[od_key] = {
            "filter": filter_dict,
            "values": normalise_all_to_dict(
                b, route, trip_pair, class_split_override=class_override
            ),
        }
    return {
        "description": meta["description"],
        "normalisations": meta["normalisations"],
        "data": data,
    }


def _per_trip_per_stop_view_to_dict(
    matrix: dict[tuple[str, str], Breakdown],
    route: Route,
    trip_pair_by_key: dict[str, TripPair],
) -> dict:
    """Keyed by (trip_id, stop_id) — trip_id here is a single trip (outbound
    OR return), genuinely one-directional, so this uses _trip_filter()
    (→, with an explicit outbound/return tag) rather than _pair_filter()
    (↔, for whole trip pairs). trip_pair_by_key is keyed by outbound trip_id
    only (see views_to_dict()), so the lookup below resolves a TripPair for
    outbound trip_ids and falls back to None for return trip_ids —
    unchanged from the matrix_to_dict() behavior this replaces, not a new
    inconsistency."""
    meta = VIEW_META["per_trip_per_stop"]
    stop_names, trip_labels, _ = _label_context(route)
    data: dict[str, dict[str, dict]] = {}
    for (trip_key, stop_key), b in matrix.items():
        trip_pair = trip_pair_by_key.get(trip_key) if trip_key != "all" else None
        filter_dict = {
            "trip": _trip_value(trip_labels, trip_key),
            "stop": _stop_value(stop_names, stop_key),
        }
        data.setdefault(trip_key, {})[stop_key] = {
            "filter": filter_dict,
            "values": normalise_all_to_dict(b, route, trip_pair),
        }
    return {
        "description": meta["description"],
        "normalisations": meta["normalisations"],
        "data": data,
    }


def _per_trip_pair_per_section_view_to_dict(
    matrix: dict[tuple[str, str], Breakdown],
    scopes: dict[tuple[str, str], NormalisationScope],
    route: Route,
    trip_pair_by_key: dict[str, TripPair],
) -> dict:
    """Keyed by (pair_key, section_key). Section cells normalise against
    their own annual physics (scopes from
    build_breakdown_per_trip_pair_per_section) — €/train-km of a section
    means per that section's train-km, not the whole pair's. The "all"
    wildcard cells have no scope entry and fall back to the default
    trip-pair/route denominators, identical to the other views.

    Class axis (CALC 0.9.9): a "__all" section cell's class split is its
    sibling "__{cls}" cells — the builder's exact per-class split, so the
    axis agrees with the class cells to the cent; a "__{cls}" cell's own
    axis is the identity. Only the "all" wildcard cells fall back to the
    shares-based split."""
    meta = VIEW_META["per_trip_pair_per_section"]
    stop_names, _, pair_labels = _label_context(route)
    data: dict[str, dict[str, dict]] = {}
    for (pair_key, section_key), b in matrix.items():
        trip_pair = trip_pair_by_key.get(pair_key) if pair_key != "all" else None
        parts = _section_parts(section_key)
        class_override: dict[str, Breakdown] | None = None
        if parts is not None:
            origin_id, destination_id, class_part = parts
            if class_part == "all":
                # exact split: every sibling class cell of this section
                prefix = f"{origin_id}__{destination_id}__"
                class_override = {
                    sk[len(prefix) :]: cell_b
                    for (pk, sk), cell_b in matrix.items()
                    if pk == pair_key and sk.startswith(prefix) and sk != section_key
                }
            else:
                class_override = {class_part: b}
        filter_dict = {
            "trip_pair": _pair_value(pair_labels, pair_key),
            "section": _section_value(stop_names, section_key),
            # class_main separately too — lets the frontend filter the class
            # dimension without re-parsing the section label
            "class_main": parts[2] if parts is not None else "all",
        }
        data.setdefault(pair_key, {})[section_key] = {
            "filter": filter_dict,
            "values": normalise_all_to_dict(
                b,
                route,
                trip_pair,
                scopes.get((pair_key, section_key)),
                class_split_override=class_override,
            ),
        }
    return {
        "description": meta["description"],
        "normalisations": meta["normalisations"],
        "data": data,
    }


def views_to_dict(
    bd_all: Breakdown,
    bd_per_pair: dict[str, Breakdown],
    matrix_country: dict[tuple[str, str], Breakdown],
    matrix_od: dict[tuple[str, str], Breakdown],
    matrix_section: dict[tuple[str, str], Breakdown],
    section_scopes: dict[tuple[str, str], NormalisationScope],
    matrix_stop: dict[tuple[str, str], Breakdown],
    route: Route,
    trip_pair_by_key: dict[str, TripPair],
) -> dict:
    """The full "views" section of the response — description, normalisation
    documentation (formerly a separate top-level "views_meta"), and data,
    together per view rather than in two places the frontend has to
    cross-reference. Every data point with a dimension to filter on (all
    views except "route") carries a human-readable "filter" — a dict, one
    entry per filter dimension, keyed by dimension name — alongside its
    "values". E.g. per_trip_pair: {"trip_pair": "Muenchen Hbf \u2194 Wien Hbf"}
    (\u2194 — a trip pair is always both directions). per_trip_pair_per_od:
    {"trip_pair": "Muenchen Hbf \u2194 Wien Hbf",
     "od_pair": "Muenchen Hbf \u2192 Wien Hbf (seat (reclining))"}
    (\u2192 for the OD pair itself — a ticket is genuinely one-way)."""
    return {
        "route": _route_view_to_dict(bd_all, route),
        "per_trip_pair": _per_trip_pair_view_to_dict(
            bd_per_pair, route, trip_pair_by_key
        ),
        "per_trip_pair_per_country": _per_trip_pair_per_country_view_to_dict(
            matrix_country, route, trip_pair_by_key
        ),
        "per_trip_pair_per_od": _per_trip_pair_per_od_view_to_dict(
            matrix_od, route, trip_pair_by_key
        ),
        "per_trip_pair_per_section": _per_trip_pair_per_section_view_to_dict(
            matrix_section, section_scopes, route, trip_pair_by_key
        ),
        "per_trip_per_stop": _per_trip_per_stop_view_to_dict(
            matrix_stop, route, trip_pair_by_key
        ),
    }


# =============================================================================
# MODELS — version + description + formulas for every model in the pipeline
# =============================================================================

# The exact set of field names that appear in breakdown_to_dict() output —
# every leaf field name plus the "total_eur"/"total_cost_eur"/
# "total_revenue_eur"/"net_eur" aggregates. Must stay in sync with
# breakdown_to_dict() above. Used to filter CALC_FORMULAS/ENERGY_FORMULAS/
# ROUTE_FORMULAS down to only formulas for fields actually present under
# "views" — see models_to_dict() — so the frontend can map a "views" field
# straight to its "models.<model>.formulas" entry by key. Route builder and
# energy formulas are keyed by their own domain's concepts (times, kWh) —
# none of those keys are ever expected to appear here, so route_builder and
# energy naturally end up with an empty "formulas" dict below; only their
# version + description are shown.
EVALUATION_OUTPUT_FIELDS: frozenset[str] = frozenset(
    {
        "driver_eur",
        "crew_eur",
        "coach_maintenance_eur",
        "loco_eur",
        "svc_stockings_eur",
        "var_overhead_eur",
        "coach_amortisation_eur",
        "financing_eur",
        "fix_overhead_eur",
        "cleaning_eur",
        "shunting_eur",
        "tac_eur",
        "energy_eur",
        "station_charge_eur",
        "parking_eur",
        "ticket_revenue_eur",
        "ebit_margin_eur",
        "total_eur",
        "total_cost_eur",
        "total_revenue_eur",
        "net_eur",
    }
)


def _formulas_to_dict(formulas: dict) -> dict:
    """CalcFormula/EnergyFormula/RouteFormula registry → plain dict, filtered
    to EVALUATION_OUTPUT_FIELDS. All three formula dataclasses share the
    same (latex, description) shape."""
    return {
        key: {"latex": f.latex, "description": f.description}
        for key, f in formulas.items()
        if key in EVALUATION_OUTPUT_FIELDS
    }


def models_to_dict() -> dict:
    """Version + description + formula registry for every model that
    contributes to an evaluation: the route builder (routing/timetable),
    the energy model (traction energy), and the evaluation model itself
    (cost/revenue). Static across all evaluations — no route-specific data,
    safe to call with no arguments."""
    return {
        "route_builder": {
            "version": ROUTE_BUILDER_VERSION,
            "description": ROUTE_BUILDER_DESCRIPTION,
            "formulas": _formulas_to_dict(ROUTE_FORMULAS),
        },
        "energy": {
            "version": ENERGY_CALC_VERSION,
            "description": ENERGY_MODEL_DESCRIPTION,
            "formulas": _formulas_to_dict(ENERGY_FORMULAS),
        },
        "evaluation": {
            "version": CALC_VERSION,
            "description": CALC_MODEL_DESCRIPTION,
            "formulas": _formulas_to_dict(CALC_FORMULAS),
        },
    }


# =============================================================================
# INPUT — the posted route plus every parameter actually used to cost it
# =============================================================================


def input_to_dict(
    route_dict: dict,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    compositions: CompositionCollection,
) -> dict:
    """Everything that went into this evaluation.

    route: the route JSON exactly as posted to POST /api/evaluation/calc —
    included verbatim (not re-serialized from the reconstructed Route) so
    it's a faithful record of the actual request body.

    parameters: every track/stop/composition parameter actually loaded to
    cost this route, reusing the same params_serialize.py functions the
    read-only /api/params/* endpoints use — each field already carries its
    own description, source, and is_default flag (see params_serialize.py),
    so there's no separate description/source scheme to maintain here.
    """
    return {
        "route": route_dict,
        "parameters": {
            "track_infrastructures": track_infra_to_dict(tracks),
            "stop_infrastructures": stop_infra_to_dict(stop_infra),
            "compositions": composition_collection_to_dict(compositions),
        },
    }
