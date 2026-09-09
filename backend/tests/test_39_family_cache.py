"""
test_39_family_cache.py
=======================
The member cache (family.members, adapters/family/member_cache.py) behind
compute_member(), plus the one thing the two family caches share: a
flush.

Hit/miss semantics are exercised in-process through compute_member() with
the cache ON — the same call the family's views endpoint, publish and
compare make — against a known-cold table: repeat requests hit, every
output-changing field misses, an omitted field and its explicit default
share one row, and the measure set is part of the key. Expiry is
simulated by back-dating rows; the write-path sweep is made deterministic
with cleanup_probability=1.0. The document cache's own contract is
test_42's; only its flush is here.

Until WP18 B2b this was test_39_compute_cache.py over the two-table cache
under proposals; the semantics are the same, the tables are one.
"""

from __future__ import annotations

import os

import pytest

from adapters.family.member_cache import FamilyMemberCache
from models.params import MeasureSet
from models.route.model import DEFAULT_SCHEDULE_MODE
from tests.conftest import DB_CONFIG, STOPS_BERLIN_WIEN
from tests.helpers import _member_compute

BASE_REQUEST = {
    "stops": STOPS_BERLIN_WIEN,
    "composition_id": "NEW-BAL-7",
    "auto_stop_addition": "off",
}

_MEMBERS = "family.members"
_DOCUMENTS = "family.documents"


def cached(body: dict, **kwargs) -> tuple[dict, bool]:
    """compute_member with the member cache ON — (payload, cache_hit)."""
    return _member_compute()(body, **kwargs)


def _count(db_cur, db_conn, table: str) -> int:
    """Row count that immediately ends its own read transaction. The
    rollback is load-bearing, not hygiene: psycopg2 implicitly opens a
    transaction on the first statement, and an open reader holds ACCESS
    SHARE on the table — which blocks flush()'s TRUNCATE (ACCESS
    EXCLUSIVE) from the adapter's separate connection until the test
    body ends."""
    db_cur.execute(f"SELECT count(*) AS n FROM {table}")
    n = db_cur.fetchone()["n"]
    db_conn.rollback()
    return n


def _backdate(db_cur, db_conn, hours: int) -> None:
    """Ages every member row past (or toward) the TTL — the deterministic
    stand-in for waiting."""
    db_cur.execute(
        f"UPDATE {_MEMBERS} SET created_at = created_at - make_interval(hours => %s)",
        (hours,),
    )
    db_conn.commit()


@pytest.fixture(autouse=True)
def flushed_cache(db_cur, db_conn):
    """Empty caches before every test — hit/miss assertions below are all
    relative to a known-cold start."""
    db_cur.execute(f"TRUNCATE {_MEMBERS}, {_DOCUMENTS}")
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
    yield FamilyMemberCache()


# =============================================================================
# Hit / miss semantics through compute_member()
# =============================================================================


class TestHitMiss:
    def test_repeat_request_hits_and_is_identical(self):
        first, hit_1 = cached(BASE_REQUEST)
        second, hit_2 = cached(BASE_REQUEST)
        assert (hit_1, hit_2) == (False, True)
        assert second == first

    def test_miss_on_each_output_changing_field(self, hsr_scenario):
        cached(BASE_REQUEST)
        # Every field here changes the OUTPUT, so every one must miss.
        # schedule_mode is absent on purpose: "alwaysDaily" is the only
        # valid value (models/route/timetable.py VALID_SCHEDULE_MODES), so
        # there is nothing to vary until a second mode exists.
        for patch in (
            {"composition_id": "REF-BUD-6"},
            {"routing_mode": "simpleRouting"},
            {"scenario_id": hsr_scenario["scenario_id"]},
            {"auto_stop_addition": "suggest"},
            {"stops": list(reversed(STOPS_BERLIN_WIEN))},
            {
                "expert_timetable": {
                    "outbound": {"departure": {"mode": "shift", "shift_min": 20}}
                }
            },
        ):
            _, hit = cached({**BASE_REQUEST, **patch})
            assert hit is False, patch
        _, hit = cached(BASE_REQUEST)
        assert hit is True

    def test_omitted_field_and_explicit_default_share_one_entry(self, db_cur, db_conn):
        """Hashing the RESOLVED request is what makes these converge."""
        cached(BASE_REQUEST)
        _, hit = cached({**BASE_REQUEST, "schedule_mode": DEFAULT_SCHEDULE_MODE})
        assert hit is True
        assert _count(db_cur, db_conn, _MEMBERS) == 1

    def test_suggest_and_off_are_two_rows(self, db_cur, db_conn):
        """One table now: a request that asks for suggestions and one that
        does not store their payloads separately, and each hits itself."""
        cached(BASE_REQUEST)
        suggest = {**BASE_REQUEST, "auto_stop_addition": "suggest"}
        _, miss = cached(suggest)
        _, hit = cached(suggest)
        assert (miss, hit) == (False, True)
        assert _count(db_cur, db_conn, _MEMBERS) == 2

    def test_measure_set_is_part_of_the_key(self, db_cur, db_conn):
        """The echo names no measure set, so the key must — two members of
        one scenario under different measures never share a row. A second
        set is not seeded, so one is made up here; at identity factors its
        payload equals the empty set's, and the row is still separate."""
        cached(BASE_REQUEST)
        other = MeasureSet(
            measure_set_id=999,
            key="test-only",
            vat_exempt=True,
            energy_tax_exempt=False,
            tac_direct_cost=False,
        )
        _, miss = cached(BASE_REQUEST, measures=other)
        _, hit = cached(BASE_REQUEST, measures=other)
        assert (miss, hit) == (False, True)
        assert _count(db_cur, db_conn, _MEMBERS) == 2
        db_cur.execute(f"SELECT measure_set_id FROM {_MEMBERS} ORDER BY 1")
        assert [r["measure_set_id"] for r in db_cur.fetchall()] == [1, 999]
        db_conn.rollback()


# =============================================================================
# TTL expiry, version guard, flush
# =============================================================================


class TestExpiryAndFlush:
    def test_ttl_expiry_is_a_miss_then_reprimes(self, db_cur, db_conn):
        assert cached(BASE_REQUEST)[1] is False
        assert cached(BASE_REQUEST)[1] is True
        _backdate(db_cur, db_conn, hours=4)  # past the 3 h default TTL
        # Expired-but-unswept rows are never served...
        assert cached(BASE_REQUEST)[1] is False
        # ...and that recompute's upsert re-primed the row (store() is
        # ON CONFLICT DO UPDATE, not DO NOTHING).
        assert cached(BASE_REQUEST)[1] is True

    def test_stale_version_payload_is_a_miss(self, db_cur, db_conn):
        """Defense in depth for a forgotten version-bump flush: a cached
        payload computed under another CALC_VERSION must never be
        served."""
        assert cached(BASE_REQUEST)[1] is False
        db_cur.execute(
            f"UPDATE {_MEMBERS} SET payload ="
            " jsonb_set(payload, '{calc_version}', '\"0.0.1\"')"
        )
        db_conn.commit()
        assert cached(BASE_REQUEST)[1] is False
        assert cached(BASE_REQUEST)[1] is True

    def test_flush_empties_the_members(self, db_cur, db_conn, cache_repo):
        assert cached(BASE_REQUEST)[1] is False
        assert _count(db_cur, db_conn, _MEMBERS) == 1
        # Safe only because _count() closed its read transaction —
        # TRUNCATE would otherwise wait on this connection's ACCESS
        # SHARE locks (see _count's docstring).
        cache_repo.flush()
        assert _count(db_cur, db_conn, _MEMBERS) == 0
        assert cached(BASE_REQUEST)[1] is False


# =============================================================================
# TTL sweep — adapter-level, deterministic
# =============================================================================


def _insert_synthetic_row(db_cur, db_conn, request_hash: str, age_hours: int) -> None:
    """A hand-written member row (no FKs, so dummy identities are fine),
    aged as requested."""
    db_cur.execute(
        f"INSERT INTO {_MEMBERS}"
        " (request_hash, route_fingerprint, scenario_id, measure_set_id,"
        "  composition_id, resolved_request, payload, created_at)"
        " VALUES (%s, %s, 1, 1, 'TEST-COMP', '{}'::jsonb, '{}'::jsonb,"
        "         now() - make_interval(hours => %s))",
        (request_hash, f"sha256:{request_hash}", age_hours),
    )
    db_conn.commit()


class TestSweep:
    def test_sweep_deletes_only_expired_rows(self, db_cur, db_conn, cache_repo):
        _insert_synthetic_row(db_cur, db_conn, "old", age_hours=4)
        _insert_synthetic_row(db_cur, db_conn, "fresh", age_hours=0)
        cache_repo.sweep()
        db_cur.execute(f"SELECT request_hash FROM {_MEMBERS}")
        assert [row["request_hash"] for row in db_cur.fetchall()] == ["fresh"]
        db_conn.rollback()

    def test_sweep_rides_the_write_path(self, db_cur, db_conn):
        """cleanup_probability=1.0 makes the '1% of writes' sampling
        certain: a single store() must take the expired rows with it."""
        _insert_synthetic_row(db_cur, db_conn, "old", age_hours=4)
        repo = FamilyMemberCache(cleanup_probability=1.0)
        repo.store(
            request_hash="fresh",
            route_fingerprint="sha256:fresh",
            scenario_id=1,
            measure_set_id=1,
            composition_id="TEST-COMP",
            resolved_request={},
            suggested_stops=None,
            payload={},
        )
        db_cur.execute(f"SELECT request_hash FROM {_MEMBERS}")
        assert [row["request_hash"] for row in db_cur.fetchall()] == ["fresh"]
        db_conn.rollback()
