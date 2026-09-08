"""
request_log_repository.py
=========================
Write-path database adapter for the API usage log — mirrors
FeedbackRepository (adapters/feedback_repository.py): one borrowed DBPool
connection per call, so DBDataLoader stays strictly read-only. See
db/dev/sql/create_admin_schema.sql for the admin.request_log schema this
module writes to.

Two things make it different from every other repository here:

AUTOCOMMIT. A usage row shares a transaction with nothing and never needs
to be rolled back alongside anything else. Autocommit means one round trip
per insert instead of insert-plus-commit. It is switched on inside the
borrowed scope only — DBPool resets it before the connection goes back.

BEST-EFFORT. Callers are expected to swallow failures
(api/request_log.py) — a logging sink must never turn a served request
into an error. insert() therefore lets the error propagate rather than
deciding on its own what a failure means; deciding is the caller's job,
and the pool discards a broken connection on the way out.
"""

from __future__ import annotations

from typing import Optional

from adapters.db_pool import DBPool, default_pool


class RequestLogRepository:
    """Appends rows to admin.request_log — one borrowed DBPool connection
    per call, mirroring FeedbackRepository, but autocommit."""

    def __init__(self, pool: DBPool | None = None) -> None:
        self._pool = pool or default_pool()

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
        with self._pool.connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
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

    def purge_older_than(self, days: int) -> int:
        """Delete rows older than `days` and return how many went.
        Retention lives here rather than in the database because it is a
        policy, not a constraint — scripts/purge_request_log.py is the
        caller, on a cron."""
        if days < 1:
            raise ValueError("Retention must be at least one day.")
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM admin.request_log "
                    "WHERE occurred_at < now() - make_interval(days => %s)",
                    (days,),
                )
                deleted = cur.rowcount
            conn.commit()
        return deleted

    def count(self) -> int:
        with self._pool.cursor(cursor_factory=None) as cur:
            cur.execute("SELECT count(*) FROM admin.request_log")
            return int(cur.fetchone()[0])

    def count_older_than(self, days: int) -> int:
        """Rows purge_older_than(days) would delete — the same boundary
        expression, so a dry run cannot disagree with the real one."""
        with self._pool.cursor(cursor_factory=None) as cur:
            cur.execute(
                "SELECT count(*) FROM admin.request_log "
                "WHERE occurred_at < now() - make_interval(days => %s)",
                (days,),
            )
            return int(cur.fetchone()[0])
