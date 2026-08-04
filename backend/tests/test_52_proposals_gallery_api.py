"""
test_52_proposals_gallery_api.py
=================================
POST /api/proposals — the full §7.1 gallery/map filter contract (WP6):
generic range/list/array/substring filters over proposal_summaries,
trip_windows, bbox, sort, windowed total, and the sectioned `include`
response.

test_50_proposals_api.py keeps the basic sectioned-envelope smoke tests
(user_ids filter, pagination, unknown-key rejection); this module is the
one-filter-of-each-kind + map-sections coverage WP6 adds on top.

Isolation: same discipline as test_50 — publishing commits outside the
suite's per-test rollback, so this module purges published proposals
before/after itself (the permanent seed proposal is preserved).
"""

import pytest
import requests

from tests.helpers import (
    PROPOSALS_URL,
    compute,
    likes_url,
    publish,
    purge_saved_proposals,
    stop_times,
)

_STOPS = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]
_COMPOSITION = "NEW-BAL-7"


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn, script_headers):
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def computed(api_base):
    """The raw compute response backing `published` — kept around so
    trip_windows tests can build an exact-match window from the real
    schedule rather than guessing."""
    return compute(api_base, _STOPS, _COMPOSITION)


@pytest.fixture(scope="module")
def published(api_base, script_headers, computed):
    return publish(
        api_base,
        computed["request"],
        name="Berlin \u2013 Wien (gallery test)",
        headers=script_headers,
    )


def _gallery(api_base, **body):
    resp = requests.post(f"{api_base}{PROPOSALS_URL}", json=body, timeout=15)
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()


def _proposal_ids(gallery_response) -> set[int]:
    return {p["proposal_id"] for p in gallery_response["summaries"]["proposals"]}


# =============================================================================
# One filter of each kind
# =============================================================================


class TestFilterKinds:
    def test_range_filter_matches(self, api_base, published):
        # summaries carries total_distance_km directly — read the real
        # value back once, then probe a range around it and one excluding
        # it. filter by proposal_ids (not user_ids) so the read-back can't
        # accidentally pick a different proposal of the same user should
        # one exist by this point in the module.
        summary = _gallery(
            api_base, filter={"proposal_ids": [published["proposal_id"]]}
        )["summaries"]["proposals"][0]
        km = summary["total_distance_km"]

        hit = _gallery(
            api_base, filter={"total_distance_km": {"min": km - 1, "max": km + 1}}
        )
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"total_distance_km": {"max": km - 1}})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_list_filter_composition_ids(self, api_base, published):
        hit = _gallery(api_base, filter={"composition_ids": [_COMPOSITION]})
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"composition_ids": ["REF-BAL-9"]})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_substring_name_filter(self, api_base, published):
        hit = _gallery(api_base, filter={"name": "wien"})  # case-insensitive
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"name": "nonexistent-corridor-xyz"})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_array_overlap_countries_filter(self, api_base, published):
        hit = _gallery(api_base, filter={"countries": ["DE"]})
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"countries": ["XX"]})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_array_overlap_stop_ids_filter(self, api_base, published):
        hit = _gallery(api_base, filter={"stop_ids": ["DE_BERLIN_HBF"]})
        assert published["proposal_id"] in _proposal_ids(hit)

    def test_proposal_ids_filter(self, api_base, published):
        hit = _gallery(api_base, filter={"proposal_ids": [published["proposal_id"]]})
        assert _proposal_ids(hit) == {published["proposal_id"]}

        miss = _gallery(api_base, filter={"proposal_ids": [-1]})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_array_filter_any_vs_all_mode(self, api_base, script_headers):
        """countries: plain list / mode "any" is OR (overlap); mode "all"
        is AND (every listed country must be touched). Doesn't hardcode
        which real countries a corridor crosses (auto_stop_addition and
        in-transit country attribution — §5.4's country_distance_shares —
        both mean a route can touch countries beyond its named stops, e.g.
        Zurich sits near the DE/CH/FR tripoint); instead reads back the
        proposal's actual `countries` and builds the any/all cases from
        that plus one country code ("XX") guaranteed absent."""
        via_zuerich = publish(
            api_base,
            compute(
                api_base,
                ["DE_BERLIN_HBF", "CH_ZUERICH_HB", "AT_WIEN_HBF"],
                _COMPOSITION,
            )["request"],
            name="Berlin \u2013 Wien via Z\u00fcrich (gallery test)",
            headers=script_headers,
        )
        pid = via_zuerich["proposal_id"]
        summary = _gallery(api_base, filter={"proposal_ids": [pid]})["summaries"][
            "proposals"
        ][0]
        actual_countries = summary["countries"]
        assert len(actual_countries) >= 1

        any_hit = _gallery(api_base, filter={"countries": [actual_countries[0], "XX"]})
        assert pid in _proposal_ids(any_hit)

        all_hit = _gallery(
            api_base, filter={"countries": {"values": actual_countries, "mode": "all"}}
        )
        assert pid in _proposal_ids(all_hit)

        all_miss = _gallery(
            api_base,
            filter={"countries": {"values": actual_countries + ["XX"], "mode": "all"}},
        )
        assert pid not in _proposal_ids(all_miss)

    def test_array_filter_invalid_mode_rejected(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"filter": {"countries": {"values": ["DE"], "mode": "sideways"}}},
            timeout=15,
        )
        assert resp.status_code == 400

    def test_created_at_range_filter(self, api_base, published):
        # filter by proposal_ids, not user_ids — by this point in the
        # module the same script user may own more than one proposal
        # (test_array_filter_any_vs_all_mode's via_zuerich), and the
        # default sort (updated_at DESC) would silently pick the wrong
        # one at index [0].
        created_at = _gallery(
            api_base, filter={"proposal_ids": [published["proposal_id"]]}
        )["summaries"]["proposals"][0]["created_at"]

        hit = _gallery(api_base, filter={"created_at": {"min": created_at}})
        assert published["proposal_id"] in _proposal_ids(hit)

        # a lower bound one year in the future excludes everything already seeded
        miss = _gallery(
            api_base, filter={"created_at": {"min": "2099-01-01T00:00:00+00:00"}}
        )
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_updated_at_range_filter(self, api_base, published):
        miss = _gallery(
            api_base, filter={"updated_at": {"max": "2000-01-01T00:00:00+00:00"}}
        )
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_version_and_scenario_filters_no_longer_accepted(self, api_base):
        """WP6.1: route_builder_version/calc_version/scenario_id are
        internal/analytical and every gallery row is always on the
        current base scenario by construction — none of the three are
        filterable anymore."""
        for key in ("route_builder_versions", "calc_versions", "scenario_ids"):
            resp = requests.post(
                f"{api_base}{PROPOSALS_URL}", json={"filter": {key: ["x"]}}, timeout=15
            )
            assert resp.status_code == 400, key

    def test_sources_existing_rejected(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"filter": {"sources": ["existing"]}},
            timeout=15,
        )
        assert resp.status_code == 400


# =============================================================================
# trip_windows
# =============================================================================


class TestTripWindows:
    def _departure_window(self, computed, stop_id: str, pad_min: int = 5):
        trip = computed["route"]["trip_pairs"][0]["outbound"]
        stops = stop_times(trip)
        stop = next(s for s in stops if s["stop_id"] == stop_id)
        dep = (
            stop["departure_time_min"]
            if stop["departure_time_min"] is not None
            else stop["arrival_time_min"]
        )
        lo_h, lo_m = divmod(max(dep - pad_min, 0), 60)
        hi_h, hi_m = divmod(dep + pad_min, 60)
        return f"{lo_h:02d}:{lo_m:02d}", f"{hi_h:02d}:{hi_m:02d}"

    def test_matching_window(self, api_base, published, computed):
        frm, to = self._departure_window(computed, "DE_BERLIN_HBF")
        hit = _gallery(
            api_base,
            filter={
                "trip_windows": [
                    {"stop_id": "DE_BERLIN_HBF", "departure": {"from": frm, "to": to}}
                ]
            },
        )
        assert published["proposal_id"] in _proposal_ids(hit)

    def test_non_matching_window(self, api_base, published):
        miss = _gallery(
            api_base,
            filter={
                "trip_windows": [
                    {
                        "stop_id": "DE_BERLIN_HBF",
                        "departure": {"from": "03:00", "to": "03:01"},
                    }
                ]
            },
        )
        assert published["proposal_id"] not in _proposal_ids(miss)


# =============================================================================
# bbox
# =============================================================================


class TestBbox:
    def test_bbox_intersecting_route(self, api_base, published):
        # Loosely covers the DACH region — the Berlin-Wien corridor sits inside.
        hit = _gallery(api_base, filter={"bbox": [8.0, 45.0, 20.0, 55.0]})
        assert published["proposal_id"] in _proposal_ids(hit)

    def test_bbox_not_intersecting_route(self, api_base, published):
        # Somewhere over the South Atlantic — no proposal route reaches here.
        miss = _gallery(api_base, filter={"bbox": [-40.0, -40.0, -30.0, -30.0]})
        assert published["proposal_id"] not in _proposal_ids(miss)


# =============================================================================
# Sort + windowed total
# =============================================================================


class TestSortAndPagination:
    def test_sort_by_total_distance_km(self, api_base):
        body = _gallery(api_base, sort=[{"by": "total_distance_km", "dir": "asc"}])
        values = [p["total_distance_km"] for p in body["summaries"]["proposals"]]
        assert values == sorted(values)

    def test_sort_rejects_unknown_column(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"sort": [{"by": "not_a_column"}]},
            timeout=15,
        )
        assert resp.status_code == 400

    def test_windowed_total_matches_filtered_count_not_page_size(
        self, api_base, published
    ):
        body = _gallery(
            api_base, filter={"user_ids": [published["user_id"]]}, limit=1, offset=0
        )
        assert len(body["summaries"]["proposals"]) <= 1
        assert body["summaries"]["total"] >= 1


# =============================================================================
# include — sectioned response, only requested sections computed
# =============================================================================


class TestIncludeSections:
    def test_default_include_is_summaries_only(self, api_base):
        body = _gallery(api_base)
        assert set(body) == {"summaries"}

    def test_map_lines_geojson(self, api_base, published):
        # published's request under default auto_stop_addition ("add")
        # commonly inserts intermediate stops between the two named
        # endpoints, so the corridor is N literal stop-pair segments, not
        # necessarily one — map_lines groups by literal segment, not by
        # "logical journey". Assert every segment the proposal appears on
        # is well-formed, not that there's exactly one.
        body = _gallery(
            api_base,
            filter={"proposal_ids": [published["proposal_id"]]},
            include=["map_lines"],
        )
        assert set(body) == {"map_lines"}
        assert body["map_lines"]["type"] == "FeatureCollection"
        matching = [
            f
            for f in body["map_lines"]["features"]
            if published["proposal_id"] in f["properties"]["proposal_ids"]
        ]
        assert len(matching) >= 1
        for feature in matching:
            assert feature["properties"]["proposal_count"] >= 1
            assert feature["geometry"]["type"] == "LineString"

    def test_map_lines_thickness_reflects_shared_corridor(
        self, api_base, script_headers, published
    ):
        """A second proposal on the exact same corridor (identical stop
        list, different composition) should land on the SAME map_lines
        feature(s) as `published`, with proposal_count bumped and both
        ids present on every one of them — the whole point of
        aggregating by corridor rather than by proposal. Identical stop
        lists under the same default auto_stop_addition behaviour insert
        the same intermediate stops, so every literal segment is shared,
        not just one."""
        second = publish(
            api_base,
            compute(api_base, _STOPS, "REF-BAL-9")["request"],
            name="Berlin \u2013 Wien (gallery test, second composition)",
            headers=script_headers,
        )
        body = _gallery(
            api_base,
            filter={"proposal_ids": [published["proposal_id"], second["proposal_id"]]},
            include=["map_lines"],
        )
        matching = [
            f
            for f in body["map_lines"]["features"]
            if published["proposal_id"] in f["properties"]["proposal_ids"]
        ]
        assert len(matching) >= 1
        for feature in matching:
            assert second["proposal_id"] in feature["properties"]["proposal_ids"]
            assert feature["properties"]["proposal_count"] >= 2

    def test_map_stop_counts(self, api_base, published):
        body = _gallery(
            api_base,
            filter={"user_ids": [published["user_id"]]},
            include=["map_stop_counts"],
        )
        stop_ids = {row["stop_id"] for row in body["map_stop_counts"]}
        assert "DE_BERLIN_HBF" in stop_ids
        berlin = next(
            r for r in body["map_stop_counts"] if r["stop_id"] == "DE_BERLIN_HBF"
        )
        assert berlin["lat"] is not None and berlin["lon"] is not None
        assert berlin["n"] >= 1

    def test_map_country_counts(self, api_base, published):
        body = _gallery(
            api_base,
            filter={"user_ids": [published["user_id"]]},
            include=["map_country_counts"],
        )
        assert body["map_country_counts"]["type"] == "FeatureCollection"
        by_country = {
            f["properties"]["country"]: f
            for f in body["map_country_counts"]["features"]
        }
        assert by_country["DE"]["properties"]["n"] >= 1
        assert by_country["AT"]["properties"]["n"] >= 1
        # both DE and AT have a seeded Natural Earth border polygon
        assert by_country["DE"]["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert by_country["AT"]["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_multiple_sections_together(self, api_base):
        body = _gallery(api_base, include=["summaries", "map_country_counts"])
        assert set(body) == {"summaries", "map_country_counts"}

    def test_unknown_include_section_rejected(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"include": ["bogus_section"]},
            timeout=15,
        )
        assert resp.status_code == 400


# =============================================================================
# likes_count — live-joined from proposals.likes, not a summary column
# =============================================================================


class TestLikesCount:
    def test_likes_count_appears_in_summary_and_is_filterable(
        self, api_base, script_headers, published
    ):
        resp = requests.post(
            f"{api_base}{likes_url(published['proposal_id'])}",
            timeout=10,
            headers=script_headers,
        )
        assert resp.status_code == 200

        body = _gallery(api_base, filter={"user_ids": [published["user_id"]]})
        row = next(
            p
            for p in body["summaries"]["proposals"]
            if p["proposal_id"] == published["proposal_id"]
        )
        assert row["likes_count"] >= 1

        hit = _gallery(api_base, filter={"likes_count": {"min": 1}})
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"likes_count": {"min": 999}})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_sort_by_likes_count(self, api_base):
        body = _gallery(api_base, sort=[{"by": "likes_count", "dir": "desc"}])
        values = [p["likes_count"] for p in body["summaries"]["proposals"]]
        assert values == sorted(values, reverse=True)
