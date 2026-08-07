"""
projection.py
=============
Fingerprint + DB-shaped summary assembly (adapters/proposal/README.md §3.1/§5.4,
WP4; slimmed with WP10 step 5). Pure functions over the same dicts
POST /api/proposal/calc already returns (route_to_dict() shape + the
evaluation "views" block) — no DB access, no domain-object construction.

The §5.4 KPI derivation itself (build_summary_row()) moved to
models/evaluation/summary.py so the calc response, the compare sides,
and the publish path all share one function without api/helpers ever
importing from adapters/ (layering, AGENTS.md). What stays here is what
only the DB side needs: the route fingerprint and the simplified
gallery-map geometry.

Public interface:
  route_fingerprint(route)                → str   (§3.1 — SHA-256 over
                                                    the route's resolved
                                                    stops/times/geometry,
                                                    prefix- and ID-
                                                    agnostic by
                                                    construction)
  build_summary_db_row(route, evaluation) → dict  (§5.4 — the shared KPI
                                                    row plus
                                                    geom_simplified, i.e.
                                                    every non-identity
                                                    proposals.
                                                    proposal_summaries
                                                    column. Identity
                                                    columns — proposal_id,
                                                    user_id,
                                                    composition_id,
                                                    scenario_id, name,
                                                    versions — are the
                                                    repository's concern
                                                    at publish time.)

Callers: api/helpers/proposal_compute.py (fingerprint only, for the
merged compute response); repository.py (both functions, at
publish/refresh time).
"""

from __future__ import annotations

import hashlib
import json

from models.evaluation.summary import build_summary_row, ordered_stops

# Douglas-Peucker tolerance for proposal_summaries.geom_simplified, in
# degrees (route geometry is stored unprojected, EPSG:4326) — a first-pass
# placeholder pending real tuning against gallery-map zoom levels (§5.4's
# own wording: "tolerance tuned for gallery-map zoom levels"). ~0.0005° is
# roughly 50m at mid-European latitudes.
GEOM_SIMPLIFY_TOLERANCE_DEG = 0.0005


# =============================================================================
# FINGERPRINT — §3.1
# =============================================================================


def route_fingerprint(route: dict) -> str:
    """SHA-256 over a canonical extract of the built route: per trip pair
    (list order preserved), per trip (outbound then return), the ordered
    (stop_id, arrival_time_min, departure_time_min) list plus that trip's
    concatenated segment geometry, coordinates rounded to 5 decimals
    (~1m — absorbs float noise). No route_id/trip_id/geometry_id ever
    enters the hash, only stop_id (a stable, unprefixed reference) — so
    ephemeral (neutral-id) and published (P{id}_V{n}_-prefixed) forms of
    the identical route hash identically by construction, without needing
    to strip anything. Returned as 'sha256:<hex>'.
    """
    geometries_by_id = {g["id"]: g["coords"] for g in route.get("geometries", [])}
    canonical = [
        {
            "outbound": _canonical_trip(pair["outbound"], geometries_by_id),
            "return_trip": _canonical_trip(pair["return_trip"], geometries_by_id),
        }
        for pair in route["trip_pairs"]
    ]
    # Fixed key insertion order above + separators with no whitespace make
    # this dump byte-identical for byte-identical input, run to run.
    canonical_json = json.dumps(canonical, separators=(",", ":"))
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_trip(trip: dict, geometries_by_id: dict[str, list]) -> dict:
    stops = ordered_stops(trip)
    coords = [
        pt
        for seg in trip["segments"]
        for pt in geometries_by_id.get(seg["geometry_id"], [])
    ]
    return {
        "stops": [
            [s["stop_id"], s["arrival_time_min"], s["departure_time_min"]]
            for s in stops
        ],
        "geometry": [[round(c, 5) for c in pt] for pt in coords],
    }


# =============================================================================
# SUMMARY ROW — §5.4 (DB-shaped assembly)
# =============================================================================


def build_summary_db_row(route: dict, evaluation: dict) -> dict:
    """The non-identity proposals.proposal_summaries columns for one
    (route, evaluation) pair: the shared §5.4 KPI row
    (models/evaluation/summary.py — identical to the calc response's
    "summary" block) plus geom_simplified, the one column that exists
    only for the gallery map. Ready to merge with the identity columns
    the publish repository adds."""
    return {
        **build_summary_row(route, evaluation),
        "geom_simplified": _geom_simplified(route),
    }


def _geom_simplified(route: dict) -> dict:
    """Per-segment shapes concatenated into one LineString per trip
    (outbound and return, every pair), collected into a MultiLineString,
    Douglas-Peucker simplified — the geom_simplified GeoJSON handed to the
    repository for ST_GeomFromGeoJSON/ST_SetSRID at insert time (WP5)."""
    from shapely.geometry import LineString, MultiLineString, mapping

    geometries_by_id = {g["id"]: g["coords"] for g in route.get("geometries", [])}
    lines = []
    for pair in route["trip_pairs"]:
        for trip in (pair["outbound"], pair["return_trip"]):
            coords = [
                pt
                for seg in trip["segments"]
                for pt in geometries_by_id.get(seg["geometry_id"], [])
            ]
            if len(coords) >= 2:
                lines.append(LineString(coords))

    simplified = MultiLineString(lines).simplify(
        GEOM_SIMPLIFY_TOLERANCE_DEG, preserve_topology=False
    )
    # simplify() on a MultiLineString collapses to a plain LineString when
    # only one line survives — normalize back so geom_simplified always
    # matches the column's MultiLineString type.
    if simplified.geom_type == "LineString":
        simplified = MultiLineString([simplified])
    return mapping(simplified)
