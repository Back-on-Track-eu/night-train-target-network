"""
test_10_params_api.py
=====================
Response contracts for the three read-only parameter endpoints:

  GET /api/params/StopInfrastructures
  GET /api/params/TrackInfrastructures
  GET /api/params/compositions

Covers the response layout (descriptions/sources/defaults/count/entities),
field-object shape ({value, is_default, version, source_id}), is_default
propagation through the API, source deduplication via source_id, and the
?scenario_id= query parameter.
"""

import pytest
import requests

# Field names every track infrastructure entry must expose as field objects —
# mirrors TRACK_INFRA_FIELD_NAMES / params_serialize._TRACK_FIELD_CASTS.
TRACK_FIELD_NAMES = (
    "tac_eur_train_km",
    "parking_eur_day",
    "shunting_eur_event",
    "energy_price_eur_kwh",
    "terrain_score",
    "terrain_category",
    "hsr_allowed",
    "min_boarding_time_min",
    "min_alighting_time_min",
    "buffer_quota_per",
)


@pytest.fixture(scope="module")
def stops_body(api_base):
    resp = requests.get(f"{api_base}/api/params/StopInfrastructures", timeout=15)
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture(scope="module")
def tracks_body(api_base):
    resp = requests.get(f"{api_base}/api/params/TrackInfrastructures", timeout=15)
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture(scope="module")
def compositions_body(api_base):
    resp = requests.get(f"{api_base}/api/params/compositions", timeout=15)
    assert resp.status_code == 200
    return resp.json()


# =============================================================================
# StopInfrastructures
# =============================================================================


class TestStopInfrastructures:
    def test_response_layout(self, stops_body):
        """Top level carries descriptions, sources, default_stops, count, stops."""
        assert set(stops_body) >= {
            "descriptions",
            "sources",
            "default_stops",
            "count",
            "stops",
        }
        assert stops_body["count"] == len(stops_body["stops"])

    def test_stops_have_required_fields(self, stops_body):
        """Every stop exposes identity, location, and its charge field object."""
        required = {"stop_id", "name", "country_code", "lat", "lon", "stop_charge_eur"}
        for stop in stops_body["stops"]:
            missing = required - set(stop)
            assert missing == set(), f"Stop '{stop.get('stop_id')}' missing: {missing}"

    def test_stop_charge_is_field_object(self, stops_body):
        """stop_charge_eur is a field object: value + is_default (bool) +
        version + source_id."""
        for stop in stops_body["stops"]:
            charge = stop["stop_charge_eur"]
            assert isinstance(charge, dict), f"{stop['stop_id']}: not a field object"
            assert {"value", "is_default", "version", "source_id"} <= set(charge)
            assert isinstance(charge["is_default"], bool)

    def test_is_default_flags_via_api(self, stops_body):
        """SE_STOCKHOLM_C (NULL charge in seed) is is_default=True; Berlin
        (explicit charge) is is_default=False — provenance survives the API."""
        stops = {s["stop_id"]: s for s in stops_body["stops"]}
        assert stops["SE_STOCKHOLM_C"]["stop_charge_eur"]["is_default"] is True
        assert stops["DE_BERLIN_HBF"]["stop_charge_eur"]["is_default"] is False

    def test_global_default_present(self, stops_body):
        """The global default row (the one SE resolves against) is exposed
        under default_stops.global with a positive charge."""
        global_default = stops_body["default_stops"]["global"]
        assert global_default is not None
        assert global_default["stop_charge_eur"]["value"] > 0

    def test_source_ids_resolve(self, stops_body):
        """Every source_id referenced by a stop field resolves to an entry in
        the top-level sources map."""
        source_ids = (
            set(map(int, stops_body["sources"].keys()))
            if stops_body["sources"]
            else set()
        )
        for stop in stops_body["stops"]:
            sid = stop["stop_charge_eur"]["source_id"]
            if sid is not None:
                assert sid in source_ids, f"{stop['stop_id']}: dangling source_id {sid}"


# =============================================================================
# TrackInfrastructures
# =============================================================================


class TestTrackInfrastructures:
    def test_response_layout(self, tracks_body):
        """Top level carries descriptions, sources, default_track_infra,
        count, track_infrastructures."""
        assert set(tracks_body) >= {
            "descriptions",
            "sources",
            "default_track_infra",
            "count",
            "track_infrastructures",
        }
        assert tracks_body["count"] == len(tracks_body["track_infrastructures"])

    def test_every_field_is_field_object(self, tracks_body):
        """All ten track fields are field objects on every country entry —
        iterating the canonical field list guards against a field silently
        dropping out of the response (as shunting_eur_event once did)."""
        for track in tracks_body["track_infrastructures"]:
            for field in TRACK_FIELD_NAMES:
                assert isinstance(track.get(field), dict), (
                    f"{track['country_code']}.{field} is not a field object"
                )
                assert {"value", "is_default"} <= set(track[field])

    def test_default_row_covers_all_fields(self, tracks_body):
        """The EU-average default row exposes a value for all ten fields."""
        default = tracks_body["default_track_infra"]
        for field in TRACK_FIELD_NAMES:
            assert field in default
            assert default[field]["value"] is not None

    def test_is_default_flags_via_api(self, tracks_body):
        """SE tac (NULL in seed) is is_default=True; DE tac (explicit) is
        is_default=False."""
        tracks = {t["country_code"]: t for t in tracks_body["track_infrastructures"]}
        assert tracks["SE"]["tac_eur_train_km"]["is_default"] is True
        assert tracks["DE"]["tac_eur_train_km"]["is_default"] is False

    def test_scenario_id_pins_parameter_version(self, api_base, historical_scenario):
        """?scenario_id=<2026-baseline> returns DE's v1 snapshot values
        (tac=3.10), while the default request returns the base's v2
        (tac=5.40)."""
        base = requests.get(
            f"{api_base}/api/params/TrackInfrastructures", timeout=15
        ).json()
        historical = requests.get(
            f"{api_base}/api/params/TrackInfrastructures",
            params={"scenario_id": historical_scenario["scenario_id"]},
            timeout=15,
        ).json()

        de_base = next(
            t for t in base["track_infrastructures"] if t["country_code"] == "DE"
        )
        de_historical = next(
            t for t in historical["track_infrastructures"] if t["country_code"] == "DE"
        )
        assert de_base["tac_eur_train_km"]["value"] == pytest.approx(5.40, rel=1e-3)
        assert de_historical["tac_eur_train_km"]["value"] == pytest.approx(
            3.10, rel=1e-3
        )


# =============================================================================
# compositions
# =============================================================================


class TestCompositions:
    def test_response_layout(self, compositions_body):
        """Top level carries descriptions, sources, count, compositions,
        operators (the restructured shape)."""
        assert set(compositions_body) >= {
            "descriptions",
            "sources",
            "count",
            "compositions",
            "operators",
        }
        assert compositions_body["count"] == len(compositions_body["compositions"])

    def test_composition_sections_present(self, compositions_body):
        """Every composition carries the grouped sub-sections of the
        restructured response."""
        sections = {
            "routing",
            "staff",
            "energy",
            "capacity",
            "equipment",
            "coaches",
            "fixed_costs",
            "variable_km",
            "source_ids",
        }
        for comp in compositions_body["compositions"]:
            missing = sections - set(comp)
            assert missing == set(), f"{comp['comp_id']} missing sections: {missing}"

    def test_capacity_non_empty_with_places_and_density(self, compositions_body):
        """Every composition has at least one capacity class, each with a
        positive place count and positive density."""
        for comp in compositions_body["compositions"]:
            assert len(comp["capacity"]) > 0, f"{comp['comp_id']} has empty capacity"
            for cls, cap in comp["capacity"].items():
                assert cap["places"] > 0, f"{comp['comp_id']}.{cls}: places <= 0"
                assert cap["density"] > 0, f"{comp['comp_id']}.{cls}: density <= 0"

    def test_coach_list_matches_count(self, compositions_body):
        """coaches.count equals the length of coaches.list, and positions are
        unique within a composition."""
        for comp in compositions_body["compositions"]:
            coaches = comp["coaches"]
            assert coaches["count"] == len(coaches["list"])
            positions = [c["position"] for c in coaches["list"]]
            assert len(positions) == len(set(positions)), (
                f"{comp['comp_id']}: duplicate coach positions"
            )

    def test_operators_referenced_by_compositions(self, compositions_body):
        """Every composition's operator_id resolves to an entry in the
        top-level operators list, which carries the staff cost rates."""
        operators = {o["operator_id"]: o for o in compositions_body["operators"]}
        for comp in compositions_body["compositions"]:
            op = operators.get(comp["operator_id"])
            assert op is not None, f"{comp['comp_id']}: unknown operator"
            assert op["driver_costs_eur_h"] > 0
            assert op["crew_costs_eur_h"] > 0

    def test_indicative_kpis_present(self, compositions_body):
        """At least one composition carries indicative KPIs (placeholder
        figures today — see calc_indicative_figures.py — but non-zero)."""
        with_ind = [
            c
            for c in compositions_body["compositions"]
            if c.get("indicative") is not None
        ]
        assert len(with_ind) >= 1
        for comp in with_ind:
            kpis = comp["indicative"]["kpis"]
            assert kpis["cost_eur_per_train_km"] > 0
            assert len(kpis["cost_eur_per_place_km_by_class"]) > 0
            assert all(v > 0 for v in kpis["cost_eur_per_place_km_by_class"].values())