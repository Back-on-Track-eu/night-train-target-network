"""
feedback_repository.py
=======================
Write-path database adapter for feedback submissions — mirrors
ProposalRepository (adapters/proposal/repository.py): borrows a
connection from the shared DBPool per call, so DBDataLoader stays
strictly read-only and no adapter holds a connection between calls. See
db/dev/sql/create_admin_schema.sql for the admin.feedback schema this
module writes to.

A submission is one insert into admin.feedback. Whether the mail
notification to the working group succeeded is recorded separately via
mark_notified() — insert() always happens first and always commits, so a
mail failure (api/feedback.py's mailer.send_feedback_email()) can never
lose a stored feedback row.
"""

from __future__ import annotations

import logging
from typing import Optional

from psycopg2.extras import RealDictCursor

from adapters.db_pool import DBPool, default_pool

logger = logging.getLogger(__name__)


class FeedbackRepository:
    """Persists feedback submissions — one borrowed DBPool connection per
    call, mirroring ProposalRepository."""

    def __init__(self, pool: DBPool | None = None) -> None:
        self._pool = pool or default_pool()

    def _cursor(self):
        """A cursor on a freshly borrowed connection — single-query reads.
        The transaction is released when the block ends. Writes borrow a
        connection explicitly and commit inside the block."""
        return self._pool.cursor()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_user(self, user_id: int) -> Optional[dict]:
        """admin.users row for user_id, or None — the one shared user
        read the API layer needs (api/feedback.py). Kept on this
        repository (not a cross-repository dependency) because every
        repository deliberately holds its own connection (see module
        docstring) and the query is a single indexed lookup."""
        with self._cursor() as cur:
            cur.execute(
                # display_name aliased to user_name: the API response field
                # is user_name across proposals/feedback; renaming that
                # contract is a separate, frontend-coordinated change.
                "SELECT user_id, display_name AS user_name, email "
                "FROM admin.users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def insert(
        self,
        user_id: Optional[int],
        email: Optional[str],
        subject: str,
        message: str,
        category: str,
        sub_category: str,
    ) -> dict:
        """Insert one feedback row. Exactly one of user_id/email identifies
        the author — enforced by validate_feedback_body() before this is
        called, and by feedback_identity_present at the DB level either
        way. Returns {feedback_id, created_at}."""
        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO admin.feedback "
                    "(user_id, email, category, sub_category, subject, message) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "RETURNING feedback_id, created_at",
                    (user_id, email, category, sub_category, subject, message),
                )
                row = cur.fetchone()
            conn.commit()

        logger.info(
            "feedback stored: feedback_id=%s user_id=%s category=%s",
            row["feedback_id"],
            user_id,
            category,
        )
        return {"feedback_id": row["feedback_id"], "created_at": row["created_at"]}

    def mark_notified(self, feedback_id: int) -> Optional[object]:
        """Set notified_at = now() after a successful mail send. Returns
        the new notified_at timestamp, or None if feedback_id doesn't
        exist (should not happen — called immediately after insert() with
        the id it just returned)."""
        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "UPDATE admin.feedback SET notified_at = now() "
                    "WHERE feedback_id = %s "
                    "RETURNING notified_at",
                    (feedback_id,),
                )
                row = cur.fetchone()
            conn.commit()
        return row["notified_at"] if row else None
