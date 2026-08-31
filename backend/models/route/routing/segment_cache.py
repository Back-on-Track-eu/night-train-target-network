"""
segment_cache.py
================
The route-segment cache's data shape and its RoutedLeg conversions —
DB-free and side-effect-free, so rail_router.py's cache path, the
precompute script, the repository's bulk loader and the tests all share
one definition of what a cached row means.

A CachedSegment is the raw physics of ONE stop pair on ONE routing graph,
stored in canonical lo→hi orientation (stop ids sorted ascending —
direction is symmetric, so one row serves both travel directions and the
table halves). Everything scenario-dependent is absent by design: buffer
quotas, traction dynamics and energy are applied downstream by
route_trip() / route_factory, so a TAC or buffer-quota recalibration
invalidates zero rows. The only thing that stales a row is a re-import of
its graph — handled per graph by RouteSegmentRepository.sync_graph_import().

Storage vs. derivation:
  stored   — geometry, country_distance_m, country_driving_ms (raw,
             unrounded), countries (path order), passages (this pair's
             FULL intersecting list, undeduped — the cross-leg
             first-leg-wins claim happens at trip assembly in
             rail_router.py), distance_m (rounded total, for screening
             queries without JSON access)
  derived  — driving_time_min and both share dicts, recomputed here in
             leg_from_cached() with the exact rounding _parse_legs uses,
             so a cache-served leg is bit-identical to a live-routed one.

CSV contract: CSV_COLUMNS is shared verbatim by
scripts/precompute_route_segments.py (writer) and
RouteSegmentRepository.load_csv() (reader). The file carries no graph
column — one file per graph, the graph named in its sidecar meta and at
load time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from models.route.routing.rail_router import RoutedLeg
from models.utils import ms_to_min

# Writer (precompute script) and reader (repository bulk load) contract —
# the table's column order minus routing_graph_key/source/routed_at, which
# the loader supplies per file.
CSV_COLUMNS = [
    "stop_lo",
    "stop_hi",
    "variant_key",
    "distance_m",
    "country_distance_m",
    "country_driving_ms",
    "countries",
    "passages",
    "geometry",
]


@dataclass
class CachedSegment:
    """One stop pair's raw routed physics, in lo→hi orientation."""

    geometry: list[list[float]]  # [[lon, lat], ...], lo→hi
    distance_m: int
    country_distance_m: dict[str, float]
    country_driving_ms: dict[str, float]
    countries: list[str]  # path order, lo→hi
    passages: list[str]  # full intersecting list, undeduped


def segment_from_leg(leg: RoutedLeg, reverse: bool) -> CachedSegment:
    """A live-routed pair leg → its canonical stored form. reverse=True
    when the leg was routed hi→lo, so geometry and country entry order
    are flipped into lo→hi; the per-country dicts and passages are
    direction-symmetric and stored as-is."""
    return CachedSegment(
        geometry=list(reversed(leg.geometry)) if reverse else list(leg.geometry),
        distance_m=leg.distance_m,
        country_distance_m=dict(leg.country_distance_m),
        country_driving_ms=dict(leg.country_driving_ms),
        countries=list(reversed(leg.countries)) if reverse else list(leg.countries),
        passages=list(leg.passages),
    )


def leg_from_cached(seg: CachedSegment, reverse: bool) -> RoutedLeg:
    """A stored row → a RoutedLeg for one trip direction. reverse=True
    when the trip travels hi→lo. Shares and driving_time_min are
    re-derived with _parse_legs' exact math; buffer/dynamics/energy stay
    0 for route_trip() to fill — identical to a live route() return."""
    total_dist_m = sum(seg.country_distance_m.values())
    total_dur_ms = sum(seg.country_driving_ms.values())
    return RoutedLeg(
        geometry=list(reversed(seg.geometry)) if reverse else list(seg.geometry),
        distance_m=seg.distance_m,
        driving_time_min=ms_to_min(total_dur_ms),
        dynamics_time_min=0,
        buffer_time_min=0,
        energy_kwh=0.0,
        country_distance_shares={
            cc: (d / total_dist_m if total_dist_m > 0 else 0.0)
            for cc, d in seg.country_distance_m.items()
        },
        country_time_shares={
            cc: (ms / total_dur_ms if total_dur_ms > 0 else 0.0)
            for cc, ms in seg.country_driving_ms.items()
        },
        countries=list(reversed(seg.countries)) if reverse else list(seg.countries),
        passages=list(seg.passages),
        country_distance_m=dict(seg.country_distance_m),
        country_driving_ms=dict(seg.country_driving_ms),
    )


def segment_to_csv_row(
    stop_lo: str, stop_hi: str, variant_key: str, seg: CachedSegment
) -> list:
    """One CSV row in CSV_COLUMNS order — JSON columns compact-encoded so
    the file stays COPY-loadable and as small as JSON gets."""
    dumps = lambda v: json.dumps(v, separators=(",", ":"))  # noqa: E731
    return [
        stop_lo,
        stop_hi,
        variant_key,
        seg.distance_m,
        dumps(seg.country_distance_m),
        dumps(seg.country_driving_ms),
        dumps(seg.countries),
        dumps(seg.passages),
        dumps(seg.geometry),
    ]


def segment_from_db_row(row: dict) -> CachedSegment:
    """A route_cache.route_segments row (psycopg2 already decodes JSONB
    into Python objects) → CachedSegment."""
    return CachedSegment(
        geometry=row["geometry"],
        distance_m=row["distance_m"],
        country_distance_m=row["country_distance_m"],
        country_driving_ms=row["country_driving_ms"],
        countries=row["countries"],
        passages=row["passages"],
    )
