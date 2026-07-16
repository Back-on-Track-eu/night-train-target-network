"""
feedback_repository.py
=======================
Write-path database adapter for feedback submissions — mirrors
ProposalRepository (adapters/proposal_repository.py): its own connection
to the same database, so DBDataLoader stays strictly read-only. See
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
import os
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


class FeedbackRepository:
    """Persists feedback submissions — thin connection wrapper mirroring
    ProposalRepository's construction (same env vars, one connection per
    process/worker)."""

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
        """admin.users row for user_id, or None. Duplicated from
        ProposalRepository.get_user() rather than shared — the two
        repositories deliberately hold independent connections (see module
        docstring), and this query is a single indexed lookup, not worth
        threading a cross-repository dependency for."""
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
        self._conn.rollback()  # release the read-only transaction
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
        try:
            with self._cursor() as cur:
                cur.execute(
                    "INSERT INTO admin.feedback "
                    "(user_id, email, category, sub_category, subject, message) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "RETURNING feedback_id, created_at",
                    (user_id, email, category, sub_category, subject, message),
                )
                row = cur.fetchone()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

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
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE admin.feedback SET notified_at = now() "
                    "WHERE feedback_id = %s "
                    "RETURNING notified_at",
                    (feedback_id,),
                )
                row = cur.fetchone()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return row["notified_at"] if row else None
