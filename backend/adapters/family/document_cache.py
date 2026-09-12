"""
document_cache.py
=================
family.documents: one row per family key, the serialised §2.5 document,
TTL-bounded, shared across gunicorn workers through an UNLOGGED Postgres
table. Strictly a performance layer — a family is a pure function of its
pins, so every row can be rebuilt and the table is safe to TRUNCATE at
any time.

Same discipline as the member cache next door (member_cache.py): TTL is
enforced on READ
(an expired-but-unswept row is a miss, never a stale hit), writes upsert
and refresh created_at, and the sweep is opportunistic — a sampled DELETE
on the write path, no scheduler. The version guard is in the key itself:
models/family/key.py folds ROUTE_BUILDER_VERSION and CALC_VERSION into
family_key(), so a bump simply never finds the old rows again and the
sweep eventually drops them. flush() is called by
scripts/refresh_proposals.py alongside the member cache's.

Public interface:
  FamilyDocumentCache(ttl_hours, cleanup_probability, pool)
    .get(family_key) -> dict | None
    .put(family_key, document) -> None
    .sweep() -> None
    .flush() -> None
"""

from __future__ import annotations

import os
import random
from typing import Optional

import psycopg2.extras

from adapters.db_pool import DBPool, default_pool

# Same knobs as the member cache — one TTL for everything derived from the
# pins, so a document never outlives the members it was assembled from.
FAMILY_DOCUMENT_TTL_HOURS = float(os.environ.get("COMPUTE_CACHE_TTL_HOURS", "3"))
FAMILY_DOCUMENT_CLEANUP_PROBABILITY = float(
    os.environ.get("COMPUTE_CACHE_CLEANUP_PROBABILITY", "0.01")
)

_GET_SQL = """
    SELECT payload
    FROM family.documents
    WHERE family_key = %(family_key)s
      AND created_at >= now() - %(ttl_hours)s * interval '1 hour'
"""

_PUT_SQL = """
    INSERT INTO family.documents
        (family_key, route_builder_version, calc_version, payload)
    VALUES (%(family_key)s, %(route_builder_version)s, %(calc_version)s,
            %(payload)s)
    ON CONFLICT (family_key)
    DO UPDATE SET payload               = EXCLUDED.payload,
                  route_builder_version = EXCLUDED.route_builder_version,
                  calc_version          = EXCLUDED.calc_version,
                  created_at            = now()
"""


class FamilyDocumentCache:
    """Read/write access to family.documents. Every call borrows a pooled
    connection for exactly its own transaction, so the object is
    thread-safe without a lock. Errors propagate: the table lives in the
    same database every compute already depends on, and swallowing would
    hide a missing migration forever."""

    def __init__(
        self,
        ttl_hours: float = FAMILY_DOCUMENT_TTL_HOURS,
        cleanup_probability: float = FAMILY_DOCUMENT_CLEANUP_PROBABILITY,
        pool: DBPool | None = None,
    ) -> None:
        self._ttl_hours = ttl_hours
        self._cleanup_probability = cleanup_probability
        self._pool = pool or default_pool()

    def get(self, family_key: str) -> Optional[dict]:
        with self._pool.cursor() as cur:
            cur.execute(
                _GET_SQL, {"family_key": family_key, "ttl_hours": self._ttl_hours}
            )
            row = cur.fetchone()
        return row["payload"] if row is not None else None

    def put(self, family_key: str, document: dict) -> None:
        """document is the serialised family; its own version fields are
        copied into the two informational columns."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _PUT_SQL,
                    {
                        "family_key": family_key,
                        "route_builder_version": document["route_builder_version"],
                        "calc_version": document["calc_version"],
                        "payload": psycopg2.extras.Json(document),
                    },
                )
                if random.random() < self._cleanup_probability:
                    self._sweep(cur)
            conn.commit()

    def _sweep(self, cur) -> None:
        cur.execute(
            "DELETE FROM family.documents "
            "WHERE created_at < now() - %(ttl_hours)s * interval '1 hour'",
            {"ttl_hours": self._ttl_hours},
        )

    def sweep(self) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                self._sweep(cur)
            conn.commit()

    def flush(self) -> None:
        """Empties the table — UNLOGGED, never a source of truth."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE family.documents")
            conn.commit()
