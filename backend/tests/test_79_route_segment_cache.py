"""
test_79_route_segment_cache.py
==============================
Route-segment cache: pure round-trip/key tests plus a live test against
the Docker stack proving (a) a cache-served trip is physics-identical to
a live-routed one and (b) a miss self-populates the table.
"""

from __future__ import annotations

import pytest

from models.route.routing.rail_router import (
    DEFAULT_ROUTING_GRAPH_KEY,
    RoutedLeg,
    route_variant_key,
)
from models.route.routing.segment_cache import (
    leg_from_cached,
    segment_from_leg,
    segment_from_db_row,
    segment_to_csv_row,
    CSV_COLUMNS,
)


def _sample_leg() -> RoutedLeg:
    return RoutedLeg(
        geometry=[[13.4, 52.5], [12.0, 52.0], [9.7, 52.4]],
        distance_m=250_000,
        driving_time_min=95,
        dynamics_time_min=0,
        buffer_time_min=0,
        energy_kwh=0.0,
        country_distance_shares={"DE": 0.8, "UNK": 0.2},
        country_time_shares={"DE": 0.82, "UNK": 0.18},
        countries=["DE", "UNK"],
        passages=["STOREBAELT"],
        country_distance_m={"DE": 200_000.0, "UNK": 50_000.0},
        country_driving_ms={"DE": 4_674_000.0, "UNK": 1_026_000.0},
    )


class TestRoundTrip:
    def test_leg_survives_store_and_load_forward(self):
        leg = _sample_leg()
        restored = leg_from_cached(segment_from_leg(leg, reverse=False), reverse=False)
        assert restored.geometry == leg.geometry
        assert restored.distance_m == leg.distance_m
        assert restored.driving_time_min == leg.driving_time_min
        assert restored.countries == leg.countries
        assert restored.passages == leg.passages
        assert restored.country_driving_ms == leg.country_driving_ms
        # Shares re-derive from the raw dicts, not the stored floats.
        assert restored.country_distance_shares["DE"] == pytest.approx(0.8)
        # Scenario-dependent fields must come back empty for route_trip().
        assert restored.buffer_time_min == 0
        assert restored.dynamics_time_min == 0
        assert restored.energy_kwh == 0.0

    def test_reverse_flips_path_but_not_physics(self):
        leg = _sample_leg()
        seg = segment_from_leg(leg, reverse=False)
        reversed_leg = leg_from_cached(seg, reverse=True)
        assert reversed_leg.geometry == list(reversed(leg.geometry))
        assert reversed_leg.countries == list(reversed(leg.countries))
        assert reversed_leg.distance_m == leg.distance_m
        assert reversed_leg.driving_time_min == leg.driving_time_min

    def test_store_reverse_then_load_reverse_is_identity(self):
        leg = _sample_leg()
        seg = segment_from_leg(leg, reverse=True)  # leg was routed hi→lo
        assert leg_from_cached(seg, reverse=True).geometry == leg.geometry

    def test_csv_row_matches_contract(self):
        seg = segment_from_leg(_sample_leg(), reverse=False)
        row = segment_to_csv_row("A", "B", "night_train-abc", seg)
        assert len(row) == len(CSV_COLUMNS)
        # A DB row (psycopg2-decoded JSONB) restores the same segment.
        import json

        db_row = dict(zip(CSV_COLUMNS, row))
        for col in (
            "country_distance_m",
            "country_driving_ms",
            "countries",
            "passages",
            "geometry",
        ):
            db_row[col] = json.loads(db_row[col])
        assert segment_from_db_row(db_row) == seg


class TestVariantKey:
    def test_key_order_independent(self):
        m1 = {"speed": [{"if": "true", "limit_to": "200"}], "priority": []}
        m2 = {"priority": [], "speed": [{"if": "true", "limit_to": "200"}]}
        assert route_variant_key("night_train", m1) == route_variant_key(
            "night_train", m2
        )

    def test_key_differs_by_model_and_profile(self):
        m200 = {"speed": [{"if": "true", "limit_to": "200"}]}
        m230 = {"speed": [{"if": "true", "limit_to": "230"}]}
        assert route_variant_key("night_train", m200) != route_variant_key(
            "night_train", m230
        )
        assert route_variant_key("night_train", m200) != route_variant_key(
            "night_train_1520", m200
        )


class TestCachedEqualsLive:
    """Live: route a pair on a cache-less router, then twice on a cached
    one — the first cached call misses and stores, the second hits;
    all three must agree on physics. Needs the Docker stack."""

    def test_miss_stores_then_hit_matches_live(self):
        from adapters.data_loader_from_db import DBDataLoader
        from adapters.route_segment_repository import RouteSegmentRepository
        from models.route.routing.rail_router import (
            CountryIndex,
            PassageIndex,
            RailRouter,
            build_router_stops,
            route_trip,
        )

        graph_key = "test_" + DEFAULT_ROUTING_GRAPH_KEY  # own namespace, purged below
        repo = RouteSegmentRepository()
        loader = DBDataLoader()
        ci = CountryIndex(loader.get_country_geometries())
        pi = PassageIndex(loader.get_passage_geometries())
        live_router = RailRouter(ci, pi)
        cached_router = RailRouter(ci, pi, graph_key=graph_key, segment_repository=repo)
        try:
            stop_infra = loader.build_all_stops()
            comp = next(iter(loader.build_all_compositions().all().values()))
            tracks = loader.build_all_tracks()
            # Two German catalog stops — densest, best-connected part of
            # the graph, so the pair routes on any healthy stack.
            stop_ids = [
                sid
                for sid, s in stop_infra.all().items()
                if s.stop_country_code == "DE"
            ][:2]
            stops = build_router_stops(stop_ids, stop_infra)

            live = route_trip(live_router, stops, comp, tracks, "fullRouting")
            first = route_trip(cached_router, stops, comp, tracks, "fullRouting")
            assert repo.count(graph_key) == 1, "miss must store one segment"
            second = route_trip(cached_router, stops, comp, tracks, "fullRouting")

            for a, b in ((live[0], first[0]), (live[0], second[0])):
                assert b.distance_m == a.distance_m
                assert b.driving_time_min == a.driving_time_min
                assert b.buffer_time_min == a.buffer_time_min
                assert b.dynamics_time_min == a.dynamics_time_min
                assert b.countries == a.countries
                assert b.passages == a.passages
                assert b.geometry == a.geometry
        finally:
            repo.purge(graph_key)
            repo.close()
