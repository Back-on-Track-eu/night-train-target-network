"""
proposal_repository.py
======================
Write-path database adapter for published proposals — the persistence
counterpart to data_loader_from_db.py (which stays strictly read-only for
parameter data).

WP5 cutover (PROPOSALS_DESIGN.md §2.2/§5): replaces the old persist-on-
calc world (save()/attach_evaluation()/get_version(), route_body/
evaluation_body JSON blobs, is_current/change_log) with the slimmed
schema's single-transaction publish. A proposal has exactly one stored
state at any time — publish() either inserts a brand-new row (mode="new")
or updates the existing one in place (mode="overwrite", previous GTFS/
sidecar rows pruned in the same transaction). See docs/PROPOSALS_DESIGN.md
§2.2 for the full new/overwrite contract this module implements.

The actual GTFS + sidecar writing is NOT here — api/helpers/
route_gtfs_serialize.py's insert_route_gtfs() (WP3) is the sole writer,
called from within publish()'s transaction via the same cursor. This
module owns the proposals.proposals / proposal_summaries / update_log
rows and the transaction boundary around all of it, plus the low-level
prefixed-ID utilities (parse_route_id/rewrite_id_prefix) shared by
api/helpers/proposal_compute.py (strips the neutral prefix for /calc) and
this module (adds the real prefix at publish time).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

from adapters.proposal_projection import build_summary_row
from api.helpers.route_gtfs_serialize import (
    input_parameters_from_scenario,
    insert_route_gtfs,
    route_dict_from_gtfs,
)

logger = logging.getLogger(__name__)

_ROUTE_ID_PATTERN = re.compile(r"^P(\d+)_V(\d+)_R1$")

# Every ID route_factory.py mints for a route starts with this — see
# api/helpers/proposal_compute.py's _NEUTRAL_PREFIX docstring. Publish
# rewrites this bare structural form up to the real P{id}_V{version}_
# prefix; single-route proposals only (today's only reachable case — see
# route_gtfs_serialize.py and route_factory.py), so "R1" is precise, not a
# loose heuristic: nothing else in a compute response starts with it.
_STRUCTURAL_ROUTE_PREFIX = "R1"


class ProposalNotFoundError(Exception):
    """Raised by publish(mode="overwrite") when proposal_id doesn't exist."""


class ProposalForbiddenError(Exception):
    """Raised by publish(mode="overwrite") when proposal_id belongs to a
    different user."""


def parse_route_id(route_id: str) -> tuple[int, int]:
    """Extract (proposal_id, proposal_version) from a route_id following the
    P{proposal_id}_V{version}_R1 convention. Raises ValueError otherwise."""
    match = _ROUTE_ID_PATTERN.match(route_id or "")
    if not match:
        raise ValueError(
            f"route_id '{route_id}' does not follow the "
            "P{proposal_id}_V{version}_R1 convention."
        )
    return int(match.group(1)), int(match.group(2))


def rewrite_id_prefix(obj: Any, old_prefix: str, new_prefix: str) -> Any:
    """Recursively replace an ID prefix in every string value AND dict key
    of a JSON structure. Covers route_id, trip_ids, geometry_ids, and all
    trip references (od_pairs, shuntings, parkings) as values — and, in
    the evaluation response's per-trip-pair/per-stop views
    (api/helpers/evaluation_serialize.py), trip_id/pair-key strings used
    as dict keys rather than values (e.g. data[pair_key][country_key]).
    Keys are always strings in a JSON-compatible dict, so the same
    startswith/replace logic applies to both.

    old_prefix must be non-empty and precise — every caller in this
    codebase uses either the neutral P0_V0_ prefix or the bare "R1"
    structural prefix, both of which are guaranteed not to collide with
    any other string in a compute response (stop names, country codes,
    etc. never start with either). An empty old_prefix would match every
    string in the structure, which is never what a caller wants."""
    if isinstance(obj, str):
        return (
            new_prefix + obj[len(old_prefix) :] if obj.startswith(old_prefix) else obj
        )
    if isinstance(obj, list):
        return [rewrite_id_prefix(item, old_prefix, new_prefix) for item in obj]
    if isinstance(obj, dict):
        return {
            rewrite_id_prefix(key, old_prefix, new_prefix): rewrite_id_prefix(
                value, old_prefix, new_prefix
            )
            for key, value in obj.items()
        }
    return obj


class ProposalRepository:
    """Persists proposals — thin connection wrapper mirroring DBDataLoader's
    construction (same env vars, one connection per process/worker)."""

    def __init__(self) -> None:
        self._conn = self._connect()

    def _connect(self):
        required = {
            "POSTGRES_HOST": os.environ.get("POSTGRES_HOST"),
            "POSTGRES_PORT": os.environ.get("POSTGRES_PORT"),
            "POSTGRES_DB": os.environ.get("POSTGRES_DB"),
            "POSTGRES_USER": os.environ.get("POSTGRES_USER"),
            "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                f"Missing required environment variable(s) for DB connection: "
                f"{', '.join(missing)}."
            )
        return psycopg2.connect(
            host=required["POSTGRES_HOST"],
            port=required["POSTGRES_PORT"],
            dbname=required["POSTGRES_DB"],
            user=required["POSTGRES_USER"],
            password=required["POSTGRES_PASSWORD"],
        )

    def _cursor(self):
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_user(self, user_id: int) -> Optional[dict]:
        """admin.users row for user_id, or None."""
        with self._cursor() as cur:
            cur.execute(
                # display_name aliased to user_name — see feedback_repository
                # .get_user(): the API field name stays user_name for now.
                "SELECT user_id, display_name AS user_name, email "
                "FROM admin.users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()  # release the read-only transaction
        return dict(row) if row else None

    @staticmethod
    def _next_proposal_id(cur) -> int:
        cur.execute(
            "SELECT nextval(pg_get_serial_sequence('proposals.proposals', 'proposal_id'))"
        )
        return cur.fetchone()["nextval"]

    # ------------------------------------------------------------------
    # Publish — §2.2
    # ------------------------------------------------------------------

    def publish(
        self,
        mode: str,
        user_id: int,
        name: str,
        computed: dict,
        proposal_id: Optional[int] = None,
        based_on_proposal_id: Optional[int] = None,
    ) -> dict:
        """Publish a computed proposal (new or overwrite) — one
        transaction: container row + GTFS/sidecars + summary row +
        update_log, prefixed IDs assigned here.

        computed: api/helpers/proposal_compute.compute_proposal()'s
        output — bare structural ids ("R1", "R1_D0_T1", ...), NOT yet
        persistence-eligible. Publish is what mints the real
        P{proposal_id}_V{version}_ prefix (the reverse of what
        compute_proposal() stripped off for /calc).

        mode: "new" | "overwrite". "new" ignores proposal_id (a fresh one
        is allocated from the sequence); "overwrite" requires it and
        raises ProposalNotFoundError/ProposalForbiddenError if the id
        doesn't exist or isn't owned by user_id.

        Returns a dict of what was stored, ready for
        api/helpers/proposal_serialize.py to shape into a response:
        {proposal_id, proposal_version, user_id, name, route_fingerprint,
         composition_id, scenario_id, route_builder_version, calc_version,
         request, route, evaluation, created_at, updated_at}. "evaluation"
        is the FULL shape (models/input/views) as computed — richer than
        what's actually persisted in evaluation_output (models/views
        only, §5.1), since the caller already has the full one in hand
        and re-trimming it would be pure waste.
        """
        if mode not in ("new", "overwrite"):
            raise ValueError(f"publish: unknown mode '{mode}'.")

        try:
            with self._cursor() as cur:
                if mode == "overwrite":
                    new_pid, new_version = self._lock_for_overwrite(
                        cur, proposal_id, user_id
                    )
                else:
                    new_pid = self._next_proposal_id(cur)
                    new_version = 1

                prefixed = rewrite_id_prefix(
                    computed,
                    _STRUCTURAL_ROUTE_PREFIX,
                    f"P{new_pid}_V{new_version}_{_STRUCTURAL_ROUTE_PREFIX}",
                )
                route_dict = prefixed["route"]
                evaluation_full = prefixed["evaluation"]
                request_echo = prefixed["request"]
                # §5.1 — only models + views are irreducible/stored;
                # input.parameters is rebuilt on read via the scenario pin
                # (route_gtfs_serialize.input_parameters_from_scenario()).
                storage_evaluation = {
                    "models": evaluation_full["models"],
                    "views": evaluation_full["views"],
                }

                if mode == "overwrite":
                    self._prune_gtfs(cur, new_pid, new_version - 1)
                    updated_at = self._update_container(
                        cur,
                        proposal_id=new_pid,
                        proposal_version=new_version,
                        name=name,
                        prefixed=prefixed,
                        storage_evaluation=storage_evaluation,
                    )
                else:
                    updated_at = self._insert_container(
                        cur,
                        proposal_id=new_pid,
                        proposal_version=new_version,
                        user_id=user_id,
                        name=name,
                        prefixed=prefixed,
                        storage_evaluation=storage_evaluation,
                    )

                insert_route_gtfs(cur, route_dict)

                summary = build_summary_row(route_dict, evaluation_full)
                self._upsert_summary(
                    cur,
                    proposal_id=new_pid,
                    proposal_version=new_version,
                    user_id=user_id,
                    name=name,
                    prefixed=prefixed,
                    summary=summary,
                )

                self._write_update_log(
                    cur,
                    proposal_id=new_pid,
                    proposal_version=new_version,
                    user_id=user_id,
                    event="published" if mode == "new" else "overwritten",
                    based_on_proposal_id=based_on_proposal_id,
                )

            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        logger.info(
            "proposal publish: mode=%s proposal_id=%s version=%s user_id=%s",
            mode,
            new_pid,
            new_version,
            user_id,
        )
        return {
            "proposal_id": new_pid,
            "proposal_version": new_version,
            "user_id": user_id,
            "name": name,
            "route_fingerprint": prefixed["route_fingerprint"],
            "composition_id": request_echo["composition_id"],
            "scenario_id": request_echo["scenario_id"],
            "route_builder_version": prefixed["route_builder_version"],
            "calc_version": prefixed["calc_version"],
            "request": request_echo,
            "route": route_dict,
            "evaluation": evaluation_full,
            "updated_at": updated_at,
        }

    def _lock_for_overwrite(
        self, cur, proposal_id: Optional[int], user_id: int
    ) -> tuple[int, int]:
        """FOR UPDATE serializes concurrent overwrites of the same
        proposal (two overwrite-publishes, or a publish racing a future
        refresh batch). Returns (proposal_id, next_version)."""
        if proposal_id is None:
            raise ValueError("publish(mode='overwrite') requires proposal_id.")
        cur.execute(
            "SELECT proposal_id, proposal_version, user_id "
            "FROM proposals.proposals WHERE proposal_id = %s FOR UPDATE",
            (proposal_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ProposalNotFoundError(proposal_id)
        if row["user_id"] != user_id:
            raise ProposalForbiddenError(proposal_id)
        return proposal_id, row["proposal_version"] + 1

    def _prune_gtfs(self, cur, proposal_id: int, old_version: int) -> None:
        """Delete the previous state's GTFS + sidecar rows before writing
        the new state (§4: 'previous state hard-deleted in the same
        transaction'). routes/services cascade almost everything
        (trips -> stop_times/segments/od_pairs/timetable_warnings;
        routes -> parkings/shuntings/seasonal_schedules; services ->
        calendar/calendar_dates) — shapes don't cascade from either (both
        trips.shape_id and segments.shape_id are ON DELETE SET NULL, not
        the reverse), so they're deleted explicitly by the shared
        route_id/service_id prefix."""
        old_route_id = f"P{proposal_id}_V{old_version}_{_STRUCTURAL_ROUTE_PREFIX}"
        # old_route_id itself contains underscores that must match
        # literally, not as LIKE's single-char wildcard — escape every
        # underscore in the route id, then append the trailing "_" (also
        # escaped) that separates it from the rest of each shape_id.
        escaped_route_id = old_route_id.replace("_", "\\_")
        cur.execute(
            "DELETE FROM proposals.shapes WHERE shape_id LIKE %s",
            (f"{escaped_route_id}\\_%",),
        )
        cur.execute("DELETE FROM proposals.routes WHERE route_id = %s", (old_route_id,))
        cur.execute(
            "DELETE FROM proposals.services WHERE service_id = %s",
            (f"{old_route_id}_SVC",),
        )

    def _insert_container(
        self,
        cur,
        proposal_id: int,
        proposal_version: int,
        user_id: int,
        name: str,
        prefixed: dict,
        storage_evaluation: dict,
    ):
        request_echo = prefixed["request"]
        cur.execute(
            "INSERT INTO proposals.proposals "
            "(proposal_id, proposal_version, user_id, name, route_fingerprint, "
            " composition_id, scenario_id, route_builder_version, calc_version, "
            " compute_request, evaluation_output) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING updated_at",
            (
                proposal_id,
                proposal_version,
                user_id,
                name,
                prefixed["route_fingerprint"],
                request_echo["composition_id"],
                request_echo["scenario_id"],
                prefixed["route_builder_version"],
                prefixed["calc_version"],
                Json(request_echo),
                Json(storage_evaluation),
            ),
        )
        return cur.fetchone()["updated_at"]

    def _update_container(
        self,
        cur,
        proposal_id: int,
        proposal_version: int,
        name: str,
        prefixed: dict,
        storage_evaluation: dict,
    ):
        """user_id is deliberately not a parameter here — overwrite never
        changes ownership (that's what "overwrite vs new" already gates),
        and the caller-supplied user_id was already checked to match the
        existing row's in _lock_for_overwrite()."""
        request_echo = prefixed["request"]
        cur.execute(
            "UPDATE proposals.proposals SET "
            " proposal_version = %s, name = %s, route_fingerprint = %s, "
            " composition_id = %s, scenario_id = %s, route_builder_version = %s, "
            " calc_version = %s, compute_request = %s, evaluation_output = %s, "
            " updated_at = now() "
            "WHERE proposal_id = %s "
            "RETURNING updated_at",
            (
                proposal_version,
                name,
                prefixed["route_fingerprint"],
                request_echo["composition_id"],
                request_echo["scenario_id"],
                prefixed["route_builder_version"],
                prefixed["calc_version"],
                Json(request_echo),
                Json(storage_evaluation),
                proposal_id,
            ),
        )
        return cur.fetchone()["updated_at"]

    def _upsert_summary(
        self,
        cur,
        proposal_id: int,
        proposal_version: int,
        user_id: int,
        name: str,
        prefixed: dict,
        summary: dict,
    ) -> None:
        """One row per proposal (§5.4) — identity columns from the
        container write, metrics/KPIs from proposal_projection.
        build_summary_row(). geom_simplified is the one column needing a
        non-literal SQL expression (ST_GeomFromGeoJSON), so it's handled
        separately from the rest of summary's plain-valued columns rather
        than folded into one uniform placeholder list."""
        request_echo = prefixed["request"]
        identity = {
            "proposal_id": proposal_id,
            "proposal_version": proposal_version,
            "user_id": user_id,
            "route_fingerprint": prefixed["route_fingerprint"],
            "composition_id": request_echo["composition_id"],
            "scenario_id": request_echo["scenario_id"],
            "name": name,
            "route_builder_version": prefixed["route_builder_version"],
            "calc_version": prefixed["calc_version"],
        }
        metric_columns = [k for k in summary if k != "geom_simplified"]
        columns = list(identity) + metric_columns + ["geom_simplified"]
        placeholders = ["%s"] * (len(identity) + len(metric_columns)) + [
            "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"
        ]
        values = (
            list(identity.values())
            + [summary[k] for k in metric_columns]
            + [Json(summary["geom_simplified"])]
        )
        assignments = ", ".join(
            f"{col} = EXCLUDED.{col}" for col in columns if col != "proposal_id"
        )
        cur.execute(
            f"INSERT INTO proposals.proposal_summaries ({', '.join(columns)}) "
            f"VALUES ({', '.join(placeholders)}) "
            f"ON CONFLICT (proposal_id) DO UPDATE SET {assignments}, updated_at = now()",
            values,
        )

    def _write_update_log(
        self,
        cur,
        proposal_id: int,
        proposal_version: int,
        user_id: int,
        event: str,
        based_on_proposal_id: Optional[int],
    ) -> None:
        cur.execute(
            "INSERT INTO proposals.update_log "
            "(proposal_id, proposal_version, user_id, event) VALUES (%s, %s, %s, %s)",
            (proposal_id, proposal_version, user_id, event),
        )
        if based_on_proposal_id is not None:
            cur.execute(
                "INSERT INTO proposals.update_log "
                "(proposal_id, proposal_version, user_id, event, detail) "
                "VALUES (%s, %s, %s, 'branched_from', %s)",
                (
                    proposal_id,
                    proposal_version,
                    user_id,
                    Json({"source_proposal_id": based_on_proposal_id}),
                ),
            )
            cur.execute(
                "INSERT INTO proposals.update_log "
                "(proposal_id, proposal_version, user_id, event, detail) "
                "VALUES (%s, %s, %s, 'branched_to', %s)",
                (
                    based_on_proposal_id,
                    proposal_version,
                    user_id,
                    Json({"source_proposal_id": proposal_id}),
                ),
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_container(self, proposal_id: int) -> Optional[dict]:
        """The slimmed proposals.proposals container row (§5.3) + owner
        display name, or None if unknown. Does NOT include the route or
        evaluation — GET /api/proposal/<id> (api/proposals.py) rebuilds
        those separately via route_gtfs_serialize.py, since the container
        alone doesn't carry them (§5.1: route lives in GTFS, evaluation's
        input.parameters is rebuilt from the scenario pin)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT p.proposal_id, p.proposal_version, p.user_id, "
                "       u.display_name AS user_name, p.name, p.route_fingerprint, "
                "       p.composition_id, p.scenario_id, p.route_builder_version, "
                "       p.calc_version, p.compute_request, p.evaluation_output, "
                "       p.created_at, p.updated_at "
                "FROM proposals.proposals p "
                "LEFT JOIN admin.users u USING (user_id) "
                "WHERE p.proposal_id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return dict(row) if row else None

    def reconstruct_route(
        self, proposal_id: int, proposal_version: int, scenario_id: int, loader
    ) -> dict:
        """route_to_dict()-shaped route, rebuilt from GTFS + sidecar rows
        (route_gtfs_serialize.route_dict_from_gtfs(), WP3) — the read-side
        counterpart of publish()'s insert_route_gtfs() call. Encapsulated
        here (rather than handing api/proposals.py a raw cursor) so the
        repository stays the sole owner of DB access."""
        with self._cursor() as cur:
            route_dict = route_dict_from_gtfs(
                proposal_id, proposal_version, loader, scenario_id, cur
            )
        self._conn.rollback()
        return route_dict

    def reconstruct_evaluation(self, container: dict, loader) -> dict:
        """Full evaluation shape (models/input/views) for a loaded
        proposal — models/views come back verbatim from the stored
        evaluation_output column (§5.1: irreducible, stored as-is);
        input.parameters is rebuilt fresh via the scenario pin
        (route_gtfs_serialize.input_parameters_from_scenario()), never
        stored (would duplicate the params tables into every row)."""
        stored = container["evaluation_output"]
        # input_parameters_from_scenario() returns the whole {"parameters":
        # {...}} input dict already (see its own docstring), not just the
        # inner parameters — so it slots straight under "input" below.
        input_section = input_parameters_from_scenario(container["scenario_id"], loader)
        return {
            "models": stored["models"],
            "input": input_section,
            "views": stored["views"],
        }

    def owner(self, proposal_id: int) -> Optional[int]:
        """user_id of a proposal's owner, or None if unknown — a cheap
        existence+ownership check for callers that don't need the full
        container row (e.g. proposal_engagement.py)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT user_id FROM proposals.proposals WHERE proposal_id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return row["user_id"] if row else None

    def list_summaries(
        self,
        user_ids: Optional[list[int]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Minimal WP5 list — straight off proposal_summaries, newest
        first (updated_at). Full filter/sort/section support (§7.1) is
        WP6; this only carries the one filter (user_ids, e.g. "my
        proposals") and pagination needed for a bare gallery to work.
        Returns (rows, total_before_pagination)."""
        where = ""
        params: tuple = ()
        if user_ids:
            where = " WHERE user_id = ANY(%s)"
            params = (user_ids,)

        with self._cursor() as cur:
            cur.execute(
                f"SELECT count(*) AS total FROM proposals.proposal_summaries{where}",
                params,
            )
            total = cur.fetchone()["total"]

            sql = (
                "SELECT proposal_id, proposal_version, user_id, name, "
                "       route_fingerprint, composition_id, scenario_id, "
                "       route_builder_version, calc_version, total_distance_km, "
                "       total_time_h, avg_speed_kmh, n_stops, countries, stop_ids, "
                "       cost_eur_per_train_km, revenue_eur_per_train_km, "
                "       margin_eur_per_train_km, subsidy_eur_per_year, "
                "       demand_trips_per_year, demand_trip_km_per_year, "
                "       shift_air_trips_per_year, shift_air_trip_km_per_year, "
                "       shift_car_trips_per_year, shift_car_trip_km_per_year, "
                "       co2_savings_t_per_year, subsidy_eur_per_t_co2, "
                "       demand_kpis_placeholder, updated_at "
                f"FROM proposals.proposal_summaries{where} "
                "ORDER BY updated_at DESC"
            )
            if limit is not None:
                sql += " LIMIT %s OFFSET %s"
                params = params + (limit, offset)
            cur.execute(sql, params)
            rows = cur.fetchall()
        self._conn.rollback()
        return [dict(row) for row in rows], total
