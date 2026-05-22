
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Stop:
    id: int
    name: str
    lat: float
    lon: float

@dataclass
class LegResult:
    origin:        Stop
    destination:   Stop
    distance_km:   float
    travel_time_h: float
    avg_speed_kmh: float
    geometry:      list[tuple[float, float]]   # (lon, lat) pairs
