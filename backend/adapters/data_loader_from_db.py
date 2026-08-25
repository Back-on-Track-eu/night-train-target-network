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
    scenarios    = loader.list_all_scenarios()

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
  list_all_scenarios()    → list[Scenario]  (every scenario.scenarios row)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import time, timedelta

import psycopg2
import psycopg2.extras

from typing import Optional

from db.schema import STOP_NAME_LANGS
from models.params import (
    ParamsSource,
    IndicativeFigures,
    ParamVersions,
    ServiceClass,
    Operator,
    CoachType,
    LocoType,
    CoachClassAssignment,
    CompositionType,
    Composition,
    CompositionCollection,
    DefaultTrackInfra,
    TrackInfrastructure,
    TrackInfraCollection,
    TrackInfraDescriptions,
    TRACK_INFRA_FIELD_NAMES,
    TAC_COMPONENT_FIELD_NAMES,
    ENERGY_PRICE_FIELD_NAMES,
    FACILITY_FIELD_NAMES,
    TAC_RATE_FIELD_NAMES,
    PassageCharge,
    PassageChargeCollection,
    PASSAGE_FIELD_NAMES,
    DefaultStopInfra,
    StopInfrastructure,
    StopInfraCollection,
    StopInfraDescriptions,
    Scenario,
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


def _time_to_min_or_none(value) -> int | None:
    """Convert a psycopg2 datetime.time (from a TIME column) to minutes from
    midnight, or return None. Used for the TAC night and peak bands, which
    are times of day rather than durations — hence a separate helper from
    _interval_to_min_or_none()."""
    if value is None:
        return None
    if isinstance(value, time):
        return value.hour * 60 + value.minute
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
        operators/coach_types/composition_types are
        unversioned catalogs and have no scenario pointer at all (see
        scenario.scenarios definition in db/schema.py).

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
            "passage_charges": row["passage_charges_version"],
        }

    def list_all_scenarios(self) -> list[Scenario]:
        """
        Return every row of scenario.scenarios as Scenario objects, ordered
        by scenario_key then newest-first within each key. Grouping by
        is_current_base / is_current_scenario (e.g. for GET /api/scenarios)
        is a display concern and happens in
        api/helpers/scenario_serialize.py, not here.
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM scenario.scenarios "
                "ORDER BY scenario_key, created_at DESC"
            )
            rows = cur.fetchall()

        return [
            Scenario(
                scenario_id=row["scenario_id"],
                scenario_key=row["scenario_key"],
                scenario_name=row["scenario_name"],
                description=row["description"],
                change_log=row["change_log"],
                editor=row["editor"],
                created_at=row["created_at"].isoformat(),
                is_current_base=row["is_current_base"],
                is_current_scenario=row["is_current_scenario"],
                track_infrastructures_version=row["track_infrastructures_version"],
                track_infrastructure_defaults_version=row[
                    "track_infrastructure_defaults_version"
                ],
                stop_infrastructures_version=row["stop_infrastructures_version"],
                stop_infrastructure_defaults_version=row[
                    "stop_infrastructure_defaults_version"
                ],
                passage_charges_version=row["passage_charges_version"],
            )
            for row in rows
        ]

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
                is_night_accommodation=_b(row["service_class_is_night_accommodation"]),
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
                driver_max_duty_h=_f(row["operator_driver_max_duty_h"]),
                crew_max_duty_h=_f(row["operator_crew_max_duty_h"]),
                driver_roster_eff_ref=_f(row["operator_driver_roster_eff_ref"]),
                crew_roster_eff_ref=_f(row["operator_crew_roster_eff_ref"]),
                relief_allowance_h=_f(row["operator_relief_allowance_h"]),
                ebit_margin_per=_f(row["operator_ebit_margin_per"]),
                financing_quota_per=_f(row["operator_financing_quota_per"]),
                var_overhead_per=_f(row["operator_var_overhead_per"]),
                fix_overhead_quota_per=_f(row["operator_fix_overhead_quota_per"]),
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
                "ebit_margin_per": operator.ebit_margin_per,
                "financing_quota_per": operator.financing_quota_per,
                "var_overhead_per": operator.var_overhead_per,
                "fix_overhead_quota_per": operator.fix_overhead_quota_per,
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
                SELECT coach_type_row_id, service_class_id,
                       coach_type_class_places,
                       section_length_m, section_weight_t, section_crew_factor
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
                is_night_accommodation=sc.is_night_accommodation,
                places=_i(cr["coach_type_class_places"]),
                section_length_m=_f(cr["section_length_m"] or 0),
                section_weight_t=_f(cr["section_weight_t"] or 0),
                section_crew_factor=_f(cr["section_crew_factor"] or 0),
            )

        coach_types: dict[str, CoachType] = {}
        row_id_to_id: dict[int, str] = {}
        for row in ct_rows:
            coachtype_id = row["coach_type_id"]
            row_id_to_id[row["coach_type_row_id"]] = coachtype_id
            coach_type = CoachType(
                coachtype_id=coachtype_id,
                weight_gross_t=_f(row["coach_type_weight_gross_t"]),
                length_m=_f(row["coach_type_length_m"]),
                length_wo_service_m=_f(row["coach_type_length_wo_service_m"]),
                weight_wo_service_t=_f(row["coach_type_weight_wo_service_t"]),
                has_wifi=bool(row["coach_type_has_wifi"]),
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

    # ------------------------------------------------------------------
    # LOCOMOTIVES
    # ------------------------------------------------------------------

    def _load_loco_types(self) -> dict[str, LocoType]:
        """Locomotive catalog keyed by loco_type_id."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM input_params.loco_types")
            return {
                row["loco_type_id"]: LocoType(
                    loco_type_id=row["loco_type_id"],
                    description=row["loco_type_description"],
                    traction=row["loco_type_traction"],
                    weight_t=_f(row["loco_type_weight_t"]),
                    max_speed_kmh=_i(row["loco_type_max_speed_kmh"]),
                )
                for row in cur.fetchall()
            }

    def _load_operator_loco_costs(self) -> dict[tuple[str, str], float]:
        """{(operator_id, loco_type_id): EUR/h}. Sparse on purpose — an
        absent pairing is not priced, and _compose_locos() refuses rather
        than inventing a rate. Joined to natural keys here so nothing
        downstream has to carry SERIAL row ids around."""
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT o.operator_id, l.loco_type_id,
                       c.operator_loco_lease_eur_h
                FROM input_params.operator_loco_costs c
                JOIN input_params.operators o
                  ON o.operator_row_id = c.operator_row_id
                JOIN input_params.loco_types l
                  ON l.loco_type_row_id = c.loco_type_row_id
                """
            )
            return {
                (row["operator_id"], row["loco_type_id"]): _f(
                    row["operator_loco_lease_eur_h"]
                )
                for row in cur.fetchall()
            }

    def _load_composition_locos(self) -> dict[str, list[str]]:
        """{composition_type_id: [loco_type_id, ...]} in position order.
        One query for the whole catalog, matching the coach wiring."""
        wiring: dict[str, list[str]] = {}
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT ct.composition_type_id, l.loco_type_id
                FROM input_params.composition_type_locos cl
                JOIN input_params.composition_types ct
                  ON ct.composition_type_row_id = cl.composition_type_row_id
                JOIN input_params.loco_types l
                  ON l.loco_type_row_id = cl.loco_type_row_id
                ORDER BY ct.composition_type_id, cl.position
                """
            )
            for row in cur.fetchall():
                wiring.setdefault(row["composition_type_id"], []).append(
                    row["loco_type_id"]
                )
        return wiring

    @staticmethod
    def _compose_locos(
        composition_type_id: str,
        operator_id: str,
        loco_type_ids: list[str],
        catalog: dict[str, LocoType],
        costs: dict[tuple[str, str], float],
    ) -> tuple[list[LocoType], dict[str, float]]:
        """Resolve a composition's machines and this operator's rate for
        each.

        Fails loudly on an unpriced (operator, machine) pairing. A missing
        row means the catalog and the cost table disagree about what this
        operator can run — substituting a list price would produce a
        plausible number from inconsistent data, which is the one outcome
        worth preventing outright.
        """
        locos, rates = [], {}
        for loco_type_id in loco_type_ids:
            rate = costs.get((operator_id, loco_type_id))
            if rate is None:
                raise ValueError(
                    f"Composition '{composition_type_id}' hauls "
                    f"'{loco_type_id}', but operator '{operator_id}' has no "
                    "rate for it in input_params.operator_loco_costs. Seed "
                    "the pairing — a locomotive nobody has priced cannot be "
                    "costed."
                )
            locos.append(catalog[loco_type_id])
            rates[loco_type_id] = rate
        return locos, rates

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
        are all unversioned catalogs (see their
        docstrings in models/params.py) — a changed value means a new id,
        never editing a row in place. scenario_id is still accepted, and
        scenario_id has no effect on composition/operator/coach type
        field values themselves (all unversioned catalogs); since
        CALC_VERSION 0.9.7 indicative KPIs are seeded values too, so
        scenario_id no longer influences them either.

        include_indicative: set False to skip attaching
        Composition.indicative — route_factory doesn't use indicative
        KPIs (a composition-comparison display figure, not a routing
        input). Since CALC_VERSION 0.9.7 the KPIs are seeded calibration
        values read from composition_types columns, so this flag no
        longer gates any tracks/stops loading — it only controls whether
        the field is populated. composition_reference provenance is
        registered either way.
        """
        sources = self._load_sources()
        service_classes = self._load_service_classes()
        loco_catalog = self._load_loco_types()
        loco_costs = self._load_operator_loco_costs()
        loco_wiring = self._load_composition_locos()

        # descriptions mirrors the ACTUAL response structure built by
        # api/helpers/params_serialize.py's composition_collection_to_dict()
        # — grouped by response section (routing/staff/capacity/
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
                    "n_locos": (
                        "Number of locomotives hauling this composition — "
                        "the count of its rows in "
                        "input_params.composition_type_locos, never a "
                        "stored column."
                    ),
                },
                "staff": {
                    "driver_factor": comp_type_columns.get(
                        "composition_type_driver_factor"
                    ),
                    "crew_factor_total": (
                        "Total fractional cabin crew: Σ coach crew "
                        "factors + the Zugchef factor, priced at the "
                        "operator crew rate."
                    ),
                    "zugchef_crew_factor": comp_type_columns.get(
                        "composition_type_zugchef_crew_factor"
                    ),
                    "crew_factor_coaches": (
                        "Σ crew factors across the composition's coaches "
                        "(crew_factor_total minus the Zugchef factor)."
                    ),
                    "costs_per_hour": (
                        "Hourly staff rates (denormalised from the "
                        "operator) and the combined staff cost per "
                        "operated hour: driver_factor × driver rate + "
                        "crew_factor_total × crew rate. These are wages "
                        "per PRODUCTIVE hour: evaluation divides them by "
                        "the roster efficiency it computes for each trip, "
                        "so the amount actually charged is higher — most "
                        "of all on trips long enough to need a relief "
                        "crew. Unit: €/h"
                    ),
                },
                "capacity": {
                    "total_places": ("Total places across all classes and coaches."),
                    "places": (
                        "Total places of this class across all coaches in "
                        "the composition — summed across coaches."
                    ),
                    "density": (
                        "Places-weighted average density of this class "
                        "across all coaches in the composition — space "
                        "units consumed per place, used for cost allocation."
                    ),
                    "avg_density_length_m_per_place": (
                        "Average length density on the FULL composition "
                        "length — service areas included, every "
                        "passenger uses them (workbook AL). Unit: m/place"
                    ),
                    "avg_density_weight_t_per_place": (
                        "Average weight density on the full weight, "
                        "service areas included (workbook AM). "
                        "Unit: t/place"
                    ),
                },
                "equipment": {
                    "has_bikes": (
                        "True if ANY coach in the composition has bicycle spaces."
                    ),
                    "has_climatization": (
                        "True if ANY coach in the composition has air conditioning."
                    ),
                    "has_plugs": (
                        "True if ANY coach in the composition has passenger "
                        "power sockets."
                    ),
                    "food_and_beverages": comp_type_columns.get(
                        "composition_type_food_and_beverages"
                    ),
                },
                "coaches": {
                    "count": "Number of coaches in this composition.",
                    "coach_type_id": coach_type_columns.get("coach_type_id"),
                    "position": comp_type_coaches_columns.get("position"),
                    "remarks": coach_type_columns.get("coach_type_remarks"),
                    "list": (
                        "Ordered formation; coach_type_id references the "
                        "top-level coach_types catalog."
                    ),
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
                "driver_max_duty_h": operator_columns.get("operator_driver_max_duty_h"),
                "crew_max_duty_h": operator_columns.get("operator_crew_max_duty_h"),
                "driver_roster_eff_ref": operator_columns.get(
                    "operator_driver_roster_eff_ref"
                ),
                "crew_roster_eff_ref": operator_columns.get(
                    "operator_crew_roster_eff_ref"
                ),
                "relief_allowance_h": operator_columns.get(
                    "operator_relief_allowance_h"
                ),
                "ebit_margin_per": operator_columns.get("operator_ebit_margin_per"),
                "financing_quota_per": operator_columns.get(
                    "operator_financing_quota_per"
                ),
                "var_overhead_per": operator_columns.get("operator_var_overhead_per"),
                "fix_overhead_quota_per": operator_columns.get(
                    "operator_fix_overhead_quota_per"
                ),
                "loco_lease_eur_h": (
                    "Locomotive rental rate per hour, for each machine this "
                    "operator runs (input_params.operator_loco_costs)."
                ),
                "cost_per_class": operator_class_cost_columns.get(
                    "operator_class_svc_stockings_eur_place"
                ),
            },
            "coach_types": (
                "All coach types across the catalog, keyed by "
                "coach_type_id and referenced from compositions' "
                "coaches.list: physicals incl./excl. service areas "
                "(a dining car has zero revenue space), crew factor, "
                "places, equipment, and class_ids referencing the "
                "classes section."
            ),
            "classes": (
                "All service classes across the catalog grouped by "
                "class_main — one entry per class_id "
                '("<coach_type_id> - <section label>") with its '
                "carrying coach type and places."
            ),
            "cost_allocation": {
                "by_class_main": (
                    "Per class_main: its blended cost proportion "
                    "(workbook cost_acc columns) — X·length + "
                    "(1−X)·weight of the revenue space, service-area "
                    "costs per head — identical to the evaluation's "
                    "by_class_main hardware basis; sums to 1. See "
                    "calib/CALIBRATION.md."
                ),
            },
            "indicative": {
                "kpis": {
                    "cost_eur_per_train_km": (
                        "Seeded calibration value: annual operator-"
                        "controllable cost per train-km on the S41 "
                        "reference route (1,000 km, 14.5 h trip, 350 "
                        "operating days, 2 trainsets), nominal 2032 "
                        "prices, excl. infrastructure charges, energy, "
                        "variable overhead and EBIT. Derivation: "
                        "calib/CALIBRATION.md (umbrella source)."
                    ),
                    "cost_ct_per_place_km": (
                        "The same cost basis divided by total places — "
                        "ct per available place-km on the S41 reference "
                        "route, 2032 prices."
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

                locos, loco_rates = self._compose_locos(
                    comp_id,
                    operator.operator_id,
                    loco_wiring.get(comp_id, []),
                    loco_catalog,
                    loco_costs,
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
                    material_strategy=row["composition_type_material_strategy"],
                    locos=locos,
                    zugchef_crew_factor=_f(row["composition_type_zugchef_crew_factor"]),
                    length_cost_prop=_f(row["composition_type_length_cost_prop"]),
                    food_and_beverages=row["composition_type_food_and_beverages"],
                    indicative_cost_eur_train_km=(
                        _f(row["composition_type_indicative_cost_eur_train_km"])
                        if row["composition_type_indicative_cost_eur_train_km"]
                        is not None
                        else None
                    ),
                    indicative_cost_ct_place_km=(
                        _f(row["composition_type_indicative_cost_ct_place_km"])
                        if row["composition_type_indicative_cost_ct_place_km"]
                        is not None
                        else None
                    ),
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

                comp = Composition.from_type(comp_type, loco_rates)

                # --- indicative KPIs: seeded calibration values from the
                #     composition_types columns (calib/CALIBRATION.md).
                #     Their basis is documented in the column comments
                #     (→ API descriptions block) and derived in
                #     calib/CALIBRATION.md — no per-composition row. ---
                if (
                    include_indicative
                    and comp_type.indicative_cost_eur_train_km is not None
                    and comp_type.indicative_cost_ct_place_km is not None
                ):
                    comp.indicative = IndicativeFigures(
                        cost_eur_per_train_km=(comp_type.indicative_cost_eur_train_km),
                        cost_ct_per_place_km=(comp_type.indicative_cost_ct_place_km),
                    )
                else:
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

    @staticmethod
    def _tac_components(row) -> dict:
        """The TAC component fields of one track row, as domain values.

        Shared by the country rows and the defaults row, which carry the
        same columns — so the two can never map differently. Bands are
        TIME columns in the database and minutes of day here; everything
        else passes through with only a numeric cast.
        """
        return {
            "tac_b_day": _f_or_none(row["track_tac_b_day"]),
            "tac_b_night": _f_or_none(row["track_tac_b_night"]),
            "tac_gamma": _f_or_none(row["track_tac_gamma"]),
            "tac_seat_km": _f_or_none(row["track_tac_seat_km"]),
            "tac_per_stop": _f_or_none(row["track_tac_per_stop"]),
            "tac_revenue_share": _f_or_none(row["track_tac_revenue_share"]),
            "tac_fixed_per_train_km": _f_or_none(row["track_tac_fixed_per_train_km"]),
            "tac_peak_multiplier": _f_or_none(row["track_tac_peak_multiplier"]),
            "tac_congestion_surcharge_eur_km": _f_or_none(
                row["track_tac_congestion_surcharge_eur_km"]
            ),
            "tac_night_mode": row["track_tac_night_mode"] or "none",
            "tac_night_band_start_min": _time_to_min_or_none(
                row["track_tac_night_band_start"]
            ),
            "tac_night_band_end_min": _time_to_min_or_none(
                row["track_tac_night_band_end"]
            ),
            "tac_night_full_if_accommodation": bool(
                row["track_tac_night_full_if_accommodation"]
            ),
            "tac_peak_band1_start_min": _time_to_min_or_none(
                row["track_tac_peak_band1_start"]
            ),
            "tac_peak_band1_end_min": _time_to_min_or_none(
                row["track_tac_peak_band1_end"]
            ),
            "tac_peak_band2_start_min": _time_to_min_or_none(
                row["track_tac_peak_band2_start"]
            ),
            "tac_peak_band2_end_min": _time_to_min_or_none(
                row["track_tac_peak_band2_end"]
            ),
            "tac_peak_weekdays_only": bool(row["track_tac_peak_weekdays_only"]),
        }

    @staticmethod
    def _energy_components(row) -> dict:
        """The traction-energy price terms of one track row, beyond the day
        rate, as domain values.

        Shared by the country rows and the defaults row so the two can never
        map differently. Nothing is defaulted here and nothing is coerced to
        zero: a NULL night price means the country charges one rate around
        the clock, and a NULL catenary term means it levies no separate
        supply-equipment charge — both of which the cost model has to be able
        to tell apart from a rate of 0.0.
        """
        return {
            "energy_price_night_eur_kwh": _f_or_none(
                row["track_energy_price_night_eur_kwh"]
            ),
            "energy_night_band_start_min": _time_to_min_or_none(
                row["track_energy_night_band_start"]
            ),
            "energy_night_band_end_min": _time_to_min_or_none(
                row["track_energy_night_band_end"]
            ),
            "energy_catenary_eur_train_km": _f_or_none(
                row["track_energy_catenary_eur_train_km"]
            ),
            "energy_catenary_eur_gross_tonne_km": _f_or_none(
                row["track_energy_catenary_eur_gross_tonne_km"]
            ),
        }

    @staticmethod
    def _facility_components(row) -> dict:
        """The service-facility terms of one track row. Shared by the country
        rows and the defaults row so the two can never map differently."""
        return {
            "parking_basis": row["track_parking_basis"],
            "parking_eur_metre_day": _f_or_none(row["track_parking_eur_metre_day"]),
            "parking_eur_hour": _f_or_none(row["track_parking_eur_hour"]),
            "parking_eur_event": _f_or_none(row["track_parking_eur_event"]),
            "parking_free_hours": _f_or_none(row["track_parking_free_hours"]),
            "parking_hotel_power_eur_hour": _f_or_none(
                row["track_parking_hotel_power_eur_hour"]
            ),
        }

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
            **self._tac_components(default_row),
            **self._energy_components(default_row),
            **self._facility_components(default_row),
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
            "Infrastructure-dependent minimum dwell time at boarding stops. Unit: min"
        )
        descriptions.fields["min_alighting_time_min"] = (
            "Infrastructure-dependent minimum dwell time at alighting stops. Unit: min"
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
            for field_name in (
                TRACK_INFRA_FIELD_NAMES
                + TAC_COMPONENT_FIELD_NAMES
                + ENERGY_PRICE_FIELD_NAMES
                + FACILITY_FIELD_NAMES
            ):
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
            for field_name in (
                TRACK_INFRA_FIELD_NAMES
                + TAC_COMPONENT_FIELD_NAMES
                + ENERGY_PRICE_FIELD_NAMES
                + FACILITY_FIELD_NAMES
            )
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
                field_is_default={
                    # The energy terms are absent from the defaults row by
                    # design, so they are not "defaulted" even here — a
                    # country with no row is priced at the median day rate
                    # with no night band and no catenary charge, which is
                    # what the fallback row says.
                    **dict.fromkeys(
                        TRACK_INFRA_FIELD_NAMES + TAC_COMPONENT_FIELD_NAMES, True
                    ),
                    **dict.fromkeys(ENERGY_PRICE_FIELD_NAMES, False),
                    **dict.fromkeys(FACILITY_FIELD_NAMES, True),
                },
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
                **{
                    f: getattr(default, f)
                    for f in (
                        TAC_COMPONENT_FIELD_NAMES
                        + ENERGY_PRICE_FIELD_NAMES
                        + FACILITY_FIELD_NAMES
                    )
                },
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
            "Built track infrastructure for %d countries "
            "(%d synthesized entirely from defaults, "
            "%d individual fields resolved via defaults).",
            len(result),
            synthesized,
            sum(sum(track.field_is_default.values()) for track in result.values()),
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
        Substitutes None fields with default values (logged at DEBUG —
        expected resolution, counted in build_all_tracks()'s summary).
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
                # DEBUG, not WARNING: NULL → default is the documented,
                # expected resolution path, and this fires per field per
                # country per catalog build — at WARNING it was ~210
                # synchronous stderr lines per build, a measurable share
                # of request latency once the ONTD-derived stops grew the
                # catalog (2026-08-06). Aggregate counts land in the
                # per-build INFO summary instead.
                logger.debug(
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

        # The TAC component group resolves as a whole, not field by field.
        # A country levying any distance-based rate term is calibrated, and
        # its other components being NULL is then the documented fact "not
        # levied here" — substituting an EU median into those would invent a
        # Spanish seat surcharge or a Swiss stop charge for a country that
        # has neither. Only when NO rate term is present at all does the
        # whole group come from the defaults row.
        tac_components = self._tac_components(row)
        tac_group_default = all(tac_components[f] is None for f in TAC_RATE_FIELD_NAMES)
        if tac_group_default:
            logger.debug(
                "TrackInfrastructure[%s]: no TAC rate term — using the "
                "EU-median component group.",
                country_code,
            )
            tac_components = {f: getattr(default, f) for f in TAC_COMPONENT_FIELD_NAMES}

        # The energy price terms are read as they stand. There is no group
        # resolution and no field-by-field default: the defaults row carries
        # none of them, and a NULL is the tariff fact "not levied" (see
        # models/params.py: ENERGY_PRICE_FIELD_NAMES). Only the day rate
        # above resolves, because every country pays something for
        # electricity — but only three band their tariff and roughly half
        # levy a supply-equipment charge.
        energy_components = self._energy_components(row)

        # The facility group resolves as a whole, keyed on the basis. A NULL
        # basis means the calibration has no figures for this country at all —
        # distinct from the documented basis 'none', which means the country
        # levies no siding charge and must NOT pick up the European default.
        facility_components = self._facility_components(row)
        facility_group_default = facility_components["parking_basis"] is None
        if facility_group_default:
            logger.debug(
                "TrackInfrastructure[%s]: no stabling basis — using the EU "
                "default facility group.",
                country_code,
            )
            facility_components = {f: getattr(default, f) for f in FACILITY_FIELD_NAMES}

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
            **dict.fromkeys(TAC_COMPONENT_FIELD_NAMES, tac_group_default),
            **dict.fromkeys(ENERGY_PRICE_FIELD_NAMES, False),
            **dict.fromkeys(FACILITY_FIELD_NAMES, facility_group_default),
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
            # The whole component group shares track_tac_src — see
            # models/params.py: _TRACK_DEFAULT_SRC_ATTRS.
            **dict.fromkeys(
                TAC_COMPONENT_FIELD_NAMES,
                default.tac_src if tac_group_default else field_src("track_tac_src"),
            ),
            # The energy terms qualify the day rate, so they share its
            # source — see models/params.py: _TRACK_DEFAULT_SRC_ATTRS.
            **dict.fromkeys(
                ENERGY_PRICE_FIELD_NAMES, field_src("track_energy_price_src")
            ),
            # The stabling terms share the parking source, as the shunting
            # figure they were calibrated alongside does.
            **dict.fromkeys(
                FACILITY_FIELD_NAMES,
                default.parking_src
                if facility_group_default
                else field_src("track_parking_src"),
            ),
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
            **tac_components,
            **energy_components,
            **facility_components,
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
        default_charge_count = 0
        for row in stop_rows:
            try:
                country_cc = row.get("country_code", "")
                fallback = defaults.get(country_cc, global_default)
                stop, loc_src, charge_src, charge_is_default = self._row_to_stop(
                    row, fallback, sources, country_cc in defaults
                )
                default_charge_count += charge_is_default
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

        logger.info(
            "Built %d stops (%d charges resolved via defaults).",
            len(result),
            default_charge_count,
        )
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
        (logged at DEBUG, counted in build_all_stops()'s summary). Same
        resolve() pattern as _row_to_track().
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
                # DEBUG, not WARNING — same reasoning as _row_to_track()'s
                # resolve(): expected path, fires per stop per build, and
                # the ONTD-derived stops (NULL charge by design) made this
                # ~575 lines per catalog build at WARNING level. The
                # per-build INFO summary carries the count.
                logger.debug(
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

        # Localized columns fold into language-keyed dicts here, so nothing
        # downstream ever touches a column suffix. City names exist only
        # where a city was resolved; the dict is empty otherwise, not
        # None-valued per language.
        country_names = {lang: row[f"country_{lang}"] for lang in STOP_NAME_LANGS}
        city_names = {
            lang: row[f"city_{lang}"]
            for lang in STOP_NAME_LANGS
            if row.get(f"city_{lang}")
        }

        stop = StopInfrastructure(
            stop_id=stop_id,
            stop_name=row.get("stop_name") or "",
            stop_country_code=row.get("country_code", ""),
            lat=_f(row["stop_lat"]),
            lon=_f(row["stop_lon"]),
            stop_charge_eur=charge,
            provenance=row.get("stop_provenance") or "",
            name_latin=row.get("name_latin") or "",
            name_ascii=row.get("name_ascii") or "",
            uic_ref=row.get("uic_ref"),
            country_names=country_names,
            city=row.get("city"),
            city_osm_id=row.get("city_osm_id"),
            city_names=city_names,
            # psycopg2 returns INTEGER[] as a Python list, NULL as None.
            gauges_mm=row.get("gauges_mm"),
            gauge_evidence=row.get("gauge_evidence"),
        )
        return stop, loc_src, charge_src, charge_is_default

    # ------------------------------------------------------------------
    # PASSAGE CHARGES
    # ------------------------------------------------------------------

    def build_all_passages(
        self, scenario_id: int | None = None
    ) -> PassageChargeCollection:
        """
        Return the separately charged crossings at a scenario's pinned
        version — passage_charges is the fifth scenario-versioned
        infrastructure table, under the same full-snapshot contract as the
        other four.

        There is no defaults table and no synthesis: a crossing either has
        a charge row at this version or is not charged. Provenance is
        registered per crossing per field under "passage:{id}:{field}",
        mirroring the track pattern.

        Geometry is deliberately not returned here — polygon matching is a
        routing concern, see get_passage_geometries().
        """
        versions = self._resolve_scenario_versions(scenario_id)
        sources = self._load_sources()

        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM input_params.passage_charges
                WHERE passage_version = %s
                """,
                (versions["passage_charges"],),
            )
            rows = cur.fetchall()

        result: dict[str, PassageCharge] = {}
        param_versions = ParamVersions()
        for row in rows:
            passage_id = row["passage_id"]
            charge = PassageCharge(
                passage_id=passage_id,
                passage_name=row["passage_name"],
                fixed_eur=_f(row["passage_fixed_eur"]),
                per_passenger_eur=_f(row["passage_per_passenger_eur"]),
            )
            result[passage_id] = charge
            source = _src(row, "passage_src", sources)
            for field_name in PASSAGE_FIELD_NAMES:
                param_versions.add(
                    key=f"passage:{passage_id}:{field_name}",
                    value=getattr(charge, field_name),
                    version=_i(row["passage_version"]),
                    source=source,
                )

        logger.info("Built %d passage charges.", len(result))
        return PassageChargeCollection(result, param_versions)

    def get_passage_geometries(self) -> list[tuple[str, dict]]:
        """
        Return (passage_id, GeoJSON geometry) pairs for routing-time
        crossing detection (rail_router.PassageIndex).

        Version-independent by design, like get_country_geometries(): a
        tunnel does not move between scenarios, so this reads each
        passage_id's newest row rather than resolving a scenario. What a
        scenario pins are the charges, resolved separately in
        build_all_passages().

        Plain (str, dict) pairs rather than a domain object, for the same
        reason as get_country_geometries(): a data-access method must not
        pull a routing-layer import into this layer.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (passage_id)
                       passage_id, ST_AsGeoJSON(passage_geom) AS geom
                FROM input_params.passage_charges
                ORDER BY passage_id, passage_version DESC
                """
            )
            rows = cur.fetchall()
        result = [(row["passage_id"], json.loads(row["geom"])) for row in rows]
        logger.info("Loaded %d passage geometries.", len(result))
        return result

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
