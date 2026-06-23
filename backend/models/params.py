"""
params.py
=========
Shared parameter dataclasses and collection classes for the night train model.

Each domain has two classes:
  - A dataclass holding the parameters for one item (CompositionParams, InfraParams, etc.)
  - A collection class holding a dict of items with lookup helpers (CompositionCollection, etc.)

These are loaded once from Google Sheets by SheetDataLoader and passed to
both the routing engine and the cost model. No calculation logic lives here.

Import path: from params import CompositionParams, CompositionCollection, ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# =============================================================================
# COMPOSITION
# =============================================================================


@dataclass
class CompositionParams:
    """
    Full parameter set for one train composition.
    Loaded from the c_compositions sheet.

    Routing-relevant fields are consumed by rail_router.py.
    Cost-relevant fields are consumed by run_model.py.
    """

    # --- identity ---
    comp_id: str
    comp_description: str = ""
    company: str = ""

    # --- routing ---
    weight_gross_t: float = 0.0
    max_speed_kmh: float = 0.0
    hsr_allowed: bool = False
    min_boarding_time_h: float = 0.0
    min_alighting_time_h: float = 0.0

    # --- energy model ---
    energy_factor_weight: float = 0.0
    energy_factor_speed: float = 0.0
    energy_factor_terrain: float = 0.0

    # --- capacity ---
    seats_total: int = 0
    couchettes_total: int = 0
    sleepers_total: int = 0

    # --- space density (space weight per berth = 1 / berths_per_coach) ---
    seat_density: float = 0.0
    couchette_density: float = 0.0
    sleeper_density: float = 0.0

    # --- target margin ---
    ebit_margin_per: float = 0.0

    # --- fixed costs per operating day ---
    purchase_loco_eur: float = 0.0
    purchase_coach_eur: float = 0.0
    loco_avail_per: float = 0.0
    coach_avail_per: float = 0.0
    loco_amort_years: float = 0.0
    coach_amort_years: float = 0.0
    financing_quota_per: float = 0.0
    fix_overhead_quota_per: float = 0.0
    cleaning_services_eur_day: float = 0.0
    shunting_eur_day: float = 0.0

    # --- variable costs per km ---
    loco_maint_eur_km: float = 0.0
    coach_maint_eur_km: float = 0.0

    # --- variable costs per hour ---
    driver_costs_eur_h: float = 0.0
    crew_costs_eur_h: float = 0.0
    driver_overhead_h: float = 0.0
    crew_overhead_h: float = 0.0

    # --- variable costs per ticket sold (as fraction of ticket revenue) ---
    svc_stockings_seat_per: float = 0.0
    svc_stockings_couchette_per: float = 0.0
    svc_stockings_sleeper_per: float = 0.0
    var_overhead_per: float = 0.0


class CompositionCollection:
    """Collection of CompositionParams keyed by comp_id."""

    def __init__(self, items: dict[str, CompositionParams]) -> None:
        self._items = items

    def get(self, comp_id: str) -> Optional[CompositionParams]:
        """Return CompositionParams for a comp_id, or None if not found."""
        return self._items.get(comp_id)

    def get_or_default(self, comp_id: str) -> Optional[CompositionParams]:
        """Return CompositionParams for comp_id, falling back to '_default'."""
        return self._items.get(comp_id) or self._items.get("_default")

    def all(self) -> dict[str, CompositionParams]:
        return dict(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, comp_id: str) -> bool:
        return comp_id in self._items


# =============================================================================
# INFRASTRUCTURE
# =============================================================================


@dataclass
class InfraParams:
    """
    Per-country infrastructure parameters.
    Loaded from the c_infrastructure sheet.
    Keyed by ISO 3166-1 alpha-2 country code.
    """

    country_code: str

    # --- routing ---
    hsr_allowed: bool = False
    min_boarding_time_h: float = 0.0
    min_alighting_time_h: float = 0.0
    buffer_quota_per: float = 0.0

    # --- energy model ---
    terrain_score: float = 0.0
    terrain_category: str = ""

    # --- infrastructure costs ---
    tac_eur_train_km: float = 0.0
    parking_eur_day: float = 0.0
    energy_price_eur_kwh: float = 0.0


class InfraCollection:
    """Collection of InfraParams keyed by alpha-2 country code."""

    def __init__(self, items: dict[str, InfraParams]) -> None:
        self._items = items

    def get(self, country_code: str) -> Optional[InfraParams]:
        """Return InfraParams for a country code, or None if not found."""
        return self._items.get(country_code)

    def get_or_default(self, country_code: str) -> Optional[InfraParams]:
        """
        Return InfraParams for a country code.
        Falls back to '_default' entry if not found, logging a warning.
        """
        ip = self._items.get(country_code)
        if ip is None:
            default = self._items.get("_default")
            if default is not None:
                import logging

                logging.getLogger(__name__).warning(
                    "No infra params for country '%s' — using _default values.",
                    country_code,
                )
            return default
        return ip

    def all(self) -> dict[str, InfraParams]:
        return dict(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, country_code: str) -> bool:
        return country_code in self._items


# =============================================================================
# STOP
# =============================================================================


@dataclass
class StopParams:
    """
    Cost-relevant parameters for one stop.
    Loaded from the c_stops sheet.

    Routing-relevant stop data (lat, lon, name, country_code) lives on
    the Stop dataclass in rail_router.py.
    """

    stop_id: str
    stop_name: str = ""
    stop_country_code: str = ""
    lat: float = 0.0
    lon: float = 0.0
    stop_charge_eur: float = 0.0


class StopCollection:
    """Collection of StopParams keyed by stop_id."""

    def __init__(self, items: dict[str, StopParams]) -> None:
        self._items = items

    def get(self, stop_id: str) -> Optional[StopParams]:
        """Return StopParams for a stop_id, or None if not found."""
        return self._items.get(stop_id)

    def get_or_default(self, stop_id: str) -> Optional[StopParams]:
        """Return StopParams for a stop_id, falling back to '_default'."""
        return self._items.get(stop_id) or self._items.get("_default")

    def get_charge(self, stop_id: str) -> float:
        """
        Return the station access charge for a stop.
        Returns 0.0 if stop not found and no default exists.
        """
        sp = self.get_or_default(stop_id)
        return sp.stop_charge_eur if sp is not None else 0.0

    def all(self) -> dict[str, StopParams]:
        return dict(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, stop_id: str) -> bool:
        return stop_id in self._items


# =============================================================================
# DEMAND
# =============================================================================


@dataclass
class DemandParams:
    """
    Demand data for one OD pair.
    Loaded from the demand sheet.

    Market shares are runtime inputs and live on ODPair in run_model.py.
    """

    relation_id: str
    origin_stop_id: str = ""
    destination_stop_id: str = ""
    demand_type: str = ""
    demand_seat_pax: float = 0.0
    demand_couchette_pax: float = 0.0
    demand_sleeper_pax: float = 0.0


class DemandCollection:
    """Collection of DemandParams keyed by relation_id."""

    def __init__(self, items: dict[str, DemandParams]) -> None:
        self._items = items

    def get(self, relation_id: str) -> Optional[DemandParams]:
        """Return DemandParams for a relation_id, or None if not found."""
        return self._items.get(relation_id)

    def get_or_default(self, relation_id: str) -> Optional[DemandParams]:
        """Return DemandParams for a relation_id, falling back to '_default'."""
        return self._items.get(relation_id) or self._items.get("_default")

    def find(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
    ) -> Optional[DemandParams]:
        """Find a demand row by origin and destination stop ID."""
        for dp in self._items.values():
            if (
                dp.origin_stop_id == origin_stop_id
                and dp.destination_stop_id == destination_stop_id
            ):
                return dp
        return None

    def find_or_default(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
    ) -> Optional[DemandParams]:
        """Find a demand row by OD pair, falling back to '_default'."""
        dp = self.find(origin_stop_id, destination_stop_id)
        return dp if dp is not None else self._items.get("_default")

    def all(self) -> dict[str, DemandParams]:
        return dict(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, relation_id: str) -> bool:
        return relation_id in self._items
