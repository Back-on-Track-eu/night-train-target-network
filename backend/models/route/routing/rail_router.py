"""
rail_router.py
==============
Wrapper around the local OpenRailRouting (GraphHopper) instance.

Unit conventions (internal)
----------------------------
  Distance : metres  (_m)   — GraphHopper native
  Duration : minutes (_min) — converted from GraphHopper milliseconds on parse

Responsibilities
----------------
- HTTP communication with GraphHopper (two-pass routing for custom models).
- Country attribution of route geometry via shapely point-in-polygon.
- Physics per segment: distance_m, driving_time_min, buffer_time_min,
  country_distance_shares, country_time_shares.
- Gauge-aware profile selection: each call resolves ONE track gauge from
  its stops (routing/gauge.py) and routes on that gauge's own GraphHopper
  profile — night_train for 1435, night_train_<mm> otherwise (naming
  contract: SUPPORTED_GAUGES_MM in models/route/model.py ←→
  docker/config.yml). Baked per-profile so stop SNAPPING is gauge-correct.
- Belarus/Russia exclusion (BLOCKED_COUNTRIES): a speed-0 area rule over
  each blocked country's border polygon, attached to EVERY routing request
  in every mode — the fork registers no `country` encoded value, so the
  block cannot live in the graph (see docker/config.yml).
- fullRouting custom model: composition speed cap + HSR avoidance — only
  track whose permitted speed exceeds HSR_TRACK_SPEED_THRESHOLD_KMH is
  penalized, and only where hsr_allowed (composition AND country) is
  false. Thresholds/factor live in models/route/version.py (STANDARD
  VALUES); mechanism in _build_custom_model()'s docstring.
- fullRouting traction dynamics: each leg's dynamics_time_min is filled
  with the per-stop accel/brake time loss (routing/dynamics.py), kept
  separate from the raw router driving_time_min so the two stay
  differentiable — applied here so every consumer of route() gets
  consistent physics.

NOT responsible for:
- Stop timetable data  (→ models/route/route_factory.py — Stop is built there)
- Energy consumption   (→ models/energy/calc_energy_consumption.py)
- TAC / energy costs   (→ models/evaluation/calc.py)

route() returns list[RoutedLeg] — bare segment physics with no Stop
attached. route_factory._build_trip_stops_and_legs() pairs each RoutedLeg with the
Stop objects it builds, producing the final list[Segment].

Public surface
--------------
  RailRouter.route(stops, composition, tracks, routing_mode) → list[RoutedLeg]
  RailRoutingError
  RoutedLeg  (output type — public)
  StopInput  (input type — public; wraps StopInfrastructure + StopType)
  VALID_ROUTING_MODES  (single source of truth for allowed routing_mode
    strings — the routing_mode switch lives in RailRouter.route() below,
    so its registry lives here too, mirroring VALID_TIMETABLE_MODES /
    VALID_SCHEDULE_MODES in models/route/timetable.py; the compute
    request validation in api/helpers/proposal_compute.py reads from it)
  build_router_stops(stop_ids, stop_infra) → list[StopInput]  (shared stop_id
    → StopInput conversion — used by route_factory.py and timetable.py's
    auto_stop_addition trial re-routes)
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field

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
    (filled for routing_mode="fullRouting" — see routing/dynamics.py) so
    the two stay differentiable downstream. buffer_time_min carries the
    country buffer quota applied to driving (at parse time) and to
    dynamics (added afterwards by apply_traction_dynamics — computed
    strictly AFTER the dynamics' cruise speed was derived from raw
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

    def _profile_for_gauge(self, gauge_mm: int) -> str:
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
        profile = self._profile_for_gauge(resolve_trip_gauge(s.stop for s in stops))
        raw = self._post_route(
            self._build_payload(stops, self._build_custom_model(None, None), profile)
        )
        paths = raw.get("paths") or []
        if not paths:
            raise ValueError("Router returned no path.")
        return paths[0]["points"]["coordinates"]

    def route(
        self,
        stops: list[StopInput],
        composition: Composition,
        tracks: TrackInfraCollection,
        routing_mode: str,
    ) -> list[RoutedLeg]:
        """
        Route a trip and return bare segment physics.

        routing_mode (no default here — defaulting is an API-boundary
        concern, see api/helpers/proposal_compute.py; every caller passes it explicitly):
          "fullRouting"   — speed capped at the composition's own
                             max_speed_kmh everywhere, plus HSR avoidance:
                             track segments whose PERMITTED speed exceeds
                             HSR_TRACK_SPEED_THRESHOLD_KMH (see
                             models/route/version.py) are heavily
                             penalized in every country where HSR is not
                             allowed (composition.hsr_allowed AND that
                             country's track hsr_allowed — evaluated for
                             every country, transited-only ones included).
                             Each returned leg also carries the per-stop
                             traction dynamics surcharge (accel/brake
                             time loss) in its own dynamics_time_min
                             field (see routing/dynamics.py). Two-pass routing
                             when a custom model is needed. See
                             _build_custom_model().
          "simpleRouting" — bypass all of that: single-pass, no speed cap,
                             no HSR avoidance, no traction dynamics.
                             Cheap/fast, for quick manual checks — not
                             representative of real physics.

        Two-pass routing is used when a custom model is needed:
          pass 1 — CH routing to snap stops to the rail network
          pass 2 — custom model routing with snapped coordinates

        energy_kwh on all RoutedLegs is 0.0 on return — populated by
        calc_energy_consumption() in route_factory.
        """
        if len(stops) < 2:
            raise ValueError("At least 2 stops are required.")

        # Gauge first — resolved from THIS call's own stops, so every
        # entry point (trips, auto-stop mini-reroutes with a candidate
        # spliced in) gets the right profile without threading a value
        # through. An impossible pairing raises GaugeMismatchError here,
        # before any HTTP — a domain answer, not a snap error.
        gauge_mm = resolve_trip_gauge((s.stop for s in stops), composition)
        profile = self._profile_for_gauge(gauge_mm)

        # routing_mode SWITCH — VALID_ROUTING_MODES is the same set
        # the compute request validation (api/helpers/proposal_compute.py) checks against, so an unknown mode
        # can only reach here if that validation was bypassed.
        if routing_mode == "simpleRouting":
            # No HSR avoidance and no traction dynamics, but since 0.9.27
            # not custom-model-free either: the BLOCKED_COUNTRIES rules
            # ride on every request, and with the model already attached
            # the composition speed cap is free — so simpleRouting times
            # are capped at max_speed_kmh like fullRouting instead of the
            # graph's 230 ceiling. Single-pass LM (custom model disables
            # CH); still no snap pass, no HSR, no dynamics.
            simple_model = self._build_custom_model(
                int(composition.max_speed_kmh), None
            )
            raw = self._post_route(self._build_payload(stops, simple_model, profile))
            return self._parse_response(raw, stops, tracks)
        if routing_mode != "fullRouting":
            raise ValueError(
                f"Unknown routing_mode '{routing_mode}'. "
                f"Supported: {sorted(VALID_ROUTING_MODES)}."
            )

        vehicle_max_speed_kmh = int(composition.max_speed_kmh)
        # HSR permission per country: high-speed line access in a country is
        # allowed only when BOTH the composition and that country's track
        # infrastructure say hsr_allowed — evaluated over the FULL track
        # collection (complete over every country, see TrackInfraCollection),
        # not just countries with a stop on this trip: a route can transit a
        # country without stopping in it, and that country's hsr_allowed
        # must still bind. What "avoid" means per segment (permitted track
        # speed above HSR_TRACK_SPEED_THRESHOLD_KMH, not the whole country
        # network) is _build_custom_model()'s concern below.
        avoid_hsr = {
            cc: not (composition.hsr_allowed and track.hsr_allowed)
            for cc, track in tracks.all().items()
        }
        custom_model = self._build_custom_model(vehicle_max_speed_kmh, avoid_hsr)

        if custom_model:
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
                    stops,
                    custom_model,
                    profile,
                    override_coords=snapped_coords,
                )
            )
        else:
            raw = self._post_route(self._build_payload(stops, None, profile))

        legs = self._parse_response(raw, stops, tracks)
        # Traction dynamics (fullRouting only): GraphHopper has no vehicle
        # model, so parsed driving times assume the train passes every stop
        # at cruise speed. Fill each leg's dynamics_time_min with its
        # accel/brake time loss here — the single call site every consumer
        # shares (trips, auto-stop candidate mini-reroutes, final reroutes)
        # — rather than in route_factory, which would leave timetable.py's
        # reroutes without it. driving_time_min stays raw router time;
        # the dynamics' own buffer share (same country quota) is added to
        # buffer_time_min there too, strictly after the cruise speed was
        # derived from raw driving time. See routing/dynamics.py.
        apply_traction_dynamics(legs, composition, tracks)
        return legs

    def _build_custom_model(
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
        custom_model: prebuilt by _build_custom_model() (or None for a plain
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

    def _parse_response(
        self,
        body: dict,
        stops: list[StopInput],
        tracks: TrackInfraCollection,
    ) -> list[RoutedLeg]:
        path_data = body["paths"][0]
        coords = path_data["points"]["coordinates"]

        details = path_data.get("details", {})
        leg_distance_detail = details.get("leg_distance", [])
        time_detail = details.get("time", [])

        intervals = self._compute_country_intervals(coords, time_detail)
        return self._parse_legs(
            len(stops), coords, leg_distance_detail, intervals, tracks
        )

    def _parse_legs(
        self,
        n_stops: int,
        coords: list[list[float]],
        leg_distance_detail: list,
        intervals: list[tuple],
        tracks: TrackInfraCollection,
    ) -> list[RoutedLeg]:
        """
        Build one RoutedLeg per consecutive stop pair.

        For each leg, intervals overlapping the leg's coordinate range are
        apportioned by overlap fraction, summed per country, then converted
        to country_distance_shares / country_time_shares (each summing to 1.0)
        alongside the leg's total distance_m / driving_time_min / buffer_time_min.

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
            total_buffer_min = 0

            for cc, dist_m_f in leg_cc_dist.items():
                country_distance_shares[cc] = (
                    dist_m_f / total_dist_m if total_dist_m > 0 else 0.0
                )
                country_time_shares[cc] = (
                    leg_cc_dur_ms[cc] / total_dur_ms if total_dur_ms > 0 else 0.0
                )
                cc_drive_min = ms_to_min(leg_cc_dur_ms[cc])
                track = tracks.get(cc)
                if track is None:
                    continue  # "UNK" (open water/ferry) — no country, no buffer time
                total_buffer_min += round(cc_drive_min * track.buffer_quota_per)

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
                    buffer_time_min=total_buffer_min,
                    energy_kwh=0.0,  # populated by calc_energy_consumption()
                    country_distance_shares=country_distance_shares,
                    country_time_shares=country_time_shares,
                    countries=leg_countries,
                    passages=leg_passages,
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
