"""
data_loader_from_spreadsheet.py
================================
Single data access layer for the night train model.
Loads all parameter sheets from Google Sheets once and builds typed
objects consumed by both the router and the cost model.

Typical usage
-------------
    loader = SheetDataLoader("model_config.yaml")
    loader.load_all()

    composition  = loader.build_composition("NJ-3.1")
    compositions = loader.build_all_compositions()
    infra        = loader.build_all_infra()
    stops        = loader.build_stops([("Wien Hbf", "boarding"), ...])
    stop_params  = loader.build_all_stop_params(["Wien Hbf", "München Hbf"])
    demand       = loader.build_all_demand()
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import yaml

import re

from models.params import (
    CompositionParams,
    CompositionCollection,
    InfraParams,
    InfraCollection,
    StopParams,
    StopCollection,
    DemandParams,
    DemandCollection,
)

logger = logging.getLogger(__name__)

# =============================================================================
# HELPERS
# =============================================================================


def _col_letter_to_index(col: str) -> int:
    """Convert Excel column letter(s) to 0-based index. 'A'->0, 'Z'->25, 'AA'->26."""
    col = col.strip().upper()
    result = 0
    for char in col:
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1


def _parse_float(value: str, default: float = 0.0) -> float:
    try:
        # strip currency symbols, whitespace
        cleaned = re.sub(r"[€%\s]", "", str(value))
        # remove all dots/commas that are thousands separators
        # a thousands separator is always followed by exactly 3 digits
        cleaned = re.sub(r"[.,](?=\d{3}([.,]|$))", "", cleaned)
        # replace remaining comma (decimal separator) with dot
        cleaned = cleaned.replace(",", ".")
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", ".").strip()))
    except (ValueError, TypeError):
        return default


def _parse_bool(value: str) -> bool:
    """Parse 'yes'/'no' string to bool. Defaults to False."""
    return str(value).strip().lower() == "yes"


def _parse_pct(value: str, default: float = 0.0) -> float:
    try:
        has_pct = "%" in str(value)
        f = _parse_float(value, default)
        return f / 100.0 if has_pct else f
    except (ValueError, TypeError):
        return default


def _parse_time_h(value: str) -> float:
    """
    Parse a time value to decimal hours.
      - HH:MM:SS  ('00:02:00' → 0.0333h)
      - HH:MM     ('00:02'    → 0.0333h)
      - decimal   ('0.0333'   → 0.0333h)
      - day frac  ('0.001388' → 0.0333h, Google Sheets raw time)
    """
    value = str(value).strip()
    if ":" in value:
        parts = value.split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            s = int(parts[2]) if len(parts) > 2 else 0
            return h + m / 60 + s / 3600
        except (ValueError, IndexError):
            return 0.0
    f = _parse_float(value, 0.0)
    if 0.0 < f < 1.0:
        return f * 24.0
    return f


# =============================================================================
# SHEET DATA LOADER
# =============================================================================


class SheetDataLoader:
    """
    Single data access layer for the night train model.

    Loads all parameter sheets from Google Sheets once on startup.
    Builds typed collection objects for the router and cost model.
    All sheet structure is driven entirely by model_config.yaml.
    """

    def __init__(self, config_path: str) -> None:
        with open(config_path, "r", encoding="utf-8") as f:
            self._cfg = yaml.safe_load(f)
        self._sheets_cfg = self._cfg["google_sheets"]
        self._spreadsheet_id = self._sheets_cfg["spreadsheet_id"]
        self._data: dict[str, dict] = {}
        self._loaded = False

    def load_all(self) -> None:
        """Connect to Google Sheets and load all configured sheets."""
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as e:
            raise ImportError(
                "gspread and google-auth are required: uv add gspread google-auth"
            ) from e

        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            raise EnvironmentError(
                "GOOGLE_APPLICATION_CREDENTIALS environment variable is not set."
            )

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self._spreadsheet_id)

        for alias, sheet_cfg in self._sheets_cfg["sheets"].items():
            self._load_sheet(spreadsheet, alias, sheet_cfg)

        self._loaded = True
        logger.info("SheetDataLoader: all sheets loaded.")

    def _load_sheet(self, spreadsheet, alias: str, sheet_cfg: dict) -> None:
        """Load one sheet and cache as { key -> row_dict }."""
        import gspread

        sheet_name = sheet_cfg["sheet_name"]
        header_row = sheet_cfg.get("header_row", 1)
        key_col_name = sheet_cfg["key_column"]
        col_map = sheet_cfg["columns"]

        try:
            ws = spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            logger.error("Sheet '%s' not found in spreadsheet.", sheet_name)
            self._data[alias] = {}
            return

        all_values = ws.get_all_values()
        if len(all_values) < header_row:
            logger.warning(
                "Sheet '%s' has fewer rows than header_row=%d.", sheet_name, header_row
            )
            self._data[alias] = {}
            return

        key_col_idx = _col_letter_to_index(col_map[key_col_name]["col"])

        rows: dict[str, dict] = {}
        for row in all_values[header_row:]:
            if len(row) <= key_col_idx:
                continue
            key_val = row[key_col_idx].strip()
            if not key_val:
                continue
            row_dict = {}
            for col_name, col_cfg in col_map.items():
                idx = _col_letter_to_index(col_cfg["col"])
                row_dict[col_name] = row[idx].strip() if idx < len(row) else ""
            rows[key_val] = row_dict

        self._data[alias] = rows
        logger.info("Loaded sheet '%s' — %d rows.", sheet_name, len(rows))

    def _require_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError("Call load_all() before accessing data.")

    def get(self, sheet_alias: str, key: str) -> Optional[dict]:
        """Return the row dict for a given key, or None if not found."""
        return self._data.get(sheet_alias, {}).get(key)

    def all_rows(self, sheet_alias: str) -> dict:
        """Return all rows for a sheet alias as { key -> row_dict }."""
        return self._data.get(sheet_alias, {})

    # ------------------------------------------------------------------
    # BUILDER METHODS — single item
    # ------------------------------------------------------------------

    def build_composition(self, comp_id: str) -> CompositionParams:
        """
        Look up a composition by ID and return a fully populated
        CompositionParams. Raises ValueError if not found.
        """
        self._require_loaded()
        row = self.get("compositions", comp_id)
        if row is None:
            raise ValueError(
                f"Composition '{comp_id}' not found in compositions sheet."
            )
        return self._row_to_composition(comp_id, row)

    def build_infra_country(self, country_code: str) -> Optional[InfraParams]:
        """
        Look up one country and return an InfraParams.
        Returns None with a warning if not found.
        """
        self._require_loaded()
        row = self.get("infrastructure", country_code)
        if row is None:
            logger.warning(
                "Country '%s' not found in infrastructure sheet.", country_code
            )
            return None
        return self._row_to_infra(country_code, row)

    def build_stop_params(self, stop_id: str) -> Optional[StopParams]:
        """
        Look up a stop by ID and return a StopParams.
        Returns None with a warning if not found.
        """
        self._require_loaded()
        row = self.get("stops", stop_id)
        if row is None:
            logger.warning(
                "Stop '%s' not found in stops sheet — stop charge set to 0.", stop_id
            )
            return None
        return self._row_to_stop_params(stop_id, row)

    def build_demand(self, relation_id: str) -> Optional[DemandParams]:
        """Look up one demand row by relation_id."""
        self._require_loaded()
        row = self.get("demand", relation_id)
        if row is None:
            logger.warning("Demand relation '%s' not found.", relation_id)
            return None
        return self._row_to_demand(relation_id, row)

    # ------------------------------------------------------------------
    # BUILDER METHODS — full collections
    # ------------------------------------------------------------------

    def build_all_compositions(self) -> CompositionCollection:
        """Return all compositions as a CompositionCollection."""
        self._require_loaded()
        result: dict[str, CompositionParams] = {}
        for comp_id, row in self.all_rows("compositions").items():
            try:
                result[comp_id] = self._row_to_composition(comp_id, row)
            except Exception as e:
                logger.warning("Skipping composition '%s': %s", comp_id, e)
        logger.info("Built %d compositions.", len(result))
        return CompositionCollection(result)

    def build_all_infra(self) -> InfraCollection:
        """
        Return all infrastructure rows as an InfraCollection.
        Includes '_default' row if present in the sheet.
        """
        self._require_loaded()
        result: dict[str, InfraParams] = {}
        for country_code, row in self.all_rows("infrastructure").items():
            if not country_code:
                continue
            try:
                result[country_code] = self._row_to_infra(country_code, row)
            except Exception as e:
                logger.warning("Skipping infrastructure row '%s': %s", country_code, e)
        logger.info("Built infra params for %d countries.", len(result))
        return InfraCollection(result)

    def build_all_stop_params(self, stop_ids: list[str]) -> StopCollection:
        """
        Build a StopCollection for a list of stop IDs.
        Stops not found are logged and omitted.
        """
        self._require_loaded()
        result: dict[str, StopParams] = {}
        for stop_id in stop_ids:
            sp = self.build_stop_params(stop_id)
            if sp is not None:
                result[stop_id] = sp
        return StopCollection(result)

    def build_all_demand(self) -> DemandCollection:
        """Return all demand rows as a DemandCollection."""
        self._require_loaded()
        result: dict[str, DemandParams] = {}
        for relation_id, row in self.all_rows("demand").items():
            try:
                result[relation_id] = self._row_to_demand(relation_id, row)
            except Exception as e:
                logger.warning("Skipping demand row '%s': %s", relation_id, e)
        logger.info("Built %d demand rows.", len(result))
        return DemandCollection(result)

    # ------------------------------------------------------------------
    # PRIVATE ROW PARSERS — one per sheet
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_composition(comp_id: str, row: dict) -> CompositionParams:
        return CompositionParams(
            comp_id=comp_id,
            comp_description=row.get("comp_description", ""),
            company=row.get("comp_company", ""),
            weight_gross_t=_parse_float(row["comp_weight_gross_t"]),
            max_speed_kmh=_parse_float(row["comp_max_speed_kmh"]),
            hsr_allowed=_parse_bool(row["comp_hsr_allowed"]),
            min_boarding_time_h=_parse_time_h(row["comp_veh_min_boarding_time_h"]),
            min_alighting_time_h=_parse_time_h(row["comp_veh_min_alighting_time_h"]),
            energy_factor_weight=_parse_float(row["comp_energy_factor_weight"]),
            energy_factor_speed=_parse_float(row["comp_energy_factor_speed"]),
            energy_factor_terrain=_parse_float(row["comp_energy_factor_terrain"]),
            seats_total=_parse_int(row["comp_seats_total"]),
            couchettes_total=_parse_int(row["comp_couchettes_total"]),
            sleepers_total=_parse_int(row["comp_sleepers_total"]),
            seat_density=_parse_float(row["comp_seat_density"]),
            couchette_density=_parse_float(row["comp_couchette_density"]),
            sleeper_density=_parse_float(row["comp_sleeper_density"]),
            ebit_margin_per=_parse_pct(row["comp_ebit_margin_per"]),
            purchase_loco_eur=_parse_float(row["comp_purchase_loco_eur"]),
            purchase_coach_eur=_parse_float(row["comp_purchase_coach_eur"]),
            loco_avail_per=_parse_pct(row["comp_loco_avail_per"]),
            coach_avail_per=_parse_pct(row["comp_coach_avail_per"]),
            loco_amort_years=_parse_float(row["comp_loco_amort_years"]),
            coach_amort_years=_parse_float(row["comp_coach_amort_years"]),
            financing_quota_per=_parse_pct(row["comp_financing_quota_per"]),
            fix_overhead_quota_per=_parse_pct(row["comp_fix_overhead_quota_per"]),
            cleaning_services_eur_day=_parse_float(
                row["comp_cleaning_services_eur_day"]
            ),
            shunting_eur_day=_parse_float(row["comp_shunting_eur_day"]),
            loco_maint_eur_km=_parse_float(row["comp_loco_maint_eur_km"]),
            coach_maint_eur_km=_parse_float(row["comp_coach_maint_eur_km"]),
            driver_costs_eur_h=_parse_float(row["comp_driver_costs_eur_h"]),
            crew_costs_eur_h=_parse_float(row["comp_crew_costs_eur_h"]),
            driver_overhead_h=_parse_time_h(row["comp_driver_overhead_h"]),
            crew_overhead_h=_parse_time_h(row["comp_crew_overhead_h"]),
            svc_stockings_seat_per=_parse_pct(row["comp_svc_stockings_seat_per"]),
            svc_stockings_couchette_per=_parse_pct(
                row["comp_svc_stockings_couchette_per"]
            ),
            svc_stockings_sleeper_per=_parse_pct(row["comp_svc_stockings_sleeper_per"]),
            var_overhead_per=_parse_pct(row["comp_var_overhead_per"]),
        )

    @staticmethod
    def _row_to_infra(country_code: str, row: dict) -> InfraParams:
        return InfraParams(
            country_code=country_code,
            tac_eur_train_km=_parse_float(row["infra_tac_eur_train_km"]),
            parking_eur_day=_parse_float(row["infra_parking_eur_day"]),
            energy_price_eur_kwh=_parse_float(row["infra_energy_price_eur_kwh"]),
            terrain_score=_parse_float(row["infra_terrain_score"]),
            terrain_category=row.get("infra_terrain_category", ""),
            hsr_allowed=_parse_bool(row["infra_hsr_allowed"]),
            min_boarding_time_h=_parse_time_h(row["infra_min_boarding_time_h"]),
            min_alighting_time_h=_parse_time_h(row["infra_min_alighting_time_h"]),
            buffer_quota_per=_parse_pct(row["infra_buffer_quota_per"]),
        )

    @staticmethod
    def _row_to_stop_params(stop_id: str, row: dict) -> StopParams:
        return StopParams(
            stop_id=stop_id,
            stop_name=row.get("stop_name", ""),
            stop_country_code=row.get("stop_country_code", ""),
            lat=_parse_float(row.get("stop_lat", "0")),
            lon=_parse_float(row.get("stop_lon", "0")),
            stop_charge_eur=_parse_float(row.get("stop_charge_eur", "0")),
        )

    @staticmethod
    def _row_to_demand(relation_id: str, row: dict) -> DemandParams:
        return DemandParams(
            relation_id=relation_id,
            origin_stop_id=row.get("demand_origin_stop_id", ""),
            destination_stop_id=row.get("demand_destination_stop_id", ""),
            demand_type=row.get("demand_type", ""),
            demand_seat_pax=_parse_float(row.get("demand_seat_pax", "0")),
            demand_couchette_pax=_parse_float(row.get("demand_couchette_pax", "0")),
            demand_sleeper_pax=_parse_float(row.get("demand_sleeper_pax", "0")),
        )
