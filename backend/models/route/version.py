"""
version.py
==========
Version constant and model description for the Night Train Route Builder.

Bump ROUTE_BUILDER_VERSION when any change affects the Trip output:
  - Routing logic or GraphHopper configuration
  - Schedule / dwell time computation
  - Any change to Trip, TripPath, TripSegment, CountryLeg, TripStats, StopTime

ROUTE_FORMULAS documents the key calculations in the route builder
with LaTeX and plain-English descriptions.

TODO: GIT_SHA injected at build time by CI — see .github/workflows/backend-tests.yml
"""

from __future__ import annotations
from dataclasses import dataclass


# =============================================================================
# VERSION
# =============================================================================

ROUTE_BUILDER_VERSION: str = "1.0.0"

GIT_SHA: str = "unknown"  # injected by CI

CHANGELOG: dict = {
    "1.0.0": {
        "date":    "2026-06-25",
        "author":  "david",
        "changes": "Initial implementation. GTFS-aligned Route/Trip domain model. "
                   "TripPath with CountryLeg-level physics. plan_route() + adjust_route() "
                   "factory pattern. ID convention P{id}_V{ver}_R1_D{dir}_T{idx}. "
                   "RailRouter returns TripPath directly.",
    },
}


# =============================================================================
# ROUTE FORMULA REGISTRY
# =============================================================================

@dataclass(frozen=True)
class RouteFormula:
    """One entry in the route builder calculation model."""
    latex:       str
    description: str


ROUTE_FORMULAS: dict[str, RouteFormula] = {

    # ------------------------------------------------------------------
    # ROUTING
    # ------------------------------------------------------------------
    "buffer_time": RouteFormula(
        latex       = r"t_{buffer,l} = t_{drive,l} \times q_{buffer,country(l)}",
        description = "Buffer time per country leg: driving time multiplied by the "
                      "country's schedule buffer quota (accounts for construction, "
                      "delays, and operational margins).",
    ),
    "total_time_per_leg": RouteFormula(
        latex       = r"t_{total,l} = t_{drive,l} + t_{buffer,l}",
        description = "Total travel time per country leg: driving time plus buffer.",
    ),
    "total_time_per_segment": RouteFormula(
        latex       = r"t_{seg} = \sum_{l \in seg} t_{total,l}",
        description = "Total travel time per segment (stop pair): sum over all "
                      "country legs within the segment.",
    ),
    "avg_speed": RouteFormula(
        latex       = r"\bar{v}_{kmh} = \frac{d_{km}}{t_{drive,h}}",
        description = "Average speed: distance divided by pure driving time "
                      "(excluding buffer). Display value only — not stored.",
    ),

    # ------------------------------------------------------------------
    # DWELL TIME
    # ------------------------------------------------------------------
    "dwell_time_boarding": RouteFormula(
        latex       = r"t_{dwell} = \max(t_{board,comp},\ t_{board,infra})",
        description = "Dwell time at boarding stop: maximum of composition minimum "
                      "boarding time and infrastructure minimum boarding time.",
    ),
    "dwell_time_alighting": RouteFormula(
        latex       = r"t_{dwell} = \max(t_{alight,comp},\ t_{alight,infra})",
        description = "Dwell time at alighting stop: maximum of composition minimum "
                      "alighting time and infrastructure minimum alighting time.",
    ),
    "dwell_time_both": RouteFormula(
        latex       = r"t_{dwell} = \max(t_{board,comp},\ t_{board,infra},\ t_{alight,comp},\ t_{alight,infra})",
        description = "Dwell time at boarding+alighting stop: maximum of all four "
                      "boarding and alighting time constraints.",
    ),

    # ------------------------------------------------------------------
    # SCHEDULE
    # ------------------------------------------------------------------
    "arrival_time": RouteFormula(
        latex       = r"t_{arr,i} = t_{dep,i-1} + t_{seg,i-1}",
        description = "Arrival time at stop i: departure from previous stop plus "
                      "total segment travel time (driving + buffer).",
    ),
    "departure_time": RouteFormula(
        latex       = r"t_{dep,i} = t_{arr,i} + t_{dwell,i}",
        description = "Departure time at intermediate stop: arrival time plus dwell time.",
    ),

    # ------------------------------------------------------------------
    # TRIP STATS
    # ------------------------------------------------------------------
    "total_distance": RouteFormula(
        latex       = r"d_{total} = \sum_{seg} \sum_{l \in seg} d_{m,l}",
        description = "Total trip distance: sum of all country leg distances in metres.",
    ),
    "total_driving_time": RouteFormula(
        latex       = r"t_{drive,total} = \sum_{seg} \sum_{l \in seg} t_{drive,l}",
        description = "Total driving time: sum of pure engine time across all country legs.",
    ),
    "total_time": RouteFormula(
        latex       = r"t_{total} = \sum_{seg} t_{total,seg}",
        description = "Total trip time: driving time plus all buffer times.",
    ),
}