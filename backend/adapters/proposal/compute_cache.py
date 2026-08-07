"""
compute_cache.py
=================
The compute cache (README.md §2.3): a server-side,
TTL-bounded cache over merged compute results, shared across gunicorn
workers via two UNLOGGED Postgres tables (created in WP1's phase-1
migration). Strictly a performance layer — never a source of truth, safe
to flush at any time.

Two maps, because the result identity (route_fingerprint, scenario_id,
composition_id) is only known AFTER routing — the very step the cache
exists to skip:

  compute_cache_pointer : request_hash -> the identity triple, plus the
                          request-SPECIFIC response parts (resolved
                          request echo, suggested_stops). Tiny rows.
  compute_cache_result  : identity triple -> the shared payload (route +
                          evaluation + summary + the version constants it
                          was computed under), stored once per distinct
                          result no matter how many requests converge on
                          it.

The split matters because publish reads cached payloads: the shared
result core must never carry another request's echo.

Read path (driven by api/helpers/proposal_compute.py): pointer lookup by
request hash, TTL-filtered on BOTH rows — an expired-but-unswept row is a
miss, never a stale hit — joined to the result row in one query. The
version guard (served payload must match the running ROUTE_BUILDER_/
CALC_VERSION) lives in proposal_compute.py, not here: version constants
are model-layer knowledge and this adapter stays models-free.

Write path: result upsert, then pointer upsert, then (on
`cleanup_probability` of writes) the TTL sweep — all in one transaction.
Upsert (ON CONFLICT DO UPDATE refreshing created_at), not the design
draft's DO NOTHING: with the read-side TTL filter above, DO NOTHING would
leave an expired row permanently blocking its own key — recomputes could
then never re-prime that request/result until a sweep happened to run.
DO UPDATE is equally race-safe under concurrent identical computes (last
write wins with identical content) and preserves the design's
no-refresh-on-READ property: only a write after a miss ever touches
created_at, a hit never does.

TTL cleanup is opportunistic, not scheduled (§2.3): no pg_cron, no
background thread — the tables self-bound purely from ordinary write
traffic, and correctness never depends on the sweep having run (the read
filter guarantees expired rows are never served). flush() TRUNCATEs both
tables; scripts/refresh_proposals.py calls it as the first step of every
version bump / base move.

Key-correctness verification (§2.3's stated implementation task): every
input that can change a compute result is covered by the key or by the
flush discipline —
  - track/stop infrastructure: pinned by scenario_id (scenario rows are
    immutable snapshots; edits mint new ids)
  - compositions/operators: keyed by composition_id
  - demand stopgap constants, emission factors, model formulas: version
    constants — changing them bumps ROUTE_BUILDER_/CALC_VERSION, which
    flushes (and the proposal_compute.py version guard backstops a
    forgotten flush)
  - static reference data (countries, country geometries): loaded into
    process memory at startup — a DB edit there is invisible to a fresh
    compute too until restart, so a cached result is never staler than
    the process serving it.

Cache tuning knobs live here, next to the only code that enforces them
(the §16 parameter-placement rule — api/config.py is for limits enforced
across blueprints, which these are not). Env-overridable per deployment
(documented in backend/docker/.env.example); constructor params exist for
tests (cleanup_probability=1.0 makes the sweep deterministic).

Public interface:
  ComputeCacheRepository().lookup(request_hash) -> dict | None
  ComputeCacheRepository().store(...)
  ComputeCacheRepository().sweep()
  ComputeCacheRepository().flush()
"""

from __future__ import annotations

import os
import random
from typing import Optional

import psycopg2
import psycopg2.extras

COMPUTE_CACHE_TTL_HOURS = float(os.environ.get("COMPUTE_CACHE_TTL_HOURS", "3"))
COMPUTE_CACHE_CLEANUP_PROBABILITY = float(
    os.environ.get("COMPUTE_CACHE_CLEANUP_PROBABILITY", "0.01")
)

_LOOKUP_SQL = """
    SELECT p.route_fingerprint,
           p.scenario_id,
           p.composition_id,
           p.resolved_request,
           p.suggested_stops,
           r.payload
    FROM proposals.compute_cache_pointer p
    JOIN proposals.compute_cache_result r
      USING (route_fingerprint, scenario_id, composition_id)
    WHERE p.request_hash = %(request_hash)s
      AND p.created_at >= now() - %(ttl_hours)s * interval '1 hour'
      AND r.created_at >= now() - %(ttl_hours)s * interval '1 hour'
"""

_STORE_RESULT_SQL = """
    INSERT INTO proposals.compute_cache_result
        (route_fingerprint, scenario_id, composition_id, payload)
    VALUES (%(route_fingerprint)s, %(scenario_id)s, %(composition_id)s,
            %(payload)s)
    ON CONFLICT (route_fingerprint, scenario_id, composition_id)
    DO UPDATE SET payload = EXCLUDED.payload, created_at = now()
"""

_STORE_POINTER_SQL = """
    INSERT INTO proposals.compute_cache_pointer
        (request_hash, route_fingerprint, scenario_id, composition_id,
         resolved_request, suggested_stops)
    VALUES (%(request_hash)s, %(route_fingerprint)s, %(scenario_id)s,
            %(composition_id)s, %(resolved_request)s, %(suggested_stops)s)
    ON CONFLICT (request_hash)
    DO UPDATE SET route_fingerprint = EXCLUDED.route_fingerprint,
                  scenario_id       = EXCLUDED.scenario_id,
                  composition_id    = EXCLUDED.composition_id,
                  resolved_request  = EXCLUDED.resolved_request,
                  suggested_stops   = EXCLUDED.suggested_stops,
                  created_at        = now()
"""


class ComputeCacheRepository:
    """Read/write access to the two §2.3 cache tables — thin connection
    wrapper mirroring ProposalRepository's construction (same env vars,
    one connection per process/worker). Errors propagate: the tables live
    in the same database every compute already depends on, so a failure
    here means the request was doomed regardless — and swallowing would
    hide a missing migration forever."""

    def __init__(
        self,
        ttl_hours: float = COMPUTE_CACHE_TTL_HOURS,
        cleanup_probability: float = COMPUTE_CACHE_CLEANUP_PROBABILITY,
    ) -> None:
        self._ttl_hours = ttl_hours
        self._cleanup_probability = cleanup_probability
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

    # -------------------------------------------------------------------------
    # Read
    # -------------------------------------------------------------------------

    def lookup(self, request_hash: str) -> Optional[dict]:
        """One joined pointer+result fetch, TTL-filtered. Returns
        {route_fingerprint, scenario_id, composition_id, resolved_request,
        suggested_stops, payload} or None on a miss. A pointer whose
        result row is gone (TTL raced between the two tables) simply
        fails the JOIN and reads as a miss."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    _LOOKUP_SQL,
                    {"request_hash": request_hash, "ttl_hours": self._ttl_hours},
                )
                row = cur.fetchone()
            self._conn.rollback()
        except Exception:
            # Never leave the long-lived singleton connection inside an
            # aborted transaction — one failed SELECT would otherwise
            # cascade "current transaction is aborted" into every later
            # request on this worker.
            self._conn.rollback()
            raise
        return dict(row) if row is not None else None

    # -------------------------------------------------------------------------
    # Write
    # -------------------------------------------------------------------------

    def store(
        self,
        request_hash: str,
        route_fingerprint: str,
        scenario_id: int,
        composition_id: str,
        resolved_request: dict,
        suggested_stops: Optional[list],
        payload: dict,
    ) -> None:
        """Upsert result then pointer (§2.3's write order), plus the
        sampled TTL sweep, in one transaction. suggested_stops is None
        for non-suggest requests (SQL NULL, distinct from an empty
        suggest-mode list)."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    _STORE_RESULT_SQL,
                    {
                        "route_fingerprint": route_fingerprint,
                        "scenario_id": scenario_id,
                        "composition_id": composition_id,
                        "payload": psycopg2.extras.Json(payload),
                    },
                )
                cur.execute(
                    _STORE_POINTER_SQL,
                    {
                        "request_hash": request_hash,
                        "route_fingerprint": route_fingerprint,
                        "scenario_id": scenario_id,
                        "composition_id": composition_id,
                        "resolved_request": psycopg2.extras.Json(resolved_request),
                        "suggested_stops": (
                            psycopg2.extras.Json(suggested_stops)
                            if suggested_stops is not None
                            else None
                        ),
                    },
                )
                if random.random() < self._cleanup_probability:
                    self._sweep(cur)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -------------------------------------------------------------------------
    # Maintenance
    # -------------------------------------------------------------------------

    def _sweep(self, cur) -> None:
        for table in ("compute_cache_pointer", "compute_cache_result"):
            cur.execute(
                f"DELETE FROM proposals.{table} "
                "WHERE created_at < now() - %(ttl_hours)s * interval '1 hour'",
                {"ttl_hours": self._ttl_hours},
            )

    def sweep(self) -> None:
        """The TTL sweep as a standalone transaction — the same DELETEs
        store() runs probabilistically. Exposed for tests and for any
        future external scheduler (a known non-goal today, §2.3)."""
        try:
            with self._cursor() as cur:
                self._sweep(cur)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def flush(self) -> None:
        """§2.3/§4.2: empties both cache tables — UNLOGGED, never a
        source of truth, always safe to TRUNCATE. Called by scripts/
        refresh_proposals.py as the first step of every version bump /
        base-scenario move (moved here from ProposalRepository in WP13:
        the tables now have a dedicated owning adapter)."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "TRUNCATE proposals.compute_cache_pointer, "
                    "proposals.compute_cache_result"
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
