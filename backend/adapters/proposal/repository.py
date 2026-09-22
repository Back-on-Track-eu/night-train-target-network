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
proposals.proposals / proposal_summaries / proposal_scenario_summaries /
update_log rows and the transaction boundary around all of it. The
scenario rows (README.md §5.4a) are computed by the caller
(api/helpers/scenario_summaries.py — this layer never runs a family)
and handed in as `scenario_rows`; None means "this caller could not
compute them" (db/dev/seed.py has no router) and clears the proposal's
rows so nothing stale outlives an overwrite. The prefixed-ID rewrite it applies
at publish time lives in id_prefix.py (shared with api/helpers/
member_compute.py, which strips the neutral prefix for /calc).

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
from typing import Optional

from psycopg2.extras import RealDictCursor

from adapters.db_pool import DBPool, default_pool
from psycopg2.extras import Json

from adapters.proposal.filter_builder import (
    DEFAULT_SOURCES,
    build_aggregate_select,
    build_order_by,
    build_where,
)
from adapters.proposal.gtfs_store import (
    insert_route_gtfs,
    route_dict_from_gtfs,
)
from adapters.proposal.id_prefix import rewrite_id_prefix
from adapters.proposal.projection import build_summary_db_row
from models.evaluation.model import CALC_VERSION
from models.route.model import ROUTE_BUILDER_VERSION

logger = logging.getLogger(__name__)

# Every ID route_factory.py mints for a route starts with this — see
# api/helpers/member_compute.py's _NEUTRAL_PREFIX docstring. Publish
# rewrites this bare structural form up to the real P{id}_V{version}_
# prefix; single-route proposals only (today's only reachable case — see
# gtfs_store.py and route_factory.py), so "R1" is precise, not a
# loose heuristic: nothing else in a compute response starts with it.
_STRUCTURAL_ROUTE_PREFIX = "R1"

# Douglas-Peucker tolerance, in degrees, for the corridor geometry map_lines()
# returns. Deliberately its OWN value rather than a reuse of projection.py's
# GEOM_SIMPLIFY_TOLERANCE_DEG: that one serves a single route drawn on its own,
# this one an overview of the whole network, where far more can be thrown away.
# The stored geometry is untouched — this only shapes what the section sends
# over the wire, and the gallery draws the unabridged route from map_routes the
# moment a card is hovered.
#
# ~0.002° is roughly 200 m. Sized against what the corridor layer is actually
# seen at: the gallery fits to zoom 9 or below, where this is well under a
# pixel, but nothing stops a user zooming further, and it stays acceptable
# (~6 px) at zoom 12. Coarser buys little — the payload is already dominated by
# corridor COUNT by then — and starts visibly cutting corners.
MAP_LINES_SIMPLIFY_TOLERANCE_DEG = 0.002


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
    """Persists proposals. Every public method borrows one connection
    from the shared DBPool (adapters/db_pool.py) for exactly its own
    transaction — thread-safe without locks, nothing held between
    calls."""

    def __init__(self, pool: DBPool | None = None) -> None:
        self._pool = pool or default_pool()

    def _cursor(self):
        """A cursor on a freshly borrowed connection — single-query reads.
        The transaction is released when the block ends. Writes borrow a
        connection explicitly and commit inside the block."""
        return self._pool.cursor()

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
        scenario_rows: Optional[list[dict]],
    ) -> dict:
        """The write-side state transition shared by publish() and
        refresh_proposal(): prefix rewrite, container row, GTFS + sidecar
        write, summary upsert, scenario rows (§5.4a). NOT the update_log
        row or the transaction boundary — callers own those, since they
        differ (event name, ownership check, based_on handling) between a
        user publish and a system refresh.

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
        # §5.1 — the views are the irreducible output and the only thing
        # stored. The models registry is GET /api/models and the parameters
        # a proposal was priced from are GET /api/params/* for its scenario
        # pin; neither is copied into every row (WP18 B2b — rows written
        # before it still carry a "models" key, harmless until the next
        # refresh rewrites them).
        storage_evaluation = {"views": evaluation_full["views"]}

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
        self._replace_scenario_summaries(
            cur,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            rows=scenario_rows or [],
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
        scenario_rows: Optional[list[dict]] = None,
    ) -> dict:
        """Publish a computed proposal (new or overwrite) — one
        transaction: container row + GTFS/sidecars + summary row +
        scenario rows + update_log, prefixed IDs assigned here.

        scenario_rows: api/helpers/scenario_summaries.py's
        compute_scenario_rows() output — the §5.4a projection on every
        current variant. None (the seed, which has no router) writes no
        rows; scripts/refresh_proposals.py --scenario-summaries fills
        them in later.

        computed: api/helpers/member_compute.compute_member()'s
        output — bare structural ids ("R1", "R1_D0_T1", ...), NOT yet
        persistence-eligible. Publish is what mints the real
        P{proposal_id}_V{version}_ prefix (the reverse of what
        compute_member() stripped off for the member payload).

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

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
                    scenario_rows=scenario_rows,
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

            conn.commit()

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
            # The proposal as stored, not as computed: views only, the same
            # shape GET /api/proposal/<id> serves. A compute response also
            # carries `operations` (CALC 0.9.28); like the models registry
            # before it, that is on-demand data — the member views endpoint
            # — and copying it here would make the publish reply the one
            # place it appeared alongside a stored proposal.
            "evaluation": {"views": evaluation_full["views"]},
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
        }

    def refresh_proposal(
        self,
        proposal_id: int,
        computed: dict,
        detail: dict,
        scenario_rows: Optional[list[dict]] = None,
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
        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
                    scenario_rows=scenario_rows,
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

            conn.commit()

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
        routes -> parkings/shuntings; services ->
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

    # The §5.4 KPI columns as proposal_scenario_summaries carries them —
    # build_summary_db_row()'s keys minus geom_simplified, which needs the
    # PostGIS expression. Listed once so the insert and the gallery's
    # variant branch cannot disagree.
    _SCENARIO_METRIC_COLUMNS = (
        "total_distance_km",
        "total_time_h",
        "avg_speed_kmh",
        "n_stops",
        "countries",
        "country_relations",
        "stop_ids",
        "cost_eur_per_train_km",
        "revenue_eur_per_train_km",
        "margin_eur_per_train_km",
        "net_eur_per_year",
        "subsidy_eur_per_year",
        "services_revenue_eur",
        "catering_contribution_eur",
        "operating_days_per_year",
        "departures_per_year",
        "trainsets_physical",
        "train_km_per_year",
        "available_place_km_per_year",
        "sold_place_km_per_year",
        "passengers_per_year",
        "demand_trips_per_year",
        "demand_trip_km_per_year",
        "shift_air_trips_per_year",
        "shift_air_trip_km_per_year",
        "shift_other_trips_per_year",
        "shift_other_trip_km_per_year",
        "co2_savings_t_per_year",
        "subsidy_eur_per_t_co2",
        "demand_kpis_placeholder",
        "co2_g_per_pax_km",
    )

    def _replace_scenario_summaries(
        self,
        cur,
        proposal_id: int,
        proposal_version: int,
        rows: list[dict],
    ) -> None:
        """The proposal's §5.4a rows, replaced wholesale: the variant set
        can change with the scenario catalogue and an overwrite can change
        the composition, so an upsert would leave rows behind that
        describe neither. An error row carries NULL in every figure —
        the columns are nullable for exactly that member."""
        cur.execute(
            "DELETE FROM proposals.proposal_scenario_summaries WHERE proposal_id = %s",
            (proposal_id,),
        )
        if not rows:
            return
        identity_columns = (
            "proposal_id",
            "proposal_version",
            "scenario_variant_id",
            "scenario_id",
            "measure_set_id",
            "composition_id",
            "route_builder_version",
            "calc_version",
            "status",
            "error_code",
        )
        columns = list(identity_columns) + list(self._SCENARIO_METRIC_COLUMNS)
        columns += ["geom_simplified", "segments"]
        placeholders = ["%s"] * (
            len(identity_columns) + len(self._SCENARIO_METRIC_COLUMNS)
        )
        placeholders += ["ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)", "%s"]
        sql = (
            f"INSERT INTO proposals.proposal_scenario_summaries ({', '.join(columns)}) "
            f"VALUES ({', '.join(placeholders)})"
        )
        for row in rows:
            summary = row.get("summary") or {}
            values = [
                proposal_id,
                proposal_version,
                row["scenario_variant_id"],
                row["scenario_id"],
                row["measure_set_id"],
                row["composition_id"],
                ROUTE_BUILDER_VERSION,
                CALC_VERSION,
                row["status"],
                row.get("error_code"),
            ]
            values += [summary.get(col) for col in self._SCENARIO_METRIC_COLUMNS]
            geometry = summary.get("geom_simplified")
            values += [
                Json(geometry) if geometry is not None else None,
                Json(row["segments"]) if row.get("segments") is not None else None,
            ]
            cur.execute(sql, values)

    def replace_scenario_summaries(self, proposal_id: int, rows: list[dict]) -> None:
        """The backfill's write (scripts/refresh_proposals.py
        --scenario-summaries): the §5.4a rows for one proposal in their
        own transaction, at the proposal's CURRENT version, without
        touching the container, the route or the base summary. FOR UPDATE
        so a publish racing this write serialises behind it.

        Raises ProposalNotFoundError for a proposal deleted between the
        work-queue query and this call."""
        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT proposal_version FROM proposals.proposals "
                    "WHERE proposal_id = %s FOR UPDATE",
                    (proposal_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ProposalNotFoundError(proposal_id)
                self._replace_scenario_summaries(
                    cur,
                    proposal_id=proposal_id,
                    proposal_version=row["proposal_version"],
                    rows=rows,
                )
            conn.commit()

    def list_scenario_backfill(self, limit: Optional[int] = None) -> list[dict]:
        """The backfill's work queue: proposals whose §5.4a rows are
        missing, behind the container's version, behind the running code
        versions, or not covering every current variant. Filtered in SQL
        like list_outdated() — in steady state nothing needs doing.
        Returns proposal_id and compute_request per row."""
        with self._cursor() as cur:
            cur.execute(
                "WITH current_variants AS ("
                "  SELECT v.scenario_variant_id "
                "  FROM scenario.scenario_variants v "
                "  JOIN scenario.scenarios s ON s.scenario_id = v.scenario_id "
                "  WHERE s.is_current_scenario"
                "), covered AS ("
                "  SELECT proposal_id, count(*) AS n_rows "
                "  FROM proposals.proposal_scenario_summaries ps "
                "  WHERE ps.route_builder_version = %s AND ps.calc_version = %s "
                "    AND ps.proposal_version = ("
                "      SELECT proposal_version FROM proposals.proposals p "
                "      WHERE p.proposal_id = ps.proposal_id) "
                "    AND ps.scenario_variant_id IN (SELECT scenario_variant_id "
                "                                   FROM current_variants) "
                "  GROUP BY proposal_id"
                ") "
                "SELECT p.proposal_id, p.compute_request "
                "FROM proposals.proposals p "
                "LEFT JOIN covered c ON c.proposal_id = p.proposal_id "
                "WHERE COALESCE(c.n_rows, 0) < (SELECT count(*) FROM current_variants) "
                "ORDER BY p.proposal_id" + (" LIMIT %s" if limit is not None else ""),
                (ROUTE_BUILDER_VERSION, CALC_VERSION)
                + ((limit,) if limit is not None else ()),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

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
        return route_dict

    def reconstruct_evaluation(self, container: dict) -> dict:
        """The evaluation of a loaded proposal — {views}, verbatim from the
        stored evaluation_output column (§5.1: irreducible, stored as-is).
        Nothing else: the models registry and the parameters have their
        own endpoints (WP18 B2b). Reads only the views key, so rows written
        before B2b, which also carry "models", load unchanged."""
        return {"views": container["evaluation_output"]["views"]}

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
        return row["user_id"] if row else None

    def share_name(self, proposal_id: int) -> Optional[str]:
        """A proposal's display name, or None if unknown — the whole read
        behind api/proposal_share.py's link-preview stub. Deliberately not
        get_container(): that row carries compute_request and
        evaluation_output, two large JSONB columns, and this route is hit
        by every chat client that previews a shared link."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT name FROM proposals.proposals WHERE proposal_id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
        return row["name"] if row else None

    def list_outdated(self, limit: Optional[int] = None) -> list[dict]:
        """§4.2's work queue: every proposal whose stored route_builder_
        version/calc_version has fallen behind the running code, or whose
        scenario_id is no longer the current base — scripts/
        refresh_proposals.py's batch job. Filtered at the SQL level
        (rather than fetching every proposal and checking in Python) since
        the steady-state case, most of the time, is that nothing is
        outdated. Returns just enough per row for outdated_trigger() and
        compute_member(): proposal_id, the three stale-checkable
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
        return [dict(row) for row in rows]

    # Every proposal_summaries column the `summaries` section returns.
    _SUMMARY_COLUMNS = (
        "proposal_id, proposal_version, user_id, name, "
        "route_fingerprint, composition_id, scenario_id, "
        "route_builder_version, calc_version, total_distance_km, "
        "total_time_h, avg_speed_kmh, n_stops, countries, country_relations, "
        "stop_ids, "
        "cost_eur_per_train_km, revenue_eur_per_train_km, "
        "margin_eur_per_train_km, net_eur_per_year, subsidy_eur_per_year, "
        "services_revenue_eur, catering_contribution_eur, "
        "operating_days_per_year, departures_per_year, trainsets_physical, "
        "train_km_per_year, "
        "available_place_km_per_year, sold_place_km_per_year, "
        "passengers_per_year, "
        "demand_trips_per_year, demand_trip_km_per_year, "
        "shift_air_trips_per_year, shift_air_trip_km_per_year, "
        "shift_other_trips_per_year, shift_other_trip_km_per_year, "
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
        # The three §5.4a columns, so the union branch below is one SELECT
        # list whichever table it reads: the base projection is always a
        # computed row of no particular variant.
        "         'ok'::text AS status, NULL::text AS error_code, "
        "         NULL::int AS scenario_variant_id, "
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

    # The §5.4a counterpart of _ENGAGEMENT_CTE: the SAME rows as the base
    # projection — identity, name, the filterable columns (countries,
    # stop_ids, relations, composition, timestamps) all still come from
    # proposal_summaries, so a scenario never changes which proposals a
    # filter returns — with the figures swapped in from the scenario table
    # for ONE variant. A proposal that variant could not evaluate is still
    # a row (status 'error', figures NULL), and one whose rows have not
    # been backfilled yet is still a row too (status 'missing', figures
    # NULL, the base geometry so the map keeps drawing it). The variant id
    # is inlined by _gallery_ctes(): every reader passes its own parameter
    # list straight through, and the id is a validated int before it
    # reaches this layer.
    _SCENARIO_ENGAGEMENT_CTE = (
        "proposal_summaries_with_engagement AS ("
        "  SELECT ps.proposal_id, ps.proposal_version, ps.user_id, ps.name, "
        "         ps.route_fingerprint, ps.composition_id, "
        "         COALESCE(sv.scenario_id, ps.scenario_id) AS scenario_id, "
        "         ps.route_builder_version, ps.calc_version, "
        "         ps.countries, ps.country_relations, ps.stop_ids, "
        "         {metrics}, "
        "         CASE WHEN sv.status = 'ok' THEN sv.geom_simplified "
        "              WHEN sv.proposal_id IS NULL THEN ps.geom_simplified END "
        "           AS geom_simplified, "
        "         ps.created_at, ps.updated_at, "
        "         COALESCE(sv.status, 'missing') AS status, sv.error_code, "
        "         {variant}::int AS scenario_variant_id, "
        "         u.display_name, "
        "         starts_with(u.display_name, 'guest_') AS is_guest, "
        "         COALESCE(l.likes_count, 0)::int AS likes_count, "
        "         COALESCE(c.comments_count, 0)::int AS comments_count "
        "  FROM proposals.proposal_summaries ps "
        "  LEFT JOIN proposals.proposal_scenario_summaries sv "
        "         ON sv.proposal_id = ps.proposal_id "
        "        AND sv.scenario_variant_id = {variant} "
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

    # The scenario row's figure columns — everything in
    # _SCENARIO_METRIC_COLUMNS that is a quantity of the evaluation rather
    # than a description of the route the filters read. NULL unless the
    # variant's row is status 'ok'.
    _SCENARIO_FIGURE_COLUMNS = (
        "total_distance_km",
        "total_time_h",
        "avg_speed_kmh",
        "n_stops",
        "cost_eur_per_train_km",
        "revenue_eur_per_train_km",
        "margin_eur_per_train_km",
        "net_eur_per_year",
        "subsidy_eur_per_year",
        "services_revenue_eur",
        "catering_contribution_eur",
        "operating_days_per_year",
        "departures_per_year",
        "trainsets_physical",
        "train_km_per_year",
        "available_place_km_per_year",
        "sold_place_km_per_year",
        "passengers_per_year",
        "demand_trips_per_year",
        "demand_trip_km_per_year",
        "shift_air_trips_per_year",
        "shift_air_trip_km_per_year",
        "shift_other_trips_per_year",
        "shift_other_trip_km_per_year",
        "co2_savings_t_per_year",
        "subsidy_eur_per_t_co2",
        "demand_kpis_placeholder",
        "co2_g_per_pax_km",
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
        "       total_time_h, avg_speed_kmh, n_stops, countries, "
        "       country_relations, stop_ids, "
        "       cost_eur_per_train_km, revenue_eur_per_train_km, "
        "       margin_eur_per_train_km, net_eur_per_year, subsidy_eur_per_year, "
        "       services_revenue_eur, catering_contribution_eur, "
        "       operating_days_per_year, departures_per_year, trainsets_physical, "
        "       train_km_per_year, "
        "       available_place_km_per_year, sold_place_km_per_year, "
        "       passengers_per_year, "
        "       demand_trips_per_year, demand_trip_km_per_year, "
        "       shift_air_trips_per_year, shift_air_trip_km_per_year, "
        "       shift_other_trips_per_year, shift_other_trip_km_per_year, "
        "       co2_savings_t_per_year, subsidy_eur_per_t_co2, "
        "       demand_kpis_placeholder, co2_g_per_pax_km, geom_simplified, "
        "       likes_count, comments_count, display_name, is_guest, "
        "       created_at, updated_at, "
        "       NULL::boolean AS geometry_routed, NULL::text AS ontd_url, "
        "       status, error_code, scenario_variant_id "
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
        "       countries, country_relations, stop_ids, "
        "       NULL::numeric AS cost_eur_per_train_km, "
        "       NULL::numeric AS revenue_eur_per_train_km, "
        "       NULL::numeric AS margin_eur_per_train_km, "
        "       NULL::numeric AS net_eur_per_year, "
        "       NULL::numeric AS subsidy_eur_per_year, "
        "       NULL::numeric AS services_revenue_eur, "
        "       NULL::numeric AS catering_contribution_eur, "
        "       NULL::smallint AS operating_days_per_year, "
        "       NULL::integer AS departures_per_year, "
        "       NULL::smallint AS trainsets_physical, "
        "       NULL::numeric AS train_km_per_year, "
        "       NULL::numeric AS available_place_km_per_year, "
        "       NULL::numeric AS sold_place_km_per_year, "
        "       NULL::numeric AS passengers_per_year, "
        "       NULL::numeric AS demand_trips_per_year, "
        "       NULL::numeric AS demand_trip_km_per_year, "
        "       NULL::numeric AS shift_air_trips_per_year, "
        "       NULL::numeric AS shift_air_trip_km_per_year, "
        "       NULL::numeric AS shift_other_trips_per_year, "
        "       NULL::numeric AS shift_other_trip_km_per_year, "
        "       NULL::numeric AS co2_savings_t_per_year, "
        "       NULL::numeric AS subsidy_eur_per_t_co2, "
        "       NULL::boolean AS demand_kpis_placeholder, co2_g_per_pax_km, "
        "       geom_simplified, "
        "       NULL::int AS likes_count, NULL::int AS comments_count, "
        "       NULL::text AS display_name, NULL::boolean AS is_guest, "
        "       NULL::timestamptz AS created_at, NULL::timestamptz AS updated_at, "
        "       geometry_routed, ontd_url, "
        "       NULL::text AS status, NULL::text AS error_code, "
        "       NULL::int AS scenario_variant_id "
        "FROM ontd.route_summaries"
    )

    def _gallery_ctes(
        self, filters: Optional[dict], scenario_variant_id: Optional[int] = None
    ) -> str:
        """The WITH body every gallery reader starts from: the engagement
        CTE, then `gallery AS (...)` built from only the requested source
        branch(es) (filter.sources, DEFAULT both), so a
        sources=["proposal"] request compiles to exactly the pre-6b query
        plan and never touches the ontd schema at all.

        scenario_variant_id (§5.4a) swaps the proposal side's FIGURES: the
        base projection when None (today's rows, today's plan); otherwise
        the same rows with that variant's figures joined in — never a
        different set of proposals, so a filter answers the same whichever
        scenario is read. The existing branch is scenario-independent
        either way."""
        if scenario_variant_id is None:
            engagement = self._ENGAGEMENT_CTE
        else:
            engagement = self._SCENARIO_ENGAGEMENT_CTE.format(
                metrics=", ".join(
                    f"CASE WHEN sv.status = 'ok' THEN sv.{col} END AS {col}"
                    for col in self._SCENARIO_FIGURE_COLUMNS
                ),
                variant=int(scenario_variant_id),
            )
        sources = (filters or {}).get("sources") or list(DEFAULT_SOURCES)
        branches = []
        if "proposal" in sources:
            branches.append(self._GALLERY_PROPOSAL_BRANCH)
        if "existing" in sources:
            branches.append(self._GALLERY_EXISTING_BRANCH)
        return engagement + ", gallery AS (" + " UNION ALL ".join(branches) + ")"

    def list_summaries(
        self,
        filters: Optional[dict] = None,
        sort: Optional[list[dict]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        scenario_variant_id: Optional[int] = None,
    ) -> tuple[list[dict], int]:
        """The full §7.1 `summaries` section (WP6; sources union WP10
        step 6b) — every generic filter
        (adapters/proposal/filter_builder.py), sorted (NULLS LAST, so
        existing rows trail proposals on the default newest-first),
        windowed-counted, paginated over the source union. Returns
        (rows, total_before_pagination). scenario_variant_id reads the
        proposal side from the §5.4a rows of that variant."""
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        ctes = f"WITH {self._gallery_ctes(filters, scenario_variant_id)} "

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
                f"display_name, is_guest, status, error_code, scenario_variant_id "
                f"FROM gallery{where_clause} "
                f"ORDER BY {build_order_by(sort)}"
            )
            page_params = list(params)
            if limit is not None:
                sql += " LIMIT %s OFFSET %s"
                page_params += [limit, offset]
            cur.execute(sql, page_params)
            rows = cur.fetchall()
        return [dict(row) for row in rows], total

    def map_lines(
        self, filters: Optional[dict] = None, scenario_variant_id: Optional[int] = None
    ) -> list[dict]:
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
        trains.

        The contributing id LISTS are deliberately NOT returned. They
        were the one part of this section that grew without bound (their
        combined length is the number of distinct (proposal, corridor)
        pairs, so ~10k proposals means six figures of ids and single
        popular corridors carrying thousands), and nothing consumes
        them: per-route geometry for the hovered card comes from
        map_routes(), which is paginated with the list.

        Geometry is aggregated by REFERENCE, not by value: segs carries
        shape_id / route_id, and the representative geometry is joined
        back in once per corridor at the outer level. Aggregating the
        GeoJSON text itself (the previous min(geometry)) streamed every
        segment's full polyline through the grouping aggregate — at 10k
        proposals that is ~200k multi-KB strings per gallery load, which
        dwarfed everything else this query does. Corridor COUNT is the
        well-behaved dimension (distinct stop pairs saturate), so doing
        the geometry work per corridor rather than per segment makes
        this section's cost flat in proposal count.

        A proposal shape wins over an existing corridor's own geometry
        (routed with the live tool's exact settings); min() over the id
        picks a deterministic representative either way. ST_Simplify —
        not ST_SimplifyPreserveTopology — matches the shapely
        preserve_topology=False used on the projection side, so both
        render at the same fidelity; see
        MAP_LINES_SIMPLIFY_TOLERANCE_DEG for why the tolerance is its
        own value.

        scenario_variant_id (§5.4a): a non-base variant's route is not in
        proposals.segments/shapes, so its corridors come from the
        scenario row's `segments` JSON — one LineString per collapsed
        stop pair, keyed "A__B" — unnested here at the same grain. Only
        rows the variant evaluated contribute (an error or not-yet-
        backfilled proposal draws no corridor on that scenario; its card
        is still listed). The representative geometry is still fetched by
        reference (the proposal id, then that key), so the geometry stays
        out of the grouping aggregate on this path as well."""
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        if scenario_variant_id is None:
            proposal_segs = (
                "  SELECT f.source, f.proposal_id, f.route_id, "
                "         f.margin_eur_per_train_km, "
                "         LEAST(s.from_stop_id, s.to_stop_id) AS stop_a, "
                "         GREATEST(s.from_stop_id, s.to_stop_id) AS stop_b, "
                "         s.shape_id "
                "  FROM filtered f "
                "  JOIN proposals.trips t "
                "    ON f.source = 'proposal' "
                "   AND t.route_id = 'P' || f.proposal_id || '_V' || f.proposal_version || '_R1' "
                "  JOIN proposals.segments s ON s.trip_id = t.trip_id "
                "  WHERE s.shape_id IS NOT NULL "
            )
            rep_geometry = (
                "  LEFT JOIN proposals.shapes sh ON sh.shape_id = g.rep_shape_id "
                "  LEFT JOIN ontd.route_corridors rc "
                "         ON rc.route_id = g.rep_route_id "
                "        AND rc.stop_a = g.stop_a AND rc.stop_b = g.stop_b"
            )
            rep_geometry_expr = "COALESCE(sh.geometry, rc.geometry)::text"
        else:
            variant = int(scenario_variant_id)
            # shape_id doubles as "which proposal to fetch the corridor's
            # geometry from": the key itself is the corridor, so the
            # proposal id is the whole reference.
            proposal_segs = (
                "  SELECT f.source, f.proposal_id, f.route_id, "
                "         f.margin_eur_per_train_km, "
                "         split_part(seg.key, '__', 1) AS stop_a, "
                "         split_part(seg.key, '__', 2) AS stop_b, "
                "         f.proposal_id::text AS shape_id "
                "  FROM filtered f "
                "  JOIN proposals.proposal_scenario_summaries ss "
                "    ON f.source = 'proposal' AND ss.proposal_id = f.proposal_id "
                f"   AND ss.scenario_variant_id = {variant} AND ss.status = 'ok' "
                "  CROSS JOIN LATERAL jsonb_each(COALESCE(ss.segments, '{}'::jsonb)) "
                "    AS seg(key, geometry) "
            )
            rep_geometry = (
                "  LEFT JOIN proposals.proposal_scenario_summaries sr "
                "         ON sr.proposal_id = g.rep_shape_id::int "
                f"        AND sr.scenario_variant_id = {variant} "
                "  LEFT JOIN ontd.route_corridors rc "
                "         ON rc.route_id = g.rep_route_id "
                "        AND rc.stop_a = g.stop_a AND rc.stop_b = g.stop_b"
            )
            rep_geometry_expr = (
                "COALESCE(sr.segments -> (g.stop_a || '__' || g.stop_b), "
                "         rc.geometry)::text"
            )
        with self._cursor() as cur:
            cur.execute(
                f"WITH {self._gallery_ctes(filters, scenario_variant_id)}, filtered AS ("
                "  SELECT source, route_id, proposal_id, proposal_version, "
                "         margin_eur_per_train_km "
                f"  FROM gallery{where_clause}"
                "), segs AS ("
                f"{proposal_segs}"
                "  UNION ALL "
                # route_corridors already stores direction-collapsed pairs
                # (stop_a < stop_b, db/ontd/projection.py) — no
                # LEAST/GREATEST needed on this branch. It carries its
                # geometry inline rather than by shape_id, so the outer join
                # below reaches it on (route_id, stop_a, stop_b).
                "  SELECT f.source, NULL::int, f.route_id, NULL::numeric, "
                "         rc.stop_a, rc.stop_b, NULL::text "
                "  FROM filtered f "
                "  JOIN ontd.route_corridors rc "
                "    ON f.source = 'existing' AND rc.route_id = f.route_id"
                "), grouped AS ("
                "  SELECT stop_a, stop_b, "
                "         count(DISTINCT proposal_id) AS proposal_count, "
                "         count(DISTINCT route_id) AS existing_count, "
                "         count(DISTINCT proposal_id) + count(DISTINCT route_id) "
                "           AS total_count, "
                "         avg(margin_eur_per_train_km) AS avg_margin_eur_per_train_km, "
                "         min(shape_id) FILTER (WHERE source = 'proposal') "
                "           AS rep_shape_id, "
                "         min(route_id) FILTER (WHERE source = 'existing') "
                "           AS rep_route_id "
                "  FROM segs GROUP BY stop_a, stop_b"
                "), rep AS ("
                "  SELECT g.*, "
                f"         ST_GeomFromGeoJSON({rep_geometry_expr}) AS geom "
                "  FROM grouped g "
                f"{rep_geometry}"
                ") "
                "SELECT stop_a, stop_b, proposal_count, existing_count, "
                "       total_count, avg_margin_eur_per_train_km, "
                # Measured on the UNSIMPLIFIED shape on purpose: a real routed
                # line that happens to run straight would collapse to two
                # points under ST_Simplify and be mislabelled a placeholder.
                "       ST_NPoints(geom) > 2 AS geometry_routed, "
                "       ST_AsGeoJSON(ST_Simplify(geom, %s)) AS geometry "
                "FROM rep",
                list(params) + [MAP_LINES_SIMPLIFY_TOLERANCE_DEG],
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def map_routes(
        self,
        filters: Optional[dict] = None,
        sort: Optional[list[dict]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        scenario_variant_id: Optional[int] = None,
    ) -> list[dict]:
        """`map_routes` section: one already-simplified polyline per
        LISTED row — the same filter, sort and window as
        list_summaries(), so the two sections always describe the same
        rows. That pagination is the point, and it is the one deliberate
        exception to "map sections cover the whole filtered set": this
        section exists to draw the route belonging to a card the user
        can actually see, so its cost is capped at the page size no
        matter how many proposals exist.

        Reads proposal_summaries.geom_simplified / route_summaries.
        geom_simplified, which both projections already maintain (see
        projection.py's _geom_simplified) and which the gallery union
        already carries — until now only as a bbox filter target, never
        returned. NULL for an ONTD route whose routing failed; the row
        is still emitted, with a null geometry, rather than silently
        dropped. scenario_variant_id: the §5.4a row's geometry — NULL
        on an error row, emitted the same way."""
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        sql = (
            f"WITH {self._gallery_ctes(filters, scenario_variant_id)} "
            "SELECT source, proposal_id, proposal_version, route_id, "
            "       geometry_routed, "
            "       ST_AsGeoJSON(geom_simplified) AS geometry "
            f"FROM gallery{where_clause} "
            f"ORDER BY {build_order_by(sort)}"
        )
        page_params = list(params)
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            page_params += [limit, offset]
        with self._cursor() as cur:
            cur.execute(sql, page_params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def map_stop_counts(
        self, filters: Optional[dict] = None, scenario_variant_id: Optional[int] = None
    ) -> list[dict]:
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
                f"WITH {self._gallery_ctes(filters, scenario_variant_id)} "
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
        return [dict(row) for row in rows]

    def map_country_counts(
        self, filters: Optional[dict] = None, scenario_variant_id: Optional[int] = None
    ) -> list[dict]:
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
                f"WITH {self._gallery_ctes(filters, scenario_variant_id)} "
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
        return [dict(row) for row in rows]

    # =========================================================================
    # Statistics — GET /api/proposals/stats (§7.7)
    # =========================================================================
    #
    # Four read-only queries over the same gallery CTE stack the list and
    # map sections use, so every statistic reflects exactly the rows the
    # gallery would show for the same filter. None of them paginate: an
    # aggregate over a page would be a statistic about a page.

    # The current base scenario's pinned stop snapshot — reference
    # stations and the relation universe are only meaningful against the
    # catalog they were built from (§3.1: resolved, never inferred).
    _BASE_STOP_INFRA_VERSION = (
        "(SELECT stop_infrastructures_version FROM scenario.scenarios "
        " WHERE is_current_base)"
    )

    def stats_kpis(self, filters: Optional[dict] = None) -> list[dict]:
        """count/avg/min/max (and sum, for extensive columns) of every
        numeric summary column, per source AND across both.

        One pass: GROUPING SETS ((source), ()) returns the per-source
        rows and the combined row together, with source NULL marking the
        combined one — two round trips for the same numbers would only
        risk them disagreeing under concurrent publishes.
        """
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        with self._cursor() as cur:
            cur.execute(
                f"WITH {self._gallery_ctes(filters)} "
                f"SELECT source, count(*) AS n_rows, {build_aggregate_select()} "
                f"FROM gallery{where_clause} "
                "GROUP BY GROUPING SETS ((source), ())",
                params,
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def stats_reach(self, filters: Optional[dict] = None) -> list[dict]:
        """Distinct stops and countries touched, per source and combined —
        the network-reach counterpart to the KPI aggregates, where a plain
        sum of n_stops would double-count every shared station.

        The two lateral unnests multiply rows against each other, which
        count(DISTINCT ...) is indifferent to; LEFT JOIN keeps a row whose
        array is empty from disappearing from the row count.
        """
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        with self._cursor() as cur:
            cur.execute(
                f"WITH {self._gallery_ctes(filters)}, "
                "filtered AS ("
                f"  SELECT source, stop_ids, countries FROM gallery{where_clause}"
                ") "
                "SELECT f.source, "
                "       count(DISTINCT s.stop_id) AS n_distinct_stops, "
                "       count(DISTINCT c.country) AS n_distinct_countries "
                "FROM filtered f "
                "LEFT JOIN LATERAL unnest(f.stop_ids) AS s(stop_id) ON TRUE "
                "LEFT JOIN LATERAL unnest(f.countries) AS c(country) ON TRUE "
                "GROUP BY GROUPING SETS ((f.source), ())",
                params,
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def stats_country_counts(self, filters: Optional[dict] = None) -> list[dict]:
        """Rows per country, ranked — the same "a row counts once per
        country it touches" grain as map_country_counts(), without the
        border geometry and with the countries nobody touched included.

        The universe is the rail-network catalog (country_geom NOT NULL —
        countries no route can transit are excluded by definition) unioned
        with whatever the filtered set actually mentions, so an ONTD
        country outside the catalog still ranks while a catalog country
        with no proposals shows up at zero. That zero is the whole point
        of the flop list: "nobody has proposed anything here" is the
        answer, not a missing row. UNK (the open-water sentinel, §5.4) is
        not a country and never joins the universe.
        """
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        with self._cursor() as cur:
            cur.execute(
                f"WITH {self._gallery_ctes(filters)}, "
                "observed AS ("
                "  SELECT source, unnest(countries) AS country "
                f"  FROM gallery{where_clause}"
                "), universe AS ("
                "  SELECT country_code AS country FROM input_params.countries "
                "  WHERE country_geom IS NOT NULL "
                "  UNION "
                "  SELECT DISTINCT country FROM observed WHERE country <> 'UNK'"
                ") "
                "SELECT u.country, "
                "       count(o.source) FILTER (WHERE o.source = 'proposal') "
                "         AS n_proposals, "
                "       count(o.source) FILTER (WHERE o.source = 'existing') "
                "         AS n_existing, "
                "       count(o.source) AS n "
                "FROM universe u LEFT JOIN observed o ON o.country = u.country "
                "GROUP BY u.country "
                "ORDER BY n_proposals DESC, n DESC, u.country",
                params,
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def stats_relation_counts(
        self, filters: Optional[dict] = None, max_relation_km: float = 1600.0
    ) -> list[dict]:
        """Rows per country-to-country RELATION, ranked, over the routable
        candidate set within max_relation_km.

        Driven by input_params.country_relations rather than by what the
        rows happen to contain: a relation nobody serves has to appear
        (at zero) for the flop list to mean anything, and a pair the
        router could not connect must not appear at all. The join is on
        the stored "AA__BB" key, which both summary projections write in
        the same sorted form.
        """
        where_sql, params = build_where(filters or {})
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        with self._cursor() as cur:
            cur.execute(
                f"WITH {self._gallery_ctes(filters)}, "
                "observed AS ("
                "  SELECT source, unnest(country_relations) AS relation "
                f"  FROM gallery{where_clause}"
                ") "
                "SELECT r.country_a, r.country_b, r.rail_km, r.rail_time_h, "
                "       count(o.source) FILTER (WHERE o.source = 'proposal') "
                "         AS n_proposals, "
                "       count(o.source) FILTER (WHERE o.source = 'existing') "
                "         AS n_existing, "
                "       count(o.source) AS n "
                "FROM input_params.country_relations r "
                "LEFT JOIN observed o "
                "  ON o.relation = r.country_a || '__' || r.country_b "
                f"WHERE r.stop_infra_version = {self._BASE_STOP_INFRA_VERSION} "
                "  AND r.rail_km IS NOT NULL AND r.rail_km <= %s "
                "GROUP BY r.country_a, r.country_b, r.rail_km, r.rail_time_h "
                "ORDER BY n_proposals DESC, n DESC, r.rail_km, "
                "         r.country_a, r.country_b",
                params + [max_relation_km],
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def stats_relation_universe(self, max_relation_km: float = 1600.0) -> dict:
        """What the relation candidate set is made of, and which station
        each country was measured from — filter-independent, so it
        describes the same universe every ranking was drawn from.

        Returned alongside the rankings so nothing disappears without a
        number attached: pairs too far apart and pairs with no rail path
        are counted rather than silently absent, and the reference
        stations make every distance auditable (§7.7's R2 basis — the
        catalog stop closest to that country's stop centroid).
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT count(*) FILTER (WHERE rail_km IS NOT NULL "
                "                          AND rail_km <= %s) AS n_pairs, "
                "       count(*) FILTER (WHERE rail_km IS NOT NULL "
                "                          AND rail_km > %s) "
                "         AS excluded_over_threshold, "
                "       count(*) FILTER (WHERE rail_km IS NULL) "
                "         AS excluded_unroutable, "
                "       max(built_at) AS built_at "
                "FROM input_params.country_relations "
                f"WHERE stop_infra_version = {self._BASE_STOP_INFRA_VERSION}",
                (max_relation_km, max_relation_km),
            )
            counts = dict(cur.fetchone())

            cur.execute(
                "WITH refs AS ("
                "  SELECT country_a AS country, ref_stop_a AS stop_id "
                "  FROM input_params.country_relations "
                f"  WHERE stop_infra_version = {self._BASE_STOP_INFRA_VERSION} "
                "  UNION "
                "  SELECT country_b, ref_stop_b "
                "  FROM input_params.country_relations "
                f"  WHERE stop_infra_version = {self._BASE_STOP_INFRA_VERSION}"
                ") "
                "SELECT refs.country, refs.stop_id, si.stop_name, "
                "       si.stop_lat, si.stop_lon "
                "FROM refs JOIN input_params.stop_infrastructures si "
                "  ON si.stop_id = refs.stop_id "
                f" AND si.stop_infra_version = {self._BASE_STOP_INFRA_VERSION} "
                "ORDER BY refs.country"
            )
            stations = [dict(row) for row in cur.fetchall()]
        return {**counts, "reference_stations": stations}
