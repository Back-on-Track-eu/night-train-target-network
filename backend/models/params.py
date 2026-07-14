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
  Field-level source and version provenance for TrackInfrastructure and
  StopInfrastructure values lives exclusively in each collection's
  param_versions (a ParamVersions instance) — not on the domain objects
  themselves.

  Field-level description provenance for TrackInfrastructure and
  StopInfrastructure both live separately, once per collection, on
  TrackInfraCollection.descriptions / StopInfraCollection.descriptions —
  a field's documentation is identical for every country/stop, so
  ParamVersions entries no longer carry a redundant copy of it per
  country-or-stop/field. Compositions (Operator, CoachType, etc.) still
  carry description on their ParamVersionEntry, per-field, since that
  endpoint hasn't been revisited yet.

  Composition carries no provenance — it is a derived object.

Default fallback
----------------
  TrackInfrastructure and StopInfrastructure are always fully resolved.
  DefaultTrackInfra and DefaultStopInfra (EU-average fallback values) are
  merged in by the loader at build time: per field, whenever a country's
  or stop's own value is NULL, and — for TrackInfrastructure only — as a
  complete synthesized row for any country in input_params.countries
  that has no track_infrastructures row at all. Callers never see a
  missing or partially-None entry.

Collections
-----------
  TrackInfraCollection    — keyed by country_code, fully resolved rows
  StopInfraCollection     — keyed by stop_id, fully resolved rows
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

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
    version: Optional[int] = field(default=None)
    """DB version number for versioned tables (track/stop infrastructure).
    None for unversioned catalog tables (compositions, operators, coach
    types, composition references) — those have no version to report,
    since a changed value means a new id, not a new version of this one."""
    source: Optional[ParamsSource] = field(default=None)
    description: Optional[str] = field(default=None)
    is_default: bool = field(default=False)
    # is_default=True means this value was resolved from a default row
    # because the country/stop-specific value was NULL in the database.
    # Always False for unversioned catalog tables — they have no default
    # fallback concept.


@dataclass
class ParamVersions:
    """
    Captures which version of each parameter row was used in a computation,
    together with full source provenance.

    Populated on the fly by the loader. Carried on the relevant collection
    (TrackInfraCollection.param_versions, StopInfraCollection.param_versions,
    CompositionCollection.param_versions) rather than returned
    separately.

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
        version: Optional[int] = None,
        source: Optional[ParamsSource] = None,
        description: Optional[str] = None,
        is_default: bool = False,
    ) -> None:
        """Register one parameter field. Safe to call multiple times — last
        write wins. version=None for unversioned catalog tables — see
        ParamVersionEntry."""
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
    input_params.operator_class_costs (one row per class). Not versioned —
    operator_id is a permanent natural key; a changed rate means a new
    operator_id, never editing this row in place. Deduplicated and shared
    across every CompositionType that references it (see
    CompositionCollection).
    Linked as an object on CompositionType.

    svc_stockings_eur_place: variable cost of onboard services and stockings
    per available place per trip, keyed by class_id.

    Source and description provenance is handled by
    CompositionCollection.param_versions, not stored on this object.
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
    # to a working train, i.e. segment total_time_min (driving + dynamics + buffer).
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
    keyed by position. Not versioned — coachtype_id is a permanent
    natural key; a changed spec means a new coachtype_id, never editing
    this row in place. Deduplicated and shared across every
    CompositionType that references it (see CompositionCollection).

    crew_factor: fractional cabin crew assigned per trip
                 (e.g. 0.5 = one crew member covers two coaches of this type)

    Source and description provenance is handled by
    CompositionCollection.param_versions, not stored on this object.
    """

    coachtype_id: str
    weight_gross_t: float
    crew_factor: float
    bikes: int
    climatization: bool
    plugs: bool
    classes: dict[str, CoachClassAssignment]  # keyed by class_id
    remarks: Optional[str] = (
        None  # free-text description, e.g. "STD seat coach — 80 reclining seats"
    )

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
    input_params.composition_coaches. Not versioned — composition_type_id
    is a permanent natural key; new settings mean a new composition_type_id,
    never editing this row in place.

    coaches: ordered coach slots keyed by position (1 = first coach behind loco).
    operator: the operating company for this composition type.
    driver_factor: number of drivers required per trip (e.g. 1 or 2).

    Source and description provenance is handled by
    CompositionCollection.param_versions, not stored on this object.
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

    def weighted_avg_by_main_class(
        self, per_class_id_values: dict[str, float]
    ) -> dict[str, float]:
        """
        Places-weighted average of an arbitrary per-class_id value (e.g.
        Operator.svc_stockings_eur_place), aggregated up to class_main —
        same places-weighted-average shape as density_by_main_class()
        above, but over a caller-supplied value dict instead of the
        built-in per-class density.

        Model approach (David, 2026-07-06): classes within one class_main
        are assumed to be served at the same cost factor, so the
        class_main-level figure is simply the places-weighted average of
        the underlying class_id rates actually present in this
        composition's coach mix — not a max, not an unweighted average.

        weighted[class_main] = sum(places_i * value_i) / sum(places_i),
        for every class_id in that class_main group present in this
        composition. A class_id missing from per_class_id_values
        contributes 0.0 for its places (same fallback as the .get(...) call
        sites in models/evaluation/calc.py).
        """
        weighted: dict[str, float] = {}
        totals: dict[str, int] = {}
        for coach in self.coaches.values():
            for class_id, a in coach.classes.items():
                value = per_class_id_values.get(class_id, 0.0)
                weighted[a.class_main] = (
                    weighted.get(a.class_main, 0.0) + a.places * value
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
    operator_name: str

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

    # capacity (derived from coaches) — keyed by class_main (Seat, Couchette,
    # Sleeper, Capsule, Catering), not class_id. See Composition.from_type():
    # aggregated from CompositionType.places_by_main_class() /
    # density_by_main_class() — classes within one class_main are modelled
    # as served at the same cost factor (David, 2026-07-06), so there is no
    # need for OD pairs or cost lookups to go any more granular than this.
    places_by_class: dict[str, int]  # keyed by class_main
    density_by_class: dict[str, float]  # keyed by class_main, places-weighted avg

    # equipment (derived from coaches) — True if ANY coach in the composition has it
    has_bikes: bool
    has_climatization: bool
    has_plugs: bool

    # raw coach breakdown — the one non-aggregated field on this otherwise
    # flat object, kept so API consumers can list individual coaches
    # (id + remarks) without a second lookup. Keyed by position.
    coaches: dict[int, CoachType]

    # operator cost
    driver_costs_eur_h: float
    crew_costs_eur_h: float
    driver_overhead_min: int
    crew_overhead_min: int
    ebit_margin_per: float
    financing_quota_per: float
    var_overhead_per: float
    fix_overhead_quota_per: float
    svc_stockings_eur_place: dict[
        str, float
    ]  # keyed by class_main (weighted_avg_by_main_class()) — Operator's own copy above stays class_id-keyed
    loco_full_service_lease_eur_h: (
        float  # billed on route-level deduplicated loco operating time
    )

    # composition cost — locomotives are full-service leased, not purchased
    purchase_coach_eur: float
    coach_avail_per: float
    coach_amort_years: int
    cleaning_services_eur_day: float
    coach_maint_eur_km: float

    # indicative KPIs — computed at load time via
    # models.compositions.calc_indicative_figures.compute_indicative_figures()
    # (currently a placeholder — see IndicativeFigures). None if no
    # composition_references row exists in the DB.
    indicative: Optional["IndicativeFigures"] = field(default=None)

    @classmethod
    def from_type(cls, comp_type: CompositionType) -> "Composition":
        """
        Construct a fully resolved Composition from its CompositionType.
        Called exclusively by DBDataLoader.build_all_compositions().

        places_by_class / density_by_class / svc_stockings_eur_place are all
        aggregated up to class_main here (2026-07-06) — see the field
        comments above and CompositionType.places_by_main_class() /
        density_by_main_class() / weighted_avg_by_main_class(). Previously
        these were class_id-keyed; ODPair.class_main was always documented
        as a top-level category (see ODPair's own docstring) but in
        practice callers had to pass class_id strings to get a non-zero
        cost/density lookup in models/evaluation/calc.py. This makes the
        code match that original intent instead of the other way around.
        """
        return cls(
            comp_id=comp_type.comp_id,
            comp_description=comp_type.comp_description,
            operator_id=comp_type.operator.operator_id,
            operator_name=comp_type.operator.operator_name,
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
            places_by_class=comp_type.places_by_main_class(),
            density_by_class=comp_type.density_by_main_class(),
            has_bikes=any(c.bikes > 0 for c in comp_type.coaches.values()),
            has_climatization=any(c.climatization for c in comp_type.coaches.values()),
            has_plugs=any(c.plugs for c in comp_type.coaches.values()),
            coaches=dict(comp_type.coaches),
            driver_costs_eur_h=comp_type.operator.driver_costs_eur_h,
            crew_costs_eur_h=comp_type.operator.crew_costs_eur_h,
            driver_overhead_min=comp_type.operator.driver_overhead_min,
            crew_overhead_min=comp_type.operator.crew_overhead_min,
            ebit_margin_per=comp_type.operator.ebit_margin_per,
            financing_quota_per=comp_type.operator.financing_quota_per,
            var_overhead_per=comp_type.operator.var_overhead_per,
            fix_overhead_quota_per=comp_type.operator.fix_overhead_quota_per,
            svc_stockings_eur_place=comp_type.weighted_avg_by_main_class(
                comp_type.operator.svc_stockings_eur_place
            ),
            loco_full_service_lease_eur_h=comp_type.operator.loco_full_service_lease_eur_h,
            purchase_coach_eur=comp_type.purchase_coach_eur,
            coach_avail_per=comp_type.coach_avail_per,
            coach_amort_years=comp_type.coach_amort_years,
            cleaning_services_eur_day=comp_type.cleaning_services_eur_day,
            coach_maint_eur_km=comp_type.coach_maint_eur_km,
        )


@dataclass
class CompositionCollection:
    """
    Dict-backed collection of Composition (the derived, flat operational
    object — see Composition's docstring) keyed by comp_id. Built eagerly
    and once by DBDataLoader.build_all_compositions().

    Not versioned/scenario-scoped: composition_types, operators, and
    coach_types are all unversioned catalogs (see their own docstrings) —
    a changed value means seeding a new id, never editing a row in place.
    build_all_compositions() still accepts a scenario_id, but only to
    resolve the TrackInfraCollection/StopInfraCollection used to compute
    each composition's indicative KPIs (Composition.indicative) — it has
    no bearing on composition, operator, or coach type field values
    themselves.

    Operator and CoachType instances are deduplicated at load time: every
    CompositionType (and therefore every Composition built from one) that
    references the same operator_id/coachtype_id shares the same object,
    loaded once rather than rebuilt per composition.

    param_versions carries one ParamVersionEntry per field across five
    prefixes: "composition_type:*", "operator:*", "operator_class_cost:*",
    "coach_type:*", "composition_reference:*" — provenance for the
    CompositionType blueprints these Compositions were derived from, not
    for Composition's own (already-flattened, unsourced) fields. Every
    entry's version is None (see ParamVersionEntry) since none of these
    tables are versioned. Per-entry `description` is deliberately left
    unset — see `descriptions` below.

    descriptions mirrors the ACTUAL response structure built by
    api/helpers/params_serialize.py's composition_collection_to_dict() —
    grouped as "compositions" (with "routing"/"staff"/"energy"/
    "capacity"/"equipment"/"coaches"/"fixed_costs"/"variable_km"
    sub-sections, matching that function's per-composition dict exactly),
    "operators", and "indicative" (with "kpis"/"reference" sub-sections).
    Deliberately NOT grouped by source table (composition_types/
    operators/coach_types/composition_references) the way it briefly was
    — several DB columns (e.g. weight_gross_t, crew_factor, bikes on
    coach_types) are never exposed per-coach in the response at all, only
    as composition-level sums/booleans, so a table-shaped descriptions
    block would misrepresent what's actually returned. Built once in
    build_all_compositions() rather than duplicated per entity/field on
    param_versions — mirrors StopInfraCollection.descriptions /
    TrackInfraCollection.descriptions in spirit, though the shape here is
    response-section-keyed rather than {"table":..., "fields": {...}}
    since compositions span multiple source tables per section.
    """

    _data: dict[str, Composition]
    param_versions: ParamVersions
    descriptions: dict[str, dict]

    def __init__(
        self,
        data: dict[str, Composition],
        param_versions: ParamVersions,
        descriptions: dict[str, dict],
    ) -> None:
        self._data = data
        self.param_versions = param_versions
        self.descriptions = descriptions

    def get(self, comp_id: str) -> Optional[Composition]:
        return self._data.get(comp_id)

    def all(self) -> dict[str, Composition]:
        return self._data

    def __len__(self) -> int:
        return len(self._data)


# =============================================================================
# COMPOSITION REFERENCE  (input_params.composition_references)
# =============================================================================


@dataclass
class CompositionReference:
    """
    Reference trip profile for a composition — used to compute indicative
    cost figures for composition comparison.

    Stored in input_params.composition_references and loaded alongside the
    composition. Not versioned, same as CompositionType — exactly one row
    per composition_type_id (enforced by a UNIQUE constraint on
    composition_type_row_id). The indicative figures are computed at
    runtime via models.compositions.calc_indicative_figures
    .compute_indicative_figures() — see IndicativeFigures. That module is
    currently a placeholder (returns dummy figures); a full compositions
    cost model, analogous to models/evaluation/calc.py for a concrete
    route, is planned to replace it.
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
    Pre-computed indicative cost KPIs for a composition, derived from
    models.compositions.calc_indicative_figures.compute_indicative_figures()
    using a CompositionReference profile. Used for composition comparison
    only.

    PLACEHOLDER VALUES as of this writing — models/compositions/ doesn't
    have a real cost model yet, so compute_indicative_figures() returns
    dummy figures (currently all zero) rather than raising. Treat these
    as provisional until that model exists; the field names/shape here
    are expected to stay stable across that change.
    """

    cost_eur_per_train_km: float
    """Total composition cost ÷ reference distance, for the reference
    trip profile — analogous to a route's total cost ÷ distance in
    models/evaluation/calc.py, but composition-level and route-agnostic."""

    cost_eur_per_place_km_by_class: dict[str, float]
    """Keyed by class_id (see Composition.places_by_class) — the same
    total cost allocated to each class present in the composition,
    divided by that class's density-weighted place-km."""

    # the reference profile these KPIs were computed from — carried
    # alongside so API consumers can see the assumptions, not just the result
    reference: Optional[CompositionReference] = field(default=None)


# =============================================================================
# TRACK INFRASTRUCTURE DEFAULTS  (input_params.infrastructure_defaults)
# =============================================================================


@dataclass
class DefaultTrackInfra:
    """
    EU-average fallback values for TrackInfrastructure fields.

    Populated by DBDataLoader from input_params.infrastructure_defaults.
    Used by DBDataLoader.build_all_tracks() to fill None fields on a
    country row, and to synthesize a complete row for any country in
    input_params.countries that has no track_infrastructures row at all.

    Each value has a paired _src field for provenance.
    """

    tac_eur_train_km: float
    tac_src: Optional[ParamsSource]

    parking_eur_day: float  # €/operating-day per parking event
    parking_src: Optional[ParamsSource]

    shunting_eur_event: float  # €/event per shunting movement
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

    def source_for(self, field_name: str) -> Optional[ParamsSource]:
        """
        Return this default row's source for a given TrackInfrastructure
        field name — handles the field → _src attribute mapping (most
        fields have their own, but terrain_score and terrain_category
        share terrain_src) once, here, instead of duplicated wherever
        DefaultTrackInfra values are consumed (build_all_tracks() and
        api/helpers/params_serialize.py).
        """
        return getattr(self, _TRACK_DEFAULT_SRC_ATTRS[field_name])


# =============================================================================
# TRACK INFRASTRUCTURE  (input_params.infrastructure)
# =============================================================================

TRACK_INFRA_FIELD_NAMES = (
    "tac_eur_train_km",
    "parking_eur_day",
    "shunting_eur_event",
    "energy_price_eur_kwh",
    "terrain_score",
    "terrain_category",
    "hsr_allowed",
    "min_boarding_time_min",
    "min_alighting_time_min",
    "buffer_quota_per",
)
"""Canonical value-field names on TrackInfrastructure (excludes country_code
and field_is_default). Shared by DBDataLoader for both per-field is_default
tracking on a real row and marking all of them True when synthesizing a
whole missing country's row — single source of truth so the two never
drift apart."""

_TRACK_DEFAULT_SRC_ATTRS = {
    "tac_eur_train_km": "tac_src",
    "parking_eur_day": "parking_src",
    "shunting_eur_event": "shunting_src",
    "energy_price_eur_kwh": "energy_price_src",
    "terrain_score": "terrain_src",
    "terrain_category": "terrain_src",
    "hsr_allowed": "hsr_src",
    "min_boarding_time_min": "min_boarding_src",
    "min_alighting_time_min": "min_alighting_src",
    "buffer_quota_per": "buffer_src",
}
"""Maps each TRACK_INFRA_FIELD_NAMES entry to its source attribute on
DefaultTrackInfra — see DefaultTrackInfra.source_for()."""


@dataclass
class TrackInfraDescriptions:
    """
    Static table/column documentation for input_params.track_infrastructures.

    Identical for every country — captured once per collection here rather
    than duplicated per country/field on ParamVersions (see
    TrackInfraCollection.descriptions). Mirrors StopInfraDescriptions.

    Populated by DBDataLoader.build_all_tracks() from Postgres COMMENT ON
    TABLE/COLUMN metadata — see DBDataLoader._load_table_comment() and
    ._load_column_comments(); the field → column name mapping (not a
    uniform "track_" + field_name prefix — see build_all_tracks()) lives
    there too, next to the analogous mapping for stops.
    """

    table: Optional[str]
    fields: dict[str, Optional[str]]
    # Keyed by TRACK_INFRA_FIELD_NAMES, already resolved to the right
    # underlying column comment — not the raw column names.


@dataclass
class TrackInfrastructure:
    """
    Per-country track infrastructure parameters.

    Populated by DBDataLoader.build_all_tracks(). All fields are fully
    resolved — the loader substitutes DefaultTrackInfra values for any
    None DB fields and logs a warning per substitution. Every country in
    input_params.countries is guaranteed to produce one of these — a
    country with no track_infrastructures row at all still gets one,
    synthesized entirely from DefaultTrackInfra (see build_all_tracks()).

    No _src fields here: source and version provenance for every field
    live exclusively on TrackInfraCollection.param_versions, not
    duplicated on this object.

    field_is_default: {field_name: was_this_field_defaulted} — kept ON
    this object (unlike source/version) because api/helpers/route_serialize.py
    reads it directly to build the "defaulted_fields" list in the
    /api/route/plan response. Individual defaulted fields are expected and
    fine — that's what track_infrastructure_defaults is for.

    has_row: True if a real row exists in input_params.track_infrastructures
    for this country (regardless of how many of its fields are None and
    therefore defaulted), False if the country had no row at all and this
    object was synthesized entirely from DefaultTrackInfra. Since
    TrackInfraCollection.get() is never None for a legitimate country_code
    (see build_all_tracks()), "row missing" can no longer be signaled by a
    None return — has_row is that signal instead. This is what
    route_factory._check_country_coverage() checks: a country needs a row
    to be routable, but doesn't need every field populated.
    """

    country_code: str
    field_is_default: dict[str, bool]
    """{field_name: was_this_field_defaulted} — see class docstring."""
    has_row: bool
    """Whether a real input_params.track_infrastructures row exists for
    this country — see class docstring."""

    tac_eur_train_km: float
    parking_eur_day: float  # €/operating-day per parking event
    shunting_eur_event: float  # €/event per shunting movement
    energy_price_eur_kwh: float
    terrain_score: float
    terrain_category: str
    hsr_allowed: bool
    min_boarding_time_min: int
    min_alighting_time_min: int
    buffer_quota_per: float


@dataclass
class TrackInfraCollection:
    """
    Dict-backed collection of TrackInfrastructure keyed by country_code.

    Built complete over every country in input_params.countries —
    DBDataLoader.build_all_tracks() synthesizes a full EU-average row for
    any country with no track_infrastructures row at all, at load time.
    So get(country_code) returns a real TrackInfrastructure for every
    legitimate country code; there is no lazy "return a default" method
    on this collection (there used to be a get_or_default() here — removed
    since defaulting for a whole missing country now happens once, in the
    loader, instead of being decided independently by every caller).

    param_versions carries one ParamVersionEntry per track field per
    country, keyed "track_infra:{country_code}:{field}" — including
    countries synthesized entirely from defaults. Per-entry `description`
    is deliberately left unset — see `descriptions` below, which is where
    field documentation actually lives for this collection.

    defaults carries the single EU-average fallback row (there is no
    per-country override table for tracks, unlike stops) this collection
    was resolved against — purely informational, never consulted during
    resolution itself (that already happened in build_all_tracks() before
    TrackInfraCollection was constructed).

    descriptions carries the static table/column documentation for
    track_infrastructures, captured once here rather than duplicated per
    country/field on param_versions (see TrackInfraDescriptions).

    Built once alongside _data by DBDataLoader.build_all_tracks() and
    never mutated afterwards.
    """

    _data: dict[str, TrackInfrastructure]
    param_versions: ParamVersions
    defaults: DefaultTrackInfra
    descriptions: TrackInfraDescriptions

    def __init__(
        self,
        data: dict[str, TrackInfrastructure],
        param_versions: ParamVersions,
        defaults: DefaultTrackInfra,
        descriptions: TrackInfraDescriptions,
    ) -> None:
        self._data = data
        self.param_versions = param_versions
        self.defaults = defaults
        self.descriptions = descriptions

    def get(self, country_code: str) -> Optional[TrackInfrastructure]:
        return self._data.get(country_code)

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
    Used by DBDataLoader.build_all_stops() to fill a stop's None
    stop_charge_eur — see StopInfrastructure's docstring.
    """

    stop_charge_eur: float
    stop_charge_src: Optional[ParamsSource]


# =============================================================================
# STOP INFRASTRUCTURE DESCRIPTIONS  (pg_catalog COMMENT ON TABLE/COLUMN)
# =============================================================================


@dataclass
class StopInfraDescriptions:
    """
    Static table/column documentation for input_params.stop_infrastructures.

    Identical for every stop — unlike source/version/is_default, a field's
    description never varies row to row, so it is captured once per
    collection here rather than duplicated per stop/field on ParamVersions
    (see StopInfraCollection.descriptions).

    Populated by DBDataLoader.build_all_stops() from Postgres COMMENT ON
    TABLE/COLUMN metadata — see DBDataLoader._load_table_comment() and
    ._load_column_comments().
    """

    table: Optional[str]
    fields: dict[str, Optional[str]]
    # Keyed by the field names exposed in StopInfrastructure/the API
    # response ("lat", "lon", "stop_charge_eur") — already resolved to
    # the right underlying column comment, not the raw column names.


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

    stop_charge_eur IS exposed in the /api/params/StopInfrastructures
    response (see api/params.py get_stop_infrastructures()), alongside
    its full provenance. It's also used internally by
    models/evaluation/calc.py.

    No _src fields here: source and version provenance for every field
    (lat, lon, stop_charge_eur — including which one, if any, was
    resolved from the default row) live exclusively on
    StopInfraCollection.param_versions, not duplicated on this object.
    """

    stop_id: str
    stop_name: str
    stop_country_code: str

    lat: float
    lon: float

    stop_charge_eur: float


@dataclass
class StopInfraCollection:
    """
    Dict-backed collection of StopInfrastructure keyed by stop_id.

    All rows are fully resolved by the loader — stop_charge_eur is never None.

    param_versions carries one ParamVersionEntry per stop field (lat, lon,
    stop_charge_eur — see build_all_stops()), keyed "stop_infra:{stop_id}:{field}".
    Per-entry `description` is deliberately left unset for stop fields —
    see `descriptions` below, which is where field documentation actually
    lives for this collection.

    defaults carries the raw EU-average fallback rows this collection was
    resolved against, keyed by country_code (None = the global fallback) —
    purely informational (e.g. for API responses that want to show what a
    stop with a NULL charge would have fallen back to), never consulted
    during resolution itself (that already happened in build_all_stops()
    before StopInfraCollection was constructed).

    descriptions carries the static table/column documentation for
    stop_infrastructures, captured once here rather than duplicated per
    stop/field on param_versions (see StopInfraDescriptions).

    Built once alongside _data by DBDataLoader.build_all_stops() and never
    mutated afterwards — this is now the single source of provenance for
    everything in this collection; callers no longer receive any of it as
    a separate return value.
    """

    _data: dict[str, StopInfrastructure]
    param_versions: ParamVersions
    defaults: dict[Optional[str], DefaultStopInfra]
    descriptions: StopInfraDescriptions

    def __init__(
        self,
        data: dict[str, StopInfrastructure],
        param_versions: ParamVersions,
        defaults: dict[Optional[str], DefaultStopInfra],
        descriptions: StopInfraDescriptions,
    ) -> None:
        self._data = data
        self.param_versions = param_versions
        self.defaults = defaults
        self.descriptions = descriptions

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
    Sleeper demand, that is two ODPair objects. Matches
    Composition.places_by_class / density_by_class / svc_stockings_eur_place
    (2026-07-06) — those are now aggregated up to class_main too, so there
    is no need (and no way) to target a more granular class_id here.

    places_sold: annual total tickets sold for this OD pair / class / trip.
    Operators think and plan in annual figures — per-trip demand is derived
    by dividing by operating_days_per_year from the relevant TripPair's
    Schedule.

    avg_price: average ticket price across all tickets sold for this
    OD pair, class, and trip. EUR.
    """

    origin_stop_id: str
    destination_stop_id: str
    class_main: str  # "Seat" | "Couchette" | "Sleeper" | "Capsule" | "Catering"
    trip_id: str  # references Trip.trip_id within the same Route
    places_sold: int  # annual tickets sold for this OD pair / class / trip
    avg_price: float  # EUR — average fare across all sold tickets


# =============================================================================
# SCENARIO  (scenario.scenarios)
# =============================================================================


@dataclass
class Scenario:
    """
    One row of scenario.scenarios — a container pinning one version of
    each versioned infrastructure table. See
    db/dev/sql/create_scenario_schema.sql for the full versioning
    contract; summarized here for the fields this object carries:

    is_current_base: TRUE for exactly one row in the whole table — the
    live default scenario used whenever an API call omits scenario_id.

    is_current_scenario: TRUE for exactly one row per scenario_key — the
    head of that what-if lineage. Older versions of the same lineage
    carry the same scenario_key with is_current_scenario=False.

    Populated exclusively by DBDataLoader.list_all_scenarios(). Read-only
    — scenario rows are written directly in SQL/notebooks for now, not
    through the API.
    """

    scenario_id: int
    scenario_key: str
    scenario_name: str
    description: Optional[str]
    change_log: Optional[str]
    editor: Optional[str]
    created_at: str  # ISO datetime string
    is_current_base: bool
    is_current_scenario: bool
    track_infrastructures_version: int
    track_infrastructure_defaults_version: int
    stop_infrastructures_version: int
    stop_infrastructure_defaults_version: int