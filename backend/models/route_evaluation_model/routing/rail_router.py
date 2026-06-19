"""
rail_router.py
Wrapper around the local OpenRailRouting (GraphHopper) instance.
"""

from __future__ import annotations

import math
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ISO 3166-1 alpha-3 → alpha-2 conversion table (European rail countries)
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
# Input model
# ---------------------------------------------------------------------------

@dataclass
class Stop:
    """A named stop on the route. lat/lon in WGS-84 decimal degrees."""
    stop_id: str
    name: str
    lat: float
    lon: float
    country_code: str = ""
    stop_type: str = "both"

    @classmethod
    def from_params(cls, params: "StopParams", stop_type: str = "both") -> "Stop":
        """Build a routing Stop from a StopParams object."""
        from models.params import StopParams as _StopParams
        return cls(
            stop_id      = params.stop_id,
            name         = params.stop_name,
            lat          = params.lat,
            lon          = params.lon,
            country_code = params.stop_country_code,
            stop_type    = stop_type,
        )

@dataclass
class CompositionParams:
    """
    Composition parameters needed by the router for routing and schedule calculation.
    Built from the compositions sheet by SheetDataLoader.
    """
    comp_id: str
    weight_gross_t: float
    max_speed_kmh: float
    hsr_allowed: bool
    energy_factor_weight: float     # kWh/(t·km)
    energy_factor_speed: float      # kWh/((km/h)²·km)
    energy_factor_terrain: float    # multiplier for terrain score
    min_boarding_time_h: float      # comp_veh_min_boarding_time_h
    min_alighting_time_h: float     # comp_veh_min_alighting_time_h


@dataclass
class InfraParams:
    """
    Per-country infrastructure parameters needed by the router.
    Built from the infrastructure sheet by SheetDataLoader.
    Keyed by ISO 3166-1 alpha-2 country code in the dict passed to route().
    """
    country_code: str
    tac_eur_train_km: float
    parking_eur_day: float
    energy_price_eur_kwh: float
    terrain_score: float            # 1–100, used in energy regression
    hsr_allowed: bool
    min_boarding_time_h: float      # infra_min_boarding_time_h
    min_alighting_time_h: float     # infra_min_alighting_time_h
    buffer_quota_per: float         # additional time on top of driving time, per country


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

@dataclass
class SnappedStop:
    """Input stop plus the coordinate snapped to the rail network."""
    stop: Stop          # original input stop (stop_id, name, lat, lon)
    snapped_lat: float
    snapped_lon: float


@dataclass
class CountryLeg:
    """
    One rail segment between two consecutive stops within a single country.
    Produced by route_legs_by_country() for consumption by the cost model.
    A RouteSegment crossing two countries produces two CountryLeg entries.
    """
    from_stop_id: str
    to_stop_id: str
    country_code: str           # ISO 3166-1 alpha-2
    distance_km: float
    driving_time_h: float       # pure engine time, no buffer
    avg_speed_kmh: float
    buffer_time_h: float        # infra_buffer_quota_per × driving_time_h
    energy_kwh: float           # weight × km × (f_weight + f_speed×v² + f_terrain×score)
    energy_kwh_per_km: float    # energy_kwh / distance_km
    tac_eur: float              # tac_eur_train_km × distance_km
    tac_eur_per_km: float       # reference rate for this country (infra_tac_eur_train_km)


@dataclass
class RouteSegment:
    """One segment between two consecutive stops, potentially spanning multiple countries."""
    from_stop: SnappedStop
    to_stop: SnappedStop
    distance_m: float
    duration_ms: int
    avg_speed_kmh: float
    geometry: list[list[float]]     # [[lon, lat], …]
    country_legs: list[CountryLeg]  # breakdown by country, populated after routing

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000

    @property
    def driving_time_h(self) -> float:
        return self.duration_ms / 3_600_000

    @property
    def buffer_time_h(self) -> float:
        return sum(cl.buffer_time_h for cl in self.country_legs)

    @property
    def total_time_h(self) -> float:
        """Driving time including buffer."""
        return self.driving_time_h + self.buffer_time_h

    @property
    def energy_kwh(self) -> float:
        return sum(cl.energy_kwh for cl in self.country_legs)

    @property
    def tac_eur(self) -> float:
        return sum(cl.tac_eur for cl in self.country_legs)


@dataclass
class CountrySegment:
    """Aggregated route summary for one country across all legs."""
    country_code: str
    country_legs: list[CountryLeg]      # all legs in this country, in route order

    @property
    def distance_km(self) -> float:
        return sum(cl.distance_km for cl in self.country_legs)

    @property
    def driving_time_h(self) -> float:
        return sum(cl.driving_time_h for cl in self.country_legs)

    @property
    def buffer_time_h(self) -> float:
        return sum(cl.buffer_time_h for cl in self.country_legs)

    @property
    def total_time_h(self) -> float:
        return self.driving_time_h + self.buffer_time_h

    @property
    def avg_speed_kmh(self) -> float:
        return self.distance_km / self.driving_time_h if self.driving_time_h > 0 else 0.0

    @property
    def energy_kwh(self) -> float:
        return sum(cl.energy_kwh for cl in self.country_legs)

    @property
    def tac_eur(self) -> float:
        return sum(cl.tac_eur for cl in self.country_legs)


@dataclass
class ScheduleStop:
    """
    One row in the trip schedule table.
    References the incoming and outgoing RouteSegment for full context.
    """
    snapped_stop: SnappedStop
    stop_type: str                      # "boarding" | "alighting" | "both"
    arrival_time_h: float | None        # None for first stop
    departure_time_h: float | None      # None for last stop
    dwell_time_h: float | None          # None for first and last stop
    incoming_leg: RouteSegment | None   # None for first stop
    outgoing_leg: RouteSegment | None   # None for last stop

    @property
    def stop_id(self) -> str:
        return self.snapped_stop.stop.stop_id

    @property
    def stop_name(self) -> str:
        return self.snapped_stop.stop.name

    def format_time(self, time_h: float | None) -> str:
        """Format a decimal hour value as HH:MM, handling overnight (>24h)."""
        if time_h is None:
            return "—"
        total_minutes = round(time_h * 60)
        hours = (total_minutes // 60) % 24
        minutes = total_minutes % 60
        day = total_minutes // (60 * 24)
        day_str = f" (+{day}d)" if day > 0 else ""
        return f"{hours:02d}:{minutes:02d}{day_str}"

    def __str__(self) -> str:
        arr = self.format_time(self.arrival_time_h)
        dep = self.format_time(self.departure_time_h)
        dwell = f"{self.dwell_time_h * 60:.0f} min" if self.dwell_time_h is not None else "—"
        return (
            f"  {self.stop_name:30s}"
            f"  arr {arr:12s}"
            f"  dep {dep:12s}"
            f"  dwell {dwell:8s}"
            f"  [{self.stop_type}]"
        )


@dataclass
class RouteResult:
    """Full structured result of a multi-stop routing request."""
    stops: list[SnappedStop]
    legs: list[RouteSegment]
    countries: list[CountrySegment]
    schedule: list[ScheduleStop]
    total_distance_m: float
    total_duration_ms: int
    geometry: dict               # GeoJSON LineString

    # Internal data retained for potential external use — not for display
    coords: list[list[float]] = None
    leg_distance_detail: list = None

    @property
    def total_distance_km(self) -> float:
        return self.total_distance_m / 1000

    @property
    def total_driving_time_h(self) -> float:
        return self.total_duration_ms / 3_600_000

    @property
    def total_buffer_time_h(self) -> float:
        return sum(leg.buffer_time_h for leg in self.legs)

    @property
    def total_time_h(self) -> float:
        return self.total_driving_time_h + self.total_buffer_time_h

    @property
    def avg_speed_kmh(self) -> float:
        if self.total_duration_ms == 0:
            return 0.0
        return self.total_distance_km / self.total_driving_time_h

    @property
    def total_energy_kwh(self) -> float:
        return sum(leg.energy_kwh for leg in self.legs)

    @property
    def total_tac_eur(self) -> float:
        return sum(leg.tac_eur for leg in self.legs)

    def __str__(self) -> str:
        lines = [
            "=== RouteResult ===",
            f"Total distance    : {self.total_distance_km:,.1f} km",
            f"Driving time      : {self.total_driving_time_h:,.2f} h",
            f"Buffer time       : {self.total_buffer_time_h:,.2f} h",
            f"Total time        : {self.total_time_h:,.2f} h",
            f"Average speed     : {self.avg_speed_kmh:,.1f} km/h",
            f"Total energy      : {self.total_energy_kwh:,.1f} kWh",
            f"Total TAC         : {self.total_tac_eur:,.0f} €",
            "",
            "--- Schedule ---",
        ]
        for s in self.schedule:
            lines.append(str(s))
        lines += ["", "--- Legs ---"]
        for i, leg in enumerate(self.legs, 1):
            lines.append(
                f"  Leg {i}: {leg.from_stop.stop.name} → {leg.to_stop.stop.name}"
                f"  |  {leg.distance_km:,.1f} km"
                f"  |  {leg.driving_time_h:,.2f} h driving"
                f"  |  {leg.buffer_time_h:,.2f} h buffer"
                f"  |  {leg.avg_speed_kmh:,.1f} km/h"
                f"  |  {leg.energy_kwh:,.1f} kWh"
                f"  |  {leg.tac_eur:,.0f} € TAC"
            )
            for cl in leg.country_legs:
                lines.append(
                    f"    [{cl.country_code}]"
                    f"  {cl.distance_km:,.1f} km"
                    f"  {cl.driving_time_h:,.2f} h"
                    f"  {cl.buffer_time_h:,.2f} h buf"
                    f"  {cl.energy_kwh:,.1f} kWh"
                    f"  {cl.tac_eur:,.0f} € TAC"
                )
        lines += ["", "--- Countries ---"]
        for c in sorted(self.countries, key=lambda x: -x.distance_km):
            lines.append(
                f"  {c.country_code}"
                f"  {c.distance_km:>8,.1f} km"
                f"  {c.driving_time_h:>6,.2f} h"
                f"  {c.buffer_time_h:>5,.2f} h buf"
                f"  {c.energy_kwh:>8,.1f} kWh"
                f"  {c.tac_eur:>8,.0f} € TAC"
            )
        return "\n".join(lines)

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres between two WGS-84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _haversine_path_m(coords: list[list[float]]) -> float:
    """Sum of haversine distances along a [lon, lat] coordinate list."""
    total = 0.0
    for i in range(len(coords) - 1):
        total += _haversine_m(
            coords[i][0],     coords[i][1],
            coords[i + 1][0], coords[i + 1][1],
        )
    return total


def _ms_m_to_kmh(distance_m: float, duration_ms: int) -> float:
    """Convert metres + milliseconds to km/h."""
    if duration_ms <= 0:
        return 0.0
    return (distance_m / 1000) / (duration_ms / 3_600_000)

def _bbox_area(ring: list) -> float:
    """Bounding box area of a coordinate ring — used to find largest polygon."""
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return (max(lons) - min(lons)) * (max(lats) - min(lats))

# ---------------------------------------------------------------------------
# Country index
# ---------------------------------------------------------------------------

_COUNTRIES_PATH = Path(__file__).parent / "countries.geojson"


class CountryIndex:
    """
    Loads a GeoJSON country borders file and provides point-in-polygon lookup.
    Uses shapely if available (fast), otherwise pure-Python ray-casting (slow).
    On first use the GeoJSON is downloaded and cached next to this file.
    """

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
                f"Country borders file not found at {path}. "
                f"Download it from:\n"
                f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector"
                f"/master/geojson/ne_110m_admin_0_countries.geojson\n"
                f"and save it as {path.name} in {path.parent}"
            )
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(data["features"])

    def lookup(self, lon: float, lat: float) -> str | None:
        """Return ISO 3166-1 alpha-3 code for the country at (lon, lat)."""
        from shapely.geometry import Point
        pt = Point(lon, lat)
        for iso3, shape in self._shapes:
            if shape.contains(pt):
                return iso3
        return None

    def get_largest_polygon(self, iso3: str) -> list | None:
        """
        Return the coordinate ring of the largest polygon for a country.
        For Polygon geometries, returns the outer ring directly.
        For MultiPolygon geometries, returns the outer ring of the largest polygon.
        Coordinates are in [lon, lat] order as required by GraphHopper areas.
        """
        for feature in self._features:
            if feature["properties"].get("ADM0_A3") != iso3:
                continue
            geom = feature["geometry"]
            if geom["type"] == "Polygon":
                return geom["coordinates"][0]
            elif geom["type"] == "MultiPolygon":
                largest = max(
                    geom["coordinates"],
                    key=lambda poly: _bbox_area(poly[0]),
                )
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
    Parameters
    ----------
    base_url : str
        Base URL of the routing engine. Default: "http://localhost:8989".
    profile : str
        GraphHopper profile name. Must match config.yml. Default: "night_train".
    timeout : int
        HTTP request timeout in seconds.
    """

    ROUTE_ENDPOINT = "/route"
    INFO_ENDPOINT  = "/info"
    DETAILS = ["leg_distance", "leg_time", "time"]

    def __init__(
        self,
        base_url: str = "http://localhost:8989",
        profile: str  = "night_train",
        timeout: int  = 30,
    ) -> None:
        self.base_url        = base_url.rstrip("/")
        self.profile         = profile
        self.timeout         = timeout
        self._session = requests.Session()
        self._country_index: CountryIndex = CountryIndex.load()

    def check_server(self) -> dict:
        """GET /info — confirm server is up."""
        resp = self._session.get(
            f"{self.base_url}{self.INFO_ENDPOINT}",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _build_custom_model(
            self,
            vehicle_max_speed_kmh: int | None,
            avoid_high_speed_lines: dict[str, bool] | None,
    ) -> dict | None:
        """
        Build a GraphHopper custom_model dict for runtime routing overrides.

        Parameters
        ----------
        vehicle_max_speed_kmh : int | None
            Caps the speed used for routing. e.g. 160 for a slower loco.
        avoid_high_speed_lines : dict[str, bool] | None
            Per-country flag to avoid tracks with max_speed > 250 km/h.
            e.g. {"FRA": True, "ESP": True, "DEU": False}
        """
        speed_rules = []
        priority_rules = []
        areas = {}

        # --- speed cap --------------------------------------------------------
        if vehicle_max_speed_kmh is not None:
            speed_rules.append({
                "if": "true",
                "limit_to": str(vehicle_max_speed_kmh),
            })

        # --- per-country HSR avoidance ----------------------------------------
        if avoid_high_speed_lines:
            for country_code, avoid in avoid_high_speed_lines.items():
                if not avoid:
                    continue
                iso3 = _ISO2_TO_ISO3.get(country_code, country_code)
                ring = self._country_index.get_largest_polygon(iso3)

                if ring is None:
                    logger.warning("No polygon found for country '%s' — skipping.", iso3)
                    continue

                # GraphHopper area rings must be closed (first == last point)
                closed_ring = ring if ring[0] == ring[-1] else ring + [ring[0]]

                area_name = f"hsr{iso3.lower()}"
                areas[area_name] = {
                    "type": "Feature",
                    "id": area_name,  # ← add this line
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [closed_ring],
                    },
                }

                # Avoid tracks with max_speed > 250 inside this country polygon
                priority_rules.append({
                    "if": f"in_{area_name}",
                    "multiply_by": "0.0001",  # strong penalty but not impassable
                })

        # --- assemble ---------------------------------------------------------
        if not speed_rules and not priority_rules:
            return None  # no custom model needed

        custom_model = {}
        if speed_rules:
            custom_model["speed"] = speed_rules
        if priority_rules:
            custom_model["priority"] = priority_rules
        if areas:
            custom_model["areas"] = {
                "type": "FeatureCollection",
                "features": list(areas.values()),
            }
        return custom_model

    def route(
            self,
            stops: list[Stop],
            composition: CompositionParams,
            infra: dict[str, InfraParams],
            departure_time_h: float,
    ) -> RouteResult:
        """
        Route a train trip and compute schedule, energy and TAC.

        Parameters
        ----------
        stops : list[Stop]
            Ordered stop list. Each stop has stop_type: "boarding"|"alighting"|"both".
        composition : CompositionParams
            Vehicle composition — drives routing constraints and energy model.
        infra : dict[str, InfraParams]
            Per-country infrastructure parameters keyed by alpha-2 country code.
        departure_time_h : float
            Departure time from the first stop in decimal hours (e.g. 21.067 for 21:04).
        """
        if len(stops) < 2:
            raise ValueError("At least 2 stops are required.")

        # Derive routing constraints from composition + infra
        vehicle_max_speed_kmh = int(composition.max_speed_kmh)
        avoid_high_speed_lines = {
            country_code: not (composition.hsr_allowed and ip.hsr_allowed)
            for country_code, ip in infra.items()
        }

        custom_model = self._build_custom_model(vehicle_max_speed_kmh, avoid_high_speed_lines)

        if custom_model:
            snap_payload = self._build_payload(stops, None, None)
            snap_raw = self._post_route(snap_payload)
            snapped_coords = snap_raw["paths"][0]["snapped_waypoints"]["coordinates"]
            snapped_stops_as_input = [
                Stop(
                    stop_id=stops[i].stop_id,
                    name=stops[i].name,
                    lat=snapped_coords[i][1],
                    lon=snapped_coords[i][0],
                    country_code=stops[i].country_code,
                    stop_type=stops[i].stop_type,
                )
                for i in range(len(stops))
            ]
            payload = self._build_payload(snapped_stops_as_input, vehicle_max_speed_kmh, avoid_high_speed_lines)
            raw = self._post_route(payload)
        else:
            payload = self._build_payload(stops, None, None)
            raw = self._post_route(payload)

        return self._parse_response(raw, stops, composition, infra, departure_time_h)

    def _build_payload(
            self,
            stops: list[Stop],
            vehicle_max_speed_kmh: int | None,
            avoid_high_speed_lines: dict[str, bool] | None,
    ) -> dict:
        payload: dict = {
            "profile": self.profile,
            "points": [[s.lon, s.lat] for s in stops],
            "points_encoded": False,
            "instructions": False,
            "details": self.DETAILS,
        }
        custom_model = self._build_custom_model(vehicle_max_speed_kmh, avoid_high_speed_lines)
        if custom_model:
            payload["custom_model"] = custom_model
            payload["ch.disable"] = True
        return payload

    def _post_route(self, payload: dict) -> dict:
        url = f"{self.base_url}{self.ROUTE_ENDPOINT}"
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            try:
                msg = resp.json().get("message", resp.text)
            except Exception:
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
            stops: list[Stop],
            composition: CompositionParams,
            infra: dict[str, InfraParams],
            departure_time_h: float,
    ) -> RouteResult:
        path = body["paths"][0]

        geometry: dict = path["points"]
        coords: list[list[float]] = geometry["coordinates"]

        total_distance_m: float = path["distance"]
        total_duration_ms: int = int(path["time"])

        snapped_coords = path["snapped_waypoints"]["coordinates"]
        snapped_stops = self._parse_snapped_stops(stops, snapped_coords)

        details = path.get("details", {})
        leg_distance_detail = details.get("leg_distance", [])
        leg_time_detail = details.get("leg_time", [])
        time_detail = details.get("time", [])

        # Single shapely pass — all country attribution reuses these intervals
        intervals = self._compute_country_intervals(coords, time_detail)

        # Build RouteSegments with country legs, energy and TAC attached
        legs = self._parse_legs(
            stops, snapped_stops, coords,
            leg_distance_detail, leg_time_detail,
            intervals, composition, infra,
        )

        # Aggregate country segments from country legs across all route segments
        countries = self._compute_countries(legs)

        # Build schedule from stops + legs + composition + infra
        schedule = self._compute_schedule(
            snapped_stops, legs, composition, infra, departure_time_h
        )

        return RouteResult(
            stops=snapped_stops,
            legs=legs,
            countries=countries,
            schedule=schedule,
            total_distance_m=total_distance_m,
            total_duration_ms=total_duration_ms,
            geometry=geometry,
            coords=coords,
            leg_distance_detail=leg_distance_detail,
        )

    @staticmethod
    def _parse_snapped_stops(stops, snapped_coords):
        result = []
        for i, stop in enumerate(stops):
            if i < len(snapped_coords):
                lon, lat = snapped_coords[i][0], snapped_coords[i][1]
            else:
                lon, lat = stop.lon, stop.lat
                logger.warning("No snapped coordinate for stop '%s'.", stop.name)
            result.append(SnappedStop(
                stop=stops[i],
                snapped_lat=lat,
                snapped_lon=lon,
            ))
        return result

    @staticmethod
    def _parse_legs(
            stops,
            snapped_stops,
            coords,
            leg_distance_detail,
            leg_time_detail,
            intervals,
            composition: CompositionParams,
            infra: dict[str, InfraParams],
    ):
        legs = []
        for i in range(len(stops) - 1):
            if i < len(leg_distance_detail):
                from_idx = leg_distance_detail[i][0]
                to_idx = leg_distance_detail[i][1]
                distance_m = float(leg_distance_detail[i][2])
            else:
                from_idx, to_idx, distance_m = 0, len(coords) - 1, 0.0
                logger.warning("leg_distance detail missing for leg %d.", i)

            if i < len(leg_time_detail):
                duration_ms = int(leg_time_detail[i][2])
            else:
                duration_ms = 0
                logger.warning("leg_time detail missing for leg %d.", i)

            # --- attribute country legs for this segment ---
            leg_country_distance: dict[str, float] = defaultdict(float)
            leg_country_duration: dict[str, float] = defaultdict(float)

            for iv_from, iv_to, country_code, dist_m, iv_ms in intervals:
                overlap_from = max(iv_from, from_idx)
                overlap_to = min(iv_to, to_idx)
                if overlap_from >= overlap_to:
                    continue
                interval_span = iv_to - iv_from
                overlap_span = overlap_to - overlap_from
                fraction = overlap_span / interval_span if interval_span > 0 else 1.0
                leg_country_distance[country_code] += dist_m * fraction
                leg_country_duration[country_code] += iv_ms * fraction

            # --- build CountryLeg objects ---
            country_legs = []
            for country_code, dist_m in leg_country_distance.items():
                cl_duration_ms = leg_country_duration[country_code]
                cl_distance_km = dist_m / 1000
                cl_driving_h = cl_duration_ms / 3_600_000
                cl_speed = cl_distance_km / cl_driving_h if cl_driving_h > 0 else 0.0

                ip = infra.get(country_code)
                if ip is None:
                    default_ip = infra.get("_default")
                    if default_ip is not None:
                        logger.warning(
                            "No infra params for country '%s' — using _default values.",
                            country_code,
                        )
                        ip = default_ip
                    else:
                        logger.warning(
                            "No infra params for country '%s' and no _default — TAC, energy and buffer set to 0.",
                            country_code,
                        )

                if ip is None:
                    buffer_h = 0.0
                    energy_kwh = 0.0
                    tac_eur = 0.0
                    tac_eur_km = 0.0
                    energy_km = 0.0
                else:
                    buffer_h = cl_driving_h * ip.buffer_quota_per
                    energy_kwh = (
                            composition.weight_gross_t
                            * cl_distance_km
                            * (
                                    composition.energy_factor_weight
                                    + composition.energy_factor_speed * cl_speed ** 2
                                    + composition.energy_factor_terrain * ip.terrain_score
                            )
                    )
                    tac_eur = ip.tac_eur_train_km * cl_distance_km
                    tac_eur_km = ip.tac_eur_train_km
                    energy_km = energy_kwh / cl_distance_km if cl_distance_km > 0 else 0.0

                country_legs.append(CountryLeg(
                    from_stop_id=snapped_stops[i].stop.stop_id,
                    to_stop_id=snapped_stops[i + 1].stop.stop_id,
                    country_code=country_code,
                    distance_km=cl_distance_km,
                    driving_time_h=cl_driving_h,
                    avg_speed_kmh=cl_speed,
                    buffer_time_h=buffer_h,
                    energy_kwh=energy_kwh,
                    energy_kwh_per_km=energy_km,
                    tac_eur=tac_eur,
                    tac_eur_per_km=tac_eur_km,
                ))

            legs.append(RouteSegment(
                from_stop=snapped_stops[i],
                to_stop=snapped_stops[i + 1],
                distance_m=distance_m,
                duration_ms=duration_ms,
                avg_speed_kmh=_ms_m_to_kmh(distance_m, duration_ms),
                geometry=coords[from_idx: to_idx + 1],
                country_legs=country_legs,
            ))

        return legs

    def _compute_country_intervals(
            self,
            coords: list[list[float]],
            time_detail: list,
    ) -> list[tuple[int, int, str, float, int]]:
        """
        Walk the full route geometry once and return a list of intervals:
            (from_idx, to_idx, country_code, distance_m, duration_ms)
        One entry per time_detail segment, tagged with alpha-2 country code.
        This is the single shapely pass — all other methods reuse this data.
        """

        intervals = []
        for entry in time_detail:
            from_idx, to_idx, interval_ms = entry[0], entry[1], entry[2]

            segment = coords[from_idx: to_idx + 1]
            dist_m = _haversine_path_m(segment)

            mid_idx = (from_idx + to_idx) // 2
            iso3 = self._country_index.lookup(coords[mid_idx][0], coords[mid_idx][1]) or "UNK"
            country_code = _ISO3_TO_ISO2.get(iso3, iso3)

            intervals.append((from_idx, to_idx, country_code, dist_m, interval_ms))

        return intervals

    @staticmethod
    def _compute_countries(legs: list[RouteSegment]) -> list[CountrySegment]:
        """
        Aggregate CountryLeg objects from all RouteSegments into one
        CountrySegment per country, preserving route order.
        """
        country_legs: dict[str, list[CountryLeg]] = {}

        for leg in legs:
            for cl in leg.country_legs:
                if cl.country_code not in country_legs:
                    country_legs[cl.country_code] = []
                country_legs[cl.country_code].append(cl)

        return [
            CountrySegment(
                country_code=country_code,
                country_legs=cls,
            )
            for country_code, cls in country_legs.items()
        ]

    @staticmethod
    def _compute_schedule(
            snapped_stops: list[SnappedStop],
            legs: list[RouteSegment],
            composition: CompositionParams,
            infra: dict[str, InfraParams],
            departure_time_h: float,
    ) -> list[ScheduleStop]:
        """
        Build the full schedule table from snapped stops and route segments.

        Dwell time at each stop is:
            max(
                comp.min_boarding_time_h  if boarding stop,
                comp.min_alighting_time_h if alighting stop,
                infra.min_boarding_time_h  if boarding stop,
                infra.min_alighting_time_h if alighting stop,
            )

        Driving time per leg is the pure engine time from GraphHopper.
        Buffer time per leg is the sum of country-level buffers.
        Clock times are accumulated from departure_time_h forward.
        """
        schedule = []
        current_time_h = departure_time_h

        for i, snapped_stop in enumerate(snapped_stops):
            stop = snapped_stop.stop
            stop_type = stop.stop_type

            is_first = (i == 0)
            is_last = (i == len(snapped_stops) - 1)

            incoming_leg = legs[i - 1] if not is_first else None
            outgoing_leg = legs[i] if not is_last else None

            # --- arrival time ---
            arrival_time_h: float | None = None if is_first else current_time_h

            # --- dwell time ---
            dwell_time_h: float | None = None
            if not is_first and not is_last:
                ip = infra.get(stop.country_code)
                candidates: list[float] = []
                if stop_type in ("boarding", "both"):
                    candidates.append(composition.min_boarding_time_h)
                    if ip:
                        candidates.append(ip.min_boarding_time_h)
                if stop_type in ("alighting", "both"):
                    candidates.append(composition.min_alighting_time_h)
                    if ip:
                        candidates.append(ip.min_alighting_time_h)
                dwell_time_h = max(candidates) if candidates else 0.0

            # --- departure time ---
            departure_time_h_stop: float | None = None
            if not is_last:
                if is_first:
                    departure_time_h_stop = current_time_h
                else:
                    assert arrival_time_h is not None
                    assert dwell_time_h is not None
                    departure_time_h_stop = arrival_time_h + dwell_time_h
                current_time_h = departure_time_h_stop

            # --- advance clock by outgoing leg total time ---
            if outgoing_leg is not None and departure_time_h_stop is not None:
                current_time_h = (departure_time_h_stop
                                  + outgoing_leg.driving_time_h
                                  + outgoing_leg.buffer_time_h)

            schedule.append(ScheduleStop(
                snapped_stop=snapped_stop,
                stop_type=stop_type,
                arrival_time_h=arrival_time_h,
                departure_time_h=departure_time_h_stop,
                dwell_time_h=dwell_time_h,
                incoming_leg=incoming_leg,
                outgoing_leg=outgoing_leg,
            ))

        return schedule


# ---------------------------------------------------------------------------
# Dict export for night train model
# ---------------------------------------------------------------------------

def route_result_to_dict(result: RouteResult) -> dict:
    """
    Plain dict export for JSON serialisation.
    """
    return {
        "total_distance_km":    result.total_distance_km,
        "total_driving_time_h": result.total_driving_time_h,
        "total_buffer_time_h":  result.total_buffer_time_h,
        "total_time_h":         result.total_time_h,
        "avg_speed_kmh":        result.avg_speed_kmh,
        "total_energy_kwh":     result.total_energy_kwh,
        "total_tac_eur":        result.total_tac_eur,
        "schedule": [
            {
                "stop_id":            s.stop_id,
                "stop_name":          s.stop_name,
                "stop_type":          s.stop_type,
                "arrival_time_h":     s.arrival_time_h,
                "departure_time_h":   s.departure_time_h,
                "dwell_time_h":       s.dwell_time_h,
                "arrival_time_fmt":   s.format_time(s.arrival_time_h),
                "departure_time_fmt": s.format_time(s.departure_time_h),
            }
            for s in result.schedule
        ],
        "legs": [
            {
                "from_stop_id":    leg.from_stop.stop.stop_id,
                "from_stop_name":  leg.from_stop.stop.name,
                "to_stop_id":      leg.to_stop.stop.stop_id,
                "to_stop_name":    leg.to_stop.stop.name,
                "distance_km":     leg.distance_km,
                "driving_time_h":  leg.driving_time_h,
                "buffer_time_h":   leg.buffer_time_h,
                "total_time_h":    leg.total_time_h,
                "avg_speed_kmh":   leg.avg_speed_kmh,
                "energy_kwh":      leg.energy_kwh,
                "tac_eur":         leg.tac_eur,
                "country_legs": [
                    {
                        "country_code":     cl.country_code,
                        "distance_km":      cl.distance_km,
                        "driving_time_h":   cl.driving_time_h,
                        "buffer_time_h":    cl.buffer_time_h,
                        "avg_speed_kmh":    cl.avg_speed_kmh,
                        "energy_kwh":       cl.energy_kwh,
                        "energy_kwh_per_km":cl.energy_kwh_per_km,
                        "tac_eur":          cl.tac_eur,
                        "tac_eur_per_km":   cl.tac_eur_per_km,
                    }
                    for cl in leg.country_legs
                ],
            }
            for leg in result.legs
        ],
        "countries": [
            {
                "country_code":   c.country_code,
                "distance_km":    c.distance_km,
                "driving_time_h": c.driving_time_h,
                "buffer_time_h":  c.buffer_time_h,
                "total_time_h":   c.total_time_h,
                "avg_speed_kmh":  c.avg_speed_kmh,
                "energy_kwh":     c.energy_kwh,
                "tac_eur":        c.tac_eur,
            }
            for c in result.countries
        ],
        "geometry": result.geometry,
    }