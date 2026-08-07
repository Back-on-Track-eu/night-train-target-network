"""
engagement_repository.py
========================
Write-path database adapter for proposal likes and comments, plus the
read path for the merged engagement timeline (WP11) — mirrors
FeedbackRepository (adapters/feedback_repository.py): its own connection
to the same database, kept separate from ProposalRepository
(repository.py, which owns the heavier route/GTFS write path) and from
DBDataLoader (read-only). See db/dev/sql/create_proposal_schema.sql for
the proposals.likes / proposals.comments / proposals.update_log tables
this module touches.

proposal_id is a soft reference to proposals.proposals (composite-PK'd on
(proposal_id, proposal_version), so it can't be an FK target — same
convention as stop_times.stop_id / trips.composition_type_id). Every
write here first resolves the proposal's current version via
_current_version(), which both confirms the proposal_id exists and
supplies the proposal_version stamped onto the row. That lookup is
duplicated from ProposalRepository.get_container()/.owner() rather than
shared — the two repositories deliberately hold independent connections
(same rationale as FeedbackRepository.get_user()) — but kept
intentionally cheap: proposal_version only, no route/evaluation data.

update_log is WRITTEN by ProposalRepository (inside the publish/refresh
transaction, where it belongs) and only READ here, as the third source of
the timeline. The split follows the same independent-connection rule as
everything else in this module: reading a table another repository owns
is ordinary, sharing its connection is not.

Timeline semantics (§7.5, locked decision 28): the timeline is a
PROJECTION OF CURRENT STATE merged with the append-only update_log, not
an audit trail. A withdrawn like and a deleted comment leave no trace,
and an edited comment appears at its edit time rather than its post time.
Only update_log rows are genuinely immutable history.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


class ProposalEngagementRepository:
    """Persists proposal likes and comments — thin connection wrapper
    mirroring FeedbackRepository's construction (same env vars, one
    connection per process/worker)."""

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
    # Shared: resolve + validate proposal_id
    # ------------------------------------------------------------------

    def _current_version(self, cur, proposal_id: int) -> Optional[int]:
        """proposal_version of proposal_id's current row, or None if
        proposal_id doesn't exist. Used both to validate the soft
        reference and to stamp the version context on writes."""
        cur.execute(
            # WP5 (proposals redesign cutover): proposals.proposals is now
            # one row per proposal, always current — is_current dropped.
            "SELECT proposal_version FROM proposals.proposals WHERE proposal_id = %s",
            (proposal_id,),
        )
        row = cur.fetchone()
        return row["proposal_version"] if row else None

    def proposal_exists(self, proposal_id: int) -> bool:
        """Read-only existence check, for endpoints that validate before
        doing anything else."""
        with self._cursor() as cur:
            version = self._current_version(cur, proposal_id)
        self._conn.rollback()
        return version is not None

    # ------------------------------------------------------------------
    # Aggregate read — GET /api/proposal/<id>/engagements
    # ------------------------------------------------------------------

    def get_engagement(
        self, proposal_id: int, user_id: Optional[int]
    ) -> Optional[dict]:
        """Everything the engagements endpoint returns: like summary,
        live comment thread, and the merged timeline. One cursor, one
        transaction, so the three sections can't disagree with each
        other. Returns None if proposal_id doesn't exist."""
        with self._cursor() as cur:
            if self._current_version(cur, proposal_id) is None:
                self._conn.rollback()
                return None
            engagement = {
                "likes": self._likes_summary(cur, proposal_id, user_id),
                "comments": self._live_comments(cur, proposal_id),
                "timeline": self._timeline(cur, proposal_id),
            }
        self._conn.rollback()
        return engagement

    # ------------------------------------------------------------------
    # Likes
    # ------------------------------------------------------------------

    def _likes_summary(self, cur, proposal_id: int, user_id: Optional[int]) -> dict:
        """{count, liked_by_me} on an open cursor. liked_by_me is False
        for an anonymous caller (user_id=None) without a second query."""
        cur.execute(
            "SELECT count(*) AS count FROM proposals.likes WHERE proposal_id = %s",
            (proposal_id,),
        )
        count = cur.fetchone()["count"]
        liked_by_me = False
        if user_id is not None:
            cur.execute(
                "SELECT 1 FROM proposals.likes WHERE proposal_id = %s AND user_id = %s",
                (proposal_id, user_id),
            )
            liked_by_me = cur.fetchone() is not None
        return {"count": count, "liked_by_me": liked_by_me}

    def add_like(self, proposal_id: int, user_id: int) -> Optional[dict]:
        """Idempotent like: inserts if absent, no-ops if the user already
        liked this proposal. Returns the fresh {count, liked_by_me}
        summary, or None if proposal_id doesn't exist."""
        try:
            with self._cursor() as cur:
                version = self._current_version(cur, proposal_id)
                if version is None:
                    self._conn.rollback()
                    return None
                cur.execute(
                    "INSERT INTO proposals.likes (proposal_id, proposal_version, user_id) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (proposal_id, user_id) DO NOTHING",
                    (proposal_id, version, user_id),
                )
                summary = self._likes_summary(cur, proposal_id, user_id)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        logger.info("like added: proposal_id=%s user_id=%s", proposal_id, user_id)
        return summary

    def remove_like(self, proposal_id: int, user_id: int) -> dict:
        """Idempotent unlike — a hard DELETE, so the like leaves the
        timeline with it (locked decision 28). Returns the fresh summary
        regardless of whether a like existed to remove."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "DELETE FROM proposals.likes "
                    "WHERE proposal_id = %s AND user_id = %s",
                    (proposal_id, user_id),
                )
                summary = self._likes_summary(cur, proposal_id, user_id)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        logger.info("like removed: proposal_id=%s user_id=%s", proposal_id, user_id)
        return summary

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    _COMMENT_COLUMNS = (
        "comment_id, proposal_id, proposal_version, user_id, "
        "body, created_at, updated_at"
    )

    def _live_comments(self, cur, proposal_id: int) -> dict:
        """{count, items} — the flat thread, oldest first. Soft-deleted
        rows are excluded everywhere (WP11): the thread is non-threaded,
        so a tombstone holds no position open, and leaving them out keeps
        the thread and the timeline telling the same story."""
        cur.execute(
            "SELECT c.comment_id, c.proposal_id, c.proposal_version, c.user_id, "
            "       c.body, c.created_at, c.updated_at, "
            "       u.display_name AS user_name "
            "FROM proposals.comments c "
            "LEFT JOIN admin.users u USING (user_id) "
            "WHERE c.proposal_id = %s AND NOT c.is_deleted "
            "ORDER BY c.created_at ASC",
            (proposal_id,),
        )
        items = [dict(row) for row in cur.fetchall()]
        return {"count": len(items), "items": items}

    def add_comment(self, proposal_id: int, user_id: int, body: str) -> Optional[dict]:
        """Insert one comment. Returns the full row, or None if
        proposal_id doesn't exist."""
        try:
            with self._cursor() as cur:
                version = self._current_version(cur, proposal_id)
                if version is None:
                    self._conn.rollback()
                    return None
                cur.execute(
                    "INSERT INTO proposals.comments "
                    "(proposal_id, proposal_version, user_id, body) "
                    "VALUES (%s, %s, %s, %s) "
                    f"RETURNING {self._COMMENT_COLUMNS}",
                    (proposal_id, version, user_id, body),
                )
                row = dict(cur.fetchone())
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        row["user_name"] = self._display_name(user_id)
        logger.info(
            "comment added: proposal_id=%s comment_id=%s user_id=%s",
            proposal_id,
            row["comment_id"],
            user_id,
        )
        return row

    def get_comment(self, comment_id: int) -> Optional[dict]:
        """One comment row, for ownership checks before edit/delete.
        Carries is_deleted, which no API shape does: the flag is the
        internal tombstone the 404-on-deleted rule reads."""
        with self._cursor() as cur:
            cur.execute(
                f"SELECT {self._COMMENT_COLUMNS}, is_deleted "
                "FROM proposals.comments WHERE comment_id = %s",
                (comment_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return dict(row) if row else None

    def edit_comment(self, comment_id: int, body: str) -> Optional[dict]:
        """Update a comment's text. Caller (api/proposal_engagement.py)
        has already checked ownership and that the comment isn't deleted.
        The bumped updated_at is also where the comment's timeline event
        moves to (§7.5)."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE proposals.comments SET body = %s, updated_at = now() "
                    "WHERE comment_id = %s "
                    f"RETURNING {self._COMMENT_COLUMNS}",
                    (body, comment_id),
                )
                row = cur.fetchone()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        if row is None:
            return None
        row = dict(row)
        row["user_name"] = self._display_name(row["user_id"])
        return row

    def delete_comment(self, comment_id: int) -> bool:
        """Soft-delete: clears body server-side and sets is_deleted. The
        row is kept (stable comment_id, no hard delete under a live
        transaction) but is invisible from here on — neither the thread
        nor the timeline returns it. Returns False if comment_id doesn't
        exist."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE proposals.comments "
                    "SET is_deleted = TRUE, body = '', updated_at = now() "
                    "WHERE comment_id = %s "
                    "RETURNING comment_id",
                    (comment_id,),
                )
                deleted = cur.fetchone() is not None
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        if deleted:
            logger.info("comment soft-deleted: comment_id=%s", comment_id)
        return deleted

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    # One UNION ALL over the three event sources, merged and ordered by
    # the database rather than in Python — the alternative is three round
    # trips and a sort here, for the same result.
    #
    # `source` is carried because it is the only thing that separates the
    # two meanings of a NULL user_id: on an update_log row it means the
    # system acted (refresh), on a comment it means the author's account
    # was deleted. It doubles as the ordering tiebreak, which matters
    # only for rows sharing a timestamp — the branch_* pair a publish
    # writes in its own transaction, where ref_id (log_id, insertion
    # order) then puts them behind the publish event itself.
    _TIMELINE_SQL = (
        "SELECT ul.event, ul.created_at AS occurred_at, ul.proposal_version, "
        "       ul.user_id, u.display_name AS user_name, ul.detail, "
        "       'update_log' AS source, ul.log_id AS ref_id "
        "FROM proposals.update_log ul "
        "LEFT JOIN admin.users u USING (user_id) "
        "WHERE ul.proposal_id = %s "
        "UNION ALL "
        "SELECT 'liked', l.created_at, l.proposal_version, "
        "       l.user_id, u.display_name, NULL::jsonb, "
        "       'like', l.like_id "
        "FROM proposals.likes l "
        "LEFT JOIN admin.users u USING (user_id) "
        "WHERE l.proposal_id = %s "
        "UNION ALL "
        # updated_at, not created_at: an edited comment moves to its edit
        # time (§7.5). They are equal until the first edit, so an
        # untouched comment still sits where it was written.
        "SELECT 'commented', c.updated_at, c.proposal_version, "
        "       c.user_id, u.display_name, "
        "       jsonb_build_object('comment_id', c.comment_id, "
        "                          'edited', c.updated_at > c.created_at), "
        "       'comment', c.comment_id "
        "FROM proposals.comments c "
        "LEFT JOIN admin.users u USING (user_id) "
        "WHERE c.proposal_id = %s AND NOT c.is_deleted "
        "ORDER BY occurred_at ASC, source ASC, ref_id ASC"
    )

    def _timeline(self, cur, proposal_id: int) -> list[dict]:
        """The merged event list, oldest first."""
        cur.execute(self._TIMELINE_SQL, (proposal_id,) * 3)
        return [dict(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _display_name(self, user_id: Optional[int]) -> Optional[str]:
        if user_id is None:
            return None
        with self._cursor() as cur:
            cur.execute(
                "SELECT display_name FROM admin.users WHERE user_id = %s", (user_id,)
            )
            row = cur.fetchone()
        self._conn.rollback()
        return row["display_name"] if row else None
