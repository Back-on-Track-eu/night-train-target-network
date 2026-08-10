"""
test_39_compute_cache.py
=========================
The §2.3 compute cache (WP13). Every test runs behind its own cache
flush (autouse fixture below), so hit/miss assertions are deterministic
regardless of what conftest's session route fixtures or other test files
have already computed — which is also why the OTHER suites only assert
cache_hit's shape, never its value.

Covers the WP13 "testable by" list: hit on a repeated identical request;
hit via a DIFFERENT request converging on the same result (pointer ->
shared result row); miss on every output-changing field; the response
request echo always matching the actual request (omitted field ==
explicit default); TTL expiry (via backdating created_at — deterministic,
no env restart); the version guard (stale-version payloads read as
misses); flush emptying both maps; and the TTL sweep, driven
deterministically through ComputeCacheRepository(cleanup_probability=1.0).

Berlin–Wien (2 stops) rather than the 3-stop corridor: the cheapest
route this suite can compute, and it computes several — every miss here
is a real routing + evaluation pass.
"""

from __future__ import annotations

import os

import pytest

from adapters.proposal.compute_cache import ComputeCacheRepository
from models.route.model import DEFAULT_SCHEDULE_MODE
from tests.conftest import DB_CONFIG, STOPS_BERLIN_WIEN
from tests.helpers import compute

BASE_REQUEST = {
    "stops": STOPS_BERLIN_WIEN,
    "composition_id": "NEW-BAL-7",
    # Pinned off so the base request and its suggest-mode twin below
    # resolve to the same physical route (suggest never inserts stops),
    # which the convergence test relies on.
    "auto_stop_addition": "off",
}

_POINTER = "proposals.compute_cache_pointer"
_RESULT = "proposals.compute_cache_result"


def _count(db_cur, db_conn, table: str) -> int:
    """Row count that immediately ends its own read transaction. The
    rollback is load-bearing, not hygiene: psycopg2 implicitly opens a
    transaction on the first statement, and an open reader holds ACCESS
    SHARE on the table — which blocks flush()'s TRUNCATE (ACCESS
    EXCLUSIVE) from the adapter's separate connection until the test
    body ends. Self-cleaning here means no call site can recreate that
    stall."""
    db_cur.execute(f"SELECT count(*) AS n FROM {table}")
    n = db_cur.fetchone()["n"]
    db_conn.rollback()
    return n


def _backdate(db_cur, db_conn, hours: int) -> None:
    """Ages every cache row past (or toward) the TTL — the deterministic
    stand-in for waiting."""
    for table in (_POINTER, _RESULT):
        db_cur.execute(
            f"UPDATE {table} SET created_at = created_at - make_interval(hours => %s)",
            (hours,),
        )
    db_conn.commit()


@pytest.fixture(autouse=True)
def flushed_cache(db_cur, db_conn):
    """Empty cache before every test — hit/miss assertions below are all
    relative to a known-cold start."""
    db_cur.execute(f"TRUNCATE {_POINTER}, {_RESULT}")
    db_conn.commit()
    yield


@pytest.fixture(scope="module")
def cache_repo():
    """A direct adapter handle for the flush/sweep tests — same host-side
    env bootstrapping as conftest's loader fixture."""
    os.environ.setdefault("POSTGRES_HOST", DB_CONFIG["host"])
    os.environ.setdefault("POSTGRES_PORT", str(DB_CONFIG["port"]))
    os.environ.setdefault("POSTGRES_DB", DB_CONFIG["dbname"])
    os.environ.setdefault("POSTGRES_USER", DB_CONFIG["user"])
    os.environ.setdefault("POSTGRES_PASSWORD", DB_CONFIG["password"])
    repo = ComputeCacheRepository()
    yield repo
    repo.close()


# =============================================================================
# Hit / miss semantics through POST /api/proposal/calc
# =============================================================================


class TestHitMiss:
    def test_repeat_request_hits_and_is_identical(self, api_base):
        first = compute(api_base, **BASE_REQUEST)
        second = compute(api_base, **BASE_REQUEST)
        assert first["cache_hit"] is False
        assert second["cache_hit"] is True
        # A hit is byte-for-byte the same response as the compute it
        # replays — cache_hit itself is the single legitimate difference.
        first.pop("cache_hit")
        second.pop("cache_hit")
        assert first == second

    def test_miss_on_each_output_changing_field(self, api_base):
        base = compute(api_base, **BASE_REQUEST)
        assert base["cache_hit"] is False
        variations = [
            {**BASE_REQUEST, "stops": list(reversed(STOPS_BERLIN_WIEN))},
            {**BASE_REQUEST, "composition_id": "REF-BAL-9"},
            {**BASE_REQUEST, "routing_mode": "simpleRouting"},
        ]
        for body in variations:
            varied = compute(api_base, **body)
            assert varied["cache_hit"] is False, body
        # ...and none of them evicted or shadowed the base entry.
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is True

    def test_convergent_requests_share_one_result_row(self, api_base, db_cur, db_conn):
        """§2.3's storage dedup: 'off' and 'suggest' are distinct
        requests (distinct pointer rows, each computed once) that resolve
        to the identical route — so the result map holds ONE row, and the
        request-specific suggested_stops lives on the suggest pointer
        only."""
        off = compute(api_base, **BASE_REQUEST)
        suggest = compute(api_base, **{**BASE_REQUEST, "auto_stop_addition": "suggest"})
        assert off["cache_hit"] is False
        assert suggest["cache_hit"] is False
        assert off["route_fingerprint"] == suggest["route_fingerprint"]
        assert _count(db_cur, db_conn, _POINTER) == 2
        assert _count(db_cur, db_conn, _RESULT) == 1

        off_hit = compute(api_base, **BASE_REQUEST)
        suggest_hit = compute(
            api_base, **{**BASE_REQUEST, "auto_stop_addition": "suggest"}
        )
        assert off_hit["cache_hit"] is True
        assert suggest_hit["cache_hit"] is True
        assert "suggested_stops" not in off_hit
        assert "suggested_stops" in suggest_hit

    def test_omitted_field_and_explicit_default_share_one_entry(
        self, api_base, db_cur, db_conn
    ):
        """The hash is over the RESOLVED request, so posting a default
        explicitly is the same cache entry as omitting it — and the echo
        on the hit carries the resolved form either way."""
        omitted = compute(api_base, **BASE_REQUEST)
        explicit = compute(
            api_base, **{**BASE_REQUEST, "schedule_mode": DEFAULT_SCHEDULE_MODE}
        )
        assert omitted["cache_hit"] is False
        assert explicit["cache_hit"] is True
        assert explicit["request"] == omitted["request"]
        assert explicit["request"]["schedule_mode"] == DEFAULT_SCHEDULE_MODE
        assert _count(db_cur, db_conn, _POINTER) == 1


# =============================================================================
# TTL, version guard, flush
# =============================================================================


class TestExpiryAndFlush:
    def test_ttl_expiry_is_a_miss_then_reprimes(self, api_base, db_cur, db_conn):
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is False
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is True
        _backdate(db_cur, db_conn, hours=4)  # past the 3 h default TTL
        # Expired-but-unswept rows are never served...
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is False
        # ...and that recompute's upsert re-primed the entry (the reason
        # store() is ON CONFLICT DO UPDATE, not the design draft's DO
        # NOTHING — see the WP13 notes).
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is True

    def test_stale_version_payload_is_a_miss(self, api_base, db_cur, db_conn):
        """Defense in depth for a forgotten version-bump flush: a cached
        payload computed under another CALC_VERSION must never be
        served."""
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is False
        db_cur.execute(
            f"UPDATE {_RESULT} SET payload ="
            " jsonb_set(payload::jsonb, '{calc_version}', '\"0.0.1\"')::json"
        )
        db_conn.commit()
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is False
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is True

    def test_flush_empties_both_maps(self, api_base, db_cur, db_conn, cache_repo):
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is False
        assert _count(db_cur, db_conn, _POINTER) == 1
        assert _count(db_cur, db_conn, _RESULT) == 1
        # Safe only because _count() closed its read transaction —
        # TRUNCATE would otherwise wait on this connection's ACCESS
        # SHARE locks (see _count's docstring).
        cache_repo.flush()
        assert _count(db_cur, db_conn, _POINTER) == 0
        assert _count(db_cur, db_conn, _RESULT) == 0
        assert compute(api_base, **BASE_REQUEST)["cache_hit"] is False


# =============================================================================
# TTL sweep — adapter-level, deterministic
# =============================================================================


def _insert_synthetic_rows(db_cur, db_conn, request_hash: str, age_hours: int) -> None:
    """Hand-written pointer+result pair (the cache tables have no FKs, so
    dummy identities are fine), aged as requested."""
    triple = (f"sha256:{request_hash}", 1, "TEST-COMP")
    db_cur.execute(
        f"INSERT INTO {_RESULT}"
        " (route_fingerprint, scenario_id, composition_id, payload, created_at)"
        " VALUES (%s, %s, %s, '{}'::json,"
        "         now() - make_interval(hours => %s))",
        (*triple, age_hours),
    )
    db_cur.execute(
        f"INSERT INTO {_POINTER}"
        " (request_hash, route_fingerprint, scenario_id, composition_id,"
        "  resolved_request, created_at)"
        " VALUES (%s, %s, %s, %s, '{}'::json,"
        "         now() - make_interval(hours => %s))",
        (request_hash, *triple, age_hours),
    )
    db_conn.commit()


class TestSweep:
    def test_sweep_deletes_only_expired_rows(self, db_cur, db_conn, cache_repo):
        _insert_synthetic_rows(db_cur, db_conn, "old", age_hours=4)
        _insert_synthetic_rows(db_cur, db_conn, "fresh", age_hours=0)
        cache_repo.sweep()
        db_cur.execute(f"SELECT request_hash FROM {_POINTER}")
        assert [row["request_hash"] for row in db_cur.fetchall()] == ["fresh"]
        assert _count(db_cur, db_conn, _RESULT) == 1

    def test_sweep_rides_the_write_path(self, db_cur, db_conn):
        """cleanup_probability=1.0 makes the §2.3 '1% of writes' sampling
        certain: a single store() must take the expired rows with it."""
        _insert_synthetic_rows(db_cur, db_conn, "old", age_hours=4)
        repo = ComputeCacheRepository(cleanup_probability=1.0)
        try:
            repo.store(
                request_hash="fresh",
                route_fingerprint="sha256:fresh",
                scenario_id=1,
                composition_id="TEST-COMP",
                resolved_request={},
                suggested_stops=None,
                payload={},
            )
        finally:
            repo.close()
        db_cur.execute(f"SELECT request_hash FROM {_POINTER}")
        assert [row["request_hash"] for row in db_cur.fetchall()] == ["fresh"]
        assert _count(db_cur, db_conn, _RESULT) == 1
