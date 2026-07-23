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

    def test_service_areas_reduce_wo_service_totals(self, compositions_body):
        """REF-PREM-12 carries a dining car: wo_service totals must be
        strictly smaller than full totals; pure-revenue compositions are
        equal both ways."""
        comps = {c["comp_id"]: c for c in compositions_body["compositions"]}
        # the dining car carries zero revenue space — visible in the
        # coach_types catalog (composition wo_service totals are internal)
        ark = compositions_body["coach_types"]["ARkimmbz"]
        assert ark["length_wo_service_m"] == 0.0
        assert ark["places_total"] == 0 and ark["crew_factor"] == 2.0
        assert comps["NEW-BAL-7"]["staff"]["zugchef_crew_factor"] == 1.19
        assert comps["NEW-BAL-14"]["staff"]["zugchef_crew_factor"] == 2.38
        # allocation value pin: REF-PREM-12 seat carries its dining-car
        # per-head slice on top of the pure space share
        prem_mix = comps["REF-PREM-12"]["cost_allocation"]["by_class_main"]
        assert prem_mix["Seat"] == pytest.approx(0.0944, abs=0.001)

    def test_coach_types_catalog(self, compositions_body):
        """Top-level coach_types: every referenced type once, equipment
        keys complete, class_ids resolve into the classes section."""
        cts = compositions_body["coach_types"]
        assert len(cts) == 24
        all_class_ids = {
            e["class_id"] for lst in compositions_body["classes"].values() for e in lst
        }
        for ct in cts.values():
            assert set(ct["equipment"]) == {
                "has_wifi",
                "has_bikes",
                "has_climatization",
                "has_plugs",
            }
            for cid in ct["class_ids"]:
                assert cid in all_class_ids

    def test_classes_catalog_grouped_by_class_main(self, compositions_body):
        """Top-level classes section: every class_id once, grouped by
        class_main, with carrying coach type and places."""
        classes = compositions_body["classes"]
        assert set(classes) <= {"Seat", "Couchette", "Sleeper", "Capsule"}
        all_ids = [e["class_id"] for lst in classes.values() for e in lst]
        assert len(all_ids) == len(set(all_ids)), "class_ids must be unique"
        assert len(all_ids) == 25  # one per coach section (2026-07-22)
        for cm, lst in classes.items():
            for e in lst:
                assert e["places"] > 0 and e["coach_type_id"]

    def test_capacity_non_empty_with_places_and_density(self, compositions_body):
        """Every composition has at least one capacity class, each with a
        positive place count and positive density."""
        for comp in compositions_body["compositions"]:
            assert len(comp["capacity"]["by_class"]) > 0, (
                f"{comp['comp_id']} has empty capacity"
            )
            for cls, cap in comp["capacity"]["by_class"].items():
                assert cap["places"] > 0, f"{comp['comp_id']}.{cls}: places <= 0"
                assert cap["density_length_m_per_place"] > 0, (
                    f"{comp['comp_id']}.{cls}: length density <= 0"
                )
                assert cap["density_weight_t_per_place"] > 0, (
                    f"{comp['comp_id']}.{cls}: weight density <= 0"
                )

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
        """Indicative block carries the seeded calibration KPIs (per-train-km
        and ct-per-place-km) plus the reference profile; the per-class
        placeholder breakdown is gone since CALC_VERSION 0.9.7."""
        comps = {c["comp_id"]: c for c in compositions_body["compositions"]}
        with_ind = [c for c in comps.values() if c.get("indicative")]
        assert with_ind, "no composition returned indicative KPIs"
        for c in with_ind:
            kpis = c["indicative"]["kpis"]
            assert kpis["cost_eur_per_train_km"] > 0
            assert kpis["cost_ct_per_place_km"] > 0
            assert "cost_eur_per_place_km_by_class" not in kpis
            assert c["material_strategy"] in ("new", "refurbished")
            assert c["routing"]["total_length_m"] > 0
            r = c["routing"]
            assert "total_length_wo_service_m" not in r  # internal only
            assert r["n_locos"] >= 1
            s = c["staff"]
            assert s["zugchef_crew_factor"] > 0
            assert s["crew_factor_total"] == pytest.approx(
                s["crew_factor_coaches"] + s["zugchef_crew_factor"], abs=1e-3
            )
            assert set(c["cost_allocation"]) == {"by_class_main"}
            assert "food_and_beverages" in c["equipment"]
            cap = c["capacity"]
            assert cap["avg_density_length_m_per_place"] > 0
            assert cap["avg_density_weight_t_per_place"] > 0
            assert "energy" not in c  # dropped from the API for now
            assert "length_cost_prop" not in c["cost_allocation"]
            mix = c["cost_allocation"]["by_class_main"]
            assert sum(mix.values()) == pytest.approx(1.0, abs=0.001)
            cap = c["capacity"]
            assert cap["total_places"] == sum(
                v["places"] for v in cap["by_class"].values()
            )
            sph = c["staff"]["costs_per_hour"]
            assert sph["total_staff_eur_h"] == pytest.approx(
                sph["driver_eur_h"] * c["staff"]["driver_factor"]
                + sph["crew_eur_h"] * c["staff"]["crew_factor_total"],
                abs=0.05,
            )
            assert len(c["coaches"]["list"]) == c["coaches"]["count"]
            for entry in c["coaches"]["list"]:
                assert entry["coach_type_id"] in compositions_body["coach_types"]
        # the KPI basis is carried by the column-comment descriptions
        desc = compositions_body["descriptions"]
        ind_desc = desc["indicative"]["kpis"]["cost_eur_per_train_km"]
        assert "S41" in ind_desc and "2032" in ind_desc
