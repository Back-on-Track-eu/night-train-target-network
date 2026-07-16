"""
auth_repository.py
==================
Write-path database adapter for authentication — mirrors
ProposalRepository / FeedbackRepository (own connection to the same
database, so DBDataLoader stays strictly read-only). See
db/dev/sql/create_admin_schema.sql for admin.users / admin.auth_tokens.

Transaction shape: each public method is one commit. The request-code
flow spans two methods (ensure user exists → issue_otp) and tolerates a
failure between them — a user row without a pending OTP is recoverable
by simply requesting a new code, and issue_otp() invalidates old codes
and stores the new one atomically.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


class AuthRepository:
    """Persists users and OTP tokens for the local auth plane, and maps
    Keycloak identities to local rows for the OIDC plane."""

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
    # Reads
    # ------------------------------------------------------------------

    def get_user_by_email(self, email: str) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT user_id, email, display_name, is_verified "
                "FROM admin.users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
        self._conn.rollback()  # release the read-only transaction
        return dict(row) if row else None

    def display_name_taken(self, display_name: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM admin.users WHERE LOWER(display_name) = LOWER(%s)",
                (display_name,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return row is not None

    # ------------------------------------------------------------------
    # Writes — users
    # ------------------------------------------------------------------

    def create_user(
        self, email: Optional[str], display_name: str, is_verified: bool = False
    ) -> dict:
        """Insert one admin.users row. Returns {user_id, email,
        display_name, is_verified}."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "INSERT INTO admin.users (email, display_name, is_verified) "
                    "VALUES (%s, %s, %s) "
                    "RETURNING user_id, email, display_name, is_verified",
                    (email, display_name, is_verified),
                )
                row = cur.fetchone()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        logger.info(
            "user created: user_id=%s display_name=%s verified=%s",
            row["user_id"],
            display_name,
            is_verified,
        )
        return dict(row)

    def get_or_create_sso_user(self, email: str, preferred_name: str) -> dict:
        """
        Map a verified Keycloak identity (OIDC plane) to a local
        admin.users row, creating one on first sign-in. Email is the join
        key — Keycloak owns operator identity; this row only exists so
        proposals/feedback foreign keys work.

        The preferred display name comes from the token; when it's taken
        or invalid locally, fall back to a suffixed variant rather than
        failing the sign-in.
        """
        existing = self.get_user_by_email(email)
        if existing:
            return existing

        from api.auth_utils import AuthError, validate_display_name

        candidate = preferred_name
        try:
            validate_display_name(candidate)
        except AuthError:
            candidate = f"bot-{abs(hash(email)) % 100000}"

        name = candidate
        suffix = 1
        while self.display_name_taken(name):
            suffix += 1
            name = f"{candidate}-{suffix}"

        return self.create_user(email=email, display_name=name, is_verified=True)

    # ------------------------------------------------------------------
    # Writes — OTP tokens
    # ------------------------------------------------------------------

    def issue_otp(self, user_id: int, code_hash: str, expires_at) -> None:
        """Invalidate any unused OTPs for this user and store the new one —
        atomically, so there is never more than one live code per user."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE admin.auth_tokens SET used = TRUE "
                    "WHERE user_id = %s AND NOT used",
                    (user_id,),
                )
                cur.execute(
                    "INSERT INTO admin.auth_tokens (user_id, code_hash, expires_at) "
                    "VALUES (%s, %s, %s)",
                    (user_id, code_hash, expires_at),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def latest_valid_otp(self, user_id: int) -> Optional[dict]:
        """The most recent unused, unexpired token row for this user —
        {token_id, code_hash} — or None."""
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT token_id, code_hash
                FROM   admin.auth_tokens
                WHERE  user_id    = %s
                  AND  NOT used
                  AND  expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return dict(row) if row else None

    def consume_otp(self, token_id: int, user_id: int) -> None:
        """Mark the token used and the user verified — one transaction,
        so a verified user can never re-play the same code."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE admin.auth_tokens SET used = TRUE WHERE token_id = %s",
                    (token_id,),
                )
                cur.execute(
                    "UPDATE admin.users SET is_verified = TRUE WHERE user_id = %s",
                    (user_id,),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
