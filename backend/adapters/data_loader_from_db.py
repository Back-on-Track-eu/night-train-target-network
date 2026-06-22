"""
data_loader_from_db.py
======================
Database data access layer for the night train model.
Reads all parameter tables from PostgreSQL and builds the same typed
objects as SheetDataLoader — drop-in replacement for the API layer.

Typical usage
-------------
    loader = DBDataLoader()
    composition  = loader.build_composition("NJ-3.1")
    infra        = loader.build_all_infra()
    stop_params  = loader.build_all_stop_params(["Wien Hbf", "München Hbf"])

Schema mapping for CompositionParams
-------------------------------------
Most composition fields come from input_params.compositions directly.
The following require JOINs or aggregation:

  weight_gross_t          — SUM(coachtypes.coachtype_weight_gross_t) per composition
  seats/couchettes/sleepers_total — SUM(coachtype_class_places) grouped by class_main
  seat/couchette/sleeper_density  — 1 / places for first coach of each class
  driver/crew costs & overheads   — input_params.operators (JOIN via comp_operator_id)
  ebit_margin_per         — operators.operator_ebit_margin_per
  financing_quota_per     — operators.operator_financing_quota_per
  shunting_eur_day        — operators.operator_shunting_eur_per_event
  var_overhead_per        — operators.operator_var_overhead_per
  fix_overhead_quota_per  — operators.operator_fix_overhead_quota_per
  svc_stockings_*_per     — input_params.operator_class_costs (per class_main)
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

import psycopg2
import psycopg2.extras

from models.params import (
    CompositionParams, CompositionCollection,
    InfraParams, InfraCollection,
    StopParams, StopCollection,
)

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def _f(value) -> float:
    """Safely cast Decimal or None to float."""
    if value is None:
        return 0.0
    return float(value)


def _i(value) -> int:
    """Safely cast Decimal or None to int."""
    if value is None:
        return 0
    return int(value)


def _b(value) -> bool:
    """Safely cast None to bool."""
    return bool(value) if value is not None else False


def _h(value) -> float:
    """
    Convert a timedelta (psycopg2 maps INTERVAL to timedelta) to decimal hours.
    Falls back to 0.0 for None.
    """
    if value is None:
        return 0.0
    if isinstance(value, timedelta):
        return value.total_seconds() / 3600.0
    return float(value)


# =============================================================================
# DB DATA LOADER
# =============================================================================

class DBDataLoader:
    """
    Data access layer that reads parameters from PostgreSQL.
    Implements the same builder interface as SheetDataLoader so it can be
    used as a drop-in replacement in dependencies.py and run_model.py.
    """

    def __init__(self) -> None:
        self._conn = self._connect()

    def _connect(self):
        return psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", 5432)),
            dbname=os.environ.get("POSTGRES_DB"),
            user=os.environ.get("POSTGRES_USER"),
            password=os.environ.get("POSTGRES_PASSWORD"),
        )

    def _cursor(self):
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    # ------------------------------------------------------------------
    # BUILDER METHODS — compositions
    # ------------------------------------------------------------------

    def build_composition(self, comp_id: str) -> CompositionParams:
        """
        Build a CompositionParams for a single composition ID.

        Assembles data from four tables:
          - compositions        — base composition row
          - operators           — operator-level cost params (JOIN via comp_operator_id)
          - composition_coaches + coachtypes — weight aggregation
          - composition_coaches + coachtype_classes + classes — capacity and density
          - operator_class_costs + classes — per-class service stocking costs
        """
        with self._cursor() as cur:

            # --- core composition + operator JOIN ---
            cur.execute("""
                SELECT
                    c.*,
                    op.operator_name,
                    op.operator_driver_costs_eur_h,
                    op.operator_crew_costs_eur_h,
                    op.operator_driver_overhead_h,
                    op.operator_crew_overhead_h,
                    op.operator_ebit_margin_per,
                    op.operator_financing_quota_per,
                    op.operator_shunting_eur_per_event,
                    op.operator_var_overhead_per,
                    op.operator_fix_overhead_quota_per
                FROM input_params.compositions c
                JOIN input_params.operators op ON op.operator_id = c.comp_operator_id
                WHERE c.comp_id = %s AND c.is_current = TRUE
            """, (comp_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Composition '{comp_id}' not found in database.")

            comp_row_id = row["comp_row_id"]

            # --- total gross weight: sum of all coach weights in composition ---
            cur.execute("""
                SELECT COALESCE(SUM(ct.coachtype_weight_gross_t), 0) AS weight_gross_t
                FROM input_params.composition_coaches co
                JOIN input_params.coachtypes ct ON ct.coachtype_row_id = co.coachtype_row_id
                WHERE co.comp_row_id = %s
            """, (comp_row_id,))
            weight_row = cur.fetchone()

            # --- capacity totals: sum places by class_main ---
            cur.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN cl.class_main = 'Seat'      THEN cc.coachtype_class_places ELSE 0 END), 0) AS seats_total,
                    COALESCE(SUM(CASE WHEN cl.class_main = 'Couchette' THEN cc.coachtype_class_places ELSE 0 END), 0) AS couchettes_total,
                    COALESCE(SUM(CASE WHEN cl.class_main = 'Sleeper'   THEN cc.coachtype_class_places ELSE 0 END), 0) AS sleepers_total
                FROM input_params.composition_coaches co
                JOIN input_params.coachtype_classes   cc ON cc.coachtype_row_id = co.coachtype_row_id
                JOIN input_params.classes             cl ON cl.class_id = cc.class_id
                WHERE co.comp_row_id = %s
                  AND cl.class_main IN ('Seat', 'Couchette', 'Sleeper')
            """, (comp_row_id,))
            cap = cur.fetchone()

            # --- density: 1/places for first coach of each class (ordered by position) ---
            cur.execute("""
                SELECT cl.class_main, cc.coachtype_class_places
                FROM input_params.composition_coaches co
                JOIN input_params.coachtype_classes   cc ON cc.coachtype_row_id = co.coachtype_row_id
                JOIN input_params.classes             cl ON cl.class_id = cc.class_id
                WHERE co.comp_row_id = %s
                  AND cl.class_main IN ('Seat', 'Couchette', 'Sleeper')
                ORDER BY co.position
            """, (comp_row_id,))
            density_rows = cur.fetchall()

            # --- service stocking costs per class_main ---
            cur.execute("""
                SELECT cl.class_main, occ.operator_class_svc_stockings_eur_place
                FROM input_params.operator_class_costs occ
                JOIN input_params.classes cl ON cl.class_id = occ.class_id
                WHERE occ.operator_id = %s
                  AND cl.class_main IN ('Seat', 'Couchette', 'Sleeper')
            """, (row["comp_operator_id"],))
            stocking_rows = cur.fetchall()

        # --- compute density (1/places for first occurrence of each class) ---
        densities: dict[str, float] = {}
        for dr in density_rows:
            class_main = dr["class_main"]
            if class_main not in densities and dr["coachtype_class_places"] > 0:
                densities[class_main] = 1.0 / float(dr["coachtype_class_places"])

        # --- map stocking costs by class_main ---
        stockings: dict[str, float] = {}
        for sr in stocking_rows:
            stockings[sr["class_main"]] = _f(sr["operator_class_svc_stockings_eur_place"])

        return CompositionParams(
            # --- identity ---
            comp_id             = row["comp_id"],
            comp_description    = row.get("comp_description") or "",
            company             = row.get("comp_operator_id") or "",

            # --- routing ---
            weight_gross_t      = _f(weight_row["weight_gross_t"]),
            max_speed_kmh       = _f(row.get("comp_max_speed_kmh")),
            hsr_allowed         = _b(row.get("comp_hsr_allowed")),
            min_boarding_time_h = _h(row.get("comp_veh_min_boarding_time")),
            min_alighting_time_h= _h(row.get("comp_veh_min_alighting_time")),

            # --- energy model ---
            energy_factor_weight  = _f(row.get("comp_energy_factor_weight")),
            energy_factor_speed   = _f(row.get("comp_energy_factor_speed")),
            energy_factor_terrain = _f(row.get("comp_energy_factor_terrain")),

            # --- capacity (derived from coaches) ---
            seats_total      = _i(cap["seats_total"]),
            couchettes_total = _i(cap["couchettes_total"]),
            sleepers_total   = _i(cap["sleepers_total"]),

            # --- density (1/places per first coach of each class) ---
            seat_density      = densities.get("Seat", 0.0),
            couchette_density = densities.get("Couchette", 0.0),
            sleeper_density   = densities.get("Sleeper", 0.0),

            # --- operator-level cost params ---
            ebit_margin_per         = _f(row.get("operator_ebit_margin_per")),
            financing_quota_per     = _f(row.get("operator_financing_quota_per")),
            fix_overhead_quota_per  = _f(row.get("operator_fix_overhead_quota_per")),
            var_overhead_per        = _f(row.get("operator_var_overhead_per")),
            driver_costs_eur_h      = _f(row.get("operator_driver_costs_eur_h")),
            crew_costs_eur_h        = _f(row.get("operator_crew_costs_eur_h")),
            driver_overhead_h       = _h(row.get("operator_driver_overhead_h")),
            crew_overhead_h         = _h(row.get("operator_crew_overhead_h")),
            shunting_eur_day        = _f(row.get("operator_shunting_eur_per_event")),

            # --- composition-level cost params ---
            purchase_loco_eur          = _f(row.get("comp_purchase_loco_eur")),
            purchase_coach_eur         = _f(row.get("comp_purchase_coach_eur")),
            loco_avail_per             = _f(row.get("comp_loco_avail_per")),
            coach_avail_per            = _f(row.get("comp_coach_avail_per")),
            loco_amort_years           = _f(row.get("comp_loco_amort_years")),
            coach_amort_years          = _f(row.get("comp_coach_amort_years")),
            cleaning_services_eur_day  = _f(row.get("comp_cleaning_services_eur_day")),
            loco_maint_eur_km          = _f(row.get("comp_loco_maint_eur_km")),
            coach_maint_eur_km         = _f(row.get("comp_coach_maint_eur_km")),

            # --- per-class service stocking costs ---
            svc_stockings_seat_per      = stockings.get("Seat", 0.0),
            svc_stockings_couchette_per = stockings.get("Couchette", 0.0),
            svc_stockings_sleeper_per   = stockings.get("Sleeper", 0.0),
        )

    def build_all_compositions(self) -> CompositionCollection:
        """Return all current compositions as a CompositionCollection."""
        with self._cursor() as cur:
            cur.execute("""
                SELECT comp_id
                FROM input_params.compositions
                WHERE is_current = TRUE
            """)
            rows = cur.fetchall()

        result: dict[str, CompositionParams] = {}
        for row in rows:
            try:
                result[row["comp_id"]] = self.build_composition(row["comp_id"])
            except Exception as e:
                logger.warning("Skipping composition '%s': %s", row["comp_id"], e)
                self._conn.rollback()  # reset aborted transaction before next query
        logger.info("Built %d compositions.", len(result))
        return CompositionCollection(result)

    # ------------------------------------------------------------------
    # BUILDER METHODS — infrastructure
    # ------------------------------------------------------------------

    def build_all_infra(self) -> InfraCollection:
        """Return all current infrastructure rows as an InfraCollection."""
        with self._cursor() as cur:
            cur.execute("""
                SELECT *
                FROM input_params.infrastructure
                WHERE is_current = TRUE
            """)
            rows = cur.fetchall()

            cur.execute("""
                SELECT *
                FROM input_params.infrastructure_defaults
                WHERE is_current = TRUE
                LIMIT 1
            """)
            default_row = cur.fetchone()

        result: dict[str, InfraParams] = {}
        for row in rows:
            try:
                result[row["country_code"]] = self._row_to_infra(
                    row["country_code"], row
                )
            except Exception as e:
                logger.warning(
                    "Skipping infrastructure row '%s': %s", row["country_code"], e
                )

        if default_row:
            result["_default"] = self._row_to_infra("_default", default_row)

        logger.info("Built infra params for %d countries.", len(result))
        return InfraCollection(result)

    # ------------------------------------------------------------------
    # BUILDER METHODS — stops
    # ------------------------------------------------------------------

    def build_all_stop_params(self, stop_ids: list[str]) -> StopCollection:
        """Build a StopCollection for a specific list of stop IDs."""
        with self._cursor() as cur:
            cur.execute("""
                SELECT *
                FROM input_params.stops
                WHERE stop_id = ANY(%s)
                  AND is_current = TRUE
            """, (stop_ids,))
            rows = cur.fetchall()

        result: dict[str, StopParams] = {}
        found = {row["stop_id"] for row in rows}

        for row in rows:
            result[row["stop_id"]] = StopParams(
                stop_id           = row["stop_id"],
                stop_name         = row.get("stop_name") or "",
                stop_country_code = row.get("stop_country_code") or "",
                lat               = _f(row.get("stop_lat")),
                lon               = _f(row.get("stop_lon")),
                stop_charge_eur   = _f(row.get("stop_charge_eur")),
            )

        for stop_id in stop_ids:
            if stop_id not in found:
                logger.warning(
                    "Stop '%s' not found in database — stop charge set to 0.", stop_id
                )

        return StopCollection(result)

    def build_all_stops(self) -> StopCollection:
        """Return all current stops as a StopCollection."""
        with self._cursor() as cur:
            cur.execute("""
                SELECT *
                FROM input_params.stops
                WHERE is_current = TRUE
            """)
            rows = cur.fetchall()

        result: dict[str, StopParams] = {}
        for row in rows:
            result[row["stop_id"]] = StopParams(
                stop_id           = row["stop_id"],
                stop_name         = row.get("stop_name") or "",
                stop_country_code = row.get("stop_country_code") or "",
                lat               = _f(row.get("stop_lat")),
                lon               = _f(row.get("stop_lon")),
                stop_charge_eur   = _f(row.get("stop_charge_eur")),
            )

        logger.info("Built %d stops.", len(result))
        return StopCollection(result)

    # ------------------------------------------------------------------
    # PRIVATE ROW MAPPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_infra(country_code: str, row) -> InfraParams:
        return InfraParams(
            country_code         = country_code,
            tac_eur_train_km     = _f(row.get("infra_tac_eur_train_km")),
            parking_eur_day      = _f(row.get("infra_parking_eur_day")),
            energy_price_eur_kwh = _f(row.get("infra_energy_price_eur_kwh")),
            terrain_score        = _f(row.get("infra_terrain_score")),
            terrain_category     = row.get("infra_terrain_category") or "",
            hsr_allowed          = _b(row.get("infra_hsr_allowed")),
            min_boarding_time_h  = _h(row.get("infra_min_boarding_time_h")),
            min_alighting_time_h = _h(row.get("infra_min_alighting_time_h")),
            buffer_quota_per     = _f(row.get("infra_buffer_quota_per")),
        )