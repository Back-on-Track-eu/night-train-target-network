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
    VALID_SCHEDULE_MODES in models/route/timetable.py; api/route.py's
    request validation reads from it)
  build_router_stops(stop_ids, stop_infra) → list[StopInput]  (shared stop_id
    → StopInput conversion — used by route_factory.py and timetable.py's
    auto_stop_addition trial re-routes)
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass

import requests

from models.params import (
    Composition,
    TrackInfraCollection,
    StopInfrastructure,
    StopInfraCollection,
)
from models.route.trip import StopType
from models.route.routing.dynamics import apply_traction_dynamics
from models.route.version import (
    HSR_TRACK_SPEED_THRESHOLD_KMH,
    HSR_TRACK_SPEED_SANITY_MAX_KMH,
    HSR_AVOIDANCE_PRIORITY_FACTOR,
)
from models.utils import ms_to_min, haversine_path_m, bbox_area

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

    Single call site for this conversion — route_factory.py (initial routing,
    adjust_route()) and timetable.py (auto_stop_addition's trial re-routes)
    both use this rather than each building StopInput lists themselves.
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
    other country code in the codebase — no ISO3 conversion needed, unlike
    the old geojson-file version which was keyed by Natural Earth's
    ADM0_A3 (ISO3).
    """

    def __init__(self, country_geometries: list[tuple[str, dict]]) -> None:
        from shapely.geometry import shape

        self._geometries = country_geometries
        self._shapes = [(cc, shape(geom)) for cc, geom in country_geometries]
        logger.info("CountryIndex: loaded %d country polygons.", len(self._shapes))

    def lookup(self, lon: float, lat: float) -> str | None:
        from shapely.geometry import Point

        pt = Point(lon, lat)
        for cc, shp in self._shapes:
            if shp.contains(pt):
                return cc
        return None

    def get_largest_polygon(self, country_code: str) -> list | None:
        for cc, geom in self._geometries:
            if cc != country_code:
                continue
            if geom["type"] == "Polygon":
                return geom["coordinates"][0]
            elif geom["type"] == "MultiPolygon":
                largest = max(geom["coordinates"], key=lambda poly: bbox_area(poly[0]))
                return largest[0]
        return None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

VALID_ROUTING_MODES = frozenset({"simpleRouting", "fullRouting"})
"""Single source of truth for allowed routing_mode strings — read by both
api/route.py's request validation and RailRouter.route()'s switch below.
Adding a mode means: add it to this set and add a branch in route()."""


class RailRoutingError(Exception):
    """Raised when the routing engine returns an error."""

    pass


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

    def __init__(self, country_index: CountryIndex) -> None:
        self.base_url = os.environ.get(
            "OPENRAILROUTING_URL", "http://localhost:8989"
        ).rstrip("/")
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

    def check_server(self) -> dict:
        resp = self._session.get(
            f"{self.base_url}{self.INFO_ENDPOINT}", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

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
        concern, see api/route.py; every caller passes it explicitly):
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

        # routing_mode SWITCH — VALID_ROUTING_MODES is the same set
        # api/route.py validates the request against, so an unknown mode
        # can only reach here if that validation was bypassed.
        if routing_mode == "simpleRouting":
            raw = self._post_route(self._build_payload(stops, None))
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
            snap_raw = self._post_route(self._build_payload(stops, None))
            snapped_coords = snap_raw["paths"][0]["snapped_waypoints"]["coordinates"]
            raw = self._post_route(
                self._build_payload(
                    stops,
                    custom_model,
                    override_coords=snapped_coords,
                )
            )
        else:
            raw = self._post_route(self._build_payload(stops, None))

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
        GraphHopper custom model for the fullRouting pass, or None when
        nothing needs one (no speed cap, no country disallowing HSR).

        Two independent concerns:
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
        speed_rules, priority_rules, areas = [], [], {}

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
        override_coords: list[list[float]] | None = None,
    ) -> dict:
        """
        custom_model: prebuilt by _build_custom_model() (or None for a plain
        CH pass) — passed in rather than rebuilt here, so route() builds it
        exactly once per call.
        override_coords: snapped [lon, lat] pairs from pass 1, used in place
        of the original stop coordinates for pass 2 of two-pass routing.
        """
        points = (
            override_coords
            if override_coords is not None
            else [[s.stop.lon, s.stop.lat] for s in stops]
        )
        payload: dict = {
            "profile": self.profile,
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
            except:
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

    @staticmethod
    def _parse_legs(
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
        """
        legs: list[RoutedLeg] = []

        for i in range(n_stops - 1):
            if i < len(leg_distance_detail):
                from_idx = leg_distance_detail[i][0]
                to_idx = leg_distance_detail[i][1]
            else:
                from_idx, to_idx = 0, len(coords) - 1
                logger.warning("leg_distance detail missing for segment %d.", i)

            leg_cc_dist: dict[str, float] = defaultdict(float)
            leg_cc_dur_ms: dict[str, float] = defaultdict(float)

            for iv_from, iv_to, cc, dist_m, iv_ms in intervals:
                overlap_from = max(iv_from, from_idx)
                overlap_to = min(iv_to, to_idx)
                if overlap_from >= overlap_to:
                    continue
                span = iv_to - iv_from
                fraction = (overlap_to - overlap_from) / span if span > 0 else 1.0
                leg_cc_dist[cc] += dist_m * fraction
                leg_cc_dur_ms[cc] += iv_ms * fraction

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

            legs.append(
                RoutedLeg(
                    geometry=coords[from_idx : to_idx + 1],
                    distance_m=round(total_dist_m),
                    driving_time_min=ms_to_min(total_dur_ms),
                    dynamics_time_min=0,  # filled by apply_traction_dynamics()
                    buffer_time_min=total_buffer_min,
                    energy_kwh=0.0,  # populated by calc_energy_consumption()
                    country_distance_shares=country_distance_shares,
                    country_time_shares=country_time_shares,
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
