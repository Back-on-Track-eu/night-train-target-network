"""
route_segment_repository.py
===========================
Read/write access to the route_cache schema — the stop-pair segment store
fronting RailRouter's routing path (models/route/routing/rail_router.py,
layer 1's lookup-first branch; row shape in
models/route/routing/segment_cache.py).

A cache, not a source of truth — like WP13's compute cache it may be
emptied at any time and costs only recomputes. It grows two ways: bulk
(load_csv(), fed by scripts/precompute_route_segments.py — precompute
and reseed) and per request (store(), every live-routed miss). Rows are
keyed per routing graph: (routing_graph_key, stop_lo, stop_hi,
variant_key). Each graph has its own variants — its own snapped points,
its own HSR resolution — so nothing is ever shared across graphs.

Invalidation is automatic per graph: route_cache.graph_state remembers
the GraphHopper import_date the rows were routed against;
sync_graph_import() (api/helpers/dependencies.py at startup, the script
before a batch) compares it with the live /info and purges that graph's
rows on a change. A re-import therefore empties exactly the graph it
touched, and the cache refills — from the next precompute run and from
traffic.

Write path is additive-only: ON CONFLICT DO NOTHING, so a concurrent
identical live-route never mutates an existing row.

Thread safety: RailRouter is a process singleton used concurrently
(auto-stop mini-reroutes fan out on a thread pool), psycopg2 connections
are not thread-safe — every operation takes one lock. Acceptable: each
read is a single indexed query, orders of magnitude cheaper than the
~300 ms router call it replaces.

Mirrors ComputeCacheRepository's construction (same env vars, one
connection per process). Read/store errors never propagate past
store()/fetch_many() into a request: a cache hiccup degrades to live
routing, it does not fail a compute.

Public interface:
  RouteSegmentRepository().fetch_many(graph_key, variant_key, keys)
      -> dict[(stop_lo, stop_hi), CachedSegment]
  RouteSegmentRepository().store(graph_key, variant_key, lo, hi, seg, source)
  RouteSegmentRepository().sync_graph_import(graph_key, import_date) -> bool
  RouteSegmentRepository().load_csv(path, graph_key, source) -> int
  RouteSegmentRepository().purge(graph_key) -> int
  RouteSegmentRepository().count(graph_key) -> int
  RouteSegmentRepository().close()
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import threading
from pathlib import Path

import psycopg2
import psycopg2.extras

from models.route.routing.segment_cache import (
    CSV_COLUMNS,
    CachedSegment,
    segment_from_db_row,
)

logger = logging.getLogger(__name__)

_FETCH_SQL = """
    SELECT stop_lo, stop_hi, distance_m, country_distance_m,
           country_driving_ms, countries, passages, geometry
    FROM route_cache.route_segments
    WHERE routing_graph_key = %(graph_key)s
      AND variant_key = %(variant_key)s
      AND (stop_lo, stop_hi) IN %(keys)s
"""

_STORE_SQL = """
    INSERT INTO route_cache.route_segments
        (routing_graph_key, stop_lo, stop_hi, variant_key, distance_m,
         country_distance_m, country_driving_ms, countries, passages,
         geometry, source)
    VALUES (%(graph_key)s, %(stop_lo)s, %(stop_hi)s, %(variant_key)s,
            %(distance_m)s, %(country_distance_m)s, %(country_driving_ms)s,
            %(countries)s, %(passages)s, %(geometry)s, %(source)s)
    ON CONFLICT (routing_graph_key, stop_lo, stop_hi, variant_key)
    DO NOTHING
"""

_COLUMN_LIST = ", ".join(CSV_COLUMNS)

# Only the CSV columns — a LIKE-copy would inherit NOT NULL on the
# graph/source columns the file deliberately does not carry.
_STAGING_DDL = """
    CREATE TEMP TABLE route_cache_staging (
        stop_lo VARCHAR(120), stop_hi VARCHAR(120), variant_key VARCHAR(80),
        distance_m INTEGER, country_distance_m JSONB, country_driving_ms JSONB,
        countries JSONB, passages JSONB, geometry JSONB
    ) ON COMMIT DROP
"""

_LOAD_SQL = f"""
    INSERT INTO route_cache.route_segments
        (routing_graph_key, {_COLUMN_LIST}, source)
    SELECT %(graph_key)s, {_COLUMN_LIST}, %(source)s
    FROM route_cache_staging
    ON CONFLICT (routing_graph_key, stop_lo, stop_hi, variant_key)
    DO NOTHING
"""


class RouteSegmentRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
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

    def close(self) -> None:
        self._conn.close()

    # -- request path ------------------------------------------------------

    def fetch_many(
        self, graph_key: str, variant_key: str, keys: set[tuple[str, str]]
    ) -> dict[tuple[str, str], CachedSegment]:
        """All cached segments for the given (stop_lo, stop_hi) keys on one
        graph in one query — one round trip per trip, not per pair.
        Missing pairs are simply absent; a DB error returns {} (→ every
        pair live-routes) rather than failing the request."""
        if not keys:
            return {}
        try:
            with self._lock:
                with self._conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor
                ) as cur:
                    cur.execute(
                        _FETCH_SQL,
                        {
                            "graph_key": graph_key,
                            "variant_key": variant_key,
                            "keys": tuple(keys),
                        },
                    )
                    rows = cur.fetchall()
                self._conn.commit()
        except Exception:
            logger.warning("route_cache: lookup failed — live routing.", exc_info=True)
            self._rollback()
            return {}
        return {
            (row["stop_lo"], row["stop_hi"]): segment_from_db_row(row) for row in rows
        }

    def store(
        self,
        graph_key: str,
        variant_key: str,
        stop_lo: str,
        stop_hi: str,
        segment: CachedSegment,
        source: str = "runtime",
    ) -> None:
        """Store one live-routed miss — additive-only (module docstring).
        Failures are logged, never raised: the caller already holds a
        correct leg, and a write hiccup must not fail the request it was
        meant to speed up next time."""
        try:
            with self._lock:
                with self._conn.cursor() as cur:
                    cur.execute(
                        _STORE_SQL,
                        {
                            "graph_key": graph_key,
                            "stop_lo": stop_lo,
                            "stop_hi": stop_hi,
                            "variant_key": variant_key,
                            "distance_m": segment.distance_m,
                            "country_distance_m": json.dumps(
                                segment.country_distance_m
                            ),
                            "country_driving_ms": json.dumps(
                                segment.country_driving_ms
                            ),
                            "countries": json.dumps(segment.countries),
                            "passages": json.dumps(segment.passages),
                            "geometry": json.dumps(segment.geometry),
                            "source": source,
                        },
                    )
                self._conn.commit()
        except Exception:
            logger.warning(
                "route_cache: store for (%s, %s) failed — continuing.",
                stop_lo,
                stop_hi,
                exc_info=True,
            )
            self._rollback()

    # -- maintenance -------------------------------------------------------

    def sync_graph_import(self, graph_key: str, import_date: str | None) -> bool:
        """Reconcile the cache with the graph actually being served: if the
        GraphHopper import_date differs from the one the rows were routed
        against, purge this graph's rows and record the new date. Returns
        True when a purge happened. import_date=None (instance
        unreachable at startup) leaves everything untouched — the rows
        are still valid for whatever graph comes back."""
        if import_date is None:
            return False
        with self._lock:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT import_date FROM route_cache.graph_state "
                    "WHERE routing_graph_key = %s",
                    (graph_key,),
                )
                row = cur.fetchone()
                stored = row[0] if row else None
                purged = 0
                if stored is not None and stored != import_date:
                    cur.execute(
                        "DELETE FROM route_cache.route_segments "
                        "WHERE routing_graph_key = %s",
                        (graph_key,),
                    )
                    purged = cur.rowcount
                cur.execute(
                    "INSERT INTO route_cache.graph_state "
                    "(routing_graph_key, import_date, synced_at) "
                    "VALUES (%s, %s, now()) "
                    "ON CONFLICT (routing_graph_key) DO UPDATE SET "
                    "import_date = EXCLUDED.import_date, synced_at = now()",
                    (graph_key, import_date),
                )
            self._conn.commit()
        if stored is not None and stored != import_date:
            logger.warning(
                "route_cache [%s]: graph import changed (%s -> %s) — purged %d "
                "cached segment(s); re-run the precompute for this graph.",
                graph_key,
                stored,
                import_date,
                purged,
            )
            return True
        return False

    def load_csv(self, path: Path, graph_key: str, source: str = "precompute") -> int:
        """Bulk-load a precompute CSV (.csv or .csv.gz, header =
        CSV_COLUMNS) for one graph — COPY into a temp table, then
        INSERT ... ON CONFLICT DO NOTHING, so a reload on top of
        runtime-grown rows is safe and idempotent. Returns rows inserted."""
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:
            header = fh.readline().strip().split(",")
            if header != CSV_COLUMNS:
                raise ValueError(
                    f"Unexpected CSV header {header!r} in {path.name} "
                    f"(expected {CSV_COLUMNS})."
                )
        with self._lock:
            with self._conn.cursor() as cur:
                cur.execute(_STAGING_DDL)
                with opener(path, "rt", encoding="utf-8") as fh:
                    cur.copy_expert(
                        f"COPY route_cache_staging ({_COLUMN_LIST}) "
                        "FROM STDIN WITH (FORMAT csv, HEADER true)",
                        fh,
                    )
                cur.execute(_LOAD_SQL, {"graph_key": graph_key, "source": source})
                inserted = cur.rowcount
            self._conn.commit()
        logger.info(
            "route_cache [%s]: loaded %d new segment(s) from %s.",
            graph_key,
            inserted,
            path.name,
        )
        return inserted

    def purge(self, graph_key: str) -> int:
        with self._lock:
            with self._conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM route_cache.route_segments WHERE routing_graph_key = %s",
                    (graph_key,),
                )
                deleted = cur.rowcount
            self._conn.commit()
        return deleted

    def count(self, graph_key: str) -> int:
        with self._lock:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM route_cache.route_segments "
                    "WHERE routing_graph_key = %s",
                    (graph_key,),
                )
                n = cur.fetchone()[0]
            self._conn.commit()
        return n

    def _rollback(self) -> None:
        try:
            with self._lock:
                self._conn.rollback()
        except Exception:
            pass
