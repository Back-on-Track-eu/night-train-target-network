"""
rail_router.py
==============
Wrapper around one OpenRailRouting (GraphHopper) instance — one RailRouter
per routing graph (api/helpers/dependencies.py registry).

Unit conventions (internal)
----------------------------
  Distance : metres  (_m)   — GraphHopper native
  Duration : minutes (_min) — converted from GraphHopper milliseconds on parse

Two layers
----------
Layer 1 — RailRouter.route(stops, max_speed_kmh, avoid_hsr, gauge_mm,
routing_mode): pure router physics. Its inputs are EXACTLY the inputs that
shape the routed geometry — profile (from gauge) and the resolved custom
model (speed cap, HSR vector, blocked countries) — which is what makes the
route-segment cache key honest: route_variant_key(profile, custom_model)
covers everything this layer can vary. Returned RoutedLegs carry raw
per-country distance/time dicts and buffer_time_min=0, dynamics_time_min=0,
energy_kwh=0.0 — nothing scenario-dependent. With a RouteSegmentRepository
attached (the default), every mode is served lookup-first per consecutive
stop pair against route_cache.route_segments for THIS router's graph;
misses are live-routed as two-point calls and stored back, so the cache
grows with every request. Per-pair decomposition is output-identical to
one multi-point call: GraphHopper treats via-points as hard constraints
and snapping is per-point deterministic.

Layer 2 — route_trip(router, stops, composition, tracks, routing_mode):
the shared domain entry every trip-routing call site uses
(route_factory._build_trip(), timetable.py's mini-reroutes and final
reroute, adapters/routing_context.py). Resolves the layer-1 inputs from
the domain pair (resolve_routing_params(), incl. the trip gauge via
routing/gauge.py), then applies the scenario-dependent physics on top:
country buffer quotas (apply_country_buffer()) and traction dynamics
(routing/dynamics.py). Nobody calls layer 1 directly except the cache
machinery and scripts/precompute_route_segments.py — this keeps the
single-call-site guarantee for dynamics.

Responsibilities
----------------
- HTTP communication with GraphHopper (two-pass routing for custom models).
- Country attribution of route geometry via shapely point-in-polygon.
- Raw physics per segment: distance_m, driving_time_min,
  country_distance_m, country_driving_ms (and the shares derived from
  them), countries, passages.
- Gauge-aware profile selection: the trip gauge (resolved by layer 2 from
  the call's own stops, routing/gauge.py) selects the GraphHopper profile
  — night_train for 1435, night_train_<mm> otherwise (naming contract:
  SUPPORTED_GAUGES_MM in models/route/model.py ←→ docker/config.yml).
  Baked per-profile so stop SNAPPING is gauge-correct.
- Belarus/Russia exclusion (BLOCKED_COUNTRIES): a speed-0 area rule over
  each blocked country's border polygon, attached to EVERY routing request
  in every mode — the fork registers no `country` encoded value, so the
  block cannot live in the graph (see docker/config.yml).
- fullRouting custom model: composition speed cap + HSR avoidance — only
  track whose permitted speed exceeds HSR_TRACK_SPEED_THRESHOLD_KMH is
  penalized, and only where avoid_hsr says so. Thresholds/factor live in
  models/route/model.py (STANDARD VALUES); mechanism in
  build_custom_model()'s docstring.

NOT responsible for (layer 2 / downstream):
- Country buffer quotas   (→ apply_country_buffer(), called by route_trip())
- Traction dynamics       (→ routing/dynamics.py, called by route_trip())
- Stop timetable data     (→ models/route/route_factory.py)
- Energy consumption      (→ models/energy/calc_energy_consumption.py)
- TAC / energy costs      (→ models/evaluation/calc.py)

Public surface
--------------
  route_trip(router, stops, composition, tracks, routing_mode)
      → list[RoutedLeg]                            (layer 2 — domain entry)
  resolve_routing_params(composition, tracks, stops)
      → (max_speed_kmh, avoid_hsr, gauge_mm)
  apply_country_buffer(legs, tracks)               (quota on raw driving)
  RailRouter.route(stops, max_speed_kmh, avoid_hsr, gauge_mm, routing_mode)
      → list[RoutedLeg]                            (layer 1)
  RailRouter.build_custom_model(max_speed_kmh, avoid_hsr) → dict | None
  RailRouter.profile_for_gauge(gauge_mm) → str
  RailRouter.snap_point() / route_pair_from_snapped()   (precompute script)
  route_variant_key(profile, custom_model) → str   (segment-cache key)
  RailRoutingError
  RoutedLeg  (output type — public)
  StopInput  (input type — public; wraps StopInfrastructure + StopType)
  VALID_ROUTING_MODES  (single source of truth for allowed routing_mode
    strings — the routing_mode switch lives in RailRouter.route() below;
    the compute request validation in api/helpers/proposal_compute.py
    reads from it)
  build_router_stops(stop_ids, stop_infra) → list[StopInput]
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import requests

from models.params import (
    Composition,
    TrackInfraCollection,
    StopInfrastructure,
    StopInfraCollection,
)
from models.route.trip import StopType
from models.route.routing.dynamics import apply_traction_dynamics
from models.route.routing.gauge import resolve_trip_gauge
from models.route.model import (
    BLOCKED_COUNTRIES,
    HSR_TRACK_SPEED_THRESHOLD_KMH,
    HSR_TRACK_SPEED_SANITY_MAX_KMH,
    HSR_AVOIDANCE_PRIORITY_FACTOR,
    HSR_AVOIDANCE_RING_SIMPLIFY_DEG,
    STANDARD_GAUGE_MM,
)
from models.utils import ms_to_min, haversine_path_m

if TYPE_CHECKING:
    from adapters.route_segment_repository import RouteSegmentRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public input type
# ---------------------------------------------------------------------------


@dataclass
class StopInput:
    """A stop plus its routing context for one trip. Wraps the canonical
    StopInfrastructure — no field duplication."""

    stop: StopInfrastructure
    stop_type: StopType


def build_router_stops(
    stop_ids: list[str], stop_infra: StopInfraCollection
) -> list[StopInput]:
    """
    Resolves a plain stop_id list into StopInput objects for RailRouter.route().
    stop_type is always a placeholder (route() ignores it — see route()'s
    docstring); real StopType classification happens afterwards, via
    route_factory._build_trip()'s timetable_mode switch.

    Single call site for this conversion — route_factory.py (initial
    routing) and timetable.py (auto_stop_addition's trial re-routes) both
    use this rather than each building StopInput lists themselves.
    """
    router_stops = [
        StopInput(stop=stop_infra.get(sid), stop_type=StopType.BOTH) for sid in stop_ids
    ]
    for rs, sid in zip(router_stops, stop_ids):
        if rs.stop is None:
            raise ValueError(f"Stop '{sid}' not found in database.")
    return router_stops


# ---------------------------------------------------------------------------
# Public output type
# ---------------------------------------------------------------------------


@dataclass
class RoutedLeg:
    """
    Bare physics for one segment between two consecutive stops — no Stop
    objects attached. route_factory._build_trip_stops_and_legs() pairs each RoutedLeg
    with Stop objects to produce the final trip.Segment.

    country_distance_shares and country_time_shares sum to 1.0 each.
    energy_kwh is 0.0 on return — enriched in-place by
    calc_energy_consumption() before route_factory builds Stops.
    driving_time_min is the raw router time; the per-stop traction
    dynamics surcharge is carried separately in dynamics_time_min
    (filled by route_trip() for routing_mode="fullRouting" — see
    routing/dynamics.py) so the two stay differentiable downstream.
    buffer_time_min is 0 as returned by RailRouter.route() — the country
    buffer quota is scenario-dependent and applied by route_trip() via
    apply_country_buffer() (on driving) and apply_traction_dynamics()
    (on dynamics, strictly AFTER the cruise speed was derived from raw
    driving time); never on dwell.
    """

    geometry: list[list[float]]  # [[lon, lat], ...]
    distance_m: int
    driving_time_min: int  # raw router time (constant-cruise-speed passage)
    dynamics_time_min: int  # 0 until apply_traction_dynamics() runs (fullRouting)
    buffer_time_min: int  # quota on driving (parse time) + quota on dynamics
    # (added by apply_traction_dynamics afterwards) — never on dwell
    energy_kwh: float  # 0.0 until energy model runs
    country_distance_shares: dict[str, float]  # {country_code: share}, sums to 1.0
    country_time_shares: dict[str, float]  # {country_code: share}, sums to 1.0
    countries: list[str] = field(default_factory=list)  # path order — see Segment
    passages: list[str] = field(default_factory=list)  # crossings this leg owns
    # Raw per-country apportionment the shares above are derived from —
    # kept unrounded so scenario-dependent physics (apply_country_buffer's
    # per-country ms_to_min rounding) reconstructs bit-identically from a
    # cached row. "UNK" (open water/ferry) is a key like any other.
    country_distance_m: dict[str, float] = field(default_factory=dict)
    country_driving_ms: dict[str, float] = field(default_factory=dict)

    @property
    def total_time_min(self) -> int:
        """Driving + dynamics + buffer time — matches Segment.total_time_min."""
        return self.driving_time_min + self.dynamics_time_min + self.buffer_time_min


# ---------------------------------------------------------------------------
# Country index
# ---------------------------------------------------------------------------


class CountryIndex:
    """
    Country border lookup used for HSR-avoidance areas and point-in-polygon
    country attribution of route geometry.

    Built once from DBDataLoader.get_country_geometries() — see
    api/helpers/dependencies.py — and injected into RailRouter rather than
    read from disk. input_params.countries is static reference data (not
    scenario-versioned), so this is a startup-time singleton like the
    DBDataLoader itself, not rebuilt per request.

    Keyed natively in ISO 3166-1 alpha-2 (country_code), matching every
    other country code in the codebase.

    The polygons include maritime zones (db/dev/seed.py: Marine Regions EEZ
    land union), so a leg midpoint in a strait or belt resolves to the
    country whose waters it crosses instead of falling through to "UNK".
    They are also two orders of magnitude denser than the land-only borders
    they replaced — ~178k vertices across 32 countries — which is what the
    R-tree and prepared geometries below are for: a linear contains() scan
    over that data costs ~60us per call, and _compute_country_intervals()
    calls lookup() once per routing interval.
    """

    def __init__(self, country_geometries: list[tuple[str, dict]]) -> None:
        from shapely.geometry import shape
        from shapely.prepared import prep
        from shapely.strtree import STRtree

        # Exploded into component polygons: a country's MultiPolygon has a
        # single envelope spanning every part, so the tree's prefilter is
        # far sharper per-polygon. Sorted by code so index order is stable,
        # which is what makes lookup() deterministic where polygons touch.
        self._codes: list[str] = []
        self._polygons: list = []
        for country_code, geometry in sorted(country_geometries):
            geom = shape(geometry)
            parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
            for polygon in parts:
                self._codes.append(country_code)
                self._polygons.append(polygon)
        self._prepared = [prep(polygon) for polygon in self._polygons]
        self._tree = STRtree(self._polygons)
        self._avoidance_rings: dict[str, list | None] = {}
        logger.info(
            "CountryIndex: loaded %d polygons across %d countries.",
            len(self._polygons),
            len(set(self._codes)),
        )

    def lookup(self, lon: float, lat: float) -> str | None:
        from shapely.geometry import Point

        point = Point(lon, lat)
        # Ascending index order is alphabetical country order, so the rare
        # point on a shared boundary always resolves the same way.
        for i in sorted(self._tree.query(point)):
            if self._prepared[i].contains(point):
                return self._codes[i]
        return None

    def get_largest_polygon(self, country_code: str) -> list | None:
        """Outer ring of the country's largest polygon, simplified, for
        GraphHopper's custom-model avoidance areas.

        Simplification is not optional here: raw rings reach ~20k vertices
        (Sweden), and this ring is serialized into every routing request
        that avoids HSR in some countries but not others. At
        HSR_AVOIDANCE_RING_SIMPLIFY_DEG the whole seeded set costs ~10k
        vertices total — an avoidance area only has to contain a rail
        network, not delimit sovereignty. Cached: the geometry never
        changes, and one trip can fire dozens of mini-reroutes.
        """
        if country_code not in self._avoidance_rings:
            self._avoidance_rings[country_code] = self._build_avoidance_ring(
                country_code
            )
        return self._avoidance_rings[country_code]

    def get_blocking_rings(self, country_code: str) -> list[list]:
        """EVERY component polygon's outer ring, simplified — for the
        BLOCKED_COUNTRIES exclusion, where get_largest_polygon() would be
        a hole: Russia's largest clipped polygon is the western mainland,
        and a block built from it alone leaves the Kaliningrad exclave —
        the one part of Russia a Poland–Lithuania route could actually cut
        through — wide open. Not cached: built once per process by
        RailRouter._blocked_country_rules(), which caches the result."""
        return [
            [
                list(coord)
                for coord in polygon.simplify(
                    HSR_AVOIDANCE_RING_SIMPLIFY_DEG, preserve_topology=True
                ).exterior.coords
            ]
            for polygon, code in zip(self._polygons, self._codes)
            if code == country_code
        ]

    def _build_avoidance_ring(self, country_code: str) -> list | None:
        polygons = [
            polygon
            for polygon, code in zip(self._polygons, self._codes)
            if code == country_code
        ]
        if not polygons:
            return None
        # By true area, not bounding box: an EEZ polygon's bbox is a poor
        # proxy once maritime zones stretch a country's envelope out to sea.
        largest = max(polygons, key=lambda polygon: polygon.area)
        ring = largest.simplify(
            HSR_AVOIDANCE_RING_SIMPLIFY_DEG, preserve_topology=True
        ).exterior
        return [list(coord) for coord in ring.coords]


class PassageIndex:
    """
    Crossing polygons for routing-time passage detection — which segment of
    a trip crosses which separately charged link (Storebælt, Øresund, the
    Channel Tunnel).

    Built once from DBDataLoader.get_passage_geometries() — see
    api/helpers/dependencies.py. Crossing GEOMETRY is static reference data
    (a tunnel does not move between scenarios), so like CountryIndex this
    is a startup-time singleton; the scenario-versioned CHARGES are
    resolved separately at evaluation time via
    DBDataLoader.build_all_passages().

    Two passage_ids may share one polygon — OERESUND_DK and OERESUND_SE,
    each infrastructure manager billing its half of one crossing. Both
    match, both are attributed.

    Only a handful of polygons exist, so a linear intersects() scan is
    cheaper than the R-tree CountryIndex needs for its ~178k vertices.
    """

    def __init__(self, passage_geometries: list[tuple[str, dict]]) -> None:
        from shapely.geometry import shape

        self._shapes = [(pid, shape(geom)) for pid, geom in passage_geometries]
        logger.info("PassageIndex: loaded %d passage polygons.", len(self._shapes))

    def intersecting(self, coords: list[list[float]]) -> list[str]:
        """passage_ids whose polygon this [lon, lat] path crosses."""
        if len(coords) < 2 or not self._shapes:
            return []
        from shapely.geometry import LineString

        line = LineString(coords)
        return [pid for pid, shp in self._shapes if shp.intersects(line)]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

VALID_ROUTING_MODES = frozenset({"simpleRouting", "fullRouting"})
"""Single source of truth for allowed routing_mode strings — read by both
the compute request validation (api/helpers/proposal_compute.py) and RailRouter.route()'s switch below.
Adding a mode means: add it to this set and add a branch in route()."""


class RailRoutingError(Exception):
    """Raised when the routing engine returns an error."""

    pass


# --- Routing graph naming contract -------------------------------------
#
# One OpenRailRouting instance per routing graph. Every per-graph setting
# is suffixed with the graph key, uppercased, so the default graph reads
# exactly like any other and no instance is implicitly "the" router:
#
#   OPENRAILROUTING_URL_<KEY>             backend registry entry
#   OPENRAILROUTING_HOST_PORT_<KEY>       published port
#   OPENRAILROUTING_ADMIN_HOST_PORT_<KEY> published admin port
#   GRAPH_CACHE_FILE_ID_<KEY>             Drive id of the prebuilt cache
#
# OPENRAILROUTING_CONTAINER_PORT is NOT suffixed: every instance binds the
# same port inside the stack, because they share one config.yml.
#
# Scenarios select their graph via scenario.scenarios.routing_graph_key;
# the key -> URL mapping is deployment configuration, never database
# content. See api/helpers/dependencies.py and this folder's README.
DEFAULT_ROUTING_GRAPH_KEY = "infra_2026"

ROUTING_URL_ENV_PREFIX = "OPENRAILROUTING_URL_"

_LOCAL_ROUTING_URL = "http://localhost:8989"


def routing_url_env_var(graph_key: str) -> str:
    """Environment variable holding the URL of one routing graph."""
    return f"{ROUTING_URL_ENV_PREFIX}{graph_key.upper()}"


def default_base_url() -> str:
    """URL of the DEFAULT routing graph, for callers that do no scenario
    resolution of their own — tests, host scripts, routing_context.py.

    Precedence: the default graph's own suffixed variable, then the
    unsuffixed OPENRAILROUTING_URL, then localhost. The unsuffixed name is
    kept solely as a compatibility path for the server stacks under
    deploy/, which set it and know nothing about graph keys; the dev stack
    and CI use the suffixed form.
    """
    return (
        os.environ.get(routing_url_env_var(DEFAULT_ROUTING_GRAPH_KEY))
        or os.environ.get("OPENRAILROUTING_URL")
        or _LOCAL_ROUTING_URL
    )


class RailRouter:
    """
    Wraps the OpenRailRouting (GraphHopper) instance.

    route() returns list[RoutedLeg] with physics-only data (no Stop
    objects, no energy values, no costs, no clock times). energy_kwh
    on all RoutedLegs is 0.0 on return — populated by
    calc_energy_consumption() in route_factory before Stop construction.
    """

    ROUTE_ENDPOINT = "/route"
    INFO_ENDPOINT = "/info"
    DETAILS = ["leg_distance", "leg_time", "time"]

    # requests.Session defaults to a connection pool of 10 — fine for the
    # normal one-call-per-trip case, but auto_stop_addition can fire dozens
    # of mini-reroutes concurrently (see timetable.py's
    # apply_auto_stop_addition()). A too-small pool doesn't error, it just
    # silently serializes calls beyond the limit, defeating the concurrency.
    _CONNECTION_POOL_SIZE = 64

    def __init__(
        self,
        country_index: CountryIndex,
        passage_index: PassageIndex | None = None,
        base_url: str | None = None,
        graph_key: str | None = None,
        segment_repository: "RouteSegmentRepository | None" = None,
    ) -> None:
        # Explicit base_url wins — the multi-graph registry
        # (api/helpers/dependencies.py) constructs one RailRouter per
        # routing graph in the same process, so the environment alone
        # cannot address them. Everything single-graph (tests,
        # routing_context.py, host scripts) keeps passing nothing and
        # lands on the default graph.
        self.base_url = (base_url or default_base_url()).rstrip("/")
        self.profile = os.environ.get("OPENRAILROUTING_PROFILE", "night_train")
        self.timeout = int(os.environ.get("OPENRAILROUTING_TIMEOUT", "30"))
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=self._CONNECTION_POOL_SIZE,
            pool_maxsize=self._CONNECTION_POOL_SIZE,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._country_index = country_index
        # Blocked-country rules+areas depend only on static geometry —
        # built once on first use, shared by every request (route(),
        # route_geometry(), all modes). None until built; may build to
        # ([], {}) if polygons are missing (warned, degrades to unblocked
        # — the country-coverage check in route_factory still 422s any
        # route that then leaks through, see BLOCKED_COUNTRIES).
        self._blocked_rules_cache: tuple[list, dict] | None = None
        # Optional so a router can be built before passage_charges is
        # seeded, and so tests that care only about geometry need not
        # supply one — legs then carry passages=() and evaluation charges
        # no crossings, which is the pre-0.9.21 behaviour.
        self._passage_index = passage_index
        # Segment cache: rows are keyed by graph, so a router only takes
        # part when it knows which graph it is (the registry passes the
        # key; single-graph callers — tests, host scripts — pass nothing
        # and route live). None repository = live routing, no lookups.
        self.graph_key = graph_key
        self._segment_repo = segment_repository if graph_key else None

    def profile_for_gauge(self, gauge_mm: int) -> str:
        """Routing profile name for a gauge — THE naming contract with
        docker/config.yml: the bare profile for standard gauge,
        <profile>_<gauge_mm> for everything else. gauge.py has already
        validated gauge_mm against SUPPORTED_GAUGES_MM."""
        if gauge_mm == STANDARD_GAUGE_MM:
            return self.profile
        return f"{self.profile}_{gauge_mm}"

    def _blocked_country_rules(self) -> tuple[list, dict]:
        """(speed_rules, areas) hard-excluding BLOCKED_COUNTRIES — cached.

        multiply_by 0, not the HSR 0.01: crossing Belarus or Russia is not
        expensive, it is off the table (project decision — see
        BLOCKED_COUNTRIES in models/route/model.py). Same ring machinery
        as HSR avoidance; a missing polygon warns loudly and skips, since
        an exception here would take every route down with it while the
        country-coverage check still catches an actual leak."""
        if self._blocked_rules_cache is not None:
            return self._blocked_rules_cache
        rules: list = []
        areas: dict = {}
        for cc in BLOCKED_COUNTRIES:
            # Every component polygon, not the largest: Russia's clipped
            # geometry is mainland + the Kaliningrad exclave, and the
            # exclave is the part a Poland–Lithuania route could cut
            # through. One area rule per component.
            rings = self._country_index.get_blocking_rings(cc)
            if not rings:
                logger.warning(
                    "No border polygon for blocked country '%s' — routes are "
                    "NOT hard-excluded from it (country coverage still 422s "
                    "any that pass through). Seed its geometry row.",
                    cc,
                )
                continue
            for index, ring in enumerate(rings):
                closed_ring = ring if ring[0] == ring[-1] else ring + [ring[0]]
                area_name = f"blocked{cc.lower()}{index}"
                areas[area_name] = {
                    "type": "Feature",
                    "id": area_name,
                    "properties": {},
                    "geometry": {"type": "Polygon", "coordinates": [closed_ring]},
                }
                rules.append({"if": f"in_{area_name}", "multiply_by": "0"})
        self._blocked_rules_cache = (rules, areas)
        return self._blocked_rules_cache

    def check_server(self) -> dict:
        resp = self._session.get(
            f"{self.base_url}{self.INFO_ENDPOINT}", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def route_geometry(self, stops: list[StopInput]) -> list[list[float]]:
        """
        Return only the routed shape between `stops` as [[lon, lat], ...].

        A deliberately narrow entry point for callers that need a line on a
        map and nothing else — the ONTD route_summaries projection
        (adapters/proposal/README.md §5.5, decision 25). route() cannot serve that
        case: its per-leg physics needs a Composition and a
        TrackInfraCollection to apportion country buffer quotas, and
        existing trains are never evaluated (decision 23), so there is no
        composition to speak of and nothing would consume the result.

        Single-pass, no speed cap, no HSR avoidance, no traction dynamics
        — the shape is the shape. Two things do apply, as everywhere:
        the gauge profile (resolved from the stops alone; ONTD's synthetic
        stops carry no gauges, so they resolve standard — broad-gauge ONTD
        lines keep failing to snap until the projection routes on catalog
        stops) and the BLOCKED_COUNTRIES exclusion, which forces this off
        CH and onto LM routing (a request custom model disables CH).
        """
        if len(stops) < 2:
            raise ValueError("At least 2 stops are required.")
        profile = self.profile_for_gauge(resolve_trip_gauge(s.stop for s in stops))
        raw = self._post_route(
            self._build_payload(stops, self.build_custom_model(None, None), profile)
        )
        paths = raw.get("paths") or []
        if not paths:
            raise ValueError("Router returned no path.")
        return paths[0]["points"]["coordinates"]

    def route(
        self,
        stops: list[StopInput],
        max_speed_kmh: int | None,
        avoid_hsr: dict[str, bool] | None,
        gauge_mm: int,
        routing_mode: str,
    ) -> list[RoutedLeg]:
        """
        Layer 1 — route a trip and return RAW segment physics. Callers
        wanting domain physics (buffer quotas, traction dynamics) use
        route_trip() below; nothing scenario-dependent happens here, which
        is what keeps cached segments scenario-free.

        max_speed_kmh — hard cap for the custom model (the composition's own
        max_speed_kmh; GraphHopper takes the minimum of this cap and each
        track's permitted speed, so 300-track under a 230 cap routes at
        230). None = no cap.
        avoid_hsr — resolved per-country vector: True where high-speed track
        must be penalized (caller already ANDed composition and track
        permission — resolve_routing_params()). Ignored in simpleRouting.
        gauge_mm — the trip gauge (routing/gauge.py, resolved by layer 2
        from the call's own stops) → GraphHopper profile.

        routing_mode (no default here — defaulting is an API-boundary
        concern, see api/helpers/proposal_compute.py):
          "fullRouting"   — speed cap + HSR avoidance; two-pass when
                             live-routed (pass 1: CH snap on the gauge
                             profile, pass 2: custom model on snapped
                             coordinates).
          "simpleRouting" — speed cap only (the BLOCKED_COUNTRIES rules
                             ride on every model, so the cap is free),
                             single pass. Cheap, for manual checks — not
                             representative of real physics.

        Both modes are served through the segment cache when a repository
        is attached: lookup per consecutive stop pair, live two-point
        routing for misses, store-back. A trip's variant key differs per
        mode only through the model (no HSR priority rules in
        simpleRouting), so the two never collide unless they would route
        identically anyway.

        buffer_time_min, dynamics_time_min are 0 and energy_kwh is 0.0 on
        every returned leg — see route_trip().
        """
        if len(stops) < 2:
            raise ValueError("At least 2 stops are required.")

        profile = self.profile_for_gauge(gauge_mm)

        # routing_mode SWITCH — VALID_ROUTING_MODES is the same set the
        # compute request validation (api/helpers/proposal_compute.py)
        # checks against, so an unknown mode can only reach here if that
        # validation was bypassed.
        if routing_mode == "simpleRouting":
            custom_model = self.build_custom_model(max_speed_kmh, None)
            two_pass = False
        elif routing_mode == "fullRouting":
            custom_model = self.build_custom_model(max_speed_kmh, avoid_hsr)
            two_pass = True
        else:
            raise ValueError(
                f"Unknown routing_mode '{routing_mode}'. "
                f"Supported: {sorted(VALID_ROUTING_MODES)}."
            )

        if self._segment_repo is not None:
            return self._route_via_segment_cache(stops, custom_model, profile, two_pass)
        return self._route_live(stops, custom_model, profile, two_pass)

    def _route_live(
        self,
        stops: list[StopInput],
        custom_model: dict | None,
        profile: str,
        two_pass: bool,
    ) -> list[RoutedLeg]:
        """One multi-point call — the uncached path (and the per-pair
        fallback of the cached one)."""
        if two_pass and custom_model:
            # Pass 1 snaps on the SAME gauge profile as pass 2 — that is
            # what makes snapping gauge-correct (a dual-gauge station's
            # 1435 platform vs its 1520 platform). Plain CH, no custom
            # model: snapping is per-point nearest-edge, and the path
            # between snapped points is discarded, so the blocked-country
            # rules add nothing here but would cost the CH speedup.
            snap_raw = self._post_route(self._build_payload(stops, None, profile))
            snapped_coords = snap_raw["paths"][0]["snapped_waypoints"]["coordinates"]
            raw = self._post_route(
                self._build_payload(
                    stops, custom_model, profile, override_coords=snapped_coords
                )
            )
        else:
            raw = self._post_route(self._build_payload(stops, custom_model, profile))
        return self._parse_response(raw, len(stops))

    def _route_via_segment_cache(
        self,
        stops: list[StopInput],
        custom_model: dict | None,
        profile: str,
        two_pass: bool,
    ) -> list[RoutedLeg]:
        """
        Lookup-first per consecutive pair for this router's graph;
        live-route misses pairwise (identical path to _route_live) and
        store them back, so the table grows with every request. Passage
        claiming replicates _parse_legs' cross-leg first-leg-wins dedupe:
        cached rows store each pair's FULL intersecting list, the claim
        happens here at assembly.
        """
        from models.route.routing.segment_cache import (
            leg_from_cached,
            segment_from_leg,
        )

        variant_key = route_variant_key(profile, custom_model)
        pair_ids = [
            (stops[i].stop.stop_id, stops[i + 1].stop.stop_id)
            for i in range(len(stops) - 1)
        ]
        keys = {tuple(sorted(p)) for p in pair_ids}
        rows = self._segment_repo.fetch_many(self.graph_key, variant_key, keys)

        legs: list[RoutedLeg] = []
        claimed: set[str] = set()
        n_hits = 0
        for i, (a, b) in enumerate(pair_ids):
            lo, hi = sorted((a, b))
            row = rows.get((lo, hi))
            if row is not None:
                leg = leg_from_cached(row, reverse=(a != lo))
                n_hits += 1
            else:
                leg = self._route_live(
                    [stops[i], stops[i + 1]], custom_model, profile, two_pass
                )[0]
                self._segment_repo.store(
                    self.graph_key,
                    variant_key,
                    lo,
                    hi,
                    segment_from_leg(leg, reverse=(a != lo)),
                    source="runtime",
                )
            leg.passages = [p for p in leg.passages if p not in claimed]
            claimed.update(leg.passages)
            legs.append(leg)

        logger.info(
            "segment cache [%s]: %d/%d pair(s) served, %d routed+stored (%s).",
            self.graph_key,
            n_hits,
            len(pair_ids),
            len(pair_ids) - n_hits,
            variant_key,
        )
        return legs

    # -- precompute-script surface -----------------------------------------

    def snap_point(
        self, lon: float, lat: float, helper_lonlat: list[float], profile: str
    ) -> list[float]:
        """The rail-network point [lon, lat] snaps to on this graph and
        profile — obtained from a plain CH route toward any second
        reachable point (GraphHopper has no standalone snap endpoint in
        this build). Snapping is per-point and deterministic given
        (graph, profile), which is what lets the precompute script snap
        each stop ONCE per profile instead of re-snapping in every pair's
        pass 1."""
        payload = {
            "profile": profile,
            "points": [[lon, lat], helper_lonlat],
            "points_encoded": False,
            "instructions": False,
        }
        raw = self._post_route(payload)
        return raw["paths"][0]["snapped_waypoints"]["coordinates"][0]

    def route_pair_from_snapped(
        self,
        snapped_pair: list[list[float]],
        custom_model: dict | None,
        profile: str,
    ) -> RoutedLeg:
        """One pair, pass 2 only — the precompute script's entry. Same
        payload/parse path as the runtime fallback, minus pass 1 (the
        script pre-snapped both stops via snap_point()), which halves the
        batch's call count."""
        payload = self._build_payload_from_coords(snapped_pair, custom_model, profile)
        return self._parse_response(self._post_route(payload), n_stops=2)[0]

    def build_custom_model(
        self,
        vehicle_max_speed_kmh: int | None,
        avoid_high_speed_lines: dict[str, bool] | None,
    ) -> dict | None:
        """
        GraphHopper custom model for a routing pass, or None only when
        nothing needs one at all — which since 0.9.27 requires the
        BLOCKED_COUNTRIES polygons to be missing too, as their speed-0
        area rules are folded into every model built here (route(),
        both modes, and route_geometry() all pass through this).

        Three independent concerns:
          blocked  — BLOCKED_COUNTRIES exclusion (_blocked_country_rules):
                     hard speed-0 over each blocked country's polygon,
                     every mode, non-negotiable.
          speed    — hard cap at the composition's own max_speed_kmh on
                     every segment (how fast THIS train may go, everywhere).
          priority — HSR avoidance: a segment is penalized by
                     HSR_AVOIDANCE_PRIORITY_FACTOR iff its PERMITTED track
                     speed (max_speed encoded value, from OSM maxspeed —
                     already in graph.encoded_values, see docker/config.yml)
                     lies in (HSR_TRACK_SPEED_THRESHOLD_KMH,
                     HSR_TRACK_SPEED_SANITY_MAX_KMH) AND HSR is not allowed
                     there. Only high-speed track is penalized — never a
                     country's conventional network (that was the pre-0.9.6
                     routing error, see CHANGELOG). The upper bound guards
                     against GraphHopper's missing-maxspeed sentinel (0 or
                     infinity depending on version — the two-sided range
                     excludes both), so untagged track is never mistaken
                     for high-speed infrastructure.

        Where the priority rule applies:
          - Every country disallows (composition-level ban, or e.g. the
            2032 Base Line where track_hsr_allowed=False everywhere) —
            ONE global rule, no area polygons at all: far smaller payload
            and inherently covers any country missing a border polygon.
          - Mixed permissions — one rule per disallowing country, scoped
            to that country's border polygon (in_<area> && speed range).
        """
        blocked_rules, blocked_areas = self._blocked_country_rules()
        speed_rules, priority_rules, areas = (
            list(blocked_rules),
            [],
            dict(blocked_areas),
        )

        if vehicle_max_speed_kmh is not None:
            speed_rules.append({"if": "true", "limit_to": str(vehicle_max_speed_kmh)})

        hsr_condition = (
            f"max_speed > {HSR_TRACK_SPEED_THRESHOLD_KMH} "
            f"&& max_speed < {HSR_TRACK_SPEED_SANITY_MAX_KMH}"
        )
        if avoid_high_speed_lines:
            disallowing = sorted(
                cc for cc, avoid in avoid_high_speed_lines.items() if avoid
            )
            if disallowing and len(disallowing) == len(avoid_high_speed_lines):
                priority_rules.append(
                    {
                        "if": hsr_condition,
                        "multiply_by": str(HSR_AVOIDANCE_PRIORITY_FACTOR),
                    }
                )
            else:
                for cc in disallowing:
                    ring = self._country_index.get_largest_polygon(cc)
                    if ring is None:
                        logger.warning(
                            "No polygon for '%s' — skipping HSR avoidance.", cc
                        )
                        continue
                    closed_ring = ring if ring[0] == ring[-1] else ring + [ring[0]]
                    area_name = f"hsr{cc.lower()}"
                    areas[area_name] = {
                        "type": "Feature",
                        "id": area_name,
                        "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": [closed_ring]},
                    }
                    priority_rules.append(
                        {
                            "if": f"in_{area_name} && {hsr_condition}",
                            "multiply_by": str(HSR_AVOIDANCE_PRIORITY_FACTOR),
                        }
                    )

        if not speed_rules and not priority_rules:
            return None

        cm: dict = {}
        if speed_rules:
            cm["speed"] = speed_rules
        if priority_rules:
            cm["priority"] = priority_rules
        if areas:
            cm["areas"] = {
                "type": "FeatureCollection",
                "features": list(areas.values()),
            }
        return cm

    def _build_payload(
        self,
        stops: list[StopInput],
        custom_model: dict | None,
        profile: str,
        override_coords: list[list[float]] | None = None,
    ) -> dict:
        """
        custom_model: prebuilt by build_custom_model() (or None for a plain
        CH pass) — passed in rather than rebuilt here, so route() builds it
        exactly once per call.
        profile: the gauge profile from _profile_for_gauge() — always passed
        explicitly (never defaulted to self.profile) so a call site cannot
        silently route a broad-gauge trip on the standard-gauge graph.
        override_coords: snapped [lon, lat] pairs from pass 1, used in place
        of the original stop coordinates for pass 2 of two-pass routing.
        """
        points = (
            override_coords
            if override_coords is not None
            else [[s.stop.lon, s.stop.lat] for s in stops]
        )
        payload: dict = {
            "profile": profile,
            "points": points,
            "points_encoded": False,
            "instructions": False,
            "details": self.DETAILS,
        }
        if custom_model:
            payload["custom_model"] = custom_model
            payload["ch.disable"] = True
        return payload

    def _build_payload_from_coords(
        self, coords: list[list[float]], custom_model: dict | None, profile: str
    ) -> dict:
        """_build_payload for callers holding bare [lon, lat] pairs (the
        precompute script's pre-snapped stops) instead of StopInputs."""
        payload: dict = {
            "profile": profile,
            "points": coords,
            "points_encoded": False,
            "instructions": False,
            "details": self.DETAILS,
        }
        if custom_model:
            payload["custom_model"] = custom_model
            payload["ch.disable"] = True
        return payload

    def _post_route(self, payload: dict) -> dict:
        resp = self._session.post(
            f"{self.base_url}{self.ROUTE_ENDPOINT}", json=payload, timeout=self.timeout
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            try:
                msg = resp.json().get("message", resp.text)
            except ValueError:  # body not JSON — proxies, timeouts
                msg = resp.text
            raise RailRoutingError(
                f"Routing engine HTTP {resp.status_code}: {msg}"
            ) from exc
        body = resp.json()
        if "message" in body and "paths" not in body:
            raise RailRoutingError(f"Routing engine error: {body['message']}")
        return body

    def _parse_response(self, body: dict, n_stops: int) -> list[RoutedLeg]:
        path_data = body["paths"][0]
        coords = path_data["points"]["coordinates"]

        details = path_data.get("details", {})
        leg_distance_detail = details.get("leg_distance", [])
        time_detail = details.get("time", [])

        intervals = self._compute_country_intervals(coords, time_detail)
        return self._parse_legs(n_stops, coords, leg_distance_detail, intervals)

    def _parse_legs(
        self,
        n_stops: int,
        coords: list[list[float]],
        leg_distance_detail: list,
        intervals: list[tuple],
    ) -> list[RoutedLeg]:
        """
        Build one RoutedLeg per consecutive stop pair.

        For each leg, intervals overlapping the leg's coordinate range are
        apportioned by overlap fraction, summed per country into the raw
        country_distance_m / country_driving_ms dicts, then converted to
        country_distance_shares / country_time_shares (each summing to 1.0)
        alongside the leg's total distance_m / driving_time_min.
        buffer_time_min stays 0 — scenario-dependent, applied by
        route_trip() via apply_country_buffer().

        countries additionally records the order the legs entered them, which
        the share dicts cannot express and track access charges need (see
        Segment). Passages are attributed here too: a crossing is claimed by
        the FIRST leg intersecting it, so one split by an intermediate stop
        is charged once per trip rather than by every leg touching it.
        """
        legs: list[RoutedLeg] = []
        claimed_passages: set[str] = set()

        for i in range(n_stops - 1):
            if i < len(leg_distance_detail):
                from_idx = leg_distance_detail[i][0]
                to_idx = leg_distance_detail[i][1]
            else:
                from_idx, to_idx = 0, len(coords) - 1
                logger.warning("leg_distance detail missing for segment %d.", i)

            leg_cc_dist: dict[str, float] = defaultdict(float)
            leg_cc_dur_ms: dict[str, float] = defaultdict(float)
            leg_countries: list[str] = []

            for iv_from, iv_to, cc, dist_m, iv_ms in intervals:
                overlap_from = max(iv_from, from_idx)
                overlap_to = min(iv_to, to_idx)
                if overlap_from >= overlap_to:
                    continue
                span = iv_to - iv_from
                fraction = (overlap_to - overlap_from) / span if span > 0 else 1.0
                leg_cc_dist[cc] += dist_m * fraction
                leg_cc_dur_ms[cc] += iv_ms * fraction
                # Intervals arrive in path order, so first-seen is
                # entry order. A country re-entered after a detour
                # through a neighbour keeps its first position: its
                # shares are summed into one entry either way, and one
                # clock window per country is what pricing needs.
                if cc not in leg_countries:
                    leg_countries.append(cc)

            total_dist_m = sum(leg_cc_dist.values())
            total_dur_ms = sum(leg_cc_dur_ms.values())

            country_distance_shares: dict[str, float] = {}
            country_time_shares: dict[str, float] = {}

            for cc, dist_m_f in leg_cc_dist.items():
                country_distance_shares[cc] = (
                    dist_m_f / total_dist_m if total_dist_m > 0 else 0.0
                )
                country_time_shares[cc] = (
                    leg_cc_dur_ms[cc] / total_dur_ms if total_dur_ms > 0 else 0.0
                )

            leg_geometry = coords[from_idx : to_idx + 1]
            leg_passages: list[str] = []
            if self._passage_index is not None:
                leg_passages = [
                    pid
                    for pid in self._passage_index.intersecting(leg_geometry)
                    if pid not in claimed_passages
                ]
                claimed_passages.update(leg_passages)

            legs.append(
                RoutedLeg(
                    geometry=leg_geometry,
                    distance_m=round(total_dist_m),
                    driving_time_min=ms_to_min(total_dur_ms),
                    dynamics_time_min=0,  # filled by apply_traction_dynamics()
                    buffer_time_min=0,  # filled by apply_country_buffer()
                    energy_kwh=0.0,  # populated by calc_energy_consumption()
                    country_distance_shares=country_distance_shares,
                    country_time_shares=country_time_shares,
                    countries=leg_countries,
                    passages=leg_passages,
                    country_distance_m=dict(leg_cc_dist),
                    country_driving_ms=dict(leg_cc_dur_ms),
                )
            )

        return legs

    def _compute_country_intervals(
        self,
        coords: list[list[float]],
        time_detail: list,
    ) -> list[tuple[int, int, str, float, int]]:
        """Single shapely pass → (from_idx, to_idx, cc, dist_m, dur_ms)."""
        intervals = []
        for entry in time_detail:
            from_idx, to_idx, iv_ms = entry[0], entry[1], entry[2]
            segment = coords[from_idx : to_idx + 1]
            dist_m = haversine_path_m(segment)
            mid_idx = (from_idx + to_idx) // 2
            cc = (
                self._country_index.lookup(coords[mid_idx][0], coords[mid_idx][1])
                or "UNK"
            )
            intervals.append((from_idx, to_idx, cc, dist_m, iv_ms))
        return intervals


# ---------------------------------------------------------------------------
# Segment-cache variant key
# ---------------------------------------------------------------------------


def route_variant_key(profile: str, custom_model: dict | None) -> str:
    """
    Stable key for one routing-geometry variant on a graph: the gauge
    profile plus a hash of the RESOLVED custom model — the two things
    (and the only two things) that shape what GraphHopper returns for a
    stop pair on a given graph.

    Keyed on the resolved model, never on a composition id, deliberately:
    if a scenario ever carries mixed per-country hsr_allowed,
    build_custom_model() switches to per-country area rings, the hash
    differs, the lookup misses, and the request degrades to live routing
    — degraded, never wrong. The BLOCKED_COUNTRIES areas ride on every
    model and so on every key: a border-polygon reseed changes the hash,
    which is correct — the routes would change too.

    NOT in the key, by design: ROUTE_BUILDER_VERSION (cached rows are raw
    physics — dynamics, buffers, energy, TAC are all applied downstream),
    ms_to_min rounding (driving_time_min is re-derived from the raw ms at
    read time), scenario ids (buffer quotas are recomputed per request).
    Only a routing-graph re-import stales rows, handled per graph by
    RouteSegmentRepository.sync_graph_import().
    """
    canonical = json.dumps(custom_model, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{profile}-{digest}"


# ---------------------------------------------------------------------------
# Layer 2 — the shared domain entry
# ---------------------------------------------------------------------------


def resolve_routing_params(
    composition: Composition,
    tracks: TrackInfraCollection,
    stops: list[StopInput],
) -> tuple[int, dict[str, bool], int]:
    """
    (max_speed_kmh, avoid_hsr, gauge_mm) for layer 1 from the domain pair
    and the call's own stops.

    Gauge first — resolved from THIS call's stops, so every entry point
    (trips, auto-stop mini-reroutes with a candidate spliced in) gets the
    right profile without threading a value through; an impossible pairing
    raises GaugeMismatchError here, before any HTTP — a domain answer, not
    a snap error.

    avoid_hsr is evaluated over the FULL track collection (complete over
    every country, see TrackInfraCollection), not just countries with a
    stop on the trip: a route can transit a country without stopping in
    it, and that country's hsr_allowed must still bind. What "avoid" means
    per segment (permitted track speed above HSR_TRACK_SPEED_THRESHOLD_KMH,
    not the whole country network) is build_custom_model()'s concern.

    Single derivation source: route_trip() below and
    scripts/precompute_route_segments.py's variant enumeration both use
    this, so a precomputed variant and a runtime request can never resolve
    the same composition/tracks/stops differently.
    """
    gauge_mm = resolve_trip_gauge((s.stop for s in stops), composition)
    avoid_hsr = {
        cc: not (composition.hsr_allowed and track.hsr_allowed)
        for cc, track in tracks.all().items()
    }
    return int(composition.max_speed_kmh), avoid_hsr, gauge_mm


def apply_country_buffer(legs: list[RoutedLeg], tracks: TrackInfraCollection) -> None:
    """
    Fill RoutedLeg.buffer_time_min in-place with the country buffer quota
    on raw driving time — per country, from the leg's unrounded
    country_driving_ms, with per-country ms_to_min rounding (the exact
    math _parse_legs applied before the segment cache moved buffer out of
    the router). Scenario-dependent (buffer_quota_per is a pinned track
    parameter), hence layer 2. "UNK" (open water/ferry) has no track row
    and contributes no buffer, as before. Overwrites, so re-applying
    against a different scenario is safe.
    """
    for leg in legs:
        buffer_min = 0
        for cc, dur_ms in leg.country_driving_ms.items():
            track = tracks.get(cc)
            if track is None:
                continue
            buffer_min += round(ms_to_min(dur_ms) * track.buffer_quota_per)
        leg.buffer_time_min = buffer_min


def route_trip(
    router: RailRouter,
    stops: list[StopInput],
    composition: Composition,
    tracks: TrackInfraCollection,
    routing_mode: str,
) -> list[RoutedLeg]:
    """
    Layer 2 — the entry every trip-routing call site uses
    (route_factory._build_trip(), timetable.py's candidate mini-reroutes
    and final reroute, adapters/routing_context.py). Resolves layer-1
    inputs from the domain pair, routes (cache-served or live,
    transparently), then applies the scenario-dependent physics:

      1. apply_country_buffer() — quota on raw driving time
      2. apply_traction_dynamics() (fullRouting only) — per-stop
         accel/brake time loss, plus its own buffer share, strictly AFTER
         the cruise speed was derived from raw driving time

    This is the single call site for dynamics — nobody calls layer 1
    directly except the cache machinery and the precompute script, so
    every consumer keeps consistent physics.
    """
    max_speed_kmh, avoid_hsr, gauge_mm = resolve_routing_params(
        composition, tracks, stops
    )
    legs = router.route(stops, max_speed_kmh, avoid_hsr, gauge_mm, routing_mode)
    apply_country_buffer(legs, tracks)
    if routing_mode == "fullRouting":
        apply_traction_dynamics(legs, composition, tracks)
    return legs
