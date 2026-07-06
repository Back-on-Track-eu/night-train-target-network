"""
data_loader_from_db.py
======================
Database data access layer for the night train model.
Reads all parameter tables from PostgreSQL and builds typed domain objects
defined in models/params.py.

Typical usage
-------------
    loader = DBDataLoader()
    composition  = loader.build_composition("STD-7.1")
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
  build_composition()     → Composition  (via CompositionType.from_type())
  build_all_compositions()→ dict[str, Composition]
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
    DefaultTrackInfra,
    TrackInfrastructure,
    TrackInfraCollection,
    DefaultStopInfra,
    StopInfrastructure,
    StopInfraCollection,
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
        self._track_defaults: dict[str, dict[str, bool]] = {}
        self._stop_defaults: dict[str, dict[str, bool]] = {}

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
        to its eight per-table version pointers.

        Every column on scenario.scenarios is NOT NULL, so this is always a
        single direct row fetch — no inheritance/fallback logic needed.
        Returned dict keys match the *_version column names minus the
        "_version" suffix, e.g. {"operators": 1, "track_infrastructures": 2, ...}.
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
            "operators": row["operators_version"],
            "coach_types": row["coach_types_version"],
            "composition_types": row["composition_types_version"],
            "composition_references": row["composition_references_version"],
            "track_infrastructures": row["track_infrastructures_version"],
            "track_infrastructure_defaults": row["track_infrastructure_defaults_version"],
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

    # ------------------------------------------------------------------
    # OPERATORS
    # ------------------------------------------------------------------

    def _load_operator(
        self,
        operator_id: str,
        operators_version: int,
        sources: dict[int, ParamsSource],
    ) -> tuple[Operator, ParamsSource | None, dict[str, ParamsSource | None]]:
        """
        Load one Operator (at a specific scenario-pinned version) with its class
        stocking costs.

        Returns (Operator, operator_src, class_cost_sources) — operator_src is
        the source for the operator row itself; class_cost_sources maps
        class_id -> source for that class's operator_class_costs row. Returned
        rather than resolved from the composition row, since the operator row
        has its own source_id, distinct from the composition's.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM input_params.operators
                WHERE operator_id = %s AND operator_version = %s
            """,
                (operator_id, operators_version),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(
                    f"Operator '{operator_id}' not found at version {operators_version}."
                )
            operator_row_id = row["operator_row_id"]

            cur.execute(
                """
                SELECT occ.service_class_id, occ.operator_class_svc_stockings_eur_place, occ.source_id
                FROM input_params.operator_class_costs occ
                WHERE occ.operator_row_id = %s
            """,
                (operator_row_id,),
            )
            stocking_rows = cur.fetchall()

        operator = Operator(
            operator_id=row["operator_id"],
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
                sr["service_class_id"]: _f(sr["operator_class_svc_stockings_eur_place"])
                for sr in stocking_rows
            },
        )
        operator_src = _src(row, "source_id", sources)
        class_cost_sources = {
            sr["service_class_id"]: _src(sr, "source_id", sources) for sr in stocking_rows
        }
        return operator, operator_src, class_cost_sources

    # ------------------------------------------------------------------
    # COMPOSITIONS
    # ------------------------------------------------------------------

    def build_composition(
        self, comp_id: str, scenario_id: int | None = None
    ) -> tuple[Composition, ParamVersions]:
        """
        Build a fully resolved Composition for a single composition ID, pinned
        to a scenario's versions (or the live is_current_base scenario if
        scenario_id is None).

        Returns (Composition, ParamVersions) — the caller should merge
        param_versions into the route-level ParamVersions.
        """
        versions = self._resolve_scenario_versions(scenario_id)
        sources = self._load_sources()
        service_classes = self._load_service_classes()
        param_versions = ParamVersions()

        with self._cursor() as cur:
            # --- core composition row, at the pinned version ---
            cur.execute(
                """
                SELECT * FROM input_params.composition_types
                WHERE composition_type_id = %s AND composition_type_version = %s
            """,
                (comp_id, versions["composition_types"]),
            )
            comp_row = cur.fetchone()
            if comp_row is None:
                raise ValueError(
                    f"Composition '{comp_id}' not found at version "
                    f"{versions['composition_types']}."
                )

            comp_row_id = comp_row["composition_type_row_id"]

            # --- coaches: ordered by position (coach_type_row_id is already
            #     version-pinned via composition_type_coaches, itself scoped
            #     to this composition_type_row_id) ---
            cur.execute(
                """
                SELECT
                    co.position,
                    ct.*
                FROM input_params.composition_type_coaches co
                JOIN input_params.coach_types ct ON ct.coach_type_row_id = co.coach_type_row_id
                WHERE co.composition_type_row_id = %s
                ORDER BY co.position
            """,
                (comp_row_id,),
            )
            coach_rows = cur.fetchall()

            # --- class assignments per coach_type_row_id ---
            cur.execute(
                """
                SELECT
                    co.position,
                    cc.service_class_id,
                    cc.coach_type_class_places
                FROM input_params.composition_type_coaches co
                JOIN input_params.coach_type_classes cc ON cc.coach_type_row_id = co.coach_type_row_id
                WHERE co.composition_type_row_id = %s
                ORDER BY co.position
            """,
                (comp_row_id,),
            )
            class_rows = cur.fetchall()

        # --- build coaches dict keyed by position ---
        classes_by_position: dict[int, dict[str, CoachClassAssignment]] = {}
        for cr in class_rows:
            pos = cr["position"]
            sc = service_classes.get(cr["service_class_id"])
            if sc is None:
                logger.warning(
                    "ServiceClass '%s' not found — skipping assignment "
                    "at position %d for composition '%s'.",
                    cr["service_class_id"],
                    pos,
                    comp_id,
                )
                continue
            classes_by_position.setdefault(pos, {})[cr["service_class_id"]] = (
                CoachClassAssignment(
                    class_id=cr["service_class_id"],
                    class_main=sc.class_main,
                    places=_i(cr["coach_type_class_places"]),
                    density=sc.density,
                )
            )

        coaches: dict[int, CoachType] = {}
        for cr in coach_rows:
            pos = cr["position"]
            coaches[pos] = CoachType(
                coachtype_id=cr["coach_type_id"],
                weight_gross_t=_f(cr["coach_type_weight_gross_t"]),
                crew_factor=_f(cr["coach_type_crew_factor"]),
                bikes=_i(cr["coach_type_bikes"]),
                climatization=_b(cr["coach_type_climatization"]),
                plugs=_b(cr["coach_type_plugs"]),
                classes=classes_by_position.get(pos, {}),
                remarks=cr["coach_type_remarks"],
            )
            # register coach_type fields in param_versions
            ct_descriptions = self._load_column_comments("input_params", "coach_types")
            ct_src = sources.get(cr["source_id"]) if cr.get("source_id") else None
            ct_version = _i(cr["coach_type_version"])
            ct_fields = {
                "weight_gross_t": _f(cr["coach_type_weight_gross_t"]),
                "crew_factor": _f(cr["coach_type_crew_factor"]),
                "bikes": _i(cr["coach_type_bikes"]),
                "climatization": _b(cr["coach_type_climatization"]),
                "plugs": _b(cr["coach_type_plugs"]),
            }
            for field_name, field_val in ct_fields.items():
                param_versions.add(
                    key=f"coach_type:{cr['coach_type_id']}:{field_name}",
                    value=field_val,
                    version=ct_version,
                    source=ct_src,
                    description=ct_descriptions.get(f"coach_type_{field_name}"),
                )

        operator, op_src, class_cost_sources = self._load_operator(
            comp_row["composition_type_operator_id"], versions["operators"], sources
        )

        # register operator fields in param_versions — op_src comes from the
        # operator's own row (see _load_operator), not the composition's
        op_descriptions = self._load_column_comments("input_params", "operators")
        op_version = versions["operators"]
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
                key=f"operator:{operator.operator_id}:{field_name}",
                value=field_val,
                version=op_version,
                source=op_src,
                description=op_descriptions.get(f"operator_{field_name}"),
            )

        # register operator_class_costs sources — one row per class, tied to
        # the operator row (no separate version column of its own)
        occ_descriptions = self._load_column_comments(
            "input_params", "operator_class_costs"
        )
        for class_id, svc_cost in operator.svc_stockings_eur_place.items():
            param_versions.add(
                key=f"operator_class_cost:{operator.operator_id}:{class_id}",
                value=svc_cost,
                version=op_version,
                source=class_cost_sources.get(class_id),
                description=occ_descriptions.get(
                    "operator_class_svc_stockings_eur_place"
                ),
            )

        comp_type = CompositionType(
            comp_id=comp_row["composition_type_id"],
            comp_description=comp_row["composition_type_description"],
            operator=operator,
            driver_factor=_f(comp_row["composition_type_driver_factor"]),
            max_speed_kmh=_f(comp_row["composition_type_max_speed_kmh"]),
            hsr_allowed=_b(comp_row["composition_type_hsr_allowed"]),
            coaches=coaches,
            energy_factor_weight=_f(comp_row["composition_type_energy_factor_weight"]),
            energy_factor_speed=_f(comp_row["composition_type_energy_factor_speed"]),
            energy_factor_terrain=_f(
                comp_row["composition_type_energy_factor_terrain"]
            ),
            min_boarding_time_min=_interval_to_min(
                comp_row["composition_type_min_boarding_time"]
            ),
            min_alighting_time_min=_interval_to_min(
                comp_row["composition_type_min_alighting_time"]
            ),
            purchase_coach_eur=_f(comp_row["composition_type_purchase_coach_eur"]),
            coach_avail_per=_f(comp_row["composition_type_coach_avail_per"]),
            coach_amort_years=_i(comp_row["composition_type_coach_amort_years"]),
            cleaning_services_eur_day=_f(comp_row["composition_type_cleaning_eur_day"]),
            coach_maint_eur_km=_f(comp_row["composition_type_coach_maint_eur_km"]),
        )

        # register composition_type fields in param_versions
        comp_descriptions = self._load_column_comments(
            "input_params", "composition_types"
        )
        comp_src = _src(comp_row, "source_id", sources)
        comp_version = _i(comp_row["composition_type_version"])
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
                version=comp_version,
                source=comp_src,
                description=comp_descriptions.get(f"composition_type_{field_name}"),
            )

        return Composition.from_type(comp_type), param_versions

    def build_all_compositions(
        self, scenario_id: int | None = None
    ) -> tuple[dict[str, Composition], ParamVersions]:
        """
        Return all compositions at a scenario's pinned versions (dict keyed
        by comp_id, merged ParamVersions). Loads composition_references and
        computes four indicative KPIs per composition using
        compute_indicative_figures() from calc.py — same model as evaluate_route().
        """
        versions = self._resolve_scenario_versions(scenario_id)

        with self._cursor() as cur:
            cur.execute(
                """
                SELECT composition_type_id, composition_type_row_id
                FROM input_params.composition_types
                WHERE composition_type_version = %s
            """,
                (versions["composition_types"],),
            )
            rows = cur.fetchall()

            cur.execute(
                """
                SELECT * FROM input_params.composition_references
                WHERE version = %s
            """,
                (versions["composition_references"],),
            )
            ref_rows = {r["composition_type_row_id"]: r for r in cur.fetchall()}

        # load tracks + stops once for all indicative calculations, same scenario
        tracks, _ = self.build_all_tracks(scenario_id)
        stop_infra, _ = self.build_all_stops(scenario_id)

        result: dict[str, Composition] = {}
        merged_versions = ParamVersions()

        for row in rows:
            comp_id = row["composition_type_id"]
            comp_row_id = row["composition_type_row_id"]
            try:
                comp, comp_versions = self.build_composition(comp_id, scenario_id)

                # compute indicative figures if reference exists
                ref_row = ref_rows.get(comp_row_id)
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
                    try:
                        from models.evaluation.calc import compute_indicative_figures

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
                    logger.warning(
                        "No composition_references row for '%s' — indicative figures unavailable.",
                        comp_id,
                    )
                    comp.indicative = None

                result[comp_id] = comp
                merged_versions.entries.update(comp_versions.entries)
            except Exception as e:
                logger.warning("Skipping composition '%s': %s", comp_id, e)
                self._conn.rollback()

        logger.info(
            "Built %d compositions (%d with indicative figures).",
            len(result),
            sum(1 for c in result.values() if c.indicative),
        )
        return result, merged_versions

    # ------------------------------------------------------------------
    # TRACK INFRASTRUCTURE
    # ------------------------------------------------------------------

    def build_all_tracks(
        self, scenario_id: int | None = None
    ) -> tuple[TrackInfraCollection, ParamVersions]:
        """
        Return track infrastructure at a scenario's pinned version as
        (TrackInfraCollection, ParamVersions).

        Any None field in a country row is substituted with the EU-average
        default from track_infrastructure_defaults. A WARNING is logged per
        substitution.
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

        track_descriptions = self._load_column_comments(
            "input_params", "track_infrastructures"
        )

        result: dict[str, TrackInfrastructure] = {}
        param_versions = ParamVersions()
        for row in rows:
            cc = row["country_code"]
            try:
                track = self._row_to_track(cc, row, default, sources)
                result[cc] = track
                # register param version + field-level sources
                # register one entry per track field
                track_version = _i(row["track_infra_version"])
                track_fields = {
                    "tac_eur_train_km": (track.tac_eur_train_km, track.tac_src),
                    "parking_eur_day": (track.parking_eur_day, track.parking_src),
                    "energy_price_eur_kwh": (
                        track.energy_price_eur_kwh,
                        track.energy_price_src,
                    ),
                    "terrain_score": (track.terrain_score, track.terrain_src),
                    "terrain_category": (track.terrain_category, track.terrain_src),
                    "hsr_allowed": (track.hsr_allowed, track.hsr_src),
                    "min_boarding_time_min": (
                        track.min_boarding_time_min,
                        track.min_boarding_src,
                    ),
                    "min_alighting_time_min": (
                        track.min_alighting_time_min,
                        track.min_alighting_src,
                    ),
                    "buffer_quota_per": (track.buffer_quota_per, track.buffer_src),
                }
                cc_defaults = self._track_defaults.get(cc, {})
                for field_name, (field_val, field_src) in track_fields.items():
                    param_versions.add(
                        key=f"track_infra:{cc}:{field_name}",
                        value=field_val,
                        version=track_version,
                        source=field_src,
                        description=track_descriptions.get(f"track_{field_name}"),
                        is_default=cc_defaults.get(field_name, False),
                    )
            except Exception as e:
                logger.warning("Skipping track infrastructure row '%s': %s", cc, e)

        logger.info("Built track infrastructure for %d countries.", len(result))
        return TrackInfraCollection(result, default), param_versions

    def _row_to_track(
        self,
        country_code: str,
        row,
        default: DefaultTrackInfra,
        sources: dict[int, ParamsSource],
    ) -> TrackInfrastructure:
        """
        Map one infrastructure DB row to a TrackInfrastructure.
        Substitutes None fields with default values and logs a WARNING each time.
        psycopg2 RealDictCursor handles type mapping — Decimal, bool, timedelta
        are returned natively; only NULL becomes Python None.
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

        # store is_default flags for param_versions
        self._track_defaults[country_code] = {
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

        return TrackInfrastructure(
            country_code=country_code,
            field_is_default=self._track_defaults[country_code],
            tac_eur_train_km=tac_val,
            tac_src=field_src("track_tac_src")
            or (default.tac_src if tac_def else None),
            parking_eur_day=parking_val,
            parking_src=field_src("track_parking_src")
            or (default.parking_src if parking_def else None),
            shunting_eur_event=shunting_val,
            shunting_src=field_src("track_shunting_src")
            or (default.shunting_src if shunting_def else None),
            energy_price_eur_kwh=energy_val,
            energy_price_src=field_src("track_energy_price_src")
            or (default.energy_price_src if energy_def else None),
            terrain_score=terrain_val,
            terrain_category=terr_cat_val,
            terrain_src=field_src("track_terrain_src")
            or (default.terrain_src if terrain_def else None),
            hsr_allowed=hsr_val,
            hsr_src=field_src("track_hsr_src")
            or (default.hsr_src if hsr_def else None),
            min_boarding_time_min=board_val,
            min_boarding_src=field_src("track_min_boarding_src")
            or (default.min_boarding_src if board_def else None),
            min_alighting_time_min=alight_val,
            min_alighting_src=field_src("track_min_alighting_src")
            or (default.min_alighting_src if alight_def else None),
            buffer_quota_per=buffer_val,
            buffer_src=field_src("track_buffer_src")
            or (default.buffer_src if buffer_def else None),
        )

    # ------------------------------------------------------------------
    # STOP INFRASTRUCTURE
    # ------------------------------------------------------------------

    def build_all_stops(
        self, scenario_id: int | None = None
    ) -> tuple[StopInfraCollection, ParamVersions]:
        """
        Return stops at a scenario's pinned version as (StopInfraCollection, ParamVersions).

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

        stop_descriptions = self._load_column_comments(
            "input_params", "stop_infrastructures"
        )

        result: dict[str, StopInfrastructure] = {}
        param_versions = ParamVersions()
        for row in stop_rows:
            try:
                country_cc = row.get("country_code", "")
                fallback = defaults.get(country_cc, global_default)
                stop = self._row_to_stop(row, fallback, sources, country_cc in defaults)
                result[row["stop_id"]] = stop
                # register param version + field sources
                # register one entry per stop field
                stop_version = _i(row["stop_infra_version"])
                stop_fields = {
                    "lat": (stop.lat, stop.loc_src),
                    "lon": (stop.lon, stop.loc_src),
                    "stop_charge_eur": (stop.stop_charge_eur, stop.stop_charge_src),
                }
                stop_id_key = row["stop_id"]
                sid_defaults = self._stop_defaults.get(stop_id_key, {})
                for field_name, (field_val, field_src) in stop_fields.items():
                    param_versions.add(
                        key=f"stop_infra:{stop_id_key}:{field_name}",
                        value=field_val,
                        version=stop_version,
                        source=field_src,
                        description=stop_descriptions.get(f"stop_{field_name}"),
                        is_default=sid_defaults.get(field_name, False),
                    )
            except Exception as e:
                logger.warning("Skipping stop '%s': %s", row.get("stop_id"), e)

        logger.info("Built %d stops.", len(result))
        return StopInfraCollection(result), param_versions

    def _row_to_stop(
        self,
        row,
        default: DefaultStopInfra,
        sources: dict[int, ParamsSource],
        has_country_default: bool,
    ) -> StopInfrastructure:
        """
        Map one stop DB row to a StopInfrastructure.
        Substitutes None stop_charge_eur with the country or global default
        and logs a WARNING. Same resolve() pattern as _row_to_track().
        psycopg2 RealDictCursor handles type mapping natively.
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

        # store is_default flags for param_versions
        self._stop_defaults[stop_id] = {"stop_charge_eur": charge_is_default}

        return StopInfrastructure(
            stop_id=stop_id,
            stop_name=row.get("stop_name") or "",
            stop_country_code=row.get("country_code", ""),
            lat=_f(row["stop_lat"]),
            lon=_f(row["stop_lon"]),
            loc_src=loc_src,
            stop_charge_eur=charge,
            stop_charge_src=charge_src,
        )

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