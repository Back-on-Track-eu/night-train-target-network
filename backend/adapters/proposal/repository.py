"""
repository.py
=============
Write-path database adapter for published proposals — the persistence
counterpart to adapters/data_loader_from_db.py (which stays strictly
read-only for parameter data).

The 2026-08-03 cutover (README.md §2.2/§5): replaces the old persist-on-
calc world (save()/attach_evaluation()/get_version(), route_body/
evaluation_body JSON blobs, is_current/change_log) with the slimmed
schema's single-transaction publish. A proposal has exactly one stored
state at any time — publish() either inserts a brand-new row (mode="new")
or updates the existing one in place (mode="overwrite", previous GTFS/
sidecar rows pruned in the same transaction). See adapters/proposal/README.md
§2.2 for the full new/overwrite contract this module implements.

The actual GTFS + sidecar writing is NOT here — gtfs_store.py's
insert_route_gtfs() (WP3) is the sole writer, called from within
publish()'s transaction via the same cursor. This module owns the
proposals.proposals / proposal_summaries / update_log rows and the
transaction boundary around all of it. The prefixed-ID rewrite it applies
at publish time lives in id_prefix.py (shared with api/helpers/
proposal_compute.py, which strips the neutral prefix for /calc).

Version refresh (README.md §4.2): publish()'s "write the state" middle
section (prefix rewrite, GTFS write, summary upsert) is factored into
_write_state(), shared with the new refresh_proposal() — the system-
triggered counterpart used by scripts/refresh_proposals.py and the
on-load fallback (api/proposals.py) to recompute-and-overwrite-in-place
without publish()'s ownership check or ("published" vs "overwritten")
event naming. outdated_trigger() (module-level, no DB access) is the
shared staleness check both callers run per proposal; list_outdated()
is the batch script's SQL-level work-queue query. Note: an earlier
revision of this module also surfaced a per-row `scenario_outdated` flag
on GET/POST /api/proposals for frontend consumption — removed (WP7/8,
2026-08-04): the system (batch + on-load fallback) keeps every proposal
current on its own, so no user-facing staleness signal is needed;
staleness detection now lives here, internally, for that purpose only.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

from adapters.proposal.filter_builder import (
    DEFAULT_SOURCES,
    build_order_by,
    build_where,
)
from adapters.proposal.gtfs_store import (
    input_parameters_from_scenario,
    insert_route_gtfs,
    route_dict_from_gtfs,
)
from adapters.proposal.id_prefix import rewrite_id_prefix
from adapters.proposal.projection import build_summary_db_row
from models.evaluation.model import CALC_VERSION
from models.route.model import ROUTE_BUILDER_VERSION

logger = logging.getLogger(__name__)

# Every ID route_factory.py mints for a route starts with this — see
# api/helpers/proposal_compute.py's _NEUTRAL_PREFIX docstring. Publish
# rewrites this bare structural form up to the real P{id}_V{version}_
# prefix; single-route proposals only (today's only reachable case — see
# gtfs_store.py and route_factory.py), so "R1" is precise, not a
# loose heuristic: nothing else in a compute response starts with it.
_STRUCTURAL_ROUTE_PREFIX = "R1"


def outdated_trigger(container: dict) -> Optional[dict]:
    """Whether a stored proposal's version/scenario pin has fallen behind
    current (§4.2) — the one staleness check shared by scripts/
    refresh_proposals.py (over list_outdated()'s rows) and the on-load
    fallback in api/proposals.py (over get_container()'s row); both shapes
    carry the same four keys this reads: route_builder_version,
    calc_version, scenario_id, current_base_scenario_id.

    Pure function, no DB access — the current-base lookup already
    travelled with the row (see get_container()/list_outdated()'s
    docstrings for why, rather than a second query here).

    Checked in priority order (route_builder_version > calc_version >
    base_scenario_moved) and returns only the FIRST trigger that applies:
    a recompute fixes all three at once regardless of which one fired, so
    update_log only needs to record the one that actually explains why
    this refresh happened. None if the proposal is fully current.
    """
    if container["route_builder_version"] != ROUTE_BUILDER_VERSION:
        return {
            "trigger": "route_builder_version",
            "from": container["route_builder_version"],
            "to": ROUTE_BUILDER_VERSION,
        }
    if container["calc_version"] != CALC_VERSION:
        return {
            "trigger": "calc_version",
            "from": container["calc_version"],
            "to": CALC_VERSION,
        }
    if container["scenario_id"] != container["current_base_scenario_id"]:
        return {
            "trigger": "base_scenario_moved",
            "from": container["scenario_id"],
            "to": container["current_base_scenario_id"],
        }
    return None


class ProposalNotFoundError(Exception):
    """Raised by publish(mode="overwrite") when proposal_id doesn't exist."""


class ProposalForbiddenError(Exception):
    """Raised by publish(mode="overwrite") when proposal_id belongs to a
    different user."""


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

    @staticmethod
    def _next_proposal_id(cur) -> int:
        cur.execute(
            "SELECT nextval(pg_get_serial_sequence('proposals.proposals', 'proposal_id'))"
        )
        return cur.fetchone()["nextval"]

    # ------------------------------------------------------------------
    # Publish — §2.2
    # ------------------------------------------------------------------

    def _write_state(
        self,
        cur,
        proposal_id: int,
        proposal_version: int,
        user_id: int,
        name: str,
        computed: dict,
        is_new: bool,
    ) -> dict:
        """The write-side state transition shared by publish() and
        refresh_proposal(): prefix rewrite, container row, GTFS + sidecar
        write, summary upsert. NOT the update_log row or the transaction
        boundary — callers own those, since they differ (event name,
        ownership check, based_on handling) between a user publish and a
        system refresh.

        Returns {prefixed, route_dict, evaluation_full, created_at,
        updated_at} — everything both callers' own return dicts need.
        """
        prefixed = rewrite_id_prefix(
            computed,
            _STRUCTURAL_ROUTE_PREFIX,
            f"P{proposal_id}_V{proposal_version}_{_STRUCTURAL_ROUTE_PREFIX}",
        )
        route_dict = prefixed["route"]
        evaluation_full = prefixed["evaluation"]
        # §5.1 — only models + views are irreducible/stored; input.parameters
        # is rebuilt on read via the scenario pin
        # (gtfs_store.input_parameters_from_scenario()).
        storage_evaluation = {
            "models": evaluation_full["models"],
            "views": evaluation_full["views"],
        }

        if is_new:
            timestamps = self._insert_container(
                cur,
                proposal_id=proposal_id,
                proposal_version=proposal_version,
                user_id=user_id,
                name=name,
                prefixed=prefixed,
                storage_evaluation=storage_evaluation,
            )
        else:
            self._prune_gtfs(cur, proposal_id, proposal_version - 1)
            timestamps = self._update_container(
                cur,
                proposal_id=proposal_id,
                proposal_version=proposal_version,
                name=name,
                prefixed=prefixed,
                storage_evaluation=storage_evaluation,
            )

        insert_route_gtfs(cur, route_dict)

        summary = build_summary_db_row(route_dict, evaluation_full)
        self._upsert_summary(
            cur,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            user_id=user_id,
            name=name,
            prefixed=prefixed,
            summary=summary,
        )

        return {
            "prefixed": prefixed,
            "route_dict": route_dict,
            "evaluation_full": evaluation_full,
            "created_at": timestamps["created_at"],
            "updated_at": timestamps["updated_at"],
        }

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

                state = self._write_state(
                    cur,
                    proposal_id=new_pid,
                    proposal_version=new_version,
                    user_id=user_id,
                    name=name,
                    computed=computed,
                    is_new=(mode == "new"),
                )
                prefixed = state["prefixed"]
                route_dict = state["route_dict"]
                evaluation_full = state["evaluation_full"]
                request_echo = prefixed["request"]

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
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
        }

    def refresh_proposal(
        self,
        proposal_id: int,
        computed: dict,
        detail: dict,
    ) -> dict:
        """System-triggered recompute-and-overwrite-in-place (§4.2) — the
        write-path counterpart to publish(mode="overwrite") used by
        scripts/refresh_proposals.py and the on-load fallback
        (api/proposals.py). Differs from publish() in exactly the ways a
        system refresh needs to: no ownership check (not a user action —
        proposal_id alone is enough), owner/name kept as stored rather
        than caller-supplied, update_log event is 'recalculated' (with
        `detail`, e.g. {"trigger": "calc_version", "from": "0.9.9",
        "to": "0.9.10"} — see outdated_trigger()) instead of 'overwritten',
        user_id NULL on the log row (a system event, per §4.1). FOR UPDATE
        still serializes concurrent writers (another refresh, or a genuine
        user overwrite-publish racing this one).

        Raises ProposalNotFoundError if proposal_id doesn't exist (a
        proposal deleted manually between list_outdated() and this call).
        """
        try:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT proposal_version, user_id, name "
                    "FROM proposals.proposals WHERE proposal_id = %s FOR UPDATE",
                    (proposal_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ProposalNotFoundError(proposal_id)
                new_version = row["proposal_version"] + 1
                user_id = row["user_id"]
                name = row["name"]

                state = self._write_state(
                    cur,
                    proposal_id=proposal_id,
                    proposal_version=new_version,
                    user_id=user_id,
                    name=name,
                    computed=computed,
                    is_new=False,
                )

                self._write_update_log(
                    cur,
                    proposal_id=proposal_id,
                    proposal_version=new_version,
                    user_id=None,
                    event="recalculated",
                    based_on_proposal_id=None,
                    detail=detail,
                )

            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        logger.info(
            "proposal refresh: proposal_id=%s version=%s trigger=%s",
            proposal_id,
            new_version,
            detail.get("trigger"),
        )
        return {
            "proposal_id": proposal_id,
            "proposal_version": new_version,
            "user_id": user_id,
            "name": name,
            "route_fingerprint": state["prefixed"]["route_fingerprint"],
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
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
    ) -> dict:
        """Returns {"created_at", "updated_at"} — both equal on a fresh
        insert (the row's row-level default), but returned as a pair
        rather than just updated_at so _write_state()'s result carries a
        real created_at for every caller (publish AND refresh), not just
        whatever get_container() happens to re-select afterwards."""
        request_echo = prefixed["request"]
        cur.execute(
            "INSERT INTO proposals.proposals "
            "(proposal_id, proposal_version, user_id, name, route_fingerprint, "
            " composition_id, scenario_id, route_builder_version, calc_version, "
            " compute_request, evaluation_output) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING created_at, updated_at",
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
        row = cur.fetchone()
        return {"created_at": row["created_at"], "updated_at": row["updated_at"]}

    def _update_container(
        self,
        cur,
        proposal_id: int,
        proposal_version: int,
        name: str,
        prefixed: dict,
        storage_evaluation: dict,
    ) -> dict:
        """user_id is deliberately not a parameter here — an overwrite
        (user or system-refresh) never changes ownership; the caller
        already resolved it (publish() via _lock_for_overwrite()'s
        ownership check, refresh_proposal() by simply reading it back).
        created_at is untouched by this UPDATE (not in the SET list), so
        RETURNING it here reports the proposal's original creation time,
        not this state's — the correct value for both callers."""
        request_echo = prefixed["request"]
        cur.execute(
            "UPDATE proposals.proposals SET "
            " proposal_version = %s, name = %s, route_fingerprint = %s, "
            " composition_id = %s, scenario_id = %s, route_builder_version = %s, "
            " calc_version = %s, compute_request = %s, evaluation_output = %s, "
            " updated_at = now() "
            "WHERE proposal_id = %s "
            "RETURNING created_at, updated_at",
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
        row = cur.fetchone()
        return {"created_at": row["created_at"], "updated_at": row["updated_at"]}

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
        container write, metrics/KPIs from adapters/proposal/
        projection.py's build_summary_db_row(). geom_simplified is the one column needing a
        non-literal SQL expression (ST_GeomFromGeoJSON), and created_at
        the one needing to survive an overwrite untouched (it belongs to
        the proposal's original publish, not this state's) — both handled
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
        columns = list(identity) + metric_columns + ["geom_simplified", "created_at"]
        placeholders = ["%s"] * (len(identity) + len(metric_columns)) + [
            "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)",
            "now()",
        ]
        values = (
            list(identity.values())
            + [summary[k] for k in metric_columns]
            + [Json(summary["geom_simplified"])]
        )
        # created_at is bound to "now()" directly (no param) and excluded
        # from the ON CONFLICT SET list below — an overwrite-publish keeps
        # the row's original creation time.
        assignments = ", ".join(
            f"{col} = EXCLUDED.{col}"
            for col in columns
            if col not in ("proposal_id", "created_at")
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
        user_id: Optional[int],
        event: str,
        based_on_proposal_id: Optional[int],
        detail: Optional[dict] = None,
    ) -> None:
        """detail is for the primary event row itself — e.g. refresh_
        proposal()'s 'recalculated' event carries {"trigger": ...,
        "from": ..., "to": ...} (§4.1). based_on_proposal_id's
        'branched_from'/'branched_to' pair below is unrelated and always
        NULL-detail-free on the primary row when both are given (publish
        never combines a branch with a caller-supplied detail)."""
        cur.execute(
            "INSERT INTO proposals.update_log "
            "(proposal_id, proposal_version, user_id, event, detail) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                proposal_id,
                proposal_version,
                user_id,
                event,
                Json(detail) if detail is not None else None,
            ),
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
        those separately via gtfs_store.py, since the container
        alone doesn't carry them (§5.1: route lives in GTFS, evaluation's
        input.parameters is rebuilt from the scenario pin).

        Also carries current_base_scenario_id — internal only, never
        surfaced on any API response (api/helpers/proposal_serialize.py's
        proposal_meta_to_dict() whitelists its own keys, so this just sits
        unused there) — it exists purely so the on-load refresh fallback
        (api/proposals.py, §4.2) can call outdated_trigger() on this same
        row without a second query."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT p.proposal_id, p.proposal_version, p.user_id, "
                "       u.display_name AS user_name, p.name, p.route_fingerprint, "
                "       p.composition_id, p.scenario_id, p.route_builder_version, "
                "       p.calc_version, p.compute_request, p.evaluation_output, "
                "       p.created_at, p.updated_at, "
                "       (SELECT scenario_id FROM scenario.scenarios "
                "        WHERE is_current_base) AS current_base_scenario_id "
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
        (gtfs_store.route_dict_from_gtfs(), WP3) — the read-side
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
        (gtfs_store.input_parameters_from_scenario()), never
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

    def list_outdated(self, limit: Optional[int] = None) -> list[dict]:
        """§4.2's work queue: every proposal whose stored route_builder_
        version/calc_version has fallen behind the running code, or whose
        scenario_id is no longer the current base — scripts/
        refresh_proposals.py's batch job. Filtered at the SQL level
        (rather than fetching every proposal and checking in Python) since
        the steady-state case, most of the time, is that nothing is
        outdated. Returns just enough per row for outdated_trigger() and
        compute_proposal(): proposal_id, the three stale-checkable
        columns, current_base_scenario_id (see get_container()'s
        docstring for why it travels alongside rather than a second
        query), and compute_request (the recompute input)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT proposal_id, route_builder_version, calc_version, "
                "       scenario_id, compute_request, "
                "       (SELECT scenario_id FROM scenario.scenarios "
                "        WHERE is_current_base) AS current_base_scenario_id "
                "FROM proposals.proposals "
                "WHERE route_builder_version != %s OR calc_version != %s "
                "   OR scenario_id != (SELECT scenario_id FROM scenario.scenarios "
                "                       WHERE is_current_base) "
                "ORDER BY proposal_id" + (" LIMIT %s" if limit is not None else ""),
                (ROUTE_BUILDER_VERSION, CALC_VERSION)
                + ((limit,) if limit is not None else ()),
            )
            rows = cur.fetchall()
        self._conn.rollback()
        return [dict(row) for row in rows]

    # Every proposal_summaries column the `summaries` section returns.
    _SUMMARY_COLUMNS = (
        "proposal_id, proposal_version, user_id, name, "
        "route_fingerprint, composition_id, scenario_id, "
        "route_builder_version, calc_version, total_distance_km, "
        "total_time_h, avg_speed_kmh, n_stops, countries, stop_ids, "
        "cost_eur_per_train_km, revenue_eur_per_train_km, "
        "margin_eur_per_train_km, subsidy_eur_per_year, "
        "demand_trips_per_year, demand_trip_km_per_year, "
        "shift_air_trips_per_year, shift_air_trip_km_per_year, "
        "shift_car_trips_per_year, shift_car_trip_km_per_year, "
        "co2_savings_t_per_year, subsidy_eur_per_t_co2, "
        "demand_kpis_placeholder, co2_g_per_pax_km, created_at, updated_at"
    )

    # Neither engagement count is a proposal_summaries column — both
    # change independently of publish/refresh, so storing them there
    # would go stale. Every filterable/sortable query below is built on
    # top of this CTE instead of the bare table, so filter_builder's
    # generic `likes_count >= %s` (etc.) resolves against a real column
    # of the CTE's output rather than needing special-casing per query.
    # COALESCE covers proposals with no engagement (no row to join).
    # comments_count excludes soft-deleted rows, matching what
    # GET /api/proposal/<id>/engagements returns (WP11).
    _ENGAGEMENT_CTE = (
        "proposal_summaries_with_engagement AS ("
        "  SELECT ps.*, "
        "         u.display_name, "
        "         starts_with(u.display_name, 'guest_') AS is_guest, "
        "         COALESCE(l.likes_count, 0)::int AS likes_count, "
        "         COALESCE(c.comments_count, 0)::int AS comments_count "
        "  FROM proposals.proposal_summaries ps "
        "  LEFT JOIN admin.users u ON u.user_id = ps.user_id "
        "  LEFT JOIN ("
        "    SELECT proposal_id, count(*) AS likes_count "
        "    FROM proposals.likes GROUP BY proposal_id"
        "  ) l ON l.proposal_id = ps.proposal_id "
        "  LEFT JOIN ("
        "    SELECT proposal_id, count(*) AS comments_count "
        "    FROM proposals.comments WHERE NOT is_deleted GROUP BY proposal_id"
        "  ) c ON c.proposal_id = ps.proposal_id"
        ")"
    )

    # The two UNION branches of the gallery (WP10 step 6b). One shared
    # column list — existing (ONTD) rows carry NULL in every
    # proposal-only column, which is exactly what makes every generic
    # filter_builder fragment work unchanged against the union: range
    # filters on financial KPIs, likes_count, or timestamps exclude
    # existing rows via SQL NULL semantics, trip_windows' EXISTS is
    # never true for a NULL proposal_id, and bbox works on both sides
    # because ontd.route_summaries.geom_simplified is the same PostGIS
    # geometry type as the proposal projection's. composition_id is a
    # shared column but a DIFFERENT namespace per source (curated
    # calibration ids vs ontd catalog ids) — a composition_ids filter
    # matches across both, documented in api/README.md §7.1.
    _GALLERY_PROPOSAL_BRANCH = (
        "SELECT 'proposal'::text AS source, NULL::text AS route_id, "
        "       proposal_id, proposal_version, user_id, name, "
        "       route_fingerprint, composition_id, scenario_id, "
        "       route_builder_version, calc_version, total_distance_km, "
        "       total_time_h, avg_speed_kmh, n_stops, countries, stop_ids, "
        "       cost_eur_per_train_km, revenue_eur_per_train_km, "
        "       margin_eur_per_train_km, subsidy_eur_per_year, "
        "       demand_trips_per_year, demand_trip_km_per_year, "
        "       shift_air_trips_per_year, shift_air_trip_km_per_year, "
        "       shift_car_trips_per_year, shift_car_trip_km_per_year, "
        "       co2_savings_t_per_year, subsidy_eur_per_t_co2, "
        "       demand_kpis_placeholder, co2_g_per_pax_km, geom_simplified, "
        "       likes_count, comments_count, display_name, is_guest, "
        "       created_at, updated_at, "
        "       NULL::boolean AS geometry_routed, NULL::text AS ontd_url "
        "FROM proposal_summaries_with_engagement"
    )
    _GALLERY_EXISTING_BRANCH = (
        "SELECT 'existing'::text AS source, route_id, "
        "       NULL::int AS proposal_id, NULL::int AS proposal_version, "
        "       NULL::int AS user_id, name, "
        "       NULL::text AS route_fingerprint, composition_id, "
        "       NULL::int AS scenario_id, "
        "       NULL::text AS route_builder_version, NULL::text AS calc_version, "
        "       total_distance_km, total_time_h, avg_speed_kmh, n_stops, "
        "       countries, stop_ids, "
        "       NULL::numeric AS cost_eur_per_train_km, "
        "       NULL::numeric AS revenue_eur_per_train_km, "
        "       NULL::numeric AS margin_eur_per_train_km, "
        "       NULL::numeric AS subsidy_eur_per_year, "
        "       NULL::numeric AS demand_trips_per_year, "
        "       NULL::numeric AS demand_trip_km_per_year, "
        "       NULL::numeric AS shift_air_trips_per_year, "
        "       NULL::numeric AS shift_air_trip_km_per_year, "
        "       NULL::numeric AS shift_car_trips_per_year, "
        "       NULL::numeric AS shift_car_trip_km_per_year, "
        "       NULL::numeric AS co2_savings_t_per_year, "
        "       NULL::numeric AS subsidy_eur_per_t_co2, "
        "       NULL::boolean AS demand_kpis_placeholder, co2_g_per_pax_km, "
        "       geom_simplified, "
        "       NULL::int AS likes_count, NULL::int AS comments_count, "
        "       NULL::text AS display_name, NULL::boolean AS is_guest, "
        "       NULL::timestamptz AS created_at, NULL::timestamptz AS updated_at, "
        "       geometry_routed, ontd_url "
        "FROM ontd.route_summaries"
    )

    def _gallery_cte(self, filters: Optional[dict]) -> str:
        """`gallery AS (...)` — built from only the requested source
        branch(es) (filter.sources, DEFAULT both), so a
        sources=["proposal"] request compiles to exactly the pre-6b
        query plan and never touches the ontd schema at all. Must be
        preceded by _ENGAGEMENT_CTE in the same WITH (the proposal
        branch reads proposal_summaries_with_engagement)."""
        sources = (filters or {}).get("sources") or list(DEFAULT_SOURCES)
        branches = []
        if "proposal" in sources:
            branches.append(self._GALLERY_PROPOSAL_BRANCH)
        if "existing" in sources:
            branches.append(self._GALLERY_EXISTING_BRANCH)
        return "gallery AS (" + " UNION ALL ".join(branches) + ")"

    def list_summaries(
        self,
        filters: Optional[dict] = None,
        sort: Optional[list[dict]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """The full §7.1 `summaries` section (WP6; sources union WP10
        step 6b) — every generic filter
        (adapters/proposal/filter_builder.py), sorted (NULLS LAST, so
        existing rows trail proposals on the default newest-first),
        windowed-counted, paginated over the source union. Returns
        (rows, total_before_pagination)."""
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        ctes = f"WITH {self._ENGAGEMENT_CTE}, {self._gallery_cte(filters)} "

        with self._cursor() as cur:
            cur.execute(
                f"{ctes}SELECT count(*) AS total FROM gallery{where_clause}",
                params,
            )
            total = cur.fetchone()["total"]

            sql = (
                f"{ctes}"
                f"SELECT source, route_id, geometry_routed, ontd_url, "
                f"{self._SUMMARY_COLUMNS}, likes_count, comments_count, "
                f"display_name, is_guest "
                f"FROM gallery{where_clause} "
                f"ORDER BY {build_order_by(sort)}"
            )
            page_params = list(params)
            if limit is not None:
                sql += " LIMIT %s OFFSET %s"
                page_params += [limit, offset]
            cur.execute(sql, page_params)
            rows = cur.fetchall()
        self._conn.rollback()
        return [dict(row) for row in rows], total

    def map_lines(self, filters: Optional[dict] = None) -> list[dict]:
        """`map_lines` section (§7.1, WP6.1 revision; existing-route
        merge WP10 step 6b): one row per distinct stop-pair corridor
        within the filtered set — not one row per proposal or route. A
        corridor is (stop_a, stop_b) with direction collapsed
        (LEAST/GREATEST): outbound and return traverse the same physical
        line. Proposal trips are walked via the
        P{proposal_id}_V{proposal_version}_R1 route_id convention
        trip_windows uses; existing routes contribute their
        ontd.route_corridors pieces — the exact same grain by
        construction (step 6a built that table to match), and the same
        Target Network stop-id namespace via ontd.stop_mappings, so a
        proposal and an existing train over the same two stops land on
        ONE feature. Corridors whose ONTD endpoints stayed unmapped
        (raw ONTD ids) group among themselves but can never merge with a
        proposal — expected, documented in db/ontd/README.md.

        Every corridor carries the per-source split AND the total
        (proposal_count / existing_count / total_count — decision
        2026-08-06: all three, always), so the frontend can drive
        thickness off the total and colour/toggle by source without a
        second query. avg_margin is proposals-only (existing rows carry
        no financials) — NULL on corridors served only by existing
        trains. Geometry prefers a proposal shape (routed with the live
        tool's exact settings) and falls back to the existing corridor's
        own geometry — both are stored GeoJSON, min(::text) picks a
        deterministic representative."""
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        with self._cursor() as cur:
            cur.execute(
                f"WITH {self._ENGAGEMENT_CTE}, {self._gallery_cte(filters)}, filtered AS ("
                "  SELECT source, route_id, proposal_id, proposal_version, "
                "         margin_eur_per_train_km "
                f"  FROM gallery{where_clause}"
                "), segs AS ("
                "  SELECT f.source, f.proposal_id, f.route_id, "
                "         f.margin_eur_per_train_km, "
                "         LEAST(s.from_stop_id, s.to_stop_id) AS stop_a, "
                "         GREATEST(s.from_stop_id, s.to_stop_id) AS stop_b, "
                "         sh.geometry::text AS geometry "
                "  FROM filtered f "
                "  JOIN proposals.trips t "
                "    ON f.source = 'proposal' "
                "   AND t.route_id = 'P' || f.proposal_id || '_V' || f.proposal_version || '_R1' "
                "  JOIN proposals.segments s ON s.trip_id = t.trip_id "
                "  JOIN proposals.shapes sh ON sh.shape_id = s.shape_id "
                "  WHERE s.shape_id IS NOT NULL "
                "  UNION ALL "
                # route_corridors already stores direction-collapsed pairs
                # (stop_a < stop_b, db/ontd/projection.py) — no
                # LEAST/GREATEST needed on this branch.
                "  SELECT f.source, NULL::int, f.route_id, NULL::numeric, "
                "         rc.stop_a, rc.stop_b, rc.geometry::text "
                "  FROM filtered f "
                "  JOIN ontd.route_corridors rc "
                "    ON f.source = 'existing' AND rc.route_id = f.route_id"
                ") "
                "SELECT stop_a, stop_b, "
                "       array_remove(array_agg(DISTINCT proposal_id ORDER BY proposal_id), NULL) "
                "         AS proposal_ids, "
                "       array_remove(array_agg(DISTINCT route_id ORDER BY route_id), NULL) "
                "         AS existing_route_ids, "
                "       count(DISTINCT proposal_id) AS proposal_count, "
                "       count(DISTINCT route_id) AS existing_count, "
                "       count(DISTINCT proposal_id) + count(DISTINCT route_id) "
                "         AS total_count, "
                "       avg(margin_eur_per_train_km) AS avg_margin_eur_per_train_km, "
                "       COALESCE("
                "         min(geometry) FILTER (WHERE source = 'proposal'), "
                "         min(geometry) FILTER (WHERE source = 'existing')"
                "       ) AS geometry "
                "FROM segs GROUP BY stop_a, stop_b",
                params,
            )
            rows = cur.fetchall()
        self._conn.rollback()
        return [dict(row) for row in rows]

    def map_stop_counts(self, filters: Optional[dict] = None) -> list[dict]:
        """`map_stop_counts` section (§7.1; source union WP10 step 6b):
        rows/routes touching each stop within the filtered set, joined to
        the current base scenario's pinned stop_infrastructures snapshot
        for lat/lon (§3.1's full-snapshot resolution — never inferred).
        Per stop the per-source split AND the total (n_proposals /
        n_existing / n — decision 2026-08-06: all three, always). Both
        sources share the Target Network stop-id namespace via step 6a's
        mapping; ONTD stops the mapping couldn't cover kept raw ONTD ids,
        which don't join the catalog and therefore don't get a marker —
        expected, documented in db/ontd/README.md."""
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        with self._cursor() as cur:
            cur.execute(
                f"WITH {self._ENGAGEMENT_CTE}, {self._gallery_cte(filters)} "
                "SELECT sub.stop_id, si.stop_lat, si.stop_lon, "
                "       count(*) FILTER (WHERE sub.source = 'proposal') "
                "         AS n_proposals, "
                "       count(*) FILTER (WHERE sub.source = 'existing') "
                "         AS n_existing, "
                "       count(*) AS n "
                "FROM (SELECT source, unnest(stop_ids) AS stop_id "
                f"      FROM gallery{where_clause}) sub "
                "JOIN input_params.stop_infrastructures si "
                "  ON si.stop_id = sub.stop_id "
                " AND si.stop_infra_version = ("
                "       SELECT stop_infrastructures_version FROM scenario.scenarios "
                "       WHERE is_current_base) "
                "GROUP BY sub.stop_id, si.stop_lat, si.stop_lon",
                params,
            )
            rows = cur.fetchall()
        self._conn.rollback()
        return [dict(row) for row in rows]

    def map_country_counts(self, filters: Optional[dict] = None) -> list[dict]:
        """`map_country_counts` section (§7.1, WP6.1 revision; source
        union WP10 step 6b): rows per country within the filtered set —
        per-source split AND total (n_proposals / n_existing / n —
        decision 2026-08-06: all three, always) — joined to
        input_params.countries for the border geometry the coverage
        choropleth needs, no second lookup required on the frontend.
        LEFT JOIN: a country code with no matched border (e.g. "UNK", an
        unattributed segment — §5.4, or an ONTD country outside the
        28-country catalog like UA/TR) still gets a row, geometry NULL."""
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        with self._cursor() as cur:
            cur.execute(
                f"WITH {self._ENGAGEMENT_CTE}, {self._gallery_cte(filters)} "
                "SELECT sub.country, "
                "       count(*) FILTER (WHERE sub.source = 'proposal') "
                "         AS n_proposals, "
                "       count(*) FILTER (WHERE sub.source = 'existing') "
                "         AS n_existing, "
                "       count(*) AS n, "
                "       ST_AsGeoJSON(c.country_geom) AS geom_geojson "
                "FROM ("
                "  SELECT source, unnest(countries) AS country "
                f"  FROM gallery{where_clause}"
                ") sub "
                "LEFT JOIN input_params.countries c ON c.country_code = sub.country "
                "GROUP BY sub.country, c.country_geom",
                params,
            )
            rows = cur.fetchall()
        self._conn.rollback()
        return [dict(row) for row in rows]
