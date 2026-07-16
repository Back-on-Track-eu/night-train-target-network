"""
proposal_serialize.py
=====================
Serialization for the proposals endpoints — mirrors the existing
route_serialize.py / evaluation_serialize.py / params_serialize.py split:
all dict-shaping lives here, none of it in the repository or blueprint.

Public interface:
  validate_list_body(body)              → list[str]  (structural check of POST /api/proposals)
  proposal_meta_to_dict(record)         → dict       (metadata block shared by all responses)
  proposal_summary_to_dict(row)         → dict       (metadata + metrics for list responses)

The save-path validators (validate_save_body & co.) were removed with the
POST /api/proposal endpoint (persist-on-calc, 2026-07-16): the pipelines
persist their own responses, so both stored bodies agree with each other
by construction instead of by validation. evaluation_body.input.route is
still a second, duplicate copy of the same route in route_body.route — a
deliberate simplicity tradeoff, not an oversight (see db/README.md).

A list summary derives its route metrics (distance, times, countries,
stops) from the stored route JSON on the fly, and its financial metrics
(total_revenue_eur, total_cost_eur, margin_eur, margin_per) from the
stored evaluation snapshot, if the saver included one — proposals.proposals
persists no denormalised columns of its own (see the schema refit note in
create_proposal_schema.sql). Financial fields are null for proposals saved
without an evaluation.
"""

from __future__ import annotations

SORT_KEYS = {
    "created_at",
    "total_distance_km",
    "total_time_h",
    "total_revenue_eur",
    "total_cost_eur",
    "margin_eur",
}
SORT_DIRECTIONS = {"asc", "desc"}

_LIST_FILTER_KEYS = {"user_ids", "countries", "stop_ids"}

# The five views api/helpers/evaluation_serialize.py always produces —
# see api/README.md's Evaluation section for what each contains.
_EVALUATION_VIEW_KEYS = {
    "route",
    "per_trip_pair",
    "per_trip_pair_per_country",
    "per_trip_pair_per_od",
    "per_trip_pair_per_section",
    "per_trip_per_stop",
}


# =============================================================================
# PROPOSALS — validate
# =============================================================================


def validate_list_body(body: dict) -> list[str]:
    """Structural validation of a POST /api/proposals payload."""
    errors = []

    filters = body.get("filter", {})
    if not isinstance(filters, dict):
        errors.append("'filter' must be an object if provided.")
    else:
        unknown = set(filters) - _LIST_FILTER_KEYS
        if unknown:
            errors.append(
                f"Unknown filter key(s): {sorted(unknown)}. "
                f"Supported: {sorted(_LIST_FILTER_KEYS)}."
            )
        if filters.get("user_ids") is not None and not (
            isinstance(filters["user_ids"], list)
            and all(isinstance(u, int) for u in filters["user_ids"])
        ):
            errors.append("'filter.user_ids' must be a list of integers.")
        for key in ("countries", "stop_ids"):
            if filters.get(key) is not None and not (
                isinstance(filters[key], list)
                and all(isinstance(v, str) for v in filters[key])
            ):
                errors.append(f"'filter.{key}' must be a list of strings.")

    sort = body.get("sort", [])
    if not isinstance(sort, list):
        errors.append("'sort' must be a list if provided.")
    else:
        for i, entry in enumerate(sort):
            if not isinstance(entry, dict) or entry.get("by") not in SORT_KEYS:
                errors.append(f"'sort[{i}].by' must be one of: {sorted(SORT_KEYS)}.")
            elif entry.get("dir", "asc") not in SORT_DIRECTIONS:
                errors.append(f"'sort[{i}].dir' must be 'asc' or 'desc'.")

    for key in ("limit", "offset"):
        if body.get(key) is not None and not (
            isinstance(body[key], int) and body[key] >= 0
        ):
            errors.append(f"'{key}' must be a non-negative integer if provided.")

    return errors


# =============================================================================
# PROPOSALS — serialize
# =============================================================================


def proposal_meta_to_dict(record: dict) -> dict:
    """Metadata block of one proposal version — shared by save, get, and
    list responses."""
    return {
        "proposal_id": record["proposal_id"],
        "proposal_version": record["proposal_version"],
        "is_current": record["is_current"],
        "user_id": record["user_id"],
        "user_name": record.get("user_name"),
        "change_log": record["change_log"],
        "created_at": record["created_at"].isoformat(),
    }


def proposal_summary_to_dict(row: dict) -> dict:
    """List entry: metadata + metrics derived from the trimmed route JSON
    (ProposalRepository.list_current() strips geometries and
    track_infrastructure SQL-side before it reaches this function)."""
    route = row["route_trimmed"]

    total_distance_m = 0
    total_driving_min = 0
    total_time_min = 0
    countries: set[str] = set()
    # Ordered per outbound trip, deduplicated across trip pairs — the stop
    # list a frontend card would display.
    stops: dict[str, str] = {}

    for pair in route["trip_pairs"]:
        for trip in (pair["outbound"], pair["return_trip"]):
            for seg in trip["segments"]:
                total_distance_m += seg["distance_m"]
                total_driving_min += seg["driving_time_min"]
                # .get: stored pre-0.9.8 proposals have no dynamics_time_min
                total_time_min += (
                    seg["driving_time_min"]
                    + seg.get("dynamics_time_min", 0)
                    + seg["buffer_time_min"]
                )
                countries.update(seg["country_distance_shares"])
        for stop in _outbound_stops(pair):
            stops.setdefault(stop["stop_id"], stop["stop_name"])

    return {
        **proposal_meta_to_dict(row),
        "name": _route_long_name(route),
        "total_distance_km": round(total_distance_m / 1000.0, 1),
        "total_driving_time_h": round(total_driving_min / 60.0, 2),
        "total_time_h": round(total_time_min / 60.0, 2),
        "countries": sorted(countries),
        "stops": [
            {"stop_id": stop_id, "stop_name": name} for stop_id, name in stops.items()
        ],
        **_financial_summary(row.get("eval_totals")),
    }


def _financial_summary(eval_totals: dict | None) -> dict:
    """total_revenue_eur/total_cost_eur/margin_eur/margin_per from a
    saved evaluation's views.route.data.per_year block, or all-null if the
    proposal was saved without an evaluation. margin_eur is net_eur (the
    bottom line after cost, revenue, and the EBIT margin target — see
    models/evaluation/views.py:Breakdown.net_eur), not the raw EBIT target
    itself."""
    if not eval_totals:
        return {
            "total_revenue_eur": None,
            "total_cost_eur": None,
            "margin_eur": None,
            "margin_per": None,
        }
    revenue = eval_totals["total_revenue_eur"]
    cost = eval_totals["total_cost_eur"]
    margin = eval_totals["net_eur"]
    return {
        "total_revenue_eur": revenue,
        "total_cost_eur": cost,
        "margin_eur": margin,
        "margin_per": round(margin / revenue, 4) if revenue else None,
    }


def _outbound_stops(pair: dict) -> list[dict]:
    segments = pair["outbound"]["segments"]
    return [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]


def _route_long_name(route: dict) -> str:
    """'Origin – Destination' per trip pair, joined by ' / ' for Y-shaped
    routes — same convention the repository writes to GTFS route_long_name."""
    names = []
    for pair in route["trip_pairs"]:
        stops = _outbound_stops(pair)
        names.append(f"{stops[0]['stop_name']} – {stops[-1]['stop_name']}")
    return " / ".join(names)
