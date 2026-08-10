"""
proposal_serialize.py
=====================
Serialization for the proposals endpoints — mirrors the existing
route_serialize.py / evaluation_serialize.py / params_serialize.py split:
all dict-shaping lives here, none of it in the repository or blueprint.

WP6 rewrite: validate_list_body() now covers the full §7.1 contract
(generic range/list/substring/array filters over every summary column,
trip_windows, bbox, sort, include, sources) — column-kind checks are
delegated to adapters/proposal/filter_builder.py's registry so the set of
filterable/sortable columns is declared exactly once. summary_row_to_dict()
gained scenario_outdated and created_at; three new section serializers
(map_lines/map_stop_counts/map_country_counts) shape the map response.

WP6.1 revision: route_builder_version/calc_version/scenario_id are no
longer filterable (internal/analytical, and gallery rows are always on
the current base scenario by construction — §7.1); created_at/updated_at
range filters, a proposal_ids filter, and a likes_count range filter
(live-joined from proposals.likes, not a summary column — §4.2-style
"joined, never stored") were added; countries/stop_ids gained an
explicit any (OR, default) vs all (AND) mode; map_lines is now a
segment-level aggregation (one feature per distinct stop-pair corridor,
carrying every proposal that uses it) rather than one feature per
proposal; map_country_counts now carries each country's border geometry
alongside its count.

WP7/8 revision (2026-08-04): the per-row `scenario_outdated` flag added
in WP6/WP6.1 is removed from summary_row_to_dict() and proposal_meta_to_
dict() — staleness is now handled entirely server-side (batch refresh +
on-load fallback, adapters/proposal/repository.py's outdated_trigger()),
so there's no longer a user-facing signal to expose. proposal_meta_to_
dict() also gains a genuine created_at on every caller now that
adapters/proposal/repository.py's publish()/refresh_proposal() both
return one (previously only load's get_container() had it; publish()
silently omitted it).

Public interface:
  validate_list_body(body)             -> list[str]  (structural check of POST /api/proposals, §7.1)
  proposal_meta_to_dict(record)        -> dict        (metadata block shared by publish/load responses)
  proposal_to_response_dict(...)       -> dict        (full §2.1-shaped response: metadata + route + evaluation)
  summary_row_to_dict(row)             -> dict        (one proposal_summaries row for list responses)
  map_lines_to_geojson(rows)           -> dict        (GeoJSON FeatureCollection, one feature per corridor)
  map_stop_counts_to_dict(rows)        -> list[dict]
  map_country_counts_to_geojson(rows)  -> dict         (GeoJSON FeatureCollection, one feature per country)
"""

from __future__ import annotations

import json

from adapters.proposal.filter_builder import (
    ALL_FILTER_KEYS,
    ARRAY_COLUMNS,
    DATETIME_RANGE_COLUMNS,
    LIST_COLUMNS,
    RANGE_COLUMNS,
    SORTABLE_COLUMNS,
    SUBSTRING_COLUMNS,
    SUPPORTED_SOURCES,
)

_INCLUDE_SECTIONS = {"summaries", "map_lines", "map_stop_counts", "map_country_counts"}
# The one home for the default "include" sections — api/proposals.py
# imports it for the empty-body listing path.
DEFAULT_INCLUDE = ["summaries"]
_ARRAY_FILTER_MODES = {"any", "all"}


# =============================================================================
# PROPOSALS — validate
# =============================================================================


def validate_list_body(body: dict) -> list[str]:
    """Structural validation of a POST /api/proposals payload — the full
    §7.1 contract (WP6): generic filters over every summary column,
    trip_windows, bbox, sort, include, pagination. Column-kind checks
    (which filter keys exist, which are sortable) are driven by
    filter_builder.py's registry rather than a second hand-maintained
    list here."""
    errors = []
    errors += _validate_filters(body.get("filter", {}))
    errors += _validate_sort(body.get("sort"))
    errors += _validate_include(body.get("include"))

    for key in ("limit", "offset"):
        if body.get(key) is not None and not (
            isinstance(body[key], int) and body[key] >= 0
        ):
            errors.append(f"'{key}' must be a non-negative integer if provided.")

    return errors


def _validate_filters(filters) -> list[str]:
    if not isinstance(filters, dict):
        return ["'filter' must be an object if provided."]

    errors = []
    unknown = set(filters) - ALL_FILTER_KEYS
    if unknown:
        errors.append(
            f"Unknown filter key(s): {sorted(unknown)}. "
            f"Supported: {sorted(ALL_FILTER_KEYS)}."
        )

    sources = filters.get("sources")
    if sources is not None:
        if not isinstance(sources, list) or not sources:
            errors.append(
                "'filter.sources' must be a non-empty list "
                f"of {sorted(SUPPORTED_SOURCES)}."
            )
        else:
            unsupported = set(sources) - SUPPORTED_SOURCES
            if unsupported:
                errors.append(
                    f"Unsupported filter.sources value(s): {sorted(unsupported)}. "
                    f"Supported: {sorted(SUPPORTED_SOURCES)}."
                )

    for key in RANGE_COLUMNS:
        bounds = filters.get(key)
        if bounds is None:
            continue
        if not isinstance(bounds, dict) or not set(bounds) <= {"min", "max"}:
            errors.append(f"'filter.{key}' must be an object with 'min'/'max'.")

    for key in DATETIME_RANGE_COLUMNS:
        bounds = filters.get(key)
        if bounds is None:
            continue
        if not isinstance(bounds, dict) or not set(bounds) <= {"min", "max"}:
            errors.append(f"'filter.{key}' must be an object with 'min'/'max'.")
            continue
        for bound_key in ("min", "max"):
            value = bounds.get(bound_key)
            if value is not None and not isinstance(value, str):
                errors.append(
                    f"'filter.{key}.{bound_key}' must be an ISO 8601 datetime string."
                )

    for key in LIST_COLUMNS:
        values = filters.get(key)
        if values is not None and not isinstance(values, list):
            errors.append(f"'filter.{key}' must be a list.")

    for key in ARRAY_COLUMNS:
        raw = filters.get(key)
        if raw is None:
            continue
        errors += _validate_array_filter(key, raw)

    for key in SUBSTRING_COLUMNS:
        needle = filters.get(key)
        if needle is not None and not isinstance(needle, str):
            errors.append(f"'filter.{key}' must be a string.")

    trip_windows = filters.get("trip_windows")
    if trip_windows is not None:
        errors += _validate_trip_windows(trip_windows)

    bbox = filters.get("bbox")
    if bbox is not None and not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(v, (int, float)) for v in bbox)
    ):
        errors.append("'filter.bbox' must be [west, south, east, north].")

    return errors


def _validate_array_filter(key: str, raw) -> list[str]:
    """Either a plain list of strings (mode "any"/OR, the default) or
    {"values": [...], "mode": "any"|"all"} — see filter_builder.py's
    _parse_array_filter()."""
    if isinstance(raw, list):
        if all(isinstance(v, str) for v in raw):
            return []
        return [f"'filter.{key}' must be a list of strings."]
    if isinstance(raw, dict):
        errors = []
        values = raw.get("values")
        if not (isinstance(values, list) and all(isinstance(v, str) for v in values)):
            errors.append(f"'filter.{key}.values' must be a list of strings.")
        mode = raw.get("mode", "any")
        if mode not in _ARRAY_FILTER_MODES:
            errors.append(f"'filter.{key}.mode' must be 'any' or 'all'.")
        return errors
    return [
        f"'filter.{key}' must be a list of strings, or "
        f"{{'values': [...], 'mode': 'any'|'all'}}."
    ]


def _validate_trip_windows(trip_windows) -> list[str]:
    if not isinstance(trip_windows, list):
        return ["'filter.trip_windows' must be a list."]
    errors = []
    for i, entry in enumerate(trip_windows):
        if not isinstance(entry, dict) or "stop_id" not in entry:
            errors.append(f"'filter.trip_windows[{i}]' must have a 'stop_id'.")
            continue
        if "departure" not in entry and "arrival" not in entry:
            errors.append(
                f"'filter.trip_windows[{i}]' needs a 'departure' and/or 'arrival' window."
            )
        for direction in ("departure", "arrival"):
            window = entry.get(direction)
            if window is None:
                continue
            if not isinstance(window, dict) or not ({"from", "to"} & set(window)):
                errors.append(
                    f"'filter.trip_windows[{i}].{direction}' needs 'from' and/or 'to'."
                )
    return errors


def _validate_sort(sort) -> list[str]:
    if sort is None:
        return []
    if not isinstance(sort, list):
        return ["'sort' must be a list."]
    errors = []
    for i, entry in enumerate(sort):
        if not isinstance(entry, dict) or "by" not in entry:
            errors.append(f"'sort[{i}]' must have a 'by' column.")
            continue
        if entry["by"] not in SORTABLE_COLUMNS:
            errors.append(f"'sort[{i}].by' unknown column: '{entry['by']}'.")
        if entry.get("dir", "asc") not in ("asc", "desc"):
            errors.append(f"'sort[{i}].dir' must be 'asc' or 'desc'.")
    return errors


def _validate_include(include) -> list[str]:
    if include is None:
        return []
    if not isinstance(include, list):
        return ["'include' must be a list."]
    unknown = set(include) - _INCLUDE_SECTIONS
    if unknown:
        return [
            f"Unknown include section(s): {sorted(unknown)}. "
            f"Supported: {sorted(_INCLUDE_SECTIONS)}."
        ]
    return []


# =============================================================================
# PROPOSALS — serialize
# =============================================================================


def proposal_meta_to_dict(record: dict) -> dict:
    """Metadata block shared by publish and load responses — id, owner,
    name, versions, timestamps (§7.2). record is
    ProposalRepository.publish()'s or .get_container()'s row — both carry
    the same identity fields under the same keys, including a real
    created_at (WP7/8: previously only get_container() had one)."""
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
    """One gallery row for a list response, dispatched on `source`
    (WP10 step 6b — the repository's union CTE marks every row).

    "proposal" rows: column names already match the API field names
    1:1, so this is mostly pass-through; the shaping job is casting
    NUMERIC/Decimal columns to plain floats (jsonify() can't serialize
    Decimal) and formatting created_at/updated_at. No staleness flag
    (WP7/8, 2026-08-04 revision) — every proposal is kept current by the
    system (batch refresh + on-load fallback), so there's nothing for a
    reader of this row to act on.

    "existing" rows (ONTD catalog, §5.5 decision 23): the reduced,
    descriptive shape — identity (route_id, name), the shared metric
    subset, geometry_routed (whether the drawn line is real routing or a
    straight-line fallback), and ontd_url (deep link to the route's ONTD
    page). Proposal-only fields (financials, demand, engagement counts,
    timestamps,
    user/scenario/version columns) are OMITTED rather than null-padded —
    a frontend branches on `source`, and 20 always-null keys would only
    obscure which fields are meaningful. composition_id is the ONTD
    catalog's own id namespace, not the curated calibration one —
    documented in api/README.md §7.1."""
    if row.get("source") == "existing":
        return {
            "source": "existing",
            "route_id": row["route_id"],
            "name": row["name"],
            "composition_id": row["composition_id"],
            "total_distance_km": _to_float(row["total_distance_km"]),
            "total_time_h": _to_float(row["total_time_h"]),
            "avg_speed_kmh": _to_float(row["avg_speed_kmh"]),
            "n_stops": row["n_stops"],
            "countries": list(row["countries"]),
            "stop_ids": list(row["stop_ids"]),
            "co2_g_per_pax_km": _to_float(row["co2_g_per_pax_km"]),
            "geometry_routed": row["geometry_routed"],
            "ontd_url": row["ontd_url"],
        }
    return {
        "source": "proposal",
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
        "co2_g_per_pax_km": _to_float(row["co2_g_per_pax_km"]),
        "likes_count": row["likes_count"],
        "comments_count": row["comments_count"],
        "created_at": _isoformat(row.get("created_at")),
        "updated_at": _isoformat(row.get("updated_at")),
    }


def map_lines_to_geojson(rows: list[dict]) -> dict:
    """`map_lines` section (§7.1, WP6.1 revision; existing-route merge
    WP10 step 6b): GeoJSON FeatureCollection with one feature per
    distinct stop-pair corridor (`stop_a`/`stop_b`, direction-agnostic —
    the physical line between two stops, not one feature per trip,
    proposal, or route). Proposals and existing ONTD trains land on the
    SAME feature when they share the corridor, so every feature carries
    the per-source split AND the total — `proposal_count` /
    `existing_count` / `total_count` (decision 2026-08-06: all three,
    always) — plus the id lists (`proposal_ids`, `existing_route_ids`)
    for the assignment. Thickness off `total_count`, colour/toggle by
    source, no second query. `avg_margin_eur_per_train_km` is the mean
    across the corridor's proposals only — None on corridors served
    exclusively by existing trains. geometry arrives pre-serialized JSON
    (both proposals.shapes.geometry and ontd.route_corridors.geometry
    are stored GeoJSON) — parsed here, not re-queried."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": row["geometry"]
                if isinstance(row["geometry"], dict)
                else json.loads(row["geometry"]),
                "properties": {
                    "stop_a": row["stop_a"],
                    "stop_b": row["stop_b"],
                    "proposal_count": row["proposal_count"],
                    "existing_count": row["existing_count"],
                    "total_count": row["total_count"],
                    "proposal_ids": list(row["proposal_ids"]),
                    "existing_route_ids": list(row["existing_route_ids"]),
                    "avg_margin_eur_per_train_km": _to_float(
                        row["avg_margin_eur_per_train_km"]
                    ),
                },
            }
            for row in rows
        ],
    }


def map_stop_counts_to_dict(rows: list[dict]) -> list[dict]:
    """`map_stop_counts` section (§7.1; source union WP10 step 6b):
    rows touching each stop, for the map's per-stop density markers —
    per-source split AND total (`n_proposals` / `n_existing` / `n`,
    decision 2026-08-06: all three, always)."""
    return [
        {
            "stop_id": row["stop_id"],
            "lat": _to_float(row["stop_lat"]),
            "lon": _to_float(row["stop_lon"]),
            "n_proposals": row["n_proposals"],
            "n_existing": row["n_existing"],
            "n": row["n"],
        }
        for row in rows
    ]


def map_country_counts_to_geojson(rows: list[dict]) -> dict:
    """`map_country_counts` section (§7.1, WP6.1 revision; source union
    WP10 step 6b): GeoJSON FeatureCollection for the coverage
    choropleth — one feature per country touched by the filtered set,
    carrying the per-source split and total (`n_proposals` /
    `n_existing` / `n`) and the country's own border geometry (joined from
    input_params.countries.country_geom) so the frontend doesn't need a
    second lookup to render it. `geometry` is `None` for a country code
    with no matched border polygon (e.g. "UNK" — an unattributed
    segment, §5.4) — still a valid GeoJSON Feature, just ungeometried."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(row["geom_geojson"])
                if row["geom_geojson"] is not None
                else None,
                "properties": {
                    "country": row["country"],
                    "n_proposals": row["n_proposals"],
                    "n_existing": row["n_existing"],
                    "n": row["n"],
                },
            }
            for row in rows
        ],
    }


def _to_float(value) -> float | None:
    """NUMERIC columns come back as Decimal via psycopg2 — jsonify()
    can't serialize Decimal, so every summary metric is cast explicitly.
    None passes through (nullable demand-placeholder columns)."""
    return None if value is None else float(value)


def _isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None
