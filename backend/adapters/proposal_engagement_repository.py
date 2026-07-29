"""
proposal_engagement_repository.py
==================================
Write-path database adapter for proposal likes and comments — mirrors
FeedbackRepository (adapters/feedback_repository.py): its own connection
to the same database, kept separate from ProposalRepository (which owns
the heavier route/GTFS write path) and from DBDataLoader (read-only). See
db/dev/sql/create_proposal_schema.sql for the proposals.likes /
proposals.comments tables this module writes to.

proposal_id is a soft reference to proposals.proposals (composite-PK'd on
(proposal_id, proposal_version), so it can't be an FK target — same
convention as stop_times.stop_id / trips.composition_type_id). Every
write here first resolves the proposal's current version via
_current_version(), which both confirms the proposal_id exists and
supplies the proposal_version stamped onto the row. That lookup is
duplicated from ProposalRepository.get_current() rather than shared — the
two repositories deliberately hold independent connections (same
rationale as FeedbackRepository.get_user()) — but kept intentionally
cheap: no route_body/evaluation_body in the SELECT.
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
            "SELECT proposal_version FROM proposals.proposals "
            "WHERE proposal_id = %s AND is_current",
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
    # Likes
    # ------------------------------------------------------------------

    def get_likes(self, proposal_id: int, user_id: Optional[int]) -> dict:
        """{count, liked_by_me}. liked_by_me is False for an anonymous
        caller (user_id=None) without a query."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT count(*) AS count FROM proposals.likes WHERE proposal_id = %s",
                (proposal_id,),
            )
            count = cur.fetchone()["count"]
            liked_by_me = False
            if user_id is not None:
                cur.execute(
                    "SELECT 1 FROM proposals.likes "
                    "WHERE proposal_id = %s AND user_id = %s",
                    (proposal_id, user_id),
                )
                liked_by_me = cur.fetchone() is not None
        self._conn.rollback()
        return {"count": count, "liked_by_me": liked_by_me}

    def add_like(self, proposal_id: int, user_id: int) -> Optional[dict]:
        """Idempotent like: inserts if absent, no-ops if the user already
        liked this proposal. Returns the fresh {count, liked_by_me: True}
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
                cur.execute(
                    "SELECT count(*) AS count FROM proposals.likes WHERE proposal_id = %s",
                    (proposal_id,),
                )
                count = cur.fetchone()["count"]
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        logger.info("like added: proposal_id=%s user_id=%s", proposal_id, user_id)
        return {"count": count, "liked_by_me": True}

    def remove_like(self, proposal_id: int, user_id: int) -> dict:
        """Idempotent unlike. Returns the fresh {count, liked_by_me: False}
        summary regardless of whether a like existed to remove."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "DELETE FROM proposals.likes "
                    "WHERE proposal_id = %s AND user_id = %s",
                    (proposal_id, user_id),
                )
                cur.execute(
                    "SELECT count(*) AS count FROM proposals.likes WHERE proposal_id = %s",
                    (proposal_id,),
                )
                count = cur.fetchone()["count"]
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        logger.info("like removed: proposal_id=%s user_id=%s", proposal_id, user_id)
        return {"count": count, "liked_by_me": False}

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def list_comments(self, proposal_id: int) -> list[dict]:
        """Flat thread, oldest first. Soft-deleted rows are included (with
        body already cleared in storage) so the list stays chronologically
        intact — see create_proposal_schema.sql."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT c.comment_id, c.proposal_id, c.proposal_version, "
                "       c.user_id, u.display_name AS user_name, "
                "       c.body, c.is_deleted, c.created_at, c.updated_at "
                "FROM proposals.comments c "
                "LEFT JOIN admin.users u USING (user_id) "
                "WHERE c.proposal_id = %s "
                "ORDER BY c.created_at ASC",
                (proposal_id,),
            )
            rows = cur.fetchall()
        self._conn.rollback()
        return [dict(row) for row in rows]

    def add_comment(self, proposal_id: int, user_id: int, body: str) -> Optional[dict]:
        """Insert one comment. Returns the full row (see list_comments'
        shape), or None if proposal_id doesn't exist."""
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
                    "RETURNING comment_id, proposal_id, proposal_version, user_id, "
                    "          body, is_deleted, created_at, updated_at",
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
        """One comment row, for ownership checks before edit/delete."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT comment_id, proposal_id, proposal_version, user_id, "
                "       body, is_deleted, created_at, updated_at "
                "FROM proposals.comments WHERE comment_id = %s",
                (comment_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return dict(row) if row else None

    def edit_comment(self, comment_id: int, body: str) -> Optional[dict]:
        """Update a comment's text. Caller (api/proposal_engagement.py)
        has already checked ownership and that the comment isn't deleted."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE proposals.comments SET body = %s, updated_at = now() "
                    "WHERE comment_id = %s "
                    "RETURNING comment_id, proposal_id, proposal_version, user_id, "
                    "          body, is_deleted, created_at, updated_at",
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
        """Soft-delete: clears body server-side and sets is_deleted — see
        create_proposal_schema.sql for why this is a flag, not a DELETE.
        Returns False if comment_id doesn't exist."""
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
