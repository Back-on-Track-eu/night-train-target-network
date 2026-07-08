"""
data_loader_from_db.py
======================
Database data access layer for the night train model.
Reads all parameter tables from PostgreSQL and builds typed domain objects
defined in models/params.py.

Typical usage
-------------
    loader = DBDataLoader()
    compositions = loader.build_all_compositions()
    composition  = compositions.get("STD-7.1")
    tracks       = loader.build_all_tracks()
    stops        = loader.build_all_stops()
    geometries   = loader.get_country_geometries()

Default value resolution
------------------------
  TrackInfrastructure: any None field in a country row is substituted with
  the EU-average default from input_params.infrastructure_defaults. A
  WARNING is logged per substitution.

  StopInfrastructure: a None stop_charge_eur is substituted with the
  country default from input_params.stop_defaults (keyed by country_code)
  or the global default if no country default exists. A WARNING is logged.

New domain model mapping
------------------------
  build_all_compositions()→ CompositionCollection (Composition objects,
                             via CompositionType.from_type(); operators
                             and coach types loaded once each and shared)
  build_all_tracks()      → TrackInfraCollection
  build_all_stops()       → StopInfraCollection
  get_country_geometries()→ list[tuple[str, dict]]  (country_code, GeoJSON geometry)
                             — plain data, not a domain object; callers
                             (e.g. rail_router.CountryIndex) build their own
                             representation from it. input_params.countries
                             is static reference data, not scenario-versioned.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

import psycopg2
import psycopg2.extras

from models.params import (
    ParamsSource,
    ParamVersionEntry,
    CompositionReference,
    IndicativeFigures,
    ParamVersions,
    ServiceClass,
    Operator,
    CoachType,
    CoachClassAssignment,
    CompositionType,
    Composition,
    CompositionCollection,
    DefaultTrackInfra,
    TrackInfrastructure,
    TrackInfraCollection,
    TrackInfraDescriptions,
    TRACK_INFRA_FIELD_NAMES,
    DefaultStopInfra,
    StopInfrastructure,
    StopInfraCollection,
    StopInfraDescriptions,
)

logger = logging.getLogger(__name__)

# =============================================================================
# TYPE CONVERSION HELPERS
# =============================================================================


def _f(value) -> float:
    """Cast Decimal/None to float. Raises if None — use _f_or_none for optional fields."""
    if value is None:
        raise ValueError("Expected float value but got None.")
    return float(value)


def _f_or_none(value) -> float | None:
    """Cast Decimal to float, or return None."""
    return float(value) if value is not None else None


def _i(value) -> int:
    """Cast Decimal/None to int. Raises if None."""
    if value is None:
        raise ValueError("Expected int value but got None.")
    return int(value)


def _i_or_none(value) -> int | None:
    """Cast Decimal to int, or return None."""
    return int(value) if value is not None else None


def _b(value) -> bool:
    """Cast to bool. Raises if None."""
    if value is None:
        raise ValueError("Expected bool value but got None.")
    return bool(value)


def _b_or_none(value) -> bool | None:
    """Return bool or None."""
    return bool(value) if value is not None else None


def _interval_to_min(value) -> int:
    """
    Convert a psycopg2 timedelta (from INTERVAL column) to whole minutes.
    Raises if None.
    """
    if value is None:
        raise ValueError("Expected INTERVAL value but got None.")
    if isinstance(value, timedelta):
        return round(value.total_seconds() / 60)
    return round(float(value) * 60)


def _interval_to_min_or_none(value) -> int | None:
    """Convert INTERVAL to minutes, or return None."""
    if value is None:
        return None
    if isinstance(value, timedelta):
        return round(value.total_seconds() / 60)
    return round(float(value) * 60)


def _src(
    row, source_id_field: str, sources: dict[int, ParamsSource]
) -> ParamsSource | None:
    """Look up a ParamsSource from the sources dict by source_id field on a row."""
    sid = row.get(source_id_field)
    return sources.get(sid) if sid is not None else None


# =============================================================================
# DB DATA LOADER
# =============================================================================


class DBDataLoader:
    """
    Data access layer that reads parameters from PostgreSQL and constructs
    fully typed domain objects from models/params.py.

    All default value resolution (None field substitution) happens here.
    WARNING is logged for every substituted default.
    """

    def __init__(self) -> None:
        self._conn = self._connect()

    def _connect(self):
        """
        Connect using environment variables only — no defaults.
        Raises KeyError with a clear message if any required variable is missing.
        Required: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
                  POSTGRES_USER, POSTGRES_PASSWORD.
        Set these in .env (loaded by python-dotenv in main.py).
        """
        required = [
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
        ]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise KeyError(
                f"Missing required environment variable(s) for DB connection: {', '.join(missing)}. "
                f"Check your .env file."
            )
        return psycopg2.connect(
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ["POSTGRES_PORT"]),
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )

    def _cursor(self):
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    # ------------------------------------------------------------------
    # SCENARIO RESOLUTION
    # ------------------------------------------------------------------

    def resolve_scenario_id(self, scenario_id: int | None) -> int:
        """
        Resolve None → the concrete scenario_id of the current is_current_base
        scenario. Callers building a multi-step pipeline (route_factory,
        API endpoints) should call this ONCE at the top and pass the
        concrete id to every subsequent loader call — resolving None
        independently on each call risks two calls disagreeing if
        is_current_base moves mid-request, and the concrete id is what
        needs to be stored in RouteProvenance for reproducibility.
        """
        if scenario_id is not None:
            return scenario_id
        with self._cursor() as cur:
            cur.execute(
                "SELECT scenario_id FROM scenario.scenarios WHERE is_current_base = TRUE"
            )
            row = cur.fetchone()
        if row is None:
            raise ValueError(
                "No scenario has is_current_base = TRUE — database is not "
                "correctly seeded."
            )
        return row["scenario_id"]

    def _resolve_scenario_versions(self, scenario_id: int | None) -> dict[str, int]:
        """
        Resolve a scenario_id (or None → the live is_current_base scenario)
        to its four per-table version pointers. Infrastructure only —
        operators/coach_types/composition_types/composition_references are
        unversioned catalogs and have no scenario pointer at all (see
        scenario.scenarios' docstring in create_scenario_schema.sql).

        Every column on scenario.scenarios is NOT NULL, so this is always a
        single direct row fetch — no inheritance/fallback logic needed.
        Returned dict keys match the *_version column names minus the
        "_version" suffix, e.g. {"track_infrastructures": 2, ...}.
        """
        with self._cursor() as cur:
            if scenario_id is None:
                cur.execute(
                    "SELECT * FROM scenario.scenarios WHERE is_current_base = TRUE"
                )
            else:
                cur.execute(
                    "SELECT * FROM scenario.scenarios WHERE scenario_id = %s",
                    (scenario_id,),
                )
            row = cur.fetchone()
        if row is None:
            if scenario_id is None:
                raise ValueError(
                    "No scenario has is_current_base = TRUE — database is not "
                    "correctly seeded."
                )
            raise ValueError(f"Scenario '{scenario_id}' not found.")

        return {
            "track_infrastructures": row["track_infrastructures_version"],
            "track_infrastructure_defaults": row[
                "track_infrastructure_defaults_version"
            ],
            "stop_infrastructures": row["stop_infrastructures_version"],
            "stop_infrastructure_defaults": row["stop_infrastructure_defaults_version"],
        }

    # ------------------------------------------------------------------
    # SOURCES
    # ------------------------------------------------------------------

    def _load_sources(self) -> dict[int, ParamsSource]:
        """Load all rows from input_params.sources keyed by source_id."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM input_params.sources")
            rows = cur.fetchall()
        return {
            row["source_id"]: ParamsSource(
                source_id=row["source_id"],
                source_description=row["source_description"],
                source_url=row.get("source_url"),
                source_date=str(row["source_date"]) if row.get("source_date") else None,
            )
            for row in rows
        }

    # ------------------------------------------------------------------
    # SERVICE CLASSES
    # ------------------------------------------------------------------

    def _load_service_classes(self) -> dict[str, ServiceClass]:
        """Load all rows from input_params.service_classes keyed by service_class_id."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM input_params.service_classes")
            rows = cur.fetchall()
        return {
            row["service_class_id"]: ServiceClass(
                class_id=row["service_class_id"],
                class_main=row["service_class_main"],
                density=_f(row["service_class_density"]),
            )
            for row in rows
        }

    # ------------------------------------------------------------------
    # COLUMN DESCRIPTIONS
    # ------------------------------------------------------------------

    def _load_column_comments(self, schema: str, table: str) -> dict[str, str]:
        """
        Load DB column comments for a table from pg_catalog.
        Returns {column_name: comment} for all commented columns.
        Called once per table at build time — not per row.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT a.attname, col_description(c.oid, a.attnum)
                FROM   pg_class c
                JOIN   pg_namespace n ON n.oid = c.relnamespace
                JOIN   pg_attribute a ON a.attrelid = c.oid
                WHERE  n.nspname = %s AND c.relname = %s
                  AND  a.attnum > 0 AND NOT a.attisdropped
                  AND  col_description(c.oid, a.attnum) IS NOT NULL
                ORDER BY a.attnum
            """,
                (schema, table),
            )
            rows = cur.fetchall()
        return {row["attname"]: row["col_description"] for row in rows}

    def _load_table_comment(self, schema: str, table: str) -> Optional[str]:
        """
        Load the DB table-level comment from pg_catalog.
        Returns None if the table has no comment.
        Called once per table at build time — not per row.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT obj_description(c.oid) AS table_comment
                FROM   pg_class c
                JOIN   pg_namespace n ON n.oid = c.relnamespace
                WHERE  n.nspname = %s AND c.relname = %s
            """,
                (schema, table),
            )
            row = cur.fetchone()
        return row["table_comment"] if row else None

    # ------------------------------------------------------------------
    # OPERATORS
    # ------------------------------------------------------------------

    def _load_all_operators(
        self, sources: dict[int, ParamsSource]
    ) -> tuple[dict[str, Operator], ParamVersions]:
        """
        Load every operator and its class stocking costs in two queries
        total, not one query per operator_id — operators is an unversioned
        catalog (see Operator's docstring), so there's no version to
        filter by and no reason to fetch it more than once per request.

        Returns (operators keyed by operator_id, ParamVersions covering
        "operator:*" and "operator_class_cost:*"). Every entry's version
        is None — see ParamVersionEntry. Field descriptions are no longer
        attached here — see CompositionCollection.descriptions, built
        once in build_all_compositions().
        """
        param_versions = ParamVersions()

        with self._cursor() as cur:
            cur.execute("SELECT * FROM input_params.operators")
            op_rows = cur.fetchall()

            cur.execute(
                """
                SELECT operator_row_id, service_class_id,
                       operator_class_svc_stockings_eur_place, source_id
                FROM input_params.operator_class_costs
            """
            )
            cost_rows = cur.fetchall()

        costs_by_operator_row: dict[int, list] = {}
        for cr in cost_rows:
            costs_by_operator_row.setdefault(cr["operator_row_id"], []).append(cr)

        operators: dict[str, Operator] = {}
        for row in op_rows:
            operator_id = row["operator_id"]
            stocking_rows = costs_by_operator_row.get(row["operator_row_id"], [])
            operator = Operator(
                operator_id=operator_id,
                operator_name=row["operator_name"],
                driver_costs_eur_h=_f(row["operator_driver_costs_eur_h"]),
                crew_costs_eur_h=_f(row["operator_crew_costs_eur_h"]),
                driver_overhead_min=_interval_to_min(row["operator_driver_overhead_h"]),
                crew_overhead_min=_interval_to_min(row["operator_crew_overhead_h"]),
                ebit_margin_per=_f(row["operator_ebit_margin_per"]),
                financing_quota_per=_f(row["operator_financing_quota_per"]),
                var_overhead_per=_f(row["operator_var_overhead_per"]),
                fix_overhead_quota_per=_f(row["operator_fix_overhead_quota_per"]),
                loco_full_service_lease_eur_h=_f(row["operator_loco_lease_eur_h"]),
                svc_stockings_eur_place={
                    sr["service_class_id"]: _f(
                        sr["operator_class_svc_stockings_eur_place"]
                    )
                    for sr in stocking_rows
                },
            )
            operators[operator_id] = operator

            op_src = _src(row, "source_id", sources)
            op_fields = {
                "driver_costs_eur_h": operator.driver_costs_eur_h,
                "crew_costs_eur_h": operator.crew_costs_eur_h,
                "driver_overhead_h": operator.driver_overhead_min,
                "crew_overhead_h": operator.crew_overhead_min,
                "ebit_margin_per": operator.ebit_margin_per,
                "financing_quota_per": operator.financing_quota_per,
                "var_overhead_per": operator.var_overhead_per,
                "fix_overhead_quota_per": operator.fix_overhead_quota_per,
                "loco_lease_eur_h": operator.loco_full_service_lease_eur_h,
            }
            for field_name, field_val in op_fields.items():
                param_versions.add(
                    key=f"operator:{operator_id}:{field_name}",
                    value=field_val,
                    source=op_src,
                )
            for sr in stocking_rows:
                param_versions.add(
                    key=f"operator_class_cost:{operator_id}:{sr['service_class_id']}",
                    value=_f(sr["operator_class_svc_stockings_eur_place"]),
                    source=_src(sr, "source_id", sources),
                )

        return operators, param_versions

    # ------------------------------------------------------------------
    # COACH TYPES
    # ------------------------------------------------------------------

    def _load_all_coach_types(
        self,
        sources: dict[int, ParamsSource],
        service_classes: dict[str, ServiceClass],
    ) -> tuple[dict[str, CoachType], dict[int, str], ParamVersions]:
        """
        Load every coach type and its class assignments in two queries
        total — coach_types is an unversioned catalog (see CoachType's
        docstring), so there's no version to filter by. Unlike the old
        per-composition loading, a coach type's classes are its own
        property, loaded here once rather than re-derived per composition
        that happens to use it.

        Returns (coach types keyed by coachtype_id, {coach_type_row_id:
        coachtype_id} for resolving composition_type_coaches joins,
        ParamVersions covering "coach_type:*"). Every entry's version is
        None — see ParamVersionEntry. Field descriptions are no longer
        attached here — see CompositionCollection.descriptions, built
        once in build_all_compositions().
        """
        param_versions = ParamVersions()

        with self._cursor() as cur:
            cur.execute("SELECT * FROM input_params.coach_types")
            ct_rows = cur.fetchall()

            cur.execute(
                """
                SELECT coach_type_row_id, service_class_id, coach_type_class_places
                FROM input_params.coach_type_classes
            """
            )
            class_rows = cur.fetchall()

        classes_by_coach_row: dict[int, dict[str, CoachClassAssignment]] = {}
        for cr in class_rows:
            sc = service_classes.get(cr["service_class_id"])
            if sc is None:
                logger.warning(
                    "ServiceClass '%s' not found — skipping class assignment "
                    "for coach_type_row_id %s.",
                    cr["service_class_id"],
                    cr["coach_type_row_id"],
                )
                continue
            classes_by_coach_row.setdefault(cr["coach_type_row_id"], {})[
                cr["service_class_id"]
            ] = CoachClassAssignment(
                class_id=cr["service_class_id"],
                class_main=sc.class_main,
                places=_i(cr["coach_type_class_places"]),
                density=sc.density,
            )

        coach_types: dict[str, CoachType] = {}
        row_id_to_id: dict[int, str] = {}
        for row in ct_rows:
            coachtype_id = row["coach_type_id"]
            row_id_to_id[row["coach_type_row_id"]] = coachtype_id
            coach_type = CoachType(
                coachtype_id=coachtype_id,
                weight_gross_t=_f(row["coach_type_weight_gross_t"]),
                crew_factor=_f(row["coach_type_crew_factor"]),
                bikes=_i(row["coach_type_bikes"]),
                climatization=_b(row["coach_type_climatization"]),
                plugs=_b(row["coach_type_plugs"]),
                classes=classes_by_coach_row.get(row["coach_type_row_id"], {}),
                remarks=row["coach_type_remarks"],
            )
            coach_types[coachtype_id] = coach_type

            ct_src = _src(row, "source_id", sources)
            ct_fields = {
                "weight_gross_t": coach_type.weight_gross_t,
                "crew_factor": coach_type.crew_factor,
                "bikes": coach_type.bikes,
                "climatization": coach_type.climatization,
                "plugs": coach_type.plugs,
            }
            for field_name, field_val in ct_fields.items():
                param_versions.add(
                    key=f"coach_type:{coachtype_id}:{field_name}",
                    value=field_val,
                    source=ct_src,
                )

        return coach_types, row_id_to_id, param_versions

    # ------------------------------------------------------------------
    # COMPOSITIONS
    # ------------------------------------------------------------------

    def build_all_compositions(
        self, scenario_id: int | None = None, include_indicative: bool = True
    ) -> CompositionCollection:
        """
        Return all compositions as a CompositionCollection, keyed by
        comp_id. Loaded in a fixed number of queries regardless of catalog
        size — operators and coach types are each loaded once via
        _load_all_operators()/_load_all_coach_types() and shared (by
        reference) across every composition that uses them, rather than
        rebuilt per composition (the old build_composition() + a loop
        did one round of queries per composition_id — an N+1 pattern).

        Not scenario-versioned: composition_types, operators, coach_types,
        and composition_references are all unversioned catalogs (see their
        docstrings in models/params.py) — a changed value means a new id,
        never editing a row in place. scenario_id is still accepted, and
        still matters when include_indicative=True: indicative KPIs are
        computed using track/stop infrastructure costs, which ARE
        scenario-versioned. It has no effect on composition/operator/coach
        type field values themselves.

        include_indicative: set False to skip loading tracks/stops and
        computing Composition.indicative entirely — route_factory doesn't
        use indicative KPIs (they're a composition-comparison display
        figure, not a routing input), so building a Route would otherwise
        pay for a tracks/stops reload it never uses. composition_reference
        provenance is still registered either way (cheap — no extra query).
        """
        sources = self._load_sources()
        service_classes = self._load_service_classes()

        # descriptions mirrors the ACTUAL response structure built by
        # api/helpers/params_serialize.py's composition_collection_to_dict()
        # — grouped by response section (routing/staff/energy/capacity/
        # equipment/coaches/fixed_costs/variable_km, then operators, then
        # indicative), not by raw source table. This matters because the
        # two don't line up 1:1: several DB columns (weight_gross_t,
        # crew_factor, bikes, climatization, plugs on coach_types) are
        # never exposed per-coach in the response at all — only as
        # composition-level sums/booleans (total_weight_t,
        # crew_factor_total, has_bikes, etc., derived by
        # Composition.from_type() from CompositionType.total_weight_t()
        # and friends). A table-shaped descriptions block would list
        # fields the response doesn't actually have, and miss the
        # aggregation semantics of the ones it does. Aggregated fields
        # below get hand-written text describing the aggregation; fields
        # that pass a DB column straight through use that column's real
        # comment (with the unit corrected where the API's unit differs
        # from the column's raw-storage unit — see min_boarding/
        # alighting_time_min below).
        comp_type_columns = self._load_column_comments(
            "input_params", "composition_types"
        )
        operator_columns = self._load_column_comments("input_params", "operators")
        operator_class_cost_columns = self._load_column_comments(
            "input_params", "operator_class_costs"
        )
        coach_type_columns = self._load_column_comments("input_params", "coach_types")
        comp_type_coaches_columns = self._load_column_comments(
            "input_params", "composition_type_coaches"
        )
        ref_columns = self._load_column_comments(
            "input_params", "composition_references"
        )

        descriptions = {
            "compositions": {
                "routing": {
                    "total_weight_t": (
                        "Total composition gross weight — sum of each "
                        "coach's gross weight across all coaches in this "
                        "composition. Unit: t"
                    ),
                    "max_speed_kmh": comp_type_columns.get(
                        "composition_type_max_speed_kmh"
                    ),
                    "hsr_allowed": comp_type_columns.get(
                        "composition_type_hsr_allowed"
                    ),
                    # DB stores these as an INTERVAL (column comment says
                    # "Unit: h"), but the API converts to minutes via
                    # _interval_to_min() — the comment text is corrected
                    # here rather than copied verbatim.
                    "min_boarding_time_min": (
                        "Vehicle-dependent minimum dwell time at boarding "
                        "stops. Unit: min"
                    ),
                    "min_alighting_time_min": (
                        "Vehicle-dependent minimum dwell time at alighting "
                        "stops. Unit: min"
                    ),
                },
                "staff": {
                    "driver_factor": comp_type_columns.get(
                        "composition_type_driver_factor"
                    ),
                    "crew_factor_total": (
                        "Total fractional cabin crew required — sum of "
                        "crew_factor across all coaches in this composition."
                    ),
                },
                "energy": {
                    "factor_weight": comp_type_columns.get(
                        "composition_type_energy_factor_weight"
                    ),
                    "factor_speed": comp_type_columns.get(
                        "composition_type_energy_factor_speed"
                    ),
                    "factor_terrain": comp_type_columns.get(
                        "composition_type_energy_factor_terrain"
                    ),
                },
                "capacity": {
                    "places": (
                        "Total places of this class across all coaches in "
                        "the composition — summed across coaches."
                    ),
                    "density": (
                        "Places-weighted average density of this class "
                        "across all coaches in the composition — space "
                        "units consumed per place, used for cost allocation."
                    ),
                },
                "equipment": {
                    "has_bikes": (
                        "True if ANY coach in the composition has bicycle " "spaces."
                    ),
                    "has_climatization": (
                        "True if ANY coach in the composition has air " "conditioning."
                    ),
                    "has_plugs": (
                        "True if ANY coach in the composition has passenger "
                        "power sockets."
                    ),
                },
                "coaches": {
                    "count": "Number of coaches in this composition.",
                    "coach_type_id": coach_type_columns.get("coach_type_id"),
                    "position": comp_type_coaches_columns.get("position"),
                    "remarks": coach_type_columns.get("coach_type_remarks"),
                },
                "fixed_costs": {
                    "purchase_coach_eur": comp_type_columns.get(
                        "composition_type_purchase_coach_eur"
                    ),
                    "coach_avail_per": comp_type_columns.get(
                        "composition_type_coach_avail_per"
                    ),
                    "coach_amort_years": comp_type_columns.get(
                        "composition_type_coach_amort_years"
                    ),
                    "cleaning_services_eur_day": comp_type_columns.get(
                        "composition_type_cleaning_eur_day"
                    ),
                },
                "variable_km": {
                    "coach_maint_eur_km": comp_type_columns.get(
                        "composition_type_coach_maint_eur_km"
                    ),
                },
            },
            "operators": {
                "driver_costs_eur_h": operator_columns.get(
                    "operator_driver_costs_eur_h"
                ),
                "crew_costs_eur_h": operator_columns.get("operator_crew_costs_eur_h"),
                "driver_overhead_h": operator_columns.get("operator_driver_overhead_h"),
                "crew_overhead_h": operator_columns.get("operator_crew_overhead_h"),
                "ebit_margin_per": operator_columns.get("operator_ebit_margin_per"),
                "financing_quota_per": operator_columns.get(
                    "operator_financing_quota_per"
                ),
                "var_overhead_per": operator_columns.get("operator_var_overhead_per"),
                "fix_overhead_quota_per": operator_columns.get(
                    "operator_fix_overhead_quota_per"
                ),
                "loco_full_service_lease_eur_h": operator_columns.get(
                    "operator_loco_lease_eur_h"
                ),
                "cost_per_class": operator_class_cost_columns.get(
                    "operator_class_svc_stockings_eur_place"
                ),
            },
            "indicative": {
                "kpis": {
                    "cost_eur_per_train_km": (
                        "Total composition cost ÷ reference distance, for "
                        "the reference trip profile. PLACEHOLDER figure — "
                        "see models/compositions/calc_indicative_figures.py."
                    ),
                    "cost_eur_per_place_km_by_class": (
                        "The same total cost allocated to each class "
                        "present in the composition, divided by that "
                        "class's density-weighted place-km. PLACEHOLDER "
                        "figure — see "
                        "models/compositions/calc_indicative_figures.py."
                    ),
                },
                "reference": {
                    "ref_distance_km": ref_columns.get("ref_distance_km"),
                    "ref_avg_speed_kmh": ref_columns.get("ref_avg_speed_kmh"),
                    "ref_terrain_score": ref_columns.get("ref_terrain_score"),
                    "ref_operating_days": ref_columns.get("ref_operating_days"),
                    # These two API keys are each assembled from five
                    # per-class DB columns (ref_utilization_seat/
                    # _couchette/_sleeper/_capsule/_catering, and the
                    # ref_avg_fare_* equivalents) — no single column
                    # comment applies, so this is composed rather than
                    # looked up directly.
                    "ref_utilization_by_class": (
                        "Reference load factor (share of places sold), "
                        "keyed by class_main (Seat, Couchette, Sleeper, "
                        "Capsule, Catering). Unit: %"
                    ),
                    "ref_avg_fare_by_class": (
                        "Reference average fare per sold place, keyed by "
                        "class_main (Seat, Couchette, Sleeper, Capsule, "
                        "Catering). Unit: €"
                    ),
                },
            },
        }

        operators, param_versions = self._load_all_operators(sources)
        coach_types, coach_row_id_to_id, coach_param_versions = (
            self._load_all_coach_types(sources, service_classes)
        )
        param_versions.entries.update(coach_param_versions.entries)

        with self._cursor() as cur:
            cur.execute("SELECT * FROM input_params.composition_types")
            comp_rows = cur.fetchall()

            cur.execute(
                """
                SELECT composition_type_row_id, position, coach_type_row_id
                FROM input_params.composition_type_coaches
                ORDER BY composition_type_row_id, position
            """
            )
            coach_slot_rows = cur.fetchall()

            cur.execute("SELECT * FROM input_params.composition_references")
            ref_rows = cur.fetchall()

        # --- assemble each composition's ordered coach slots, referencing
        #     the already-built shared CoachType instances ---
        coaches_by_comp_row: dict[int, dict[int, CoachType]] = {}
        for sr in coach_slot_rows:
            coach_id = coach_row_id_to_id.get(sr["coach_type_row_id"])
            if coach_id is None:
                logger.warning(
                    "composition_type_coaches references unknown "
                    "coach_type_row_id %s — skipping slot.",
                    sr["coach_type_row_id"],
                )
                continue
            coaches_by_comp_row.setdefault(sr["composition_type_row_id"], {})[
                sr["position"]
            ] = coach_types[coach_id]

        ref_rows_by_comp_row = {r["composition_type_row_id"]: r for r in ref_rows}

        # load tracks + stops once for all indicative calculations — only
        # if indicative figures are actually wanted (see include_indicative
        # docstring above)
        tracks = self.build_all_tracks(scenario_id) if include_indicative else None
        stop_infra = self.build_all_stops(scenario_id) if include_indicative else None

        result: dict[str, Composition] = {}
        for row in comp_rows:
            comp_id = row["composition_type_id"]
            comp_row_id = row["composition_type_row_id"]
            try:
                operator = operators.get(row["composition_type_operator_id"])
                if operator is None:
                    raise ValueError(
                        f"Operator '{row['composition_type_operator_id']}' "
                        f"not found for composition '{comp_id}'."
                    )

                comp_type = CompositionType(
                    comp_id=comp_id,
                    comp_description=row["composition_type_description"],
                    operator=operator,
                    driver_factor=_f(row["composition_type_driver_factor"]),
                    max_speed_kmh=_f(row["composition_type_max_speed_kmh"]),
                    hsr_allowed=_b(row["composition_type_hsr_allowed"]),
                    coaches=coaches_by_comp_row.get(comp_row_id, {}),
                    energy_factor_weight=_f(
                        row["composition_type_energy_factor_weight"]
                    ),
                    energy_factor_speed=_f(row["composition_type_energy_factor_speed"]),
                    energy_factor_terrain=_f(
                        row["composition_type_energy_factor_terrain"]
                    ),
                    min_boarding_time_min=_interval_to_min(
                        row["composition_type_min_boarding_time"]
                    ),
                    min_alighting_time_min=_interval_to_min(
                        row["composition_type_min_alighting_time"]
                    ),
                    purchase_coach_eur=_f(row["composition_type_purchase_coach_eur"]),
                    coach_avail_per=_f(row["composition_type_coach_avail_per"]),
                    coach_amort_years=_i(row["composition_type_coach_amort_years"]),
                    cleaning_services_eur_day=_f(
                        row["composition_type_cleaning_eur_day"]
                    ),
                    coach_maint_eur_km=_f(row["composition_type_coach_maint_eur_km"]),
                )

                comp_src = _src(row, "source_id", sources)
                comp_fields = {
                    "max_speed_kmh": comp_type.max_speed_kmh,
                    "hsr_allowed": comp_type.hsr_allowed,
                    "driver_factor": comp_type.driver_factor,
                    "energy_factor_weight": comp_type.energy_factor_weight,
                    "energy_factor_speed": comp_type.energy_factor_speed,
                    "energy_factor_terrain": comp_type.energy_factor_terrain,
                    "min_boarding_time_min": comp_type.min_boarding_time_min,
                    "min_alighting_time_min": comp_type.min_alighting_time_min,
                    "purchase_coach_eur": comp_type.purchase_coach_eur,
                    "coach_avail_per": comp_type.coach_avail_per,
                    "coach_amort_years": comp_type.coach_amort_years,
                    "cleaning_services_eur_day": comp_type.cleaning_services_eur_day,
                    "coach_maint_eur_km": comp_type.coach_maint_eur_km,
                }
                for field_name, field_val in comp_fields.items():
                    param_versions.add(
                        key=f"composition_type:{comp_id}:{field_name}",
                        value=field_val,
                        source=comp_src,
                    )

                comp = Composition.from_type(comp_type)

                # --- indicative KPIs, if a reference profile exists ---
                ref_row = ref_rows_by_comp_row.get(comp_row_id)
                if ref_row:
                    ref = CompositionReference(
                        composition_type_id=comp_id,
                        ref_distance_km=float(ref_row["ref_distance_km"]),
                        ref_avg_speed_kmh=float(ref_row["ref_avg_speed_kmh"]),
                        ref_terrain_score=float(ref_row["ref_terrain_score"]),
                        ref_operating_days=int(ref_row["ref_operating_days"]),
                        ref_utilization_by_class={
                            "Seat": float(ref_row["ref_utilization_seat"]),
                            "Couchette": float(ref_row["ref_utilization_couchette"]),
                            "Sleeper": float(ref_row["ref_utilization_sleeper"]),
                            "Capsule": float(ref_row["ref_utilization_capsule"]),
                            "Catering": float(ref_row["ref_utilization_catering"]),
                        },
                        ref_avg_fare_by_class={
                            "Seat": float(ref_row["ref_avg_fare_seat"]),
                            "Couchette": float(ref_row["ref_avg_fare_couchette"]),
                            "Sleeper": float(ref_row["ref_avg_fare_sleeper"]),
                            "Capsule": float(ref_row["ref_avg_fare_capsule"]),
                            "Catering": float(ref_row["ref_avg_fare_catering"]),
                        },
                    )

                    ref_src = _src(ref_row, "source_id", sources)
                    ref_fields = {
                        "ref_distance_km": ref.ref_distance_km,
                        "ref_avg_speed_kmh": ref.ref_avg_speed_kmh,
                        "ref_terrain_score": ref.ref_terrain_score,
                        "ref_operating_days": ref.ref_operating_days,
                        "ref_utilization_seat": ref.ref_utilization_by_class["Seat"],
                        "ref_utilization_couchette": ref.ref_utilization_by_class[
                            "Couchette"
                        ],
                        "ref_utilization_sleeper": ref.ref_utilization_by_class[
                            "Sleeper"
                        ],
                        "ref_utilization_capsule": ref.ref_utilization_by_class[
                            "Capsule"
                        ],
                        "ref_utilization_catering": ref.ref_utilization_by_class[
                            "Catering"
                        ],
                        "ref_avg_fare_seat": ref.ref_avg_fare_by_class["Seat"],
                        "ref_avg_fare_couchette": ref.ref_avg_fare_by_class[
                            "Couchette"
                        ],
                        "ref_avg_fare_sleeper": ref.ref_avg_fare_by_class["Sleeper"],
                        "ref_avg_fare_capsule": ref.ref_avg_fare_by_class["Capsule"],
                        "ref_avg_fare_catering": ref.ref_avg_fare_by_class["Catering"],
                    }
                    for field_name, field_val in ref_fields.items():
                        param_versions.add(
                            key=f"composition_reference:{comp_id}:{field_name}",
                            value=field_val,
                            source=ref_src,
                        )

                    if include_indicative:
                        try:
                            from models.compositions.calc_indicative_figures import (
                                compute_indicative_figures,
                            )

                            comp.indicative = compute_indicative_figures(
                                comp, ref, tracks, stop_infra
                            )
                            comp.indicative.reference = ref
                        except Exception as e:
                            logger.warning(
                                "Indicative figures failed for '%s': %s", comp_id, e
                            )
                            comp.indicative = None
                    else:
                        comp.indicative = None
                else:
                    logger.warning(
                        "No composition_references row for '%s' — indicative figures unavailable.",
                        comp_id,
                    )
                    comp.indicative = None

                result[comp_id] = comp
            except Exception as e:
                logger.warning("Skipping composition '%s': %s", comp_id, e)
                self._conn.rollback()

        logger.info(
            "Built %d compositions (%d with indicative figures).",
            len(result),
            sum(1 for c in result.values() if c.indicative),
        )
        return CompositionCollection(result, param_versions, descriptions)

    # ------------------------------------------------------------------
    # TRACK INFRASTRUCTURE
    # ------------------------------------------------------------------

    def build_all_tracks(self, scenario_id: int | None = None) -> TrackInfraCollection:
        """
        Return track infrastructure at a scenario's pinned version as a
        TrackInfraCollection. Source/version/is_default provenance for
        every field lives on the collection itself, at
        collection.param_versions; the single raw default row used for
        fallback resolution lives at collection.defaults; static
        table/column documentation lives at collection.descriptions —
        none of these are returned separately.

        Any None field in a country row is substituted with the EU-average
        default from track_infrastructure_defaults. A WARNING is logged per
        substitution. Any country in input_params.countries with NO row in
        track_infrastructures at all gets a complete row synthesized
        entirely from the defaults (TrackInfrastructure.has_row=False for
        these), so the returned collection always has one entry per known
        country — see TrackInfraCollection's docstring. has_row is what
        route_factory._check_country_coverage() uses to decide whether a
        country is routable; individual defaulted fields on an otherwise
        real row don't block a route.
        """
        versions = self._resolve_scenario_versions(scenario_id)
        sources = self._load_sources()

        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM input_params.track_infrastructures
                WHERE track_infra_version = %s
            """,
                (versions["track_infrastructures"],),
            )
            rows = cur.fetchall()

            cur.execute(
                """
                SELECT * FROM input_params.track_infrastructure_defaults
                WHERE track_infra_default_version = %s
                LIMIT 1
            """,
                (versions["track_infrastructure_defaults"],),
            )
            default_row = cur.fetchone()

            cur.execute("SELECT country_code FROM input_params.countries")
            all_country_codes = [r["country_code"] for r in cur.fetchall()]

        if default_row is None:
            raise ValueError(
                "No track infrastructure defaults found — cannot resolve missing values."
            )

        default = DefaultTrackInfra(
            tac_eur_train_km=_f(default_row["track_tac_eur_train_km"]),
            tac_src=_src(default_row, "track_tac_src", sources),
            parking_eur_day=_f(default_row["track_parking_eur_day"]),
            parking_src=_src(default_row, "track_parking_src", sources),
            shunting_eur_event=_f(default_row["track_shunting_eur_event"]),
            shunting_src=_src(default_row, "track_shunting_src", sources),
            energy_price_eur_kwh=_f(default_row["track_energy_price_eur_kwh"]),
            energy_price_src=_src(default_row, "track_energy_price_src", sources),
            terrain_score=_f(default_row["track_terrain_score"]),
            terrain_category=default_row["track_terrain_category"],
            terrain_src=_src(default_row, "track_terrain_src", sources),
            hsr_allowed=_b(default_row["track_hsr_allowed"]),
            hsr_src=_src(default_row, "track_hsr_src", sources),
            min_boarding_time_min=_interval_to_min(
                default_row["track_min_boarding_time"]
            ),
            min_boarding_src=_src(default_row, "track_min_boarding_src", sources),
            min_alighting_time_min=_interval_to_min(
                default_row["track_min_alighting_time"]
            ),
            min_alighting_src=_src(default_row, "track_min_alighting_src", sources),
            buffer_quota_per=_f(default_row["track_buffer_quota_per"]),
            buffer_src=_src(default_row, "track_buffer_src", sources),
        )

        # Table/column documentation is identical for every country, so
        # it's captured once here — as TrackInfraDescriptions — rather
        # than looked up and stashed redundantly on every per-country
        # ParamVersions entry (see TrackInfraCollection.descriptions).
        #
        # _TRACK_DESCRIPTION_COLUMNS maps each exposed field name to its
        # real column name — NOT a uniform "track_" + field_name prefix:
        # min_boarding_time_min/min_alighting_time_min drop the "_min"
        # suffix on the column side (track_min_boarding_time /
        # track_min_alighting_time). Getting this wrong silently returns
        # None from _load_column_comments() rather than raising — see
        # build_all_stops()'s _STOP_DESCRIPTION_COLUMNS for the analogous
        # bug this pattern was introduced to avoid.
        _TRACK_DESCRIPTION_COLUMNS = {
            "tac_eur_train_km": "track_tac_eur_train_km",
            "parking_eur_day": "track_parking_eur_day",
            "shunting_eur_event": "track_shunting_eur_event",
            "energy_price_eur_kwh": "track_energy_price_eur_kwh",
            "terrain_score": "track_terrain_score",
            "terrain_category": "track_terrain_category",
            "hsr_allowed": "track_hsr_allowed",
            "min_boarding_time_min": "track_min_boarding_time",
            "min_alighting_time_min": "track_min_alighting_time",
            "buffer_quota_per": "track_buffer_quota_per",
        }
        track_column_comments = self._load_column_comments(
            "input_params", "track_infrastructures"
        )
        descriptions = TrackInfraDescriptions(
            table=self._load_table_comment("input_params", "track_infrastructures"),
            fields={
                field_name: track_column_comments.get(column_name)
                for field_name, column_name in _TRACK_DESCRIPTION_COLUMNS.items()
            },
        )
        # DB stores these as an INTERVAL (column comment says "Unit: h"),
        # but the API converts to minutes via _interval_to_min() — the
        # comment text is corrected here rather than copied verbatim (same
        # fix applied to the analogous composition_type fields in
        # build_all_compositions()).
        descriptions.fields["min_boarding_time_min"] = (
            "Infrastructure-dependent minimum dwell time at boarding "
            "stops. Unit: min"
        )
        descriptions.fields["min_alighting_time_min"] = (
            "Infrastructure-dependent minimum dwell time at alighting "
            "stops. Unit: min"
        )

        result: dict[str, TrackInfrastructure] = {}
        param_versions = ParamVersions()

        def register(
            cc: str,
            track: TrackInfrastructure,
            version: int,
            field_sources: dict[str, Optional[ParamsSource]],
        ) -> None:
            """Register one ParamVersions entry per track field — source,
            version, and is_default only; description lives once on
            `descriptions` above, not duplicated per country/field here.
            Shared by both real rows and whole-country-synthesized rows
            below so the two paths can't drift apart."""
            for field_name in TRACK_INFRA_FIELD_NAMES:
                param_versions.add(
                    key=f"track_infra:{cc}:{field_name}",
                    value=getattr(track, field_name),
                    version=version,
                    source=field_sources.get(field_name),
                    is_default=track.field_is_default.get(field_name, False),
                )

        for row in rows:
            cc = row["country_code"]
            try:
                track, field_sources = self._row_to_track(cc, row, default, sources)
                result[cc] = track
                register(cc, track, _i(row["track_infra_version"]), field_sources)
            except Exception as e:
                logger.warning("Skipping track infrastructure row '%s': %s", cc, e)

        # Countries with no track_infrastructures row at all still need a
        # complete, usable TrackInfrastructure — synthesized entirely from
        # DefaultTrackInfra, versioned/sourced against the defaults table
        # itself since there's no country-specific row to reference.
        default_field_sources = {
            field_name: default.source_for(field_name)
            for field_name in TRACK_INFRA_FIELD_NAMES
        }
        synthesized = 0
        for cc in all_country_codes:
            if cc in result:
                continue
            logger.warning(
                "TrackInfrastructure[%s]: no row in track_infrastructures — using EU-average default for every field.",
                cc,
            )
            track = TrackInfrastructure(
                country_code=cc,
                field_is_default={f: True for f in TRACK_INFRA_FIELD_NAMES},
                has_row=False,
                tac_eur_train_km=default.tac_eur_train_km,
                parking_eur_day=default.parking_eur_day,
                shunting_eur_event=default.shunting_eur_event,
                energy_price_eur_kwh=default.energy_price_eur_kwh,
                terrain_score=default.terrain_score,
                terrain_category=default.terrain_category,
                hsr_allowed=default.hsr_allowed,
                min_boarding_time_min=default.min_boarding_time_min,
                min_alighting_time_min=default.min_alighting_time_min,
                buffer_quota_per=default.buffer_quota_per,
            )
            result[cc] = track
            register(
                cc,
                track,
                versions["track_infrastructure_defaults"],
                default_field_sources,
            )
            synthesized += 1

        logger.info(
            "Built track infrastructure for %d countries (%d synthesized entirely from defaults).",
            len(result),
            synthesized,
        )
        return TrackInfraCollection(result, param_versions, default, descriptions)

    def _row_to_track(
        self,
        country_code: str,
        row,
        default: DefaultTrackInfra,
        sources: dict[int, ParamsSource],
    ) -> tuple[TrackInfrastructure, dict[str, Optional[ParamsSource]]]:
        """
        Map one infrastructure DB row to a TrackInfrastructure.
        Substitutes None fields with default values and logs a WARNING each time.
        psycopg2 RealDictCursor handles type mapping — Decimal, bool, timedelta
        are returned natively; only NULL becomes Python None.

        Returns (track, field_sources) — field_sources maps each value-field
        name (see TRACK_INFRA_FIELD_NAMES) to the ParamsSource it came from.
        Returned alongside the track rather than stored on it
        (TrackInfrastructure carries no _src fields — see its docstring) or
        stashed on self, so build_all_tracks() can register them in
        ParamVersions without any cross-call instance state.
        """

        def resolve(field, raw, default_val) -> tuple:
            """Returns (value, is_default)."""
            if raw is None:
                logger.warning(
                    "TrackInfrastructure[%s].%s is None — using EU default.",
                    country_code,
                    field,
                )
                return default_val, True
            return raw, False

        row_src = _src(row, "source_id", sources)

        # per-field sources — use specific _src column if present, else row-level source
        def field_src(col: str) -> ParamsSource | None:
            return _src(row, col, sources) or row_src

        tac_val, tac_def = resolve(
            "tac_eur_train_km",
            _f_or_none(row["track_tac_eur_train_km"]),
            default.tac_eur_train_km,
        )
        parking_val, parking_def = resolve(
            "parking_eur_day",
            _f_or_none(row["track_parking_eur_day"]),
            default.parking_eur_day,
        )
        shunting_val, shunting_def = resolve(
            "shunting_eur_event",
            _f_or_none(row["track_shunting_eur_event"]),
            default.shunting_eur_event,
        )
        energy_val, energy_def = resolve(
            "energy_price_eur_kwh",
            _f_or_none(row["track_energy_price_eur_kwh"]),
            default.energy_price_eur_kwh,
        )
        terrain_val, terrain_def = resolve(
            "terrain_score",
            _f_or_none(row["track_terrain_score"]),
            default.terrain_score,
        )
        terr_cat_val, terr_cat_def = resolve(
            "terrain_category",
            row.get("track_terrain_category"),
            default.terrain_category,
        )
        hsr_val, hsr_def = resolve(
            "hsr_allowed", _b_or_none(row["track_hsr_allowed"]), default.hsr_allowed
        )
        board_val, board_def = resolve(
            "min_boarding_time_min",
            _interval_to_min_or_none(row["track_min_boarding_time"]),
            default.min_boarding_time_min,
        )
        alight_val, alight_def = resolve(
            "min_alighting_time_min",
            _interval_to_min_or_none(row["track_min_alighting_time"]),
            default.min_alighting_time_min,
        )
        buffer_val, buffer_def = resolve(
            "buffer_quota_per",
            _f_or_none(row["track_buffer_quota_per"]),
            default.buffer_quota_per,
        )

        field_is_default = {
            "tac_eur_train_km": tac_def,
            "parking_eur_day": parking_def,
            "shunting_eur_event": shunting_def,
            "energy_price_eur_kwh": energy_def,
            "terrain_score": terrain_def,
            "terrain_category": terr_cat_def,
            "hsr_allowed": hsr_def,
            "min_boarding_time_min": board_def,
            "min_alighting_time_min": alight_def,
            "buffer_quota_per": buffer_def,
        }

        field_sources = {
            "tac_eur_train_km": field_src("track_tac_src")
            or (default.tac_src if tac_def else None),
            "parking_eur_day": field_src("track_parking_src")
            or (default.parking_src if parking_def else None),
            "shunting_eur_event": field_src("track_shunting_src")
            or (default.shunting_src if shunting_def else None),
            "energy_price_eur_kwh": field_src("track_energy_price_src")
            or (default.energy_price_src if energy_def else None),
            "terrain_score": field_src("track_terrain_src")
            or (default.terrain_src if terrain_def else None),
            "terrain_category": field_src("track_terrain_src")
            or (default.terrain_src if terr_cat_def else None),
            "hsr_allowed": field_src("track_hsr_src")
            or (default.hsr_src if hsr_def else None),
            "min_boarding_time_min": field_src("track_min_boarding_src")
            or (default.min_boarding_src if board_def else None),
            "min_alighting_time_min": field_src("track_min_alighting_src")
            or (default.min_alighting_src if alight_def else None),
            "buffer_quota_per": field_src("track_buffer_src")
            or (default.buffer_src if buffer_def else None),
        }

        track = TrackInfrastructure(
            country_code=country_code,
            field_is_default=field_is_default,
            has_row=True,
            tac_eur_train_km=tac_val,
            parking_eur_day=parking_val,
            shunting_eur_event=shunting_val,
            energy_price_eur_kwh=energy_val,
            terrain_score=terrain_val,
            terrain_category=terr_cat_val,
            hsr_allowed=hsr_val,
            min_boarding_time_min=board_val,
            min_alighting_time_min=alight_val,
            buffer_quota_per=buffer_val,
        )
        return track, field_sources

    # ------------------------------------------------------------------
    # STOP INFRASTRUCTURE
    # ------------------------------------------------------------------

    def build_all_stops(self, scenario_id: int | None = None) -> StopInfraCollection:
        """
        Return stops at a scenario's pinned version as a StopInfraCollection.
        Source/version/is_default provenance for every stop field lives on
        the collection itself, at collection.param_versions; the raw default
        rows used for fallback resolution live at collection.defaults; static
        table/column documentation lives at collection.descriptions — none
        of these are returned separately.

        If a stop has no stop_charge_eur, the country default from
        stop_infrastructure_defaults is used. If no country default exists,
        the global default (country_code IS NULL) is used.
        A WARNING is logged per substitution.
        """
        versions = self._resolve_scenario_versions(scenario_id)
        sources = self._load_sources()

        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM input_params.stop_infrastructures
                WHERE stop_infra_version = %s
            """,
                (versions["stop_infrastructures"],),
            )
            stop_rows = cur.fetchall()

            cur.execute(
                """
                SELECT * FROM input_params.stop_infrastructure_defaults
                WHERE stop_infra_default_version = %s
            """,
                (versions["stop_infrastructure_defaults"],),
            )
            default_rows = cur.fetchall()

        # build defaults keyed by country_code; NULL country_code = global default
        defaults: dict[str | None, DefaultStopInfra] = {}
        for dr in default_rows:
            key = dr.get("country_code")  # None = global
            defaults[key] = DefaultStopInfra(
                stop_charge_eur=_f(dr["stop_charge_eur"]),
                stop_charge_src=_src(dr, "stop_charge_src", sources),
            )

        global_default = defaults.get(None)
        if global_default is None:
            raise ValueError(
                "No global stop default found — cannot resolve missing stop charges."
            )

        # Table/column documentation is identical for every stop, so it's
        # captured once here — as StopInfraDescriptions — rather than looked
        # up and stashed redundantly on every per-stop ParamVersions entry
        # (see StopInfraCollection.descriptions).
        #
        # _STOP_DESCRIPTION_COLUMNS maps each exposed field name to its real
        # column name: "lat"/"lon" need the "stop_" prefix added (columns are
        # stop_lat/stop_lon), but "stop_charge_eur" already IS the column
        # name — prepending "stop_" again would look up the nonexistent
        # "stop_stop_charge_eur" and silently return None (the previous bug
        # here — descriptions always came back null for stop_charge_eur).
        _STOP_DESCRIPTION_COLUMNS = {
            "lat": "stop_lat",
            "lon": "stop_lon",
            "stop_charge_eur": "stop_charge_eur",
        }
        stop_column_comments = self._load_column_comments(
            "input_params", "stop_infrastructures"
        )
        descriptions = StopInfraDescriptions(
            table=self._load_table_comment("input_params", "stop_infrastructures"),
            fields={
                field_name: stop_column_comments.get(column_name)
                for field_name, column_name in _STOP_DESCRIPTION_COLUMNS.items()
            },
        )

        result: dict[str, StopInfrastructure] = {}
        param_versions = ParamVersions()
        for row in stop_rows:
            try:
                country_cc = row.get("country_code", "")
                fallback = defaults.get(country_cc, global_default)
                stop, loc_src, charge_src, charge_is_default = self._row_to_stop(
                    row, fallback, sources, country_cc in defaults
                )
                result[row["stop_id"]] = stop

                # register one ParamVersions entry per stop field — source,
                # version, and is_default only; description lives once on
                # `descriptions` above, not duplicated per stop/field here.
                stop_version = _i(row["stop_infra_version"])
                stop_id_key = row["stop_id"]
                stop_fields = {
                    "lat": (stop.lat, loc_src, False),
                    "lon": (stop.lon, loc_src, False),
                    "stop_charge_eur": (
                        stop.stop_charge_eur,
                        charge_src,
                        charge_is_default,
                    ),
                }
                for field_name, (
                    field_val,
                    field_src,
                    is_default,
                ) in stop_fields.items():
                    param_versions.add(
                        key=f"stop_infra:{stop_id_key}:{field_name}",
                        value=field_val,
                        version=stop_version,
                        source=field_src,
                        is_default=is_default,
                    )
            except Exception as e:
                logger.warning("Skipping stop '%s': %s", row.get("stop_id"), e)

        logger.info("Built %d stops.", len(result))
        return StopInfraCollection(result, param_versions, defaults, descriptions)

    def _row_to_stop(
        self,
        row,
        default: DefaultStopInfra,
        sources: dict[int, ParamsSource],
        has_country_default: bool,
    ) -> tuple[
        StopInfrastructure, Optional[ParamsSource], Optional[ParamsSource], bool
    ]:
        """
        Map one stop DB row to a StopInfrastructure.
        Substitutes None stop_charge_eur with the country or global default
        and logs a WARNING. Same resolve() pattern as _row_to_track().
        psycopg2 RealDictCursor handles type mapping natively.

        Returns (stop, loc_src, charge_src, charge_is_default) — the three
        provenance ingredients are returned alongside the stop rather than
        stored on it (StopInfrastructure carries no _src fields — see its
        docstring) or stashed on self, so build_all_stops() can register
        them in ParamVersions without any cross-call instance state.
        """
        stop_id = row["stop_id"]

        def resolve(field, raw, default_val) -> tuple:
            """Returns (value, is_default)."""
            if raw is None:
                logger.warning(
                    "StopInfrastructure[%s].%s is None — using %s default.",
                    stop_id,
                    field,
                    "country" if has_country_default else "global",
                )
                return default_val, True
            return raw, False

        loc_src = _src(row, "stop_loc_src", sources)
        charge_src = _src(row, "stop_charge_src", sources)
        charge, charge_is_default = resolve(
            "stop_charge_eur",
            _f_or_none(row["stop_charge_eur"]),
            default.stop_charge_eur,
        )
        if charge_is_default:
            charge_src = default.stop_charge_src

        stop = StopInfrastructure(
            stop_id=stop_id,
            stop_name=row.get("stop_name") or "",
            stop_country_code=row.get("country_code", ""),
            lat=_f(row["stop_lat"]),
            lon=_f(row["stop_lon"]),
            stop_charge_eur=charge,
        )
        return stop, loc_src, charge_src, charge_is_default

    # ------------------------------------------------------------------
    # COUNTRY GEOMETRIES
    # ------------------------------------------------------------------

    def get_country_geometries(self) -> list[tuple[str, dict]]:
        """
        Return (country_code, GeoJSON geometry) pairs for every country that
        has a border polygon seeded — country_code is ISO 3166-1 alpha-2,
        matching every other country_code in the codebase.

        input_params.countries is static reference data, not one of the
        eight scenario-versioned tables, so there's no scenario_id/version
        to resolve here — this is always the current (only) generation.

        Returns plain (str, dict) pairs rather than a domain object: this
        is a data-access method, not a domain-model builder, so it doesn't
        construct rail_router.CountryIndex itself (routing-specific — would
        pull a routing-layer import into the data-access layer). Callers
        build whatever representation they need from the raw geometry.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT country_code, ST_AsGeoJSON(country_geom) AS geom
                FROM input_params.countries
                WHERE country_geom IS NOT NULL
                """
            )
            rows = cur.fetchall()
        result = [(row["country_code"], json.loads(row["geom"])) for row in rows]
        logger.info("Loaded %d country geometries.", len(result))
        return result
