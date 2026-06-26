"""
rail_router.py
==============
Wrapper around the local OpenRailRouting (GraphHopper) instance.

Unit conventions (internal)
----------------------------
  Distance : metres  (_m)   — GraphHopper native
  Duration : minutes (_min) — converted from GraphHopper milliseconds on parse
  Speed    : km/h    (_kmh) — derived display value only

Responsibilities
----------------
- HTTP communication with GraphHopper (two-pass routing for custom models).
- Country attribution of route geometry via shapely point-in-polygon.
- Physics per country leg: distance_m, driving_time_min, buffer_time_min.
- Constructs and returns a TripPath directly.

NOT responsible for:
- Energy consumption     (→ models/energy/calc_energy_consumption.py)
- TAC / energy costs     (→ models/evaluation/calc.py)
- Schedule / clock times (→ models/route/route_factory.py)

Public surface
--------------
  RailRouter.route(stops, composition, tracks) → TripPath
  RailRoutingError
  Stop  (input type — public)
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import requests

from models.params import Composition, TrackInfraCollection, StopInfrastructure
from models.route.trip import CountryLeg, TripSegment, TripPath
from models.utils import (
    ms_to_min, m_to_km,
    haversine_m, haversine_path_m, bbox_area,
    ISO2_TO_ISO3, ISO3_TO_ISO2,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public input type
# ---------------------------------------------------------------------------

@dataclass
class Stop:
    """A named stop on the route. lat/lon in WGS-84 decimal degrees."""
    stop_id:      str
    name:         str
    lat:          float
    lon:          float
    country_code: str = ""
    stop_type:    str = "both"      # "boarding" | "alighting" | "both"

    @classmethod
    def from_infra(cls, infra: StopInfrastructure, stop_type: str = "both") -> "Stop":
        return cls(
            stop_id      = infra.stop_id,
            name         = infra.stop_name,
            lat          = infra.lat,
            lon          = infra.lon,
            country_code = infra.stop_country_code,
            stop_type    = stop_type,
        )


# ---------------------------------------------------------------------------
# Private snapped stop — internal only
# ---------------------------------------------------------------------------

@dataclass
class _SnappedStop:
    """Input stop plus coordinate snapped to the rail network."""
    stop:        Stop
    snapped_lat: float
    snapped_lon: float


# ---------------------------------------------------------------------------
# Country index
# ---------------------------------------------------------------------------

_COUNTRIES_PATH = Path(os.environ.get(
    "COUNTRIES_GEOJSON_PATH",
    str(Path(__file__).parent / "countries.geojson"),  # local dev fallback
))


class CountryIndex:
    def __init__(self, features: list[dict]) -> None:
        self._features = features
        from shapely.geometry import shape
        self._shapes = [
            (f["properties"].get("ADM0_A3", ""), shape(f["geometry"]))
            for f in features
        ]
        logger.info("CountryIndex: loaded %d country polygons.", len(self._shapes))

    @classmethod
    def load(cls, path: Path = _COUNTRIES_PATH) -> "CountryIndex":
        if not path.exists():
            url = os.environ.get("NATURAL_EARTH_COUNTRIES_URL", "<see NATURAL_EARTH_COUNTRIES_URL in .env.example>")
            raise FileNotFoundError(
                f"Country borders file not found at {path}.\n"
                f"Download from: {url}\n"
                f"In Docker this file is downloaded at build time via the Dockerfile.\n"
                f"For local dev: wget -O {path} \"$NATURAL_EARTH_COUNTRIES_URL\""
            )
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(data["features"])

    def lookup(self, lon: float, lat: float) -> str | None:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        for iso3, shp in self._shapes:
            if shp.contains(pt):
                return iso3
        return None

    def get_largest_polygon(self, iso3: str) -> list | None:
        for feature in self._features:
            if feature["properties"].get("ADM0_A3") != iso3:
                continue
            geom = feature["geometry"]
            if geom["type"] == "Polygon":
                return geom["coordinates"][0]
            elif geom["type"] == "MultiPolygon":
                largest = max(geom["coordinates"], key=lambda poly: bbox_area(poly[0]))
                return largest[0]
        return None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class RailRoutingError(Exception):
    """Raised when the routing engine returns an error."""
    pass


class RailRouter:
    """
    Wraps the OpenRailRouting (GraphHopper) instance.

    route() returns a TripPath with physics-only data (no energy values,
    no costs, no clock times). route_factory.py handles all enrichment.
    energy_kwh on all CountryLegs will be 0.0 on return — populated by
    calc_energy_consumption() in route_factory before trip construction.
    """

    ROUTE_ENDPOINT = "/route"
    INFO_ENDPOINT  = "/info"
    DETAILS        = ["leg_distance", "leg_time", "time"]

    def __init__(self) -> None:
        self.base_url       = os.environ.get("OPENRAILROUTING_URL", "http://localhost:8989").rstrip("/")
        self.profile        = os.environ.get("OPENRAILROUTING_PROFILE", "night_train")
        self.timeout        = int(os.environ.get("OPENRAILROUTING_TIMEOUT", "30"))
        self._session       = requests.Session()
        self._country_index = CountryIndex.load()

    def check_server(self) -> dict:
        resp = self._session.get(
            f"{self.base_url}{self.INFO_ENDPOINT}", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def route(
        self,
        stops:       list[Stop],
        composition: Composition,
        tracks:      TrackInfraCollection,
    ) -> TripPath:
        """
        Route a trip and return a TripPath with physics-only data.

        Two-pass routing is used when a custom model is needed:
          pass 1 — CH routing to snap stops to the rail network
          pass 2 — custom model routing with snapped coordinates

        energy_kwh on all CountryLegs is 0.0 on return — populated by
        calc_energy_consumption() in route_factory.
        """
        if len(stops) < 2:
            raise ValueError("At least 2 stops are required.")

        vehicle_max_speed_kmh  = int(composition.max_speed_kmh)
        avoid_hsr = {
            cc: not (composition.hsr_allowed and (tracks.get(cc).hsr_allowed if tracks.get(cc) else True))
            for cc in [s.country_code for s in stops if s.country_code]
        }
        custom_model = self._build_custom_model(vehicle_max_speed_kmh, avoid_hsr)

        if custom_model:
            snap_raw       = self._post_route(self._build_payload(stops, None, None))
            snapped_coords = snap_raw["paths"][0]["snapped_waypoints"]["coordinates"]
            snapped_input  = [
                Stop(
                    stop_id      = stops[i].stop_id,
                    name         = stops[i].name,
                    lat          = snapped_coords[i][1],
                    lon          = snapped_coords[i][0],
                    country_code = stops[i].country_code,
                    stop_type    = stops[i].stop_type,
                )
                for i in range(len(stops))
            ]
            raw = self._post_route(
                self._build_payload(snapped_input, vehicle_max_speed_kmh, avoid_hsr)
            )
        else:
            raw = self._post_route(self._build_payload(stops, None, None))

        return self._parse_response(raw, stops, tracks)

    def _build_custom_model(
        self,
        vehicle_max_speed_kmh:  int | None,
        avoid_high_speed_lines: dict[str, bool] | None,
    ) -> dict | None:
        speed_rules, priority_rules, areas = [], [], {}

        if vehicle_max_speed_kmh is not None:
            speed_rules.append({"if": "true", "limit_to": str(vehicle_max_speed_kmh)})

        if avoid_high_speed_lines:
            for cc, avoid in avoid_high_speed_lines.items():
                if not avoid:
                    continue
                iso3 = ISO2_TO_ISO3.get(cc, cc)
                ring = self._country_index.get_largest_polygon(iso3)
                if ring is None:
                    logger.warning("No polygon for '%s' — skipping HSR avoidance.", iso3)
                    continue
                closed_ring = ring if ring[0] == ring[-1] else ring + [ring[0]]
                area_name   = f"hsr{iso3.lower()}"
                areas[area_name] = {
                    "type": "Feature", "id": area_name, "properties": {},
                    "geometry": {"type": "Polygon", "coordinates": [closed_ring]},
                }
                priority_rules.append({"if": f"in_{area_name}", "multiply_by": "0.01"})

        if not speed_rules and not priority_rules:
            return None

        cm: dict = {}
        if speed_rules:    cm["speed"]    = speed_rules
        if priority_rules: cm["priority"] = priority_rules
        if areas:          cm["areas"]    = {
            "type": "FeatureCollection", "features": list(areas.values())
        }
        return cm

    def _build_payload(
        self,
        stops:                  list[Stop],
        vehicle_max_speed_kmh:  int | None,
        avoid_high_speed_lines: dict[str, bool] | None,
    ) -> dict:
        payload: dict = {
            "profile":        self.profile,
            "points":         [[s.lon, s.lat] for s in stops],
            "points_encoded": False,
            "instructions":   False,
            "details":        self.DETAILS,
        }
        cm = self._build_custom_model(vehicle_max_speed_kmh, avoid_high_speed_lines)
        if cm:
            payload["custom_model"] = cm
            payload["ch.disable"]   = True
        return payload

    def _post_route(self, payload: dict) -> dict:
        resp = self._session.post(
            f"{self.base_url}{self.ROUTE_ENDPOINT}", json=payload, timeout=self.timeout
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            try:    msg = resp.json().get("message", resp.text)
            except: msg = resp.text
            raise RailRoutingError(
                f"Routing engine HTTP {resp.status_code}: {msg}"
            ) from exc
        body = resp.json()
        if "message" in body and "paths" not in body:
            raise RailRoutingError(f"Routing engine error: {body['message']}")
        return body

    def _parse_response(
        self,
        body:   dict,
        stops:  list[Stop],
        tracks: TrackInfraCollection,
    ) -> TripPath:
        path_data  = body["paths"][0]
        shape      = path_data["points"]
        coords     = shape["coordinates"]

        snapped_coords = path_data["snapped_waypoints"]["coordinates"]
        snapped_stops  = self._parse_snapped_stops(stops, snapped_coords)

        details             = path_data.get("details", {})
        leg_distance_detail = details.get("leg_distance", [])
        leg_time_detail     = details.get("leg_time", [])
        time_detail         = details.get("time", [])

        intervals = self._compute_country_intervals(coords, time_detail)
        segments  = self._parse_segments(
            snapped_stops, coords,
            leg_distance_detail, leg_time_detail,
            intervals, tracks,
        )

        # build per-country aggregation
        from collections import defaultdict as _dd
        country_legs_by_cc: dict[str, list[CountryLeg]] = _dd(list)
        for seg in segments:
            for cl in seg.country_legs:
                country_legs_by_cc[cl.country_code].append(cl)

        from models.route.trip import CountrySegment
        countries = [
            CountrySegment(country_code=cc, country_legs=legs)
            for cc, legs in country_legs_by_cc.items()
        ]

        return TripPath(
            shape     = shape,
            segments  = segments,
            countries = countries,
        )

    @staticmethod
    def _parse_snapped_stops(
        stops:          list[Stop],
        snapped_coords: list,
    ) -> list[_SnappedStop]:
        result = []
        for i, stop in enumerate(stops):
            if i < len(snapped_coords):
                lon, lat = snapped_coords[i][0], snapped_coords[i][1]
            else:
                lon, lat = stop.lon, stop.lat
                logger.warning("No snapped coordinate for stop '%s'.", stop.name)
            result.append(_SnappedStop(stop=stop, snapped_lat=lat, snapped_lon=lon))
        return result

    @staticmethod
    def _parse_segments(
        snapped_stops:       list[_SnappedStop],
        coords:              list[list[float]],
        leg_distance_detail: list,
        leg_time_detail:     list,
        intervals:           list[tuple],
        tracks:              TrackInfraCollection,
    ) -> list[TripSegment]:
        segments = []
        for i in range(len(snapped_stops) - 1):
            if i < len(leg_distance_detail):
                from_idx = leg_distance_detail[i][0]
                to_idx   = leg_distance_detail[i][1]
            else:
                from_idx, to_idx = 0, len(coords) - 1
                logger.warning("leg_distance detail missing for segment %d.", i)

            leg_cc_dist:   dict[str, float] = defaultdict(float)
            leg_cc_dur_ms: dict[str, float] = defaultdict(float)

            for iv_from, iv_to, cc, dist_m, iv_ms in intervals:
                overlap_from = max(iv_from, from_idx)
                overlap_to   = min(iv_to, to_idx)
                if overlap_from >= overlap_to:
                    continue
                span     = iv_to - iv_from
                fraction = (overlap_to - overlap_from) / span if span > 0 else 1.0
                leg_cc_dist[cc]   += dist_m * fraction
                leg_cc_dur_ms[cc] += iv_ms * fraction

            country_legs: list[CountryLeg] = []
            for cc, dist_m_f in leg_cc_dist.items():
                cl_dist_m    = round(dist_m_f)
                cl_drive_min = ms_to_min(leg_cc_dur_ms[cc])
                track        = tracks.get_or_default(cc)
                buffer_min   = round(cl_drive_min * track.buffer_quota_per)

                country_legs.append(CountryLeg(
                    from_stop_id     = snapped_stops[i].stop.stop_id,
                    to_stop_id       = snapped_stops[i + 1].stop.stop_id,
                    country_code     = cc,
                    distance_m       = cl_dist_m,
                    driving_time_min = cl_drive_min,
                    buffer_time_min  = buffer_min,
                    energy_kwh       = 0.0,     # populated by calc_energy_consumption()
                    energy_kwh_per_km= 0.0,     # populated by calc_energy_consumption()
                ))

            segments.append(TripSegment(
                from_stop_id = snapped_stops[i].stop.stop_id,
                to_stop_id   = snapped_stops[i + 1].stop.stop_id,
                geometry     = coords[from_idx: to_idx + 1],
                country_legs = country_legs,
            ))

        return segments

    def _compute_country_intervals(
        self,
        coords:      list[list[float]],
        time_detail: list,
    ) -> list[tuple[int, int, str, float, int]]:
        """Single shapely pass → (from_idx, to_idx, cc, dist_m, dur_ms)."""
        intervals = []
        for entry in time_detail:
            from_idx, to_idx, iv_ms = entry[0], entry[1], entry[2]
            segment = coords[from_idx: to_idx + 1]
            dist_m  = haversine_path_m(segment)
            mid_idx = (from_idx + to_idx) // 2
            iso3    = self._country_index.lookup(
                coords[mid_idx][0], coords[mid_idx][1]
            ) or "UNK"
            cc      = ISO3_TO_ISO2.get(iso3, iso3)
            intervals.append((from_idx, to_idx, cc, dist_m, iv_ms))
        return intervals