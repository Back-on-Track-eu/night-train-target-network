"""
proposal_serialize.py
=====================
Serialization for the proposals endpoints — mirrors the existing
route_serialize.py / evaluation_serialize.py / params_serialize.py split:
all dict-shaping lives here, none of it in the repository or blueprint.

WP5 rewrite: the old route_body/evaluation_body-trimming serializers
(proposal_meta_to_dict, proposal_summary_to_dict operating on a JSON blob)
are gone with those columns. This module now shapes the slimmed
container + proposal_summaries row shapes (§5.3/§5.4) instead.

Public interface:
  validate_list_body(body)        -> list[str]  (structural check of POST /api/proposals, WP5-minimal)
  proposal_meta_to_dict(record)   -> dict        (metadata block shared by publish/load responses)
  proposal_to_response_dict(...)  -> dict        (full §2.1-shaped response: metadata + route + evaluation)
  summary_row_to_dict(row)        -> dict        (one proposal_summaries row for list responses)
"""

from __future__ import annotations

_LIST_FILTER_KEYS = {"user_ids"}


# =============================================================================
# PROPOSALS — validate
# =============================================================================


def validate_list_body(body: dict) -> list[str]:
    """Structural validation of a POST /api/proposals payload. WP5-minimal
    — only the one filter (user_ids) and pagination exist so far; the
    full §7.1 filter/sort/section contract is WP6."""
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
    """Metadata block shared by publish and load responses — id, owner,
    name, versions, timestamps (§7.2). record is either
    ProposalRepository.publish()'s return value or .get_container()'s row
    — both carry the same identity fields under the same keys."""
    return {
        "proposal_id": record["proposal_id"],
        "proposal_version": record["proposal_version"],
        "user_id": record["user_id"],
        "user_name": record.get("user_name"),
        "name": record["name"],
        "created_at": _isoformat(record.get("created_at")),
        "updated_at": _isoformat(record.get("updated_at")),
    }


def proposal_to_response_dict(record: dict, route: dict, evaluation: dict) -> dict:
    """The full compute-response shape (§2.1) plus the metadata block
    (§7.2) — what both POST /api/proposal/publish and GET /api/proposal/
    <id> return. route/evaluation are passed in separately (rather than
    read off `record`) because the two callers assemble them differently:
    publish already has them in memory from the compute it just ran; load
    rebuilds them via route_gtfs_serialize.py. Both end up in this exact
    shape either way.

    evaluation must be the FULL shape (models/input/views) — load rebuilds
    input.parameters via the scenario pin (§5.1), publish already has it
    from the compute it just ran (never re-trimmed and re-expanded)."""
    request = (
        record["compute_request"] if "compute_request" in record else record["request"]
    )
    return {
        **proposal_meta_to_dict(record),
        "route_builder_version": record["route_builder_version"],
        "calc_version": record["calc_version"],
        "route_fingerprint": record["route_fingerprint"],
        "request": request,
        "route": route,
        "evaluation": evaluation,
    }


def summary_row_to_dict(row: dict) -> dict:
    """One proposal_summaries row (§5.4) for a list response — column
    names already match the API field names 1:1, so this is mostly
    pass-through; the shaping job is casting NUMERIC/Decimal columns to
    plain floats (jsonify() can't serialize Decimal) and formatting
    updated_at."""
    return {
        "proposal_id": row["proposal_id"],
        "proposal_version": row["proposal_version"],
        "user_id": row["user_id"],
        "name": row["name"],
        "route_fingerprint": row["route_fingerprint"],
        "composition_id": row["composition_id"],
        "scenario_id": row["scenario_id"],
        "route_builder_version": row["route_builder_version"],
        "calc_version": row["calc_version"],
        "total_distance_km": _to_float(row["total_distance_km"]),
        "total_time_h": _to_float(row["total_time_h"]),
        "avg_speed_kmh": _to_float(row["avg_speed_kmh"]),
        "n_stops": row["n_stops"],
        "countries": list(row["countries"]),
        "stop_ids": list(row["stop_ids"]),
        "cost_eur_per_train_km": _to_float(row["cost_eur_per_train_km"]),
        "revenue_eur_per_train_km": _to_float(row["revenue_eur_per_train_km"]),
        "margin_eur_per_train_km": _to_float(row["margin_eur_per_train_km"]),
        "subsidy_eur_per_year": _to_float(row["subsidy_eur_per_year"]),
        "demand_trips_per_year": _to_float(row["demand_trips_per_year"]),
        "demand_trip_km_per_year": _to_float(row["demand_trip_km_per_year"]),
        "shift_air_trips_per_year": _to_float(row["shift_air_trips_per_year"]),
        "shift_air_trip_km_per_year": _to_float(row["shift_air_trip_km_per_year"]),
        "shift_car_trips_per_year": _to_float(row["shift_car_trips_per_year"]),
        "shift_car_trip_km_per_year": _to_float(row["shift_car_trip_km_per_year"]),
        "co2_savings_t_per_year": _to_float(row["co2_savings_t_per_year"]),
        "subsidy_eur_per_t_co2": _to_float(row["subsidy_eur_per_t_co2"]),
        "demand_kpis_placeholder": row["demand_kpis_placeholder"],
        "updated_at": _isoformat(row.get("updated_at")),
    }


def _to_float(value) -> float | None:
    """NUMERIC columns come back as Decimal via psycopg2 — jsonify()
    can't serialize Decimal, so every summary metric is cast explicitly.
    None passes through (nullable demand-placeholder columns)."""
    return None if value is None else float(value)


def _isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None
