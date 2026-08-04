"""
filter_builder.py
==================
The generic filter/sort SQL builder behind POST /api/proposals
(PROPOSALS_DESIGN.md §7.1, WP6). One column-kind registry drives both
structural validation (api/helpers/proposal_serialize.py's
validate_list_body()) and SQL generation here, so a column's filter
behaviour is declared once rather than duplicated between the two.

Column kinds, mapped onto proposals.proposal_summaries (§5.4):
  RANGE_COLUMNS          — numeric, filtered via {"min": ..., "max": ...}
  DATETIME_RANGE_COLUMNS — timestamptz, same {"min", "max"} shape as
                            RANGE_COLUMNS (ISO 8601 strings)
  LIST_COLUMNS           — scalar identity/categorical, filtered via a
                            value list (`= ANY`) — always OR semantics,
                            since each proposal has exactly one value.
                            Filter key is the column name pluralized
                            (user_id -> user_ids)
  ARRAY_COLUMNS          — TEXT[] columns (a proposal can carry several
                            values), filtered via array overlap `&&`
                            (mode "any", OR — default) or containment `@>`
                            (mode "all", AND) — see _parse_array_filter()
  SUBSTRING_COLUMNS      — case-insensitive `ILIKE` substring match

trip_windows and bbox reach past proposal_summaries (into stop_times and
geom_simplified respectively) and are built separately, since they don't
fit the generic per-column shape. likes_count is also not a
proposal_summaries column — repository.py joins it in live from
proposals.likes (a like count changes independently of publish/refresh,
so storing it on the summary projection would go stale) — but it's
declared here as an ordinary RANGE_COLUMNS entry because, once the
repository's query aliases the joined count under that name, it behaves
exactly like any other numeric column for filtering/sorting purposes.
route_builder_version/calc_version/scenario_id are NOT filterable — every gallery row already carries the
current base scenario by construction (§7.1's "every stored proposal ...
always representing the current base scenario"), and the two version
columns are internal/analytical, not a gallery-facing dimension; all
three remain plain summary fields.

Public interface:
  build_where(filter_dict)        -> (sql_fragment, params)  (no ` WHERE `
                                                                 keyword)
  build_order_by(sort_list)       -> sql_fragment              (no
                                                                 ` ORDER BY `
                                                                 keyword)
  SORTABLE_COLUMNS                -> frozenset[str], every filterable
                                      column plus "route_fingerprint"

Callers: adapters/proposal/repository.py's list_summaries() /
map_lines() / map_stop_counts() / map_country_counts(); validated first
by api/helpers/proposal_serialize.py's validate_list_body().
"""

from __future__ import annotations

from models.utils import min_to_interval

# =============================================================================
# Column registry — the single source of truth for filter/sort behaviour
# =============================================================================

# {filter key: db column} — every numeric summary column, {"min", "max"} range.
RANGE_COLUMNS: dict[str, str] = {
    "total_distance_km": "total_distance_km",
    "total_time_h": "total_time_h",
    "avg_speed_kmh": "avg_speed_kmh",
    "n_stops": "n_stops",
    "cost_eur_per_train_km": "cost_eur_per_train_km",
    "revenue_eur_per_train_km": "revenue_eur_per_train_km",
    "margin_eur_per_train_km": "margin_eur_per_train_km",
    "subsidy_eur_per_year": "subsidy_eur_per_year",
    "demand_trips_per_year": "demand_trips_per_year",
    "demand_trip_km_per_year": "demand_trip_km_per_year",
    "shift_air_trips_per_year": "shift_air_trips_per_year",
    "shift_air_trip_km_per_year": "shift_air_trip_km_per_year",
    "shift_car_trips_per_year": "shift_car_trips_per_year",
    "shift_car_trip_km_per_year": "shift_car_trip_km_per_year",
    "co2_savings_t_per_year": "co2_savings_t_per_year",
    "subsidy_eur_per_t_co2": "subsidy_eur_per_t_co2",
    "likes_count": "likes_count",
}

# {filter key: db column} — timestamptz columns, same {"min", "max"} shape
# as RANGE_COLUMNS but ISO 8601 datetime strings instead of numbers.
DATETIME_RANGE_COLUMNS: dict[str, str] = {
    "created_at": "created_at",
    "updated_at": "updated_at",
}

# {filter key: db column} — scalar categorical columns, value-list `= ANY`
# (OR only — a proposal has exactly one value, so AND would never match).
LIST_COLUMNS: dict[str, str] = {
    "proposal_ids": "proposal_id",
    "user_ids": "user_id",
    "composition_ids": "composition_id",
    "demand_kpis_placeholder": "demand_kpis_placeholder",
}

# {filter key: db column} — TEXT[] columns, array overlap (any, default)
# or containment (all) — see _parse_array_filter().
ARRAY_COLUMNS: dict[str, str] = {
    "countries": "countries",
    "stop_ids": "stop_ids",
}

# {filter key: db column} — case-insensitive substring.
SUBSTRING_COLUMNS: dict[str, str] = {"name": "name"}

# Every filterable column a sort can target, plus route_fingerprint
# (informational/compare context, §3.2 — not itself filterable, but a
# reasonable sort key).
SORTABLE_COLUMNS: frozenset[str] = frozenset(
    set(RANGE_COLUMNS.values())
    | set(DATETIME_RANGE_COLUMNS.values())
    | set(LIST_COLUMNS.values())
    | set(ARRAY_COLUMNS.values())
    | set(SUBSTRING_COLUMNS.values())
    | {"route_fingerprint"}
)

# The one filter key that isn't a summary-table column at all — it picks
# which source table(s) to query. WP6 only implements "proposal"; the
# "existing" (ontd) union is WP10.
_SOURCES_KEY = "sources"
SUPPORTED_SOURCES: frozenset[str] = frozenset({"proposal"})

ALL_FILTER_KEYS: frozenset[str] = frozenset(
    set(RANGE_COLUMNS)
    | set(DATETIME_RANGE_COLUMNS)
    | set(LIST_COLUMNS)
    | set(ARRAY_COLUMNS)
    | set(SUBSTRING_COLUMNS)
    | {_SOURCES_KEY, "trip_windows", "bbox"}
)


# =============================================================================
# WHERE clause
# =============================================================================


def build_where(filters: dict) -> tuple[str, list]:
    """Assemble every filter key present in `filters` into one SQL
    fragment (AND-joined, no leading ` WHERE `) plus its params in
    application order. `sources` is consumed by the caller before this
    (it picks the query, not a predicate) and is ignored here if present.
    """
    clauses: list[str] = []
    params: list = []

    for key, column in RANGE_COLUMNS.items():
        bounds = filters.get(key)
        if bounds is None:
            continue
        if "min" in bounds and bounds["min"] is not None:
            clauses.append(f"{column} >= %s")
            params.append(bounds["min"])
        if "max" in bounds and bounds["max"] is not None:
            clauses.append(f"{column} <= %s")
            params.append(bounds["max"])

    for key, column in DATETIME_RANGE_COLUMNS.items():
        bounds = filters.get(key)
        if bounds is None:
            continue
        if "min" in bounds and bounds["min"] is not None:
            clauses.append(f"{column} >= %s")
            params.append(bounds["min"])
        if "max" in bounds and bounds["max"] is not None:
            clauses.append(f"{column} <= %s")
            params.append(bounds["max"])

    for key, column in LIST_COLUMNS.items():
        values = filters.get(key)
        if values is None:
            continue
        clauses.append(f"{column} = ANY(%s)")
        params.append(list(values))

    for key, column in ARRAY_COLUMNS.items():
        raw = filters.get(key)
        if raw is None:
            continue
        values, mode = _parse_array_filter(raw)
        op = "@>" if mode == "all" else "&&"
        clauses.append(f"{column} {op} %s")
        params.append(list(values))

    for key, column in SUBSTRING_COLUMNS.items():
        needle = filters.get(key)
        if needle is None:
            continue
        clauses.append(f"{column} ILIKE %s")
        params.append(f"%{needle}%")

    trip_windows = filters.get("trip_windows")
    if trip_windows:
        clause, window_params = _build_trip_windows_clause(trip_windows)
        clauses.append(clause)
        params.extend(window_params)

    bbox = filters.get("bbox")
    if bbox is not None:
        west, south, east, north = bbox
        clauses.append(
            "ST_Intersects(geom_simplified, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
        )
        params.extend([west, south, east, north])

    return " AND ".join(clauses), params


def _parse_array_filter(raw) -> tuple[list, str]:
    """An ARRAY_COLUMNS filter value is either a plain list (mode "any",
    the common case and the backward-compatible default) or
    {"values": [...], "mode": "any"|"all"} for an explicit choice —
    "any" is array overlap (`&&`, OR: at least one of these), "all" is
    containment (`@>`, AND: every one of these). Only meaningful for
    array columns — a proposal has exactly one composition_id/user_id/
    etc., so LIST_COLUMNS stays OR-only by construction."""
    if isinstance(raw, dict):
        return raw["values"], raw.get("mode", "any")
    return raw, "any"


def _build_trip_windows_clause(trip_windows: list[dict]) -> tuple[str, list]:
    """A proposal matches when a SINGLE trip satisfies every window entry
    (§7.1) — implemented as one EXISTS over proposals.trips, joined to one
    proposals.stop_times instance per entry on a shared trip_id, each
    instance range-filtered on arrival_time/departure_time. The trip must
    belong to the row's own proposal: route_id follows the
    P{proposal_id}_V{proposal_version}_R1 convention (single-route
    proposals only, same assumption repository.py's _prune_gtfs() makes),
    so the join target is built from the two summary columns rather than
    stored redundantly on stop_times.
    """
    joins: list[str] = []
    params: list = []

    for i, entry in enumerate(trip_windows):
        alias = f"stw{i}"
        joins.append(
            f"JOIN proposals.stop_times {alias} "
            f"ON {alias}.trip_id = t.trip_id AND {alias}.stop_id = %s"
        )
        params.append(entry["stop_id"])

        for direction, time_column in (
            ("departure", "departure_time"),
            ("arrival", "arrival_time"),
        ):
            window = entry.get(direction)
            if window is None:
                continue
            day_offset = window.get("day_offset", 0)
            if "from" in window:
                joins[-1] += f" AND {alias}.{time_column} >= %s"
                params.append(_to_interval(window["from"], day_offset))
            if "to" in window:
                joins[-1] += f" AND {alias}.{time_column} <= %s"
                params.append(_to_interval(window["to"], day_offset))

    trip_join_sql = " ".join(joins)
    clause = (
        "EXISTS (SELECT 1 FROM proposals.trips t "
        f"{trip_join_sql} "
        "WHERE t.route_id = 'P' || proposal_id || '_V' || proposal_version || '_R1')"
    )
    return clause, params


def _to_interval(hhmm: str, day_offset: int) -> str:
    """Wall-clock 'HH:MM' + day_offset -> the same INTERVAL-literal
    convention stop_times is stored in (models/utils.py's
    min_to_interval(), GTFS overnight convention)."""
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return min_to_interval(hours * 60 + minutes + day_offset * 1440)


# =============================================================================
# ORDER BY clause
# =============================================================================


def build_order_by(sort: list[dict] | None) -> str:
    """`sort` is a list of {"by": <sortable column>, "dir": "asc"|"desc"}
    (§7.1) — assumed already validated (validate_list_body() rejects
    unsortable columns and bad directions before this runs). Falls back
    to newest-first."""
    if not sort:
        return "updated_at DESC"
    parts = []
    for entry in sort:
        direction = "DESC" if entry.get("dir", "asc").lower() == "desc" else "ASC"
        parts.append(f"{entry['by']} {direction}")
    return ", ".join(parts)
