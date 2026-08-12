"""
proposal_stats.py
=================
Validation and serialization for GET /api/proposals/stats
(adapters/proposal/README.md §7.7) — the descriptive statistics over the
gallery's stored rows: how many proposals and existing trains there are,
what their KPIs look like in aggregate, and which countries and
country-to-country relations are served most and least.

What this endpoint is NOT: the bundle economics of
`POST /api/proposals/analyze` (parked, docs/PARKED_WORK.md). Everything
here is read straight off proposals.proposal_summaries ∪
ontd.route_summaries — nothing is recomputed, no scenario can be
overridden, and the aggregates are therefore statistics ABOUT the stored
proposals, not a network calculation. The practical consequence worth
stating on every rate column: `avg` is the unweighted mean of per-route
figures, so it answers "what does a typical proposal cost per train-km",
not "what would this set of routes cost per train-km as one network".
The second question needs annual train-km per route as a weight, which
the summary projection does not carry — that is analyze's job.

Three scopes per statistic, named with the same `source` vocabulary the
gallery rows use: "proposal", "existing", "all". Existing (ONTD) rows
carry NULL in every proposal-only column, so their scope — and the
combined one — report only the shared metric subset
(filter_builder.SHARED_SOURCE_COLUMNS) rather than repeating the
proposal figures under a label that implies more rows contributed than
did.

Public interface:
  validate_stats_query(args)              -> (params, errors)
  stats_to_dict(...)                      -> dict  (the §7.7 response)
"""

from __future__ import annotations

from adapters.proposal.filter_builder import (
    ADDITIVE_COLUMNS,
    AGGREGATE_ALIAS_SEP,
    AGGREGATE_COLUMNS,
    SHARED_SOURCE_COLUMNS,
)

# Every statistic is reported for these three scopes, always in this
# order — a stable response shape means the frontend never branches on
# which scopes happen to be non-empty.
_SCOPES = ("proposal", "existing", "all")

# The combined-row marker GROUPING SETS produces (source IS NULL).
_COMBINED = "all"


# =============================================================================
# VALIDATE
# =============================================================================


def validate_stats_query(args, defaults: dict) -> tuple[dict, list[str]]:
    """Parse and check the query string → (params, errors).

    Only `user_id` is a request parameter: the country/relation list
    lengths and the relation distance threshold are deployment settings
    (api/config.py), not something a caller tunes per request — they
    define what the statistics MEAN, and two callers reading different
    definitions of "flop" off the same deployment would be worse than
    useless.
    """
    errors: list[str] = []
    params = dict(defaults)

    raw = args.get("user_id")
    if raw is not None:
        try:
            params["user_id"] = int(raw)
        except (TypeError, ValueError):
            errors.append("'user_id' must be an integer.")

    unknown = set(args) - {"user_id"}
    if unknown:
        errors.append(
            f"Unknown query parameter(s): {sorted(unknown)}. Supported: ['user_id']."
        )

    return params, errors


def filters_for(user_id: int | None) -> dict:
    """The gallery filter this request narrows to.

    A user_id implies sources=["proposal"]: existing trains have no
    owner, so including them under a per-user question would answer a
    different one. Without it, both sources — the gallery default.
    """
    if user_id is None:
        return {}
    return {"user_ids": [user_id], "sources": ["proposal"]}


# =============================================================================
# SERIALIZE
# =============================================================================


def stats_to_dict(
    user_id: int | None,
    kpi_rows: list[dict],
    reach_rows: list[dict],
    country_rows: list[dict],
    relation_rows: list[dict],
    universe: dict,
    top: int,
    flop: int,
    max_relation_km: float,
) -> dict:
    """Assemble the §7.7 response from the repository's five result sets."""
    by_scope_kpi = _rows_by_scope(kpi_rows)
    by_scope_reach = _rows_by_scope(reach_rows)
    stations = {
        station["country"]: {
            "stop_id": station["stop_id"],
            "stop_name": station["stop_name"],
            "lat": _to_float(station["stop_lat"]),
            "lon": _to_float(station["stop_lon"]),
        }
        for station in universe["reference_stations"]
    }

    return {
        "scope": {
            "user_id": user_id,
            "sources": ["proposal"] if user_id is not None else list(_SCOPES[:2]),
        },
        "counts": {
            scope: _counts_for(by_scope_kpi.get(scope), by_scope_reach.get(scope))
            for scope in _SCOPES
        },
        "kpis": {scope: _kpis_for(by_scope_kpi.get(scope), scope) for scope in _SCOPES},
        "countries": {
            "ranked_by": "n_proposals",
            "top": [_country_to_dict(row) for row in country_rows[:top]],
            "flop": [_country_to_dict(row) for row in _flop_slice(country_rows, flop)],
        },
        "country_relations": {
            "ranked_by": "n_proposals",
            "basis": {
                "reference": "nearest_catalog_stop_to_country_stop_centroid",
                "distance": "routed_rail",
                "max_relation_km": max_relation_km,
                "built_at": _isoformat(universe.get("built_at")),
            },
            "universe": {
                "n_countries": len(stations),
                "n_pairs": universe["n_pairs"],
                "excluded_over_threshold": universe["excluded_over_threshold"],
                "excluded_unroutable": universe["excluded_unroutable"],
                "unresolved_countries": _unresolved_countries(country_rows, stations),
            },
            "reference_stations": stations,
            "top": [_relation_to_dict(row) for row in relation_rows[:top]],
            "flop": [
                _relation_to_dict(row) for row in _flop_slice(relation_rows, flop)
            ],
        },
    }


def _rows_by_scope(rows: list[dict]) -> dict[str, dict]:
    """GROUPING SETS returns the per-source rows plus one combined row
    with source NULL — keyed here under the same names the response
    uses."""
    return {(row["source"] or _COMBINED): row for row in rows}


def _counts_for(kpi_row: dict | None, reach_row: dict | None) -> dict:
    return {
        "n": kpi_row["n_rows"] if kpi_row else 0,
        "n_distinct_stops": reach_row["n_distinct_stops"] if reach_row else 0,
        "n_distinct_countries": reach_row["n_distinct_countries"] if reach_row else 0,
    }


def _kpis_for(row: dict | None, scope: str) -> dict:
    """One {n, avg, min, max, sum?} block per numeric column.

    "proposal" gets every column; the other two scopes get the shared
    subset only — see the module docstring. Columns whose `n` is zero are
    omitted rather than filled with nulls, the same
    omit-don't-null-pad rule the gallery row follows for existing trains.
    """
    if row is None:
        return {}
    columns = AGGREGATE_COLUMNS if scope == "proposal" else SHARED_SOURCE_COLUMNS
    stats = {}
    for column in columns:
        count = row[f"{column}{AGGREGATE_ALIAS_SEP}n"]
        if not count:
            continue
        entry = {
            "n": count,
            "avg": _to_float(row[f"{column}{AGGREGATE_ALIAS_SEP}avg"]),
            "min": _to_float(row[f"{column}{AGGREGATE_ALIAS_SEP}min"]),
            "max": _to_float(row[f"{column}{AGGREGATE_ALIAS_SEP}max"]),
        }
        if column in ADDITIVE_COLUMNS:
            entry["sum"] = _to_float(row[f"{column}{AGGREGATE_ALIAS_SEP}sum"])
        stats[column] = entry
    return stats


def _flop_slice(rows: list[dict], flop: int) -> list[dict]:
    """The least-served end of a ranking the repository already returned
    best-first.

    Not simply the reversed tail: within the zeros — which dominate both
    lists while proposal volume is low — the ordering that carries
    information is by distance ascending (the closest unserved relation
    is the most plausible missing night train), and the repository's
    ORDER BY already puts nearer pairs first. Re-sorting on the
    ascending key keeps that, where reversing would invert it into
    "furthest unserved first".
    """
    if flop <= 0:
        return []
    ranked = sorted(
        enumerate(rows),
        key=lambda pair: (pair[1]["n_proposals"], pair[1]["n"], pair[0]),
    )
    return [row for _, row in ranked[:flop]]


def _country_to_dict(row: dict) -> dict:
    return {
        "country": row["country"],
        "n_proposals": row["n_proposals"],
        "n_existing": row["n_existing"],
        "n": row["n"],
    }


def _relation_to_dict(row: dict) -> dict:
    return {
        "country_a": row["country_a"],
        "country_b": row["country_b"],
        "rail_km": _to_float(row["rail_km"]),
        "rail_time_h": _to_float(row["rail_time_h"]),
        "n_proposals": row["n_proposals"],
        "n_existing": row["n_existing"],
        "n": row["n"],
    }


def _unresolved_countries(country_rows: list[dict], stations: dict) -> list[str]:
    """Countries the filtered rows actually touch that have no reference
    station, and therefore no relations at all.

    The stop catalog does not cover every country yet, so an existing
    train through one of them contributes to the country ranking while
    being invisible to the relation ranking. Naming them keeps that a
    stated gap rather than a silent one — the list shrinks on its own as
    stop coverage grows.
    """
    return sorted(
        row["country"]
        for row in country_rows
        if row["n"] and row["country"] not in stations
    )


def _to_float(value) -> float | None:
    """NUMERIC and the aggregates over it come back as Decimal via
    psycopg2, which jsonify() cannot serialize."""
    return None if value is None else float(value)


def _isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None
