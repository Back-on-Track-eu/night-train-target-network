"""
member_cache.py
===============
family.members: one row per resolved member request — the cached result
of compute_member() (api/helpers/member_compute.py), shared across
gunicorn workers through an UNLOGGED Postgres table. The successor of
proposals.compute_cache_pointer / compute_cache_result (WP13's two-table
cache), collapsed to one table in WP18 B2b.

Why one table now. The split existed so two requests converging on one
routed result (a "suggest" and an "off" request for the same stops, say)
shared one payload row. The family document has taken over the role of
"every member of one stop list at once", and a member is read by the
views endpoint, publish, compare and refresh — one request each. Sharing
payloads between requests bought little and cost a JOIN, a two-step
write order and a race between two TTLs. One row per request hash is the
obvious shape; the payload is stored once per request, and a request
that asks for "suggest" and then "off" stores it twice. Accepted.

The key is the resolved request PLUS the measure set
(member_compute.canonical_request_hash): the request echo names a
scenario and a composition but no measure set — that is the variant's —
so two members of one scenario under different measures must not share a
row.

Same discipline as before and as the document cache next door: TTL
enforced on READ (an expired-but-unswept row is a miss, never a stale
hit), upserts refreshing created_at, a sampled sweep on the write path,
flush() as a plain TRUNCATE. The version guard (served payload must match
the running ROUTE_BUILDER_/CALC_VERSION) stays in member_compute.py —
version constants are model-layer knowledge and this adapter is
models-free.

Public interface:
  FamilyMemberCache(ttl_hours, cleanup_probability, pool)
    .lookup(request_hash) -> dict | None
    .store(request_hash, route_fingerprint, scenario_id, measure_set_id,
           composition_id, resolved_request, suggested_stops, payload)
    .sweep() -> None
    .flush() -> None
"""

from __future__ import annotations

import os
import random
from typing import Optional

import psycopg2.extras

from adapters.db_pool import DBPool, default_pool

COMPUTE_CACHE_TTL_HOURS = float(os.environ.get("COMPUTE_CACHE_TTL_HOURS", "3"))
COMPUTE_CACHE_CLEANUP_PROBABILITY = float(
    os.environ.get("COMPUTE_CACHE_CLEANUP_PROBABILITY", "0.01")
)

_LOOKUP_SQL = """
    SELECT route_fingerprint, scenario_id, measure_set_id, composition_id,
           resolved_request, suggested_stops, payload
    FROM family.members
    WHERE request_hash = %(request_hash)s
      AND created_at >= now() - %(ttl_hours)s * interval '1 hour'
"""

_STORE_SQL = """
    INSERT INTO family.members
        (request_hash, route_fingerprint, scenario_id, measure_set_id,
         composition_id, resolved_request, suggested_stops, payload)
    VALUES (%(request_hash)s, %(route_fingerprint)s, %(scenario_id)s,
            %(measure_set_id)s, %(composition_id)s, %(resolved_request)s,
            %(suggested_stops)s, %(payload)s)
    ON CONFLICT (request_hash)
    DO UPDATE SET route_fingerprint = EXCLUDED.route_fingerprint,
                  scenario_id       = EXCLUDED.scenario_id,
                  measure_set_id    = EXCLUDED.measure_set_id,
                  composition_id    = EXCLUDED.composition_id,
                  resolved_request  = EXCLUDED.resolved_request,
                  suggested_stops   = EXCLUDED.suggested_stops,
                  payload           = EXCLUDED.payload,
                  created_at        = now()
"""


class FamilyMemberCache:
    """Read/write access to family.members. Every call borrows a pooled
    connection for exactly its own transaction, so the object is
    thread-safe without a lock. Errors propagate — swallowing would hide a
    missing migration forever."""

    def __init__(
        self,
        ttl_hours: float = COMPUTE_CACHE_TTL_HOURS,
        cleanup_probability: float = COMPUTE_CACHE_CLEANUP_PROBABILITY,
        pool: DBPool | None = None,
    ) -> None:
        self._ttl_hours = ttl_hours
        self._cleanup_probability = cleanup_probability
        self._pool = pool or default_pool()

    def lookup(self, request_hash: str) -> Optional[dict]:
        """{route_fingerprint, scenario_id, measure_set_id, composition_id,
        resolved_request, suggested_stops, payload} or None on a miss."""
        with self._pool.cursor() as cur:
            cur.execute(
                _LOOKUP_SQL,
                {"request_hash": request_hash, "ttl_hours": self._ttl_hours},
            )
            row = cur.fetchone()
        return dict(row) if row is not None else None

    def store(
        self,
        request_hash: str,
        route_fingerprint: str,
        scenario_id: int,
        measure_set_id: int,
        composition_id: str,
        resolved_request: dict,
        suggested_stops: Optional[list],
        payload: dict,
    ) -> None:
        """Upsert plus the sampled TTL sweep, one transaction.
        suggested_stops is None outside suggest mode (SQL NULL, distinct
        from an empty suggest-mode list)."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _STORE_SQL,
                    {
                        "request_hash": request_hash,
                        "route_fingerprint": route_fingerprint,
                        "scenario_id": scenario_id,
                        "measure_set_id": measure_set_id,
                        "composition_id": composition_id,
                        "resolved_request": psycopg2.extras.Json(resolved_request),
                        "suggested_stops": (
                            psycopg2.extras.Json(suggested_stops)
                            if suggested_stops is not None
                            else None
                        ),
                        "payload": psycopg2.extras.Json(payload),
                    },
                )
                if random.random() < self._cleanup_probability:
                    self._sweep(cur)
            conn.commit()

    def _sweep(self, cur) -> None:
        cur.execute(
            "DELETE FROM family.members "
            "WHERE created_at < now() - %(ttl_hours)s * interval '1 hour'",
            {"ttl_hours": self._ttl_hours},
        )

    def sweep(self) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                self._sweep(cur)
            conn.commit()

    def flush(self) -> None:
        """Empties the table — UNLOGGED, never a source of truth. Called by
        scripts/refresh_proposals.py on every version bump, together with
        the document cache's."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE family.members")
            conn.commit()
