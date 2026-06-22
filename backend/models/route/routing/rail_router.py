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
- Segment and trip-level aggregation of the above.

NOT responsible for:
- Energy consumption     (→ models/energy/calc_energy_consumption.py)
- TAC / energy costs     (→ models/route/route_factory.py)
- Schedule / clock times (→ models/route/route_factory.py)

All output types (_CountryLeg, _Segment, _RouterResult, _SnappedStop) are
private — never imported outside this module. route_factory.py is the sole
consumer.

Public surface
--------------
  RailRouter.route() → _RouterResult
  RailRoutingError
  Stop  (input type — public)
"""


# TODO: Versionize router

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import requests

from models.params import CompositionParams, InfraParams

logger = logging.getLogger(__name__)

_ISO3_TO_ISO2: dict[str, str] = {
    "AUT": "AT", "BEL": "BE", "BGR": "BG", "HRV": "HR",
    "CZE": "CZ", "DNK": "DK", "FIN": "FI", "FRA": "FR",
    "DEU": "DE", "GRC": "GR", "HUN": "HU", "IRL": "IE",
    "ITA": "IT", "LUX": "LU", "NLD": "NL", "NOR": "NO",
    "POL": "PL", "PRT": "PT", "ROU": "RO", "SVK": "SK",
    "SVN": "SI", "ESP": "ES", "SWE": "SE", "CHE": "CH",
    "GBR": "GB", "SRB": "RS", "MKD": "MK", "MNE": "ME",
    "BIH": "BA", "ALB": "AL", "UKR": "UA", "TUR": "TR",
}
_ISO2_TO_ISO3: dict[str, str] = {v: k for k, v in _ISO3_TO_ISO2.items()}


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def _ms_to_min(ms: int) -> int:
    """Convert milliseconds to minutes (rounded)."""
    return round(ms / 60_000)


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
    def from_params(cls, params: "StopParams", stop_type: str = "both") -> "Stop":
        from models.params import StopParams as _StopParams
        return cls(
            stop_id      = params.stop_id,
            name         = params.stop_name,
            lat          = params.lat,
            lon          = params.lon,
            country_code = params.stop_country_code,
            stop_type    = stop_type,
        )


# ---------------------------------------------------------------------------
# Private output types — never imported outside this module
# ---------------------------------------------------------------------------

@dataclass
class _SnappedStop:
    """Input stop plus coordinate snapped to the rail network."""
    stop:        Stop
    snapped_lat: float
    snapped_lon: float


@dataclass
class _CountryLeg:
    """
    Physics-only sub-segment within a single country.

    energy_kwh and energy_kwh_per_km initialised to 0.0 — populated by
    calc_energy_consumption() in route_factory.py before cost enrichment.

    buffer_time_min = driving_time_min × infra_buffer_quota_per (rounded).
    """
    from_stop_id:     str
    to_stop_id:       str
    country_code:     str
    distance_m:       int           # metres
    driving_time_min: int           # pure engine time, no buffer
    buffer_time_min:  int           # infra buffer
    energy_kwh:       float = 0.0   # populated by calc_energy_consumption()
    energy_kwh_per_km: float = 0.0  # populated by calc_energy_consumption()

    @property
    def total_time_min(self) -> int:
        return self.driving_time_min + self.buffer_time_min

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000.0

    @property
    def avg_speed_kmh(self) -> float:
        if self.driving_time_min <= 0:
            return 0.0
        return self.distance_km / (self.driving_time_min / 60.0)


@dataclass
class _Segment:
    """
    Physics-only segment between two consecutive stops.
    Aggregates derived from country_legs.
    """
    from_stop_id:  str
    to_stop_id:    str
    geometry:      list[list[float]]    # [[lon, lat], ...]
    country_legs:  list[_CountryLeg]

    @property
    def distance_m(self) -> int:
        return sum(cl.distance_m for cl in self.country_legs)

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000.0

    @property
    def driving_time_min(self) -> int:
        return sum(cl.driving_time_min for cl in self.country_legs)

    @property
    def buffer_time_min(self) -> int:
        return sum(cl.buffer_time_min for cl in self.country_legs)

    @property
    def total_time_min(self) -> int:
        return self.driving_time_min + self.buffer_time_min


@dataclass
class _RouterResult:
    """
    Raw output of RailRouter.route(). Consumed exclusively by route_factory.py.

    Physics-only — no energy values (0.0 on all country legs), no clock times
    (schedule computed in route_factory after energy enrichment).

    total_driving_time_min — pure GraphHopper engine time, no buffer.
    total_buffer_time_min  — sum of all country leg buffers.
    total_time_min         — driving + buffer.
    """
    snapped_stops:         list[_SnappedStop]
    segments:              list[_Segment]
    shape:                 dict             # GeoJSON LineString (full trip)
    total_distance_m:      int
    total_driving_time_min: int
    total_buffer_time_min: int

    @property
    def total_time_min(self) -> int:
        return self.total_driving_time_min + self.total_buffer_time_min


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _haversine_path_m(coords: list[list[float]]) -> float:
    total = 0.0
    for i in range(len(coords) - 1):
        total += _haversine_m(
            coords[i][0], coords[i][1],
            coords[i + 1][0], coords[i + 1][1],
        )
    return total


def _bbox_area(ring: list) -> float:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return (max(lons) - min(lons)) * (max(lats) - min(lats))


# ---------------------------------------------------------------------------
# Country index
# ---------------------------------------------------------------------------

_COUNTRIES_PATH = Path(__file__).parent / "countries.geojson"


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
            raise FileNotFoundError(
                f"Country borders file not found at {path}.\n"
                f"Download from:\n"
                f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector"
                f"/master/geojson/ne_110m_admin_0_countries.geojson\n"
                f"and save as {path.name} in {path.parent}"
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
                largest = max(geom["coordinates"], key=lambda poly: _bbox_area(poly[0]))
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

    route() returns a _RouterResult with physics-only data (no energy,
    no costs, no clock times). route_factory.py handles all enrichment.
    """

    ROUTE_ENDPOINT = "/route"
    INFO_ENDPOINT  = "/info"
    DETAILS        = ["leg_distance", "leg_time", "time"]

    def __init__(
        self,
        base_url: str = "http://localhost:8989",
        profile:  str = "night_train",
        timeout:  int = 30,
    ) -> None:
        self.base_url       = base_url.rstrip("/")
        self.profile        = profile
        self.timeout        = timeout
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
            stops:            list[Stop],
            composition:      CompositionParams,
            infra:            dict[str, InfraParams],
            departure_time_min: int,
    ) -> _RouterResult:
        """
        Route a trip and return physics-only _RouterResult.

        departure_time_min is accepted for API consistency but not used
        here — schedule computation happens in route_factory.py.

        infra used for: HSR avoidance, buffer_quota_per per country.
        Cost fields (tac rates, energy prices) are NOT used here.

        energy_kwh on all _CountryLegs will be 0.0 on return — populated
        by calc_energy_consumption() in route_factory before enrichment.
        """
        if len(stops) < 2:
            raise ValueError("At least 2 stops are required.")

        vehicle_max_speed_kmh  = int(composition.max_speed_kmh)
        avoid_high_speed_lines = {
            cc: not (composition.hsr_allowed and ip.hsr_allowed)
            for cc, ip in infra.items()
        }
        custom_model = self._build_custom_model(vehicle_max_speed_kmh, avoid_high_speed_lines)

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
                self._build_payload(snapped_input, vehicle_max_speed_kmh, avoid_high_speed_lines)
            )
        else:
            raw = self._post_route(self._build_payload(stops, None, None))

        return self._parse_response(raw, stops, infra)

    def _build_custom_model(self, vehicle_max_speed_kmh, avoid_high_speed_lines) -> dict | None:
        speed_rules, priority_rules, areas = [], [], {}

        if vehicle_max_speed_kmh is not None:
            speed_rules.append({"if": "true", "limit_to": str(vehicle_max_speed_kmh)})

        if avoid_high_speed_lines:
            for cc, avoid in avoid_high_speed_lines.items():
                if not avoid:
                    continue
                iso3 = _ISO2_TO_ISO3.get(cc, cc)
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
                priority_rules.append({"if": f"in_{area_name}", "multiply_by": "0.0001"})

        if not speed_rules and not priority_rules:
            return None

        cm: dict = {}
        if speed_rules:    cm["speed"]    = speed_rules
        if priority_rules: cm["priority"] = priority_rules
        if areas:          cm["areas"]    = {
            "type": "FeatureCollection", "features": list(areas.values())
        }
        return cm

    def _build_payload(self, stops, vehicle_max_speed_kmh, avoid_high_speed_lines) -> dict:
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
            body:  dict,
            stops: list[Stop],
            infra: dict[str, InfraParams],
    ) -> _RouterResult:
        path_data         = body["paths"][0]
        shape             = path_data["points"]
        coords            = shape["coordinates"]
        total_distance_m  = round(path_data["distance"])
        total_duration_ms = int(path_data["time"])

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
            intervals, infra,
        )

        total_driving_time_min = _ms_to_min(total_duration_ms)
        total_buffer_time_min  = sum(
            cl.buffer_time_min
            for seg in segments
            for cl in seg.country_legs
        )

        return _RouterResult(
            snapped_stops          = snapped_stops,
            segments               = segments,
            shape                  = shape,
            total_distance_m       = total_distance_m,
            total_driving_time_min = total_driving_time_min,
            total_buffer_time_min  = total_buffer_time_min,
        )

    @staticmethod
    def _parse_snapped_stops(stops: list[Stop], snapped_coords: list) -> list[_SnappedStop]:
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
            infra:               dict[str, InfraParams],
    ) -> list[_Segment]:
        segments = []
        for i in range(len(snapped_stops) - 1):
            if i < len(leg_distance_detail):
                from_idx = leg_distance_detail[i][0]
                to_idx   = leg_distance_detail[i][1]
            else:
                from_idx, to_idx = 0, len(coords) - 1
                logger.warning("leg_distance detail missing for segment %d.", i)

            if i < len(leg_time_detail):
                seg_duration_ms = int(leg_time_detail[i][2])
            else:
                seg_duration_ms = 0
                logger.warning("leg_time detail missing for segment %d.", i)

            leg_cc_dist: dict[str, float] = defaultdict(float)
            leg_cc_dur_ms: dict[str, float] = defaultdict(float)

            for iv_from, iv_to, cc, dist_m, iv_ms in intervals:
                overlap_from = max(iv_from, from_idx)
                overlap_to   = min(iv_to, to_idx)
                if overlap_from >= overlap_to:
                    continue
                span     = iv_to - iv_from
                fraction = (overlap_to - overlap_from) / span if span > 0 else 1.0
                leg_cc_dist[cc]    += dist_m * fraction
                leg_cc_dur_ms[cc]  += iv_ms * fraction

            country_legs: list[_CountryLeg] = []
            for cc, dist_m_f in leg_cc_dist.items():
                cl_dist_m      = round(dist_m_f)
                cl_dur_ms      = leg_cc_dur_ms[cc]
                cl_drive_min   = _ms_to_min(cl_dur_ms)

                ip = infra.get(cc) or infra.get("_default")
                if ip is None:
                    logger.warning(
                        "No infra params for '%s' and no _default — buffer set to 0.", cc
                    )
                    buffer_min = 0
                else:
                    # TODO: remove * 60 conversion once params use _min
                    buffer_min = round(cl_drive_min * ip.buffer_quota_per)

                country_legs.append(_CountryLeg(
                    from_stop_id     = snapped_stops[i].stop.stop_id,
                    to_stop_id       = snapped_stops[i + 1].stop.stop_id,
                    country_code     = cc,
                    distance_m       = cl_dist_m,
                    driving_time_min = cl_drive_min,
                    buffer_time_min  = buffer_min,
                    # energy_kwh and energy_kwh_per_km left at 0.0
                    # — populated by calc_energy_consumption() in route_factory
                ))

            segments.append(_Segment(
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
            dist_m  = _haversine_path_m(segment)
            mid_idx = (from_idx + to_idx) // 2
            iso3    = self._country_index.lookup(
                coords[mid_idx][0], coords[mid_idx][1]
            ) or "UNK"
            cc      = _ISO3_TO_ISO2.get(iso3, iso3)
            intervals.append((from_idx, to_idx, cc, dist_m, iv_ms))
        return intervals