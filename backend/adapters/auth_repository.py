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
from contextlib import contextmanager
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

    @contextmanager
    def _cursor(self):
        """One cursor on this repository's single connection, rolled back
        if the block raises.

        psycopg2's own cursor context manager closes the cursor but leaves
        the transaction open, so a single failed statement puts the
        connection into "current transaction is aborted" and every later
        call on this worker fails until the process restarts. That was
        survivable while auth queries were rare; get_user() now runs on
        every authenticated request, so one transient failure would take
        down publishing, liking and commenting alongside it. Commits stay
        the caller's business — the write paths commit after their block.
        """
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cursor
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cursor.close()

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

    def get_user(self, user_id: int) -> Optional[dict]:
        """One admin.users row by id, or None if the account does not
        exist — the auth middleware's existence check for every local-plane
        bearer token.

        A JWT outlives the row it names: a reseed recreates admin.users
        from scratch while browsers keep their tokens, and a manually
        deleted account leaves the same gap. Without this lookup the API
        accepts the token, trusts its `sub`, and only discovers the
        problem when a write hits proposals.proposals' foreign key — a
        500 with a Postgres constraint message where the honest answer is
        401 "sign in again". One indexed PK lookup per authenticated
        request buys that.
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT user_id, email, display_name, is_verified, "
                "       merged_into_user_id "
                "FROM admin.users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return dict(row) if row else None

    def merged_target(self, user_id: int) -> Optional[int]:
        """merged_into_user_id of a user, or None.

        Superseded on the request path by get_user(), which returns the
        same column alongside the existence check the middleware now
        needs — one lookup where this was the second. Kept as the
        narrow, single-purpose query for callers that only want the
        merge target."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT merged_into_user_id FROM admin.users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return row["merged_into_user_id"] if row else None

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

    def complete_registration(
        self, token_id: int, user_id: int, display_name: str
    ) -> None:
        """First-ever verification of a pending account: set the chosen
        display name, mark the user verified, and mark the code used — one
        transaction, so the OTP is never consumed without the name landing
        (and vice versa). Distinct from consume_otp() because a brand-new
        account picks its name here, AFTER the code is confirmed, replacing
        the placeholder request-code created."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE admin.users SET display_name = %s, is_verified = TRUE "
                    "WHERE user_id = %s",
                    (display_name, user_id),
                )
                cur.execute(
                    "UPDATE admin.auth_tokens SET used = TRUE WHERE token_id = %s",
                    (token_id,),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Writes — guest merge
    # ------------------------------------------------------------------

    def merge_guest_into(self, guest_user_id: int, user_id: int) -> Optional[dict]:
        """Reassign everything a guest owns to a registered account and mark
        the guest row merged — one transaction, because a half-merged guest
        (proposals moved, marker missing) would allow a second, conflicting
        merge. This is the only adapter writing across schemas (proposals +
        admin): atomicity of the merge outranks the one-schema-per-adapter
        convention here.

        Likes need one extra step feedback/proposals/comments don't:
        proposals.likes carries UNIQUE(proposal_id, user_id), so if the
        guest and the target account both already liked the same proposal,
        a straight reassignment would collide. The guest's copy is dropped
        in that case (the target's own like already counts) before the
        rest are reassigned — the merge never fails on this, it just
        doesn't double-count.

        Returns {"proposals_claimed": n, "feedback_claimed": m,
        "likes_claimed": k, "comments_claimed": j}, or None when no merge
        happened: unknown user, not a guest (has an email), already merged
        into this same account (idempotent no-op), or already merged into a
        different one (logged, refused).
        """
        try:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT email, merged_into_user_id FROM admin.users "
                    "WHERE user_id = %s FOR UPDATE",
                    (guest_user_id,),
                )
                row = cur.fetchone()
                if row is None or row["email"] is not None:
                    self._conn.rollback()
                    return None
                if row["merged_into_user_id"] is not None:
                    if row["merged_into_user_id"] != user_id:
                        logger.warning(
                            "guest %d already merged into %d; refusing merge into %d",
                            guest_user_id,
                            row["merged_into_user_id"],
                            user_id,
                        )
                    self._conn.rollback()
                    return None

                cur.execute(
                    "UPDATE proposals.proposals SET user_id = %s WHERE user_id = %s",
                    (user_id, guest_user_id),
                )
                proposals_claimed = cur.rowcount
                cur.execute(
                    "UPDATE admin.feedback SET user_id = %s WHERE user_id = %s",
                    (user_id, guest_user_id),
                )
                feedback_claimed = cur.rowcount

                # Drop the guest's like on any proposal the target account
                # already liked, so the reassignment below can't violate
                # UNIQUE(proposal_id, user_id).
                cur.execute(
                    "DELETE FROM proposals.likes WHERE user_id = %s "
                    "AND proposal_id IN ("
                    "    SELECT proposal_id FROM proposals.likes WHERE user_id = %s"
                    ")",
                    (guest_user_id, user_id),
                )
                cur.execute(
                    "UPDATE proposals.likes SET user_id = %s WHERE user_id = %s",
                    (user_id, guest_user_id),
                )
                likes_claimed = cur.rowcount

                cur.execute(
                    "UPDATE proposals.comments SET user_id = %s WHERE user_id = %s",
                    (user_id, guest_user_id),
                )
                comments_claimed = cur.rowcount

                cur.execute(
                    "UPDATE admin.users SET merged_into_user_id = %s "
                    "WHERE user_id = %s",
                    (user_id, guest_user_id),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        logger.info(
            "guest %d merged into user %d (%d proposals, %d feedback rows, "
            "%d likes, %d comments)",
            guest_user_id,
            user_id,
            proposals_claimed,
            feedback_claimed,
            likes_claimed,
            comments_claimed,
        )
        return {
            "proposals_claimed": proposals_claimed,
            "feedback_claimed": feedback_claimed,
            "likes_claimed": likes_claimed,
            "comments_claimed": comments_claimed,
        }
