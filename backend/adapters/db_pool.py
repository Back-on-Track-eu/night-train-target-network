"""
db_pool.py
==========
One psycopg2 connection pool per process, shared by every adapter (WP14).

Before WP14 each adapter opened its own long-lived psycopg2 connection in
``__init__`` and held it for the process lifetime. That was fine under
gunicorn's ``sync`` worker model (one request per process at a time) but
psycopg2 connections are not thread-safe, so the moment two threads share
an adapter — gunicorn ``gthread``, the calc-matrix fan-out — every adapter
would have needed its own lock. Instead every adapter now *borrows* a
connection per unit of work and returns it:

    with self._pool.connection() as conn:      # multi-statement transaction
        with conn.cursor() as cur: ...
        conn.commit()

    with self._pool.cursor() as cur:           # single read-only query
        cur.execute(...)

Semantics of a borrowed connection:
  - acquisition blocks up to DB_POOL_ACQUIRE_TIMEOUT_S when the pool is
    exhausted (psycopg2's pool raises immediately; the semaphore here is
    what makes callers wait), then raises PoolTimeoutError;
  - on exit the connection is ALWAYS rolled back (a no-op after commit;
    it releases a read-only transaction and never hands a half-done
    transaction to the next borrower) and autocommit is reset to False,
    so an adapter that switched it on for a best-effort write leaks
    nothing;
  - a connection the server dropped (``conn.closed``) is discarded and
    replaced rather than returned.

The DSN is read from POSTGRES_HOST/PORT/DB/USER/PASSWORD here and nowhere
else — no defaults, a missing variable is a loud startup failure
(AGENTS.md, parameter placement rule 1). Sizing knobs (DB_POOL_MIN,
DB_POOL_MAX, DB_POOL_ACQUIRE_TIMEOUT_S) are documented in
backend/docker/.env.example and docs/DEPLOY_HANDOVER.md.

Public interface:
  DBPool.from_env()             -> DBPool
  DBPool.connection()           -> context manager yielding a connection
  DBPool.cursor(cursor_factory) -> context manager yielding a cursor
  DBPool.closeall()
  default_pool()                -> the lazily built process-wide pool,
                                   what adapters use when constructed
                                   without an explicit pool (scripts,
                                   tests, seed.py)
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

_REQUIRED_ENV = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)


class PoolTimeoutError(RuntimeError):
    """No connection became free within DB_POOL_ACQUIRE_TIMEOUT_S."""


class DBPool:
    def __init__(
        self,
        dsn: dict,
        minconn: int,
        maxconn: int,
        acquire_timeout_s: float,
    ) -> None:
        if minconn < 1 or maxconn < minconn:
            raise ValueError(
                f"DB pool sizing must satisfy 1 <= DB_POOL_MIN <= DB_POOL_MAX "
                f"(got {minconn}, {maxconn})."
            )
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, **dsn)
        self._slots = threading.BoundedSemaphore(maxconn)
        self._acquire_timeout_s = acquire_timeout_s
        self.maxconn = maxconn

    @classmethod
    def from_env(cls) -> "DBPool":
        missing = [key for key in _REQUIRED_ENV if not os.environ.get(key)]
        if missing:
            raise RuntimeError(
                "Missing required environment variable(s) for DB connection: "
                f"{', '.join(missing)}. Check your .env file."
            )
        dsn = {
            "host": os.environ["POSTGRES_HOST"],
            "port": int(os.environ["POSTGRES_PORT"]),
            "dbname": os.environ["POSTGRES_DB"],
            "user": os.environ["POSTGRES_USER"],
            "password": os.environ["POSTGRES_PASSWORD"],
        }
        return cls(
            dsn,
            minconn=int(os.environ.get("DB_POOL_MIN", "2")),
            maxconn=int(os.environ.get("DB_POOL_MAX", "16")),
            acquire_timeout_s=float(os.environ.get("DB_POOL_ACQUIRE_TIMEOUT_S", "10")),
        )

    @contextmanager
    def connection(self):
        if not self._slots.acquire(timeout=self._acquire_timeout_s):
            raise PoolTimeoutError(
                f"No database connection free after {self._acquire_timeout_s:g}s "
                f"(DB_POOL_MAX={self.maxconn})."
            )
        try:
            conn = self._pool.getconn()
        except Exception:
            self._slots.release()
            raise
        broken = False
        try:
            yield conn
        except Exception:
            broken = conn.closed != 0
            if not broken:
                conn.rollback()
            raise
        finally:
            try:
                if conn.closed == 0:
                    # rollback first: autocommit cannot be changed inside
                    # an open transaction.
                    conn.rollback()
                    conn.autocommit = False
                else:
                    broken = True
            except Exception:
                broken = True
                logger.warning(
                    "db_pool: discarding unresettable connection.", exc_info=True
                )
            finally:
                self._pool.putconn(conn, close=broken)
                self._slots.release()

    @contextmanager
    def cursor(self, cursor_factory=psycopg2.extras.RealDictCursor):
        """A cursor on a freshly borrowed connection — for single-query
        reads. The transaction is released when the block ends; writes
        must use connection() and commit explicitly."""
        with self.connection() as conn:
            with conn.cursor(cursor_factory=cursor_factory) as cur:
                yield cur

    def closeall(self) -> None:
        self._pool.closeall()


_default_pool: DBPool | None = None
_default_pool_lock = threading.Lock()


def default_pool() -> DBPool:
    """The process-wide pool, built from the environment on first use.
    api/helpers/dependencies.py builds it explicitly at startup; scripts,
    seed.py and tests get the same instance implicitly through the
    adapters' constructors, so one process never holds two pools."""
    global _default_pool
    with _default_pool_lock:
        if _default_pool is None:
            _default_pool = DBPool.from_env()
        return _default_pool
