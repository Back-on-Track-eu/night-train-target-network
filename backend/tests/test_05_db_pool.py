"""
test_05_db_pool.py
==================
The shared connection pool (adapters/db_pool.py, WP14) — the piece every
adapter now borrows from instead of holding a psycopg2 connection.

Covers the borrow/return semantics the adapters rely on:
  - an exhausted pool WAITS (bounded) instead of raising, then succeeds;
  - a failed block hands a clean connection to the next borrower (no
    "current transaction is aborted" carry-over);
  - autocommit switched on inside a block is reset on the way out;
  - a connection the server dropped is replaced, not returned;
  - the loader singleton serves N threads concurrently with identical
    results, which is what makes gunicorn gthread + the calc matrix safe.

Runs against the live stack's Postgres like everything else here.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import pytest

from adapters.db_pool import DBPool, PoolTimeoutError, default_pool


@pytest.fixture(scope="module")
def small_pool(loader):
    """A pool of two on the same DSN the loader uses (`loader` guarantees
    the POSTGRES_* env is set). Closed at module end."""
    pool = DBPool(
        dsn=default_pool()._pool._kwargs,
        minconn=1,
        maxconn=2,
        acquire_timeout_s=1.0,
    )
    yield pool
    pool.closeall()


class TestBorrowReturn:
    def test_exhausted_pool_waits_then_succeeds(self, small_pool):
        release = threading.Event()
        holders_ready = threading.Barrier(3)

        def hold():
            with small_pool.connection():
                holders_ready.wait()
                release.wait()

        with ThreadPoolExecutor(max_workers=2) as ex:
            ex.submit(hold)
            ex.submit(hold)
            holders_ready.wait()
            # Both slots taken: a third borrower must block, not fail.
            started = time.monotonic()
            threading.Timer(0.2, release.set).start()
            with small_pool.cursor() as cur:
                cur.execute("SELECT 1 AS one")
                assert cur.fetchone()["one"] == 1
            assert time.monotonic() - started >= 0.15

    def test_exhausted_pool_times_out(self, small_pool):
        release = threading.Event()
        holders_ready = threading.Barrier(3)

        def hold():
            with small_pool.connection():
                holders_ready.wait()
                release.wait()

        with ThreadPoolExecutor(max_workers=2) as ex:
            ex.submit(hold)
            ex.submit(hold)
            holders_ready.wait()
            try:
                with pytest.raises(PoolTimeoutError):
                    with small_pool.connection():
                        pass
            finally:
                release.set()

    def test_failed_block_leaves_next_borrower_clean(self, small_pool):
        with pytest.raises(psycopg2.errors.UndefinedTable):
            with small_pool.cursor() as cur:
                cur.execute("SELECT * FROM no_such_schema.no_such_table")
        # Same physical connection (pool of two, nothing else borrowed):
        # must not be inside an aborted transaction.
        with small_pool.cursor() as cur:
            cur.execute("SELECT 2 AS two")
            assert cur.fetchone()["two"] == 2

    def test_autocommit_reset_on_return(self, small_pool):
        with small_pool.connection() as conn:
            conn.autocommit = True
            assert conn.autocommit
        # Drain the pool so we know we get that connection back.
        seen = []
        for _ in range(2):
            with small_pool.connection() as conn:
                seen.append(conn.autocommit)
        assert seen == [False, False]

    def test_broken_connection_is_replaced(self, small_pool):
        with small_pool.connection() as conn:
            conn.close()  # simulate the server dropping it
        with small_pool.cursor() as cur:
            cur.execute("SELECT 3 AS three")
            assert cur.fetchone()["three"] == 3

    def test_uncommitted_write_is_rolled_back(self, small_pool, db_cur):
        """A borrower that forgets to commit leaks nothing: the pool rolls
        the transaction back before the connection is reused."""
        with small_pool.connection() as conn:
            with conn.cursor() as cur:
                # duration_ms is NOT NULL (db/dev/sql/create_admin_schema.sql)
                # — the probe row only exists to be rolled back, so 0.
                cur.execute(
                    "INSERT INTO admin.request_log "
                    "(method, endpoint, status_code, duration_ms) "
                    "VALUES ('POOL', 'pool_probe', 200, 0)"
                )
            # no commit
        db_cur.execute(
            "SELECT count(*) AS n FROM admin.request_log WHERE method = 'POOL'"
        )
        assert db_cur.fetchone()["n"] == 0


class TestSharedLoader:
    def test_loader_is_thread_safe(self, loader):
        """N threads on the ONE loader instance return identical catalogs —
        the property scripts/refresh_proposals.py and the matrix fan-out
        rely on."""
        reference = sorted(loader.build_all_compositions().all())

        def one(_):
            return sorted(loader.build_all_compositions().all())

        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(one, range(12)))
        assert all(result == reference for result in results)
        assert len(reference) >= 8

    def test_pool_slots_return_after_parallel_reads(self, loader):
        pool = default_pool()
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(lambda _: loader.build_all_tracks(), range(16)))
        # Every slot free again: maxconn borrows in a row must not block.
        for _ in range(pool.maxconn):
            with pool.cursor() as cur:
                cur.execute("SELECT 1")
