"""
params.py
=========
Domain parameter dataclasses for the Night Train model.

These are the typed representations of rows from input_params.* DB tables.
Populated exclusively by DBDataLoader (adapters/data_loader_from_db.py).
Shared across models/route/, models/evaluation/, and models/energy/.

DB table → domain class mapping
--------------------------------
  input_params.sources              → ParamsSource
  input_params.classes              → ServiceClass
  input_params.operators            → Operator
  input_params.operator_class_costs → Operator.svc_stockings_eur_place (dict)
  input_params.coachtypes           → CoachType
  input_params.coachtype_classes    → CoachClassAssignment (on CoachType)
  input_params.compositions         → CompositionType
  input_params.composition_coaches  → CompositionType.coaches (dict by position)
  Composition                       → fully resolved operational object
                                      built from CompositionType
  input_params.infrastructure       → TrackInfrastructure
  input_params.infrastructure_defaults → DefaultTrackInfra
  input_params.stops                → StopInfrastructure
  input_params.stop_defaults        → DefaultStopInfra

Provenance
----------
  TrackInfrastructure and StopInfrastructure carry a paired ParamsSource
  field per parameter value (e.g. tac_eur_train_km / tac_src). lat/lon
  share a single loc_src. Operator and CompositionType carry

  Composition carries no provenance — it is a derived object.

Default fallback
----------------
  TrackInfrastructure and StopInfrastructure accept None values for any
  numeric field. DefaultTrackInfra and DefaultStopInfra carry EU-average
  fallback values. TrackInfraCollection.get_or_default() and
  StopInfraCollection.get_or_default() resolve None fields against the
  relevant default object before returning to callers.

Collections
-----------
  TrackInfraCollection    — keyed by country_code, fully resolved rows
  StopInfraCollection     — keyed by stop_id, fully resolved rows
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# =============================================================================
# PARAMS SOURCE  (input_params.sources)
# =============================================================================

@dataclass
class ParamsSource:
    """
    One source document referenced by a parameter table row.

    Mirrors input_params.sources. Carried on parameter objects either as
    a list (row-level, for Operator/CompositionType) or as paired _src
    fields per parameter value (for TrackInfrastructure/StopInfrastructure).
    """

    source_id: int
    source_description: str
    source_url: Optional[str]  # URL to source document or dataset
    source_date: Optional[str]  # ISO date string (YYYY-MM-DD)

# =============================================================================
# MODEL VERSIONS
# =============================================================================

@dataclass
class ModelVersions:
    """
    Records which version of each model was used in a computation.

    Carried in RouteProvenance, returned alongside Route by route_factory
    (not stored on Trip). New models register themselves by adding a key —
    no structural change needed.

    Example:
        {
            "route_builder": "1.0.0",
            "energy_calc":   "1.0.0",
            "cost_rev_calc": "1.0.0",
            "demand_model":  "1.0.0",   # future
        }
    """

    versions: dict[str, str]

    def get(self, model_name: str) -> Optional[str]:
        """Return version string for a model, or None if not recorded."""
        return self.versions.get(model_name)

    def set(self, model_name: str, version: str) -> None:
        """Register a model version."""
        self.versions[model_name] = version

# =============================================================================
# PARAM VERSIONS
# =============================================================================

@dataclass
class ParamVersionEntry:
    """
    One captured parameter field — fully flat, directly jsonifiable.

    One entry per parameter field, keyed by "table_short:entity_id:field_name"
    in ParamVersions.entries, e.g.:
        "track_infra:DE:tac_eur_train_km"
        "stop_infra:DE_BERLIN_HBF:stop_charge_eur"
        "composition_type:STD-7.1:max_speed_kmh"
        "operator:STD:driver_costs_eur_h"
        "coach_type:type1:weight_gross_t"
    """

    value: object
    version: int
    source: Optional[ParamsSource] = field(default=None)
    description: Optional[str] = field(default=None)
    is_default: bool = field(default=False)
    # is_default=True means this value was resolved from a default row
    # because the country/stop-specific value was NULL in the database.

@dataclass
class ParamVersions:
    """
    Captures which version of each parameter row was used in a computation,
    together with full source provenance.

    Populated on the fly by the loader and route factory. Carried in
    RouteProvenance alongside ModelVersions (not stored on Trip), returned
    by route_factory so the caller has full parameter provenance to persist
    alongside the route.

    Keys follow the pattern "table_short:entity_id", e.g.:
        "track_infra:DE"            → TrackInfrastructure for Germany
        "stop_infra:DE_BERLIN_HBF"  → StopInfrastructure for Berlin Hbf
        "composition_type:STD-7.1"  → CompositionType STD-7.1
        "coach_type:WLABmz"         → CoachType WLABmz
        "operator:STD"              → Operator STD
    """

    entries: dict[str, ParamVersionEntry] = field(default_factory=dict)

    def add(
        self,
        key: str,
        value: object,
        version: int,
        source: Optional[ParamsSource] = None,
        description: Optional[str] = None,
        is_default: bool = False,
    ) -> None:
        """Register one parameter field. Safe to call multiple times — last write wins."""
        self.entries[key] = ParamVersionEntry(
            value=value,
            version=version,
            source=source,
            description=description,
            is_default=is_default,
        )

    def get(self, key: str) -> ParamVersionEntry | None:
        return self.entries.get(key)

# =============================================================================
# SERVICE CLASS  (input_params.service_classes)
# =============================================================================

@dataclass
class ServiceClass:
    """
    One entry from the global accommodation class taxonomy.

    input_params.classes — stable reference table, not versioned.
    class_main groups individual classes into top-level categories:
    Seat, Couchette, Sleeper, Capsule, Catering.

    density: space units consumed per place of this class, used for cost
    allocation. E.g. a 6-berth couchette has density 1/6 since 6 places
    share one compartment unit. Stored in DB on the classes table.
    """

    class_id: str  # e.g. "seat (reclining)", "couchette (6-berth)"
    class_main: str  # e.g. "Seat", "Couchette", "Sleeper"
    density: float  # space units per place — stored in DB, not derived

# =============================================================================
# OPERATOR  (input_params.operators + input_params.operator_class_costs)
# =============================================================================

@dataclass
class Operator:
    """
    Train operating company — bears operational costs.

    Populated by DBDataLoader from input_params.operators (one row) and
    input_params.operator_class_costs (one row per class).
    Linked as an object on CompositionType.

    svc_stockings_eur_place: variable cost of onboard services and stockings
    per available place per trip, keyed by class_id.

    Row-level version and source tracking is handled by ParamVersions in RouteProvenance.
    """

    operator_id: str
    operator_name: str
    driver_costs_eur_h: float  # EUR per driver hour (rate, not duration)
    crew_costs_eur_h: float  # EUR per crew hour (rate, not duration)
    driver_overhead_min: int  # overhead time per driver per trip in minutes
    crew_overhead_min: int  # overhead time per crew member per trip in minutes
    ebit_margin_per: float
    financing_quota_per: float
    var_overhead_per: float
    fix_overhead_quota_per: float
    svc_stockings_eur_place: dict[str, float]  # keyed by class_id

    # locomotive — utilization-based full-service lease (capital, maintenance,
    # insurance bundled into the rate). Billed per hour the loco is coupled
    # to a working train, i.e. segment total_time_min (driving + buffer).
    # Energy, TAC, and driver/crew costs are NOT included — billed separately.
    loco_full_service_lease_eur_h: float

# =============================================================================
# COACH TYPE  (input_params.coachtypes + input_params.coachtype_classes)
# =============================================================================

@dataclass
class CoachClassAssignment:
    """
    One accommodation class assignment within a coach type.

    Materialized from input_params.coachtype_classes joined with
    input_params.classes. One entry per class_id per CoachType.
    A coach type may carry zero, one, or multiple class assignments.

    density is denormalised from ServiceClass for convenient aggregation.
    """

    class_id: str  # FK → input_params.classes.class_id
    class_main: str  # denormalised from input_params.classes
    places: int  # number of places of this class in the coach
    density: float  # denormalised from ServiceClass.density

@dataclass
class CoachType:
    """
    Blueprint for a single coach vehicle.

    Populated by DBDataLoader from input_params.coachtypes and
    input_params.coachtype_classes. Stored in CompositionType.coaches
    keyed by position.

    crew_factor: fractional cabin crew assigned per trip
                 (e.g. 0.5 = one crew member covers two coaches of this type)

    Row-level version and source tracking is handled by ParamVersions in RouteProvenance.
    """

    coachtype_id: str
    weight_gross_t: float
    crew_factor: float
    bikes: int
    climatization: bool
    plugs: bool
    classes: dict[str, CoachClassAssignment]  # keyed by class_id

    def places(self, class_id: str) -> int:
        """Places of a given class in this coach, or 0 if not present."""
        assignment = self.classes.get(class_id)
        return assignment.places if assignment else 0

    def total_places(self) -> int:
        """Total places across all classes in this coach."""
        return sum(a.places for a in self.classes.values())

# =============================================================================
# COMPOSITION TYPE  (input_params.compositions + input_params.composition_coaches)
# =============================================================================

@dataclass
class CompositionType:
    """
    Generic composition blueprint — describes the physical makeup of a train.

    Populated by DBDataLoader from input_params.compositions and
    input_params.composition_coaches.

    coaches: ordered coach slots keyed by position (1 = first coach behind loco).
    operator: the operating company for this composition type.
    driver_factor: number of drivers required per trip (e.g. 1 or 2).

    Row-level version and source tracking is handled by ParamVersions in RouteProvenance.
    """

    comp_id: str
    comp_description: str
    operator: Operator
    driver_factor: float
    max_speed_kmh: float
    hsr_allowed: bool
    coaches: dict[int, CoachType]  # keyed by position

    # energy regression coefficients
    energy_factor_weight: float
    energy_factor_speed: float
    energy_factor_terrain: float

    # vehicle-dependent minimum dwell times
    min_boarding_time_min: int
    min_alighting_time_min: int

    # composition-level cost params — locomotives are full-service leased
    # (see Operator.loco_full_service_lease_eur_h), not purchased
    purchase_coach_eur: float
    coach_avail_per: float
    coach_amort_years: int
    cleaning_services_eur_day: float
    coach_maint_eur_km: float

    # --- derived getters ---

    def total_weight_t(self) -> float:
        """Total gross weight of all coaches in tonnes."""
        return sum(c.weight_gross_t for c in self.coaches.values())

    def total_crew(self) -> float:
        """Total fractional crew across all coaches."""
        return sum(c.crew_factor for c in self.coaches.values())

    def places_by_class(self) -> dict[str, int]:
        """Total places per class_id across all coaches."""
        result: dict[str, int] = {}
        for coach in self.coaches.values():
            for class_id, a in coach.classes.items():
                result[class_id] = result.get(class_id, 0) + a.places
        return result

    def places_by_main_class(self) -> dict[str, int]:
        """Total places per class_main across all coaches."""
        result: dict[str, int] = {}
        for coach in self.coaches.values():
            for a in coach.classes.values():
                result[a.class_main] = result.get(a.class_main, 0) + a.places
        return result

    def density_by_class(self) -> dict[str, float]:
        """
        Places-weighted average density per class_id across all coaches.
        density = sum(places_i * density_i) / sum(places_i)
        """
        weighted: dict[str, float] = {}
        totals: dict[str, int] = {}
        for coach in self.coaches.values():
            for class_id, a in coach.classes.items():
                weighted[class_id] = weighted.get(class_id, 0.0) + a.places * a.density
                totals[class_id] = totals.get(class_id, 0) + a.places
        return {cid: weighted[cid] / totals[cid] for cid in weighted if totals[cid] > 0}

    def density_by_main_class(self) -> dict[str, float]:
        """
        Places-weighted average density per class_main across all coaches.
        """
        weighted: dict[str, float] = {}
        totals: dict[str, int] = {}
        for coach in self.coaches.values():
            for a in coach.classes.values():
                weighted[a.class_main] = (
                    weighted.get(a.class_main, 0.0) + a.places * a.density
                )
                totals[a.class_main] = totals.get(a.class_main, 0) + a.places
        return {cm: weighted[cm] / totals[cm] for cm in weighted if totals[cm] > 0}

# =============================================================================
# COMPOSITION  (fully resolved operational object)
# =============================================================================

@dataclass
class Composition:
    """
    Fully resolved operational composition for a specific trip.

    Built from CompositionType at load time via Composition.from_type().
    All parameters are flat — no lazy loading, no optional fields.
    Stored on Trip.

    No provenance — Composition is a derived object; provenance lives on
    CompositionType, Operator, and CoachType it was built from.
    """

    # identity
    comp_id: str
    comp_description: str
    operator_id: str

    # routing
    driver_factor: float
    max_speed_kmh: float
    hsr_allowed: bool
    min_boarding_time_min: int
    min_alighting_time_min: int

    # energy
    energy_factor_weight: float
    energy_factor_speed: float
    energy_factor_terrain: float

    # general train properties (derived from coaches)
    total_weight_t: float
    total_crew: float

    # capacity (derived from coaches)
    places_by_class: dict[str, int]  # keyed by class_id
    density_by_class: dict[str, float]  # keyed by class_id, places-weighted avg

    # operator cost
    driver_costs_eur_h: float
    crew_costs_eur_h: float
    driver_overhead_min: int
    crew_overhead_min: int
    ebit_margin_per: float
    financing_quota_per: float
    var_overhead_per: float
    fix_overhead_quota_per: float
    svc_stockings_eur_place: dict[str, float]  # keyed by class_id
    loco_full_service_lease_eur_h: float  # billed on route-level deduplicated loco operating time

    # composition cost — locomotives are full-service leased, not purchased
    purchase_coach_eur: float
    coach_avail_per: float
    coach_amort_years: int
    cleaning_services_eur_day: float
    coach_maint_eur_km: float

    # indicative KPIs — computed at load time via compute_indicative_figures()
    # None if no composition_references row exists in the DB
    indicative: Optional["IndicativeFigures"] = field(default=None)

    @classmethod
    def from_type(cls, comp_type: CompositionType) -> "Composition":
        """
        Construct a fully resolved Composition from its CompositionType.
        Called exclusively by DBDataLoader.build_composition().
        """
        return cls(
            comp_id=comp_type.comp_id,
            comp_description=comp_type.comp_description,
            operator_id=comp_type.operator.operator_id,
            driver_factor=comp_type.driver_factor,
            max_speed_kmh=comp_type.max_speed_kmh,
            hsr_allowed=comp_type.hsr_allowed,
            min_boarding_time_min=comp_type.min_boarding_time_min,
            min_alighting_time_min=comp_type.min_alighting_time_min,
            energy_factor_weight=comp_type.energy_factor_weight,
            energy_factor_speed=comp_type.energy_factor_speed,
            energy_factor_terrain=comp_type.energy_factor_terrain,
            total_weight_t=comp_type.total_weight_t(),
            total_crew=comp_type.total_crew(),
            places_by_class=comp_type.places_by_class(),
            density_by_class=comp_type.density_by_class(),
            driver_costs_eur_h=comp_type.operator.driver_costs_eur_h,
            crew_costs_eur_h=comp_type.operator.crew_costs_eur_h,
            driver_overhead_min=comp_type.operator.driver_overhead_min,
            crew_overhead_min=comp_type.operator.crew_overhead_min,
            ebit_margin_per=comp_type.operator.ebit_margin_per,
            financing_quota_per=comp_type.operator.financing_quota_per,
            var_overhead_per=comp_type.operator.var_overhead_per,
            fix_overhead_quota_per=comp_type.operator.fix_overhead_quota_per,
            svc_stockings_eur_place=comp_type.operator.svc_stockings_eur_place,
            loco_full_service_lease_eur_h=comp_type.operator.loco_full_service_lease_eur_h,
            purchase_coach_eur=comp_type.purchase_coach_eur,
            coach_avail_per=comp_type.coach_avail_per,
            coach_amort_years=comp_type.coach_amort_years,
            cleaning_services_eur_day=comp_type.cleaning_services_eur_day,
            coach_maint_eur_km=comp_type.coach_maint_eur_km,
        )

# =============================================================================
# COMPOSITION REFERENCE  (input_params.composition_references)
# =============================================================================

@dataclass
class CompositionReference:
    """
    Reference trip profile for a composition — used to compute indicative
    cost/revenue figures for composition comparison.

    Stored in input_params.composition_references and loaded alongside the
    composition. The four indicative figures are computed at runtime in
    calc.py via compute_indicative_figures() using the same model as
    evaluate_route().
    """

    composition_type_id: str

    # reference trip physics
    ref_distance_km: float
    ref_avg_speed_kmh: float
    ref_terrain_score: float
    ref_operating_days: int

    # reference demand
    ref_utilization_by_class: dict[str, float]  # keyed by class_main
    ref_avg_fare_by_class: dict[str, float]  # keyed by class_main

@dataclass
class IndicativeFigures:
    """
    Pre-computed indicative cost/revenue KPIs for a composition,
    derived from compute_indicative_figures() in calc.py using a
    CompositionReference profile. Used for composition comparison only.
    """

    cost_eur_per_seat_km: float  # total cost ÷ available seat-km
    cost_eur_per_place_km: float  # total cost ÷ density-weighted place-km
    subsidy_eur_per_pax_km: float  # (cost - revenue) ÷ sold pax-km
    breakeven_load_factor: float  # load factor needed to break even

# =============================================================================
# TRACK INFRASTRUCTURE DEFAULTS  (input_params.infrastructure_defaults)
# =============================================================================

@dataclass
class DefaultTrackInfra:
    """
    EU-average fallback values for TrackInfrastructure fields.

    Populated by DBDataLoader from input_params.infrastructure_defaults.
    Used by TrackInfraCollection.get_or_default() to fill None fields
    on a TrackInfrastructure row that has no country-specific value.

    Each value has a paired _src field for provenance.
    """

    tac_eur_train_km: float
    tac_src: Optional[ParamsSource]

    parking_eur_day: float      # €/operating-day per parking event
    parking_src: Optional[ParamsSource]

    shunting_eur_event: float   # €/event per shunting movement
    shunting_src: Optional[ParamsSource]

    energy_price_eur_kwh: float
    energy_price_src: Optional[ParamsSource]

    terrain_score: float
    terrain_category: str
    terrain_src: Optional[ParamsSource]

    hsr_allowed: bool
    hsr_src: Optional[ParamsSource]

    min_boarding_time_min: int
    min_boarding_src: Optional[ParamsSource]

    min_alighting_time_min: int
    min_alighting_src: Optional[ParamsSource]

    buffer_quota_per: float
    buffer_src: Optional[ParamsSource]

# =============================================================================
# TRACK INFRASTRUCTURE  (input_params.infrastructure)
# =============================================================================

@dataclass
class TrackInfrastructure:
    """
    Per-country track infrastructure parameters.

    Populated by DBDataLoader.build_all_tracks(). All fields are fully
    resolved — the loader substitutes DefaultTrackInfra values for any
    None DB fields and logs a warning per substitution.

    Each parameter value has a paired _src field for field-level provenance.
    Row-level version and source tracking is handled by ParamVersions in RouteProvenance.
    """

    country_code: str

    tac_eur_train_km: float
    tac_src: Optional[ParamsSource]

    parking_eur_day: float      # €/operating-day per parking event
    parking_src: Optional[ParamsSource]

    shunting_eur_event: float   # €/event per shunting movement
    shunting_src: Optional[ParamsSource]

    energy_price_eur_kwh: float
    energy_price_src: Optional[ParamsSource]

    terrain_score: float
    terrain_category: str
    terrain_src: Optional[ParamsSource]

    hsr_allowed: bool
    hsr_src: Optional[ParamsSource]

    min_boarding_time_min: int
    min_boarding_src: Optional[ParamsSource]

    min_alighting_time_min: int
    min_alighting_src: Optional[ParamsSource]

    buffer_quota_per: float
    buffer_src: Optional[ParamsSource]

@dataclass
class TrackInfraCollection:
    """
    Dict-backed collection of TrackInfrastructure keyed by country_code.

    All rows are fully resolved by the loader — no None fields.
    get_or_default() returns the country row if present, otherwise None.
    Callers that need a guaranteed result should handle the None case.
    """

    _data: dict[str, TrackInfrastructure]

    def __init__(self, data: dict[str, TrackInfrastructure]) -> None:
        self._data = data

    def get(self, country_code: str) -> Optional[TrackInfrastructure]:
        return self._data.get(country_code)

    def get_or_default(self, country_code: str) -> Optional[TrackInfrastructure]:
        """Return country row if present, else the first available row as fallback."""
        if country_code in self._data:
            return self._data[country_code]
        # fall back to first available (EU average default loaded by loader)
        return next(iter(self._data.values()), None)

    def all(self) -> dict[str, TrackInfrastructure]:
        return self._data

    def __len__(self) -> int:
        return len(self._data)

# =============================================================================
# STOP INFRASTRUCTURE DEFAULTS  (input_params.stop_defaults)
# =============================================================================

@dataclass
class DefaultStopInfra:
    """
    EU-average fallback values for StopInfrastructure fields.

    Populated by DBDataLoader from input_params.stop_defaults.
    Used by StopInfraCollection.get_or_default() to fill None fields.
    """

    stop_charge_eur: float
    stop_charge_src: Optional[ParamsSource]

# =============================================================================
# STOP INFRASTRUCTURE  (input_params.stops)
# =============================================================================

@dataclass
class StopInfrastructure:
    """
    One stop — location and station access charge.

    Populated by DBDataLoader.build_all_stops(). All fields are fully
    resolved — the loader substitutes DefaultStopInfra.stop_charge_eur
    for any stop with no charge value and logs a warning.

    stop_charge_eur is an internal cost model field — NOT exposed in API
    responses. Used exclusively by models/evaluation/calc.py.

    lat/lon share a single loc_src. stop_charge_eur has its own src field.
    Row-level version and source tracking is handled by ParamVersions in RouteProvenance.
    """

    stop_id: str
    stop_name: str
    stop_country_code: str

    lat: float
    lon: float
    loc_src: Optional[ParamsSource]  # shared source for lat + lon

    stop_charge_eur: float  # internal — not exposed in API
    stop_charge_src: Optional[ParamsSource]

@dataclass
class StopInfraCollection:
    """
    Dict-backed collection of StopInfrastructure keyed by stop_id.

    All rows are fully resolved by the loader — stop_charge_eur is never None.
    """

    _data: dict[str, StopInfrastructure]

    def __init__(self, data: dict[str, StopInfrastructure]) -> None:
        self._data = data

    def get(self, stop_id: str) -> Optional[StopInfrastructure]:
        return self._data.get(stop_id)

    def get_charge(self, stop_id: str) -> float:
        """
        Return stop_charge_eur for a stop.
        Raises KeyError if stop_id is not found — a missing stop is a data
        integrity failure since routing requires lat/lon from the same row.
        """
        row = self._data.get(stop_id)
        if row is None:
            raise KeyError(f"Stop '{stop_id}' not found in StopInfraCollection.")
        return row.stop_charge_eur

    def all(self) -> dict[str, StopInfrastructure]:
        return self._data

    def __len__(self) -> int:
        return len(self._data)

# =============================================================================
# OD PAIR  (persistent demand input — lives on Route)
# =============================================================================

@dataclass
class ODPair:
    """
    Demand for one origin-destination pair on one specific trip.

    Persistent domain object stored alongside the Route. Lives on Route
    (not Trip) so that Y-shaped routes can express demand correctly: a
    Berlin→Copenhagen OD pair that spans both the Berlin→Oslo and
    Berlin→Stockholm trips is represented as two ODPair objects, each
    referencing its own trip_id with its own places_sold.

    The demand split across trips for shared legs is a user input —
    the model does not derive it.

    class_main: top-level accommodation category from ServiceClass
    (e.g. "Seat", "Couchette", "Sleeper"). One ODPair per class per
    OD pair per trip — if a single OD pair carries both Couchette and
    Sleeper demand, that is two ODPair objects.

    places_sold: annual total tickets sold for this OD pair / class / trip.
    Operators think and plan in annual figures — per-trip demand is derived
    by dividing by operating_days_per_year from the relevant TripPair's
    Schedule.

    avg_price: average ticket price across all tickets sold for this
    OD pair, class, and trip. EUR.
    """

    origin_stop_id: str
    destination_stop_id: str
    class_main: str          # "Seat" | "Couchette" | "Sleeper" | "Capsule" | "Catering"
    trip_id: str             # references Trip.trip_id within the same Route
    places_sold: int         # annual tickets sold for this OD pair / class / trip
    avg_price: float         # EUR — average fare across all sold tickets