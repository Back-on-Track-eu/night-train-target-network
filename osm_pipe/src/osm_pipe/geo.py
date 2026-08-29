"""Bounding boxes and great-circle distance.

Ported from `railnet.projects.BBox` unchanged apart from the range check —
lat/lon bounds were unvalidated, so a transposed box (lon, lat, lon, lat) got
through and scoped a rule to open ocean.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

EARTH_R = 6_371_008.8


@dataclass(frozen=True)
class BBox:
    """South, west, north, east — the order Overpass and Leaflet both use."""

    south: float
    west: float
    north: float
    east: float

    @classmethod
    def parse(cls, raw: Any, *, context: str = "") -> "BBox":
        where = f" ({context})" if context else ""
        if isinstance(raw, BBox):
            return raw
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            raise ValueError(
                f"bbox must be [south, west, north, east]{where}, got {raw!r}"
            )
        south, west, north, east = (float(v) for v in raw)
        if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
            raise ValueError(
                f"bbox latitudes out of range{where}: {raw!r}. The order is "
                "[south, west, north, east] — a transposed box is the usual cause."
            )
        if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0):
            raise ValueError(f"bbox longitudes out of range{where}: {raw!r}")
        if south > north or west > east:
            raise ValueError(f"bbox is inside out{where}: {raw!r}")
        return cls(south, west, north, east)

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    def as_list(self) -> list[float]:
        return [self.south, self.west, self.north, self.east]

    def union(self, other: "BBox") -> "BBox":
        return BBox(
            min(self.south, other.south),
            min(self.west, other.west),
            max(self.north, other.north),
            max(self.east, other.east),
        )


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Metres between two (lat, lon) pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_R * math.asin(math.sqrt(h))
