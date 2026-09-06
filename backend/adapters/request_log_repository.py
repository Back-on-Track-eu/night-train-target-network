"""
request_log_repository.py
=========================
Write-path database adapter for the API usage log — mirrors
FeedbackRepository (adapters/feedback_repository.py): its own connection
to the same database, so DBDataLoader stays strictly read-only. See
db/dev/sql/create_admin_schema.sql for the admin.request_log schema this
module writes to.

Two things make it different from every other repository here:

AUTOCOMMIT. A usage row shares a transaction with nothing and never needs
to be rolled back alongside anything else. Autocommit means one round trip
per insert instead of insert-plus-commit, and it removes the failure mode
where a request-log error leaves an open transaction that the NEXT
request's insert then trips over.

BEST-EFFORT. Callers are expected to swallow failures
(api/request_log.py) — a logging sink must never turn a served request
into an error. insert() therefore rolls the connection back and re-raises
rather than deciding on its own what a failure means; deciding is the
caller's job, and the rollback keeps the connection usable for the next
attempt either way.

One connection per gunicorn worker, like every repository here. When
WP14 swaps dependencies.py's singletons to connection pools this joins
them; until then it is one more connection per worker, which is the cost
worth knowing about.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


class RequestLogRepository:
    """Appends rows to admin.request_log — thin connection wrapper
    mirroring FeedbackRepository's construction (same env vars, one
    connection per process/worker), but autocommit."""

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
        conn = psycopg2.connect(
            host=required["POSTGRES_HOST"],
            port=required["POSTGRES_PORT"],
            dbname=required["POSTGRES_DB"],
            user=required["POSTGRES_USER"],
            password=required["POSTGRES_PASSWORD"],
        )
        conn.autocommit = True
        return conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def insert(
        self,
        *,
        method: str,
        endpoint: Optional[str],
        route_rule: Optional[str],
        status_code: int,
        duration_ms: int,
        user_id: Optional[int] = None,
        is_guest: bool = False,
        trust_level: Optional[int] = None,
        client_hash: Optional[str] = None,
        response_bytes: Optional[int] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Append one request row. occurred_at is left to the column
        default so the timestamp is the database's clock, not the
        worker's — four gunicorn workers with drifting clocks would
        otherwise interleave badly in a time-ordered read.

        Keyword-only: the argument list is long, uniformly typed and
        largely optional, which is exactly the shape positional calls get
        silently wrong."""
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin.request_log (
                        user_id, is_guest, trust_level, client_hash,
                        method, endpoint, route_rule,
                        status_code, duration_ms, response_bytes, user_agent
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        is_guest,
                        trust_level,
                        client_hash,
                        method,
                        endpoint,
                        route_rule,
                        status_code,
                        duration_ms,
                        response_bytes,
                        user_agent,
                    ),
                )
        except Exception:
            # Autocommit means there is normally nothing to roll back, but
            # a connection dropped mid-statement needs resetting before the
            # next request reuses it. Never swallowed here — see the module
            # docstring.
            self._rollback()
            raise

    def purge_older_than(self, days: int) -> int:
        """Delete rows older than `days` and return how many went.
        Retention lives here rather than in the database because it is a
        policy, not a constraint — scripts/purge_request_log.py is the
        caller, on a cron."""
        if days < 1:
            raise ValueError("Retention must be at least one day.")
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM admin.request_log "
                "WHERE occurred_at < now() - make_interval(days => %s)",
                (days,),
            )
            return cur.rowcount

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM admin.request_log")
            return int(cur.fetchone()[0])

    def _rollback(self) -> None:
        try:
            self._conn.rollback()
        except Exception:
            logger.debug("Request log rollback failed.", exc_info=True)
