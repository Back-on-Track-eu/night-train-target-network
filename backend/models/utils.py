"""
utils.py
========
Shared utilities for the Night Train model.

Sections
--------
  Unit conversions     — distance, time, speed
  Geography            — haversine distance, bbox area
  Country code lookup  — ISO 3166-1 alpha-2 ↔ alpha-3 conversion
"""

from __future__ import annotations

import math
from typing import Optional

# =============================================================================
# UNIT CONVERSIONS
# =============================================================================


def min_to_hhmm(minutes: Optional[int]) -> Optional[str]:
    """
    Convert minutes-from-midnight to HH:MM string, handling overnight.

    e.g. 1260 → "21:00"
         1920 → "08:00 (+1d)"
         2880 → "00:00 (+2d)"
    """
    if minutes is None:
        return None
    days = minutes // 1440
    h = (minutes % 1440) // 60
    m = minutes % 60
    day_s = f" (+{days}d)" if days > 0 else ""
    return f"{h:02d}:{m:02d}{day_s}"


def hhmm_to_min(hhmm: str) -> int:
    """
    Parse HH:MM departure string to minutes from midnight.

    Supports overnight times up to 47:59 (end of second operating day).
    Night trains commonly depart at e.g. 25:30 (= 01:30 next day).

    e.g. "20:00" → 1200
         "08:30" → 510
         "25:30" → 1530  (01:30 next day)
    Raises ValueError for invalid format.
    """
    parts = hhmm.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM string: '{hhmm}'")
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"Invalid HH:MM string: '{hhmm}'")
    if not (0 <= h <= 47 and 0 <= m <= 59):
        raise ValueError(f"HH:MM out of range (must be 00:00-47:59): '{hhmm}'")
    return h * 60 + m


def min_to_h(minutes: Optional[int]) -> Optional[float]:
    """Convert minutes to decimal hours. Returns None if input is None."""
    if minutes is None:
        return None
    return minutes / 60.0


def h_to_min(hours: float) -> int:
    """Convert decimal hours to whole minutes (rounded)."""
    return round(hours * 60)


def ms_to_min(ms: int | float) -> int:
    """Convert milliseconds to whole minutes (rounded)."""
    return round(ms / 60_000)


def m_to_km(metres: int) -> float:
    """Convert metres to kilometres."""
    return metres / 1000.0


def km_to_m(km: float) -> int:
    """Convert kilometres to metres (rounded)."""
    return round(km * 1000)


# =============================================================================
# GEOGRAPHY
# =============================================================================

_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres between two WGS-84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def haversine_path_m(coords: list[list[float]]) -> float:
    """Total haversine distance in metres along a sequence of [lon, lat] coords."""
    total = 0.0
    for i in range(len(coords) - 1):
        total += haversine_m(
            coords[i][0],
            coords[i][1],
            coords[i + 1][0],
            coords[i + 1][1],
        )
    return total


def bbox_area(ring: list) -> float:
    """Bounding-box area of a polygon ring — used for largest-polygon selection."""
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return (max(lons) - min(lons)) * (max(lats) - min(lats))


# =============================================================================
# COUNTRY CODE CONVERSION  (ISO 3166-1 alpha-3 ↔ alpha-2)
# =============================================================================

ISO3_TO_ISO2: dict[str, str] = {
    "AUT": "AT",
    "BEL": "BE",
    "BGR": "BG",
    "HRV": "HR",
    "CZE": "CZ",
    "DNK": "DK",
    "FIN": "FI",
    "FRA": "FR",
    "DEU": "DE",
    "GRC": "GR",
    "HUN": "HU",
    "IRL": "IE",
    "ITA": "IT",
    "LUX": "LU",
    "NLD": "NL",
    "NOR": "NO",
    "POL": "PL",
    "PRT": "PT",
    "ROU": "RO",
    "SVK": "SK",
    "SVN": "SI",
    "ESP": "ES",
    "SWE": "SE",
    "CHE": "CH",
    "GBR": "GB",
    "SRB": "RS",
    "MKD": "MK",
    "MNE": "ME",
    "BIH": "BA",
    "ALB": "AL",
    "UKR": "UA",
    "TUR": "TR",
}

ISO2_TO_ISO3: dict[str, str] = {v: k for k, v in ISO3_TO_ISO2.items()}
