"""
params.py
=========
Domain parameter dataclasses for the Night Train model.

These are the typed representations of rows from input_params.* DB tables.
Populated exclusively by DBDataLoader (adapters/data_loader_from_db.py).
Shared across models/route/, models/cost_rev_eval/, and models/energy/.

Classes
-------
  CompositionParams    — one composition (identity + routing + cost params)
  CompositionCollection
  InfraParams          — per-country infrastructure parameters
  InfraCollection
  StopParams           — one stop (identity + location + charge)
  StopCollection
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# =============================================================================
# COMPOSITION PARAMS
# =============================================================================

@dataclass
class CompositionParams:
    """
    All parameters for one train composition.

    Populated by DBDataLoader.build_composition() from four tables:
    compositions, operators, coachtypes, coachtype_classes.

    Fields marked # routing are used by rail_router.py.
    Fields marked # cost are used by models/cost_rev_eval/calc.py.
    Fields marked # energy are used by models/energy/calc_energy_consumption.py.
    """

    # identity
    comp_id:          str
    comp_description: str
    company:          str   # operator_id

    # routing
    weight_gross_t:       float
    max_speed_kmh:        float
    hsr_allowed:          bool
    min_boarding_time_h:  float
    min_alighting_time_h: float

    # energy
    energy_factor_weight:  float
    energy_factor_speed:   float
    energy_factor_terrain: float

    # capacity (derived from coach breakdown)
    seats_total:      int
    couchettes_total: int
    sleepers_total:   int

    # density (1/places for first coach of each class — for cost allocation)
    seat_density:      float
    couchette_density: float
    sleeper_density:   float

    # operator-level cost params
    ebit_margin_per:        float
    financing_quota_per:    float
    fix_overhead_quota_per: float
    var_overhead_per:       float
    driver_costs_eur_h:     float
    crew_costs_eur_h:       float
    driver_overhead_h:      float
    crew_overhead_h:        float
    shunting_eur_day:       float

    # composition-level cost params
    purchase_loco_eur:         float
    purchase_coach_eur:        float
    loco_avail_per:            float
    coach_avail_per:           float
    loco_amort_years:          float
    coach_amort_years:         float
    cleaning_services_eur_day: float
    loco_maint_eur_km:         float
    coach_maint_eur_km:        float

    # per-class service stocking costs
    svc_stockings_seat_per:      float
    svc_stockings_couchette_per: float
    svc_stockings_sleeper_per:   float

    @classmethod
    def from_display_dict(cls, d: dict) -> "CompositionParams":
        """
        Reconstruct a CompositionParams stub from the display-only subset
        serialised by Trip.to_dict()["composition"].

        All cost/routing/energy fields that are NOT in the display dict are
        filled with sentinel zeros — they are never read from this stub because
        evaluate_route() always re-loads the full CompositionParams from the DB
        via loader.build_composition(comp_id) before any cost calculation.

        This exists solely so that Route.from_dict() → Trip.from_dict() can
        round-trip the route object through the API without carrying the full
        32-field params payload in every response body.
        """
        return cls(
            comp_id          = d["comp_id"],
            comp_description = d.get("comp_description", ""),
            company          = d.get("operator_id", ""),
            # capacity — present in display dict
            seats_total      = d.get("seats_total", 0),
            couchettes_total = d.get("couchettes_total", 0),
            sleepers_total   = d.get("sleepers_total", 0),
            # routing — sentinel zeros; never used from stub
            weight_gross_t       = 0.0,
            max_speed_kmh        = 0.0,
            hsr_allowed          = False,
            min_boarding_time_h  = 0.0,
            min_alighting_time_h = 0.0,
            # energy — sentinel zeros
            energy_factor_weight  = 0.0,
            energy_factor_speed   = 0.0,
            energy_factor_terrain = 0.0,
            # density — sentinel zeros
            seat_density      = 0.0,
            couchette_density = 0.0,
            sleeper_density   = 0.0,
            # operator cost — sentinel zeros
            ebit_margin_per        = 0.0,
            financing_quota_per    = 0.0,
            fix_overhead_quota_per = 0.0,
            var_overhead_per       = 0.0,
            driver_costs_eur_h     = 0.0,
            crew_costs_eur_h       = 0.0,
            driver_overhead_h      = 0.0,
            crew_overhead_h        = 0.0,
            shunting_eur_day       = 0.0,
            # composition cost — sentinel zeros
            purchase_loco_eur         = 0.0,
            purchase_coach_eur        = 0.0,
            loco_avail_per            = 0.0,
            coach_avail_per           = 0.0,
            loco_amort_years          = 0.0,
            coach_amort_years         = 0.0,
            cleaning_services_eur_day = 0.0,
            loco_maint_eur_km         = 0.0,
            coach_maint_eur_km        = 0.0,
            # service stockings — sentinel zeros
            svc_stockings_seat_per      = 0.0,
            svc_stockings_couchette_per = 0.0,
            svc_stockings_sleeper_per   = 0.0,
        )


@dataclass
class CompositionCollection:
    """Dict-backed collection of CompositionParams keyed by comp_id."""
    _data: dict[str, CompositionParams]

    def __init__(self, data: dict[str, CompositionParams]) -> None:
        self._data = data

    def get(self, comp_id: str) -> Optional[CompositionParams]:
        return self._data.get(comp_id)

    def all(self) -> dict[str, CompositionParams]:
        return self._data

    def __len__(self) -> int:
        return len(self._data)


# =============================================================================
# INFRA PARAMS
# =============================================================================

@dataclass
class InfraParams:
    """
    Per-country infrastructure parameters.

    Populated by DBDataLoader.build_all_infra() from
    input_params.infrastructure and input_params.infrastructure_defaults.

    The _default key in InfraCollection is a fallback for countries
    not explicitly listed.
    """

    country_code:        str
    tac_eur_train_km:    float   # track access charge per train-km
    parking_eur_day:     float   # overnight stabling cost per day
    energy_price_eur_kwh: float  # electricity price per kWh
    terrain_score:       float   # topography factor for energy model
    terrain_category:    str     # human-readable terrain description
    hsr_allowed:         bool    # whether HSR lines may be used
    min_boarding_time_h: float   # minimum stop time for boarding
    min_alighting_time_h: float  # minimum stop time for alighting
    buffer_quota_per:    float   # buffer time as fraction of driving time


@dataclass
class InfraCollection:
    """Dict-backed collection of InfraParams keyed by country_code."""
    _data: dict[str, InfraParams]

    def __init__(self, data: dict[str, InfraParams]) -> None:
        self._data = data

    def get(self, country_code: str) -> Optional[InfraParams]:
        return self._data.get(country_code)

    def get_or_default(self, country_code: str) -> Optional[InfraParams]:
        """Return params for country_code, falling back to _default."""
        return self._data.get(country_code) or self._data.get("_default")

    def all(self) -> dict[str, InfraParams]:
        return self._data

    def __len__(self) -> int:
        return len(self._data)


# =============================================================================
# STOP PARAMS
# =============================================================================

@dataclass
class StopParams:
    """
    One stop — location and station access charge.

    Populated by DBDataLoader.build_all_stops() /
    DBDataLoader.build_all_stop_params() from input_params.stops.

    stop_charge_eur is an internal cost model field — NOT exposed in API
    responses. It is used exclusively by models/cost_rev_eval/calc.py.
    """

    stop_id:           str
    stop_name:         str
    stop_country_code: str
    lat:               float
    lon:               float
    stop_charge_eur:   float    # internal — not exposed in API responses


@dataclass
class StopCollection:
    """Dict-backed collection of StopParams keyed by stop_id."""
    _data: dict[str, StopParams]

    def __init__(self, data: dict[str, StopParams]) -> None:
        self._data = data

    def get(self, stop_id: str) -> Optional[StopParams]:
        return self._data.get(stop_id)

    def get_charge(self, stop_id: str) -> float:
        """Return stop_charge_eur for a stop, or 0.0 if not found."""
        sp = self._data.get(stop_id)
        return sp.stop_charge_eur if sp else 0.0

    def all(self) -> dict[str, StopParams]:
        return self._data

    def __len__(self) -> int:
        return len(self._data)