"""
test_versioning.py
==================
Tests for parameter versioning, source provenance, and default value
handling across the full stack.

Covers:
  - Loader only loads is_current=True rows (version isolation)
  - param_versions key format and field completeness
  - is_default flag on track/stop rows with NULL fields
  - Source description/URL populated in field objects
  - LaTeX formula structure in calc_formulas
  - calc_steps inputs/results mathematical consistency
  - param_versions version numbers match DB row versions
"""

import pytest
import requests

ROUTE_URL = "/api/route/planOrUpdate"
EVAL_URL  = "/api/evaluation/calc"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_route(api_base, stops=None, comp_id="STD-7.1", proposal_id=300):
    if stops is None:
        stops = [
            {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
            {"stop_id": "AT_WIEN_HBF",   "stop_type": "alighting"},
        ]
    resp = requests.post(f"{api_base}{ROUTE_URL}", json={
        "proposal_id":      proposal_id,
        "proposal_version": 1,
        "stops":            stops,
        "composition_id":   comp_id,
        "departure_time":   "21:00",
    }, timeout=60)
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["route"]


def _eval(api_base, route, operating_days=360):
    demand = {"od_pairs": [
        {"origin_stop_id": "DE_BERLIN_HBF", "destination_stop_id": "AT_WIEN_HBF",
         "class_main": "Couchette", "places_sold": 30, "avg_price": 89.0},
    ]}
    trip_ids = [t["trip_id"] for t in route["trips"]]
    resp = requests.post(f"{api_base}{EVAL_URL}", json={
        "route":               route,
        "route_demand":        {tid: demand for tid in trip_ids},
        "operating_days_year": operating_days,
    }, timeout=30)
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["result"]


# ---------------------------------------------------------------------------
# Version isolation — loader only loads is_current=True
# ---------------------------------------------------------------------------

class TestVersionIsolation:

    def test_loader_uses_current_version_only(self, loader):
        """
        DE has two rows: version=2 (is_current=True, tac=5.40) and
        version=1 (is_current=False, tac=3.10).
        Loader must return tac=5.40.
        """
        tracks, _ = loader.build_all_tracks()
        de = tracks.get("DE")
        assert de is not None
        assert de.tac_eur_train_km == pytest.approx(5.40, rel=1e-3), \
            f"Expected current version tac=5.40, got {de.tac_eur_train_km}"

    def test_old_version_not_loaded(self, loader):
        """Old DE row has tac=3.10 — must never appear in loaded data."""
        tracks, _ = loader.build_all_tracks()
        de = tracks.get("DE")
        assert de is not None
        assert de.tac_eur_train_km != pytest.approx(3.10, rel=1e-3), \
            "Old DE version (tac=3.10) should not be loaded"

    def test_db_has_both_de_versions(self, db_cur):
        """Verify both versions exist in DB to confirm test setup is correct."""
        db_cur.execute("""
            SELECT track_infra_version, is_current, track_tac_eur_train_km
            FROM input_params.track_infrastructures
            WHERE country_code = 'DE'
            ORDER BY track_infra_version
        """)
        rows = db_cur.fetchall()
        assert len(rows) == 2, f"Expected 2 DE rows, got {len(rows)}"
        versions = [r["track_infra_version"] for r in rows]
        assert 1 in versions and 2 in versions

    def test_only_one_current_per_country(self, db_cur):
        """Each country has at most one is_current=True row."""
        db_cur.execute("""
            SELECT country_code, COUNT(*) AS n
            FROM input_params.track_infrastructures
            WHERE is_current = TRUE
            GROUP BY country_code
            HAVING COUNT(*) > 1
        """)
        dupes = [r["country_code"] for r in db_cur.fetchall()]
        assert dupes == [], f"Countries with multiple current rows: {dupes}"

    def test_param_version_number_matches_db(self, loader, db_cur):
        """param_versions version field should match the DB row version."""
        tracks, pv = loader.build_all_tracks()

        db_cur.execute("""
            SELECT track_infra_version FROM input_params.track_infrastructures
            WHERE country_code = 'DE' AND is_current = TRUE
        """)
        db_version = db_cur.fetchone()["track_infra_version"]

        de_tac_key = "track_infra:DE:tac_eur_train_km"
        entry = pv.get(de_tac_key)
        assert entry is not None, f"No param_versions entry for {de_tac_key}"
        assert entry.version == db_version, \
            f"param_versions version {entry.version} != DB version {db_version}"


# ---------------------------------------------------------------------------
# param_versions structure and content
# ---------------------------------------------------------------------------

class TestParamVersionsStructure:

    def test_param_versions_key_format(self, loader):
        """Keys must follow 'table_short:entity_id:field_name' format."""
        tracks, pv = loader.build_all_tracks()
        for key in pv.entries:
            parts = key.split(":")
            assert len(parts) == 3, \
                f"param_versions key '{key}' does not follow 'table:entity:field' format"

    def test_param_versions_has_value(self, loader):
        """Every entry has a non-None value."""
        tracks, pv = loader.build_all_tracks()
        for key, entry in pv.entries.items():
            assert entry.value is not None, \
                f"param_versions['{key}'].value is None"

    def test_param_versions_has_version_int(self, loader):
        """Every entry has a positive integer version."""
        tracks, pv = loader.build_all_tracks()
        for key, entry in pv.entries.items():
            assert isinstance(entry.version, int) and entry.version > 0, \
                f"param_versions['{key}'].version = {entry.version!r}"

    def test_param_versions_has_description(self, loader):
        """Every entry should have a description (from DB column comment)."""
        tracks, pv = loader.build_all_tracks()
        # At least some entries should have descriptions
        with_desc = [k for k, v in pv.entries.items() if v.description]
        assert len(with_desc) > 0, \
            "No param_versions entries have descriptions"

    def test_param_versions_source_when_not_default(self, loader):
        """Non-default entries should have a source object."""
        tracks, pv = loader.build_all_tracks()
        de_tac = pv.get("track_infra:DE:tac_eur_train_km")
        if de_tac and not de_tac.is_default:
            assert de_tac.source is not None, \
                "Non-default param_versions entry should have a source"
            assert de_tac.source.source_description, \
                "Source description should be non-empty"

    def test_is_default_false_for_explicit_values(self, loader):
        """DE tac is explicitly set — is_default must be False."""
        tracks, pv = loader.build_all_tracks()
        de_tac = pv.get("track_infra:DE:tac_eur_train_km")
        assert de_tac is not None
        assert de_tac.is_default is False

    def test_is_default_true_for_null_values(self, loader):
        """SE tac is NULL in DB — is_default must be True."""
        tracks, pv = loader.build_all_tracks()
        se_tac = pv.get("track_infra:SE:tac_eur_train_km")
        assert se_tac is not None, "No SE tac entry in param_versions"
        assert se_tac.is_default is True, \
            f"SE tac should be is_default=True (NULL in DB), got {se_tac.is_default}"

    def test_default_value_matches_defaults_table(self, loader, db_cur):
        """SE tac value should equal the default table value."""
        tracks, pv = loader.build_all_tracks()
        se_tac = pv.get("track_infra:SE:tac_eur_train_km")
        assert se_tac is not None

        db_cur.execute("""
            SELECT track_tac_eur_train_km
            FROM input_params.track_infrastructure_defaults
            WHERE is_current = TRUE
        """)
        default_val = float(db_cur.fetchone()["track_tac_eur_train_km"])
        assert float(se_tac.value) == pytest.approx(default_val, rel=1e-3), \
            f"SE tac {se_tac.value} != default table value {default_val}"


# ---------------------------------------------------------------------------
# Stop default value handling
# ---------------------------------------------------------------------------

class TestStopDefaultValues:

    def test_se_stop_charge_is_default(self, loader):
        """SE_STOCKHOLM_C has NULL stop_charge — should use global default."""
        stops, pv = loader.build_all_stops()
        se_stop = stops.get("SE_STOCKHOLM_C")
        assert se_stop is not None

        se_charge = pv.get("stop_infra:SE_STOCKHOLM_C:stop_charge_eur")
        assert se_charge is not None
        assert se_charge.is_default is True, \
            f"SE stop charge should be is_default=True"

    def test_se_stop_charge_value_matches_global_default(self, loader, db_cur):
        """SE_STOCKHOLM_C charge should equal global default (11.28)."""
        stops, pv = loader.build_all_stops()
        se_charge = pv.get("stop_infra:SE_STOCKHOLM_C:stop_charge_eur")
        assert se_charge is not None

        db_cur.execute("""
            SELECT stop_charge_eur FROM input_params.stop_infrastructure_defaults
            WHERE country_code IS NULL AND is_current = TRUE
        """)
        default_val = float(db_cur.fetchone()["stop_charge_eur"])
        assert float(se_charge.value) == pytest.approx(default_val, rel=1e-3)

    def test_berlin_stop_charge_is_not_default(self, loader):
        """Berlin has explicit stop_charge — is_default must be False."""
        stops, pv = loader.build_all_stops()
        berlin_charge = pv.get("stop_infra:DE_BERLIN_HBF:stop_charge_eur")
        assert berlin_charge is not None
        assert berlin_charge.is_default is False

    def test_api_stop_charge_is_default_flag(self, api_base):
        """API response for SE stop should have is_default=True on stop_charge_eur."""
        resp = requests.get(f"{api_base}/api/params/StopInfrastructures")
        assert resp.status_code == 200
        stops = {s["stop_id"]: s for s in resp.json()["stops"]}

        se = stops.get("SE_STOCKHOLM_C")
        assert se is not None
        assert se["stop_charge_eur"]["is_default"] is True

        berlin = stops.get("DE_BERLIN_HBF")
        assert berlin is not None
        assert berlin["stop_charge_eur"]["is_default"] is False

    def test_api_track_infra_se_tac_is_default(self, api_base):
        """API response for SE track infra should have is_default=True on tac."""
        resp = requests.get(f"{api_base}/api/params/TrackInfrastructures")
        assert resp.status_code == 200
        tracks = {t["country_code"]: t for t in resp.json()["track_infrastructures"]}

        se = tracks.get("SE")
        assert se is not None
        assert se["tac_eur_train_km"]["is_default"] is True

        de = tracks.get("DE")
        assert de is not None
        assert de["tac_eur_train_km"]["is_default"] is False


# ---------------------------------------------------------------------------
# LaTeX and formula descriptions
# ---------------------------------------------------------------------------

class TestCalcFormulas:

    def test_all_formulas_have_latex(self, api_base):
        """Every entry in calc_formulas has a non-empty latex field."""
        route = _build_route(api_base, proposal_id=310)
        result = _eval(api_base, route)
        for key, formula in result["calc_formulas"].items():
            assert formula.get("latex"), \
                f"calc_formulas['{key}'] has empty latex"

    def test_all_formulas_have_description(self, api_base):
        """Every entry in calc_formulas has a non-empty description field."""
        route = _build_route(api_base, proposal_id=311)
        result = _eval(api_base, route)
        for key, formula in result["calc_formulas"].items():
            assert formula.get("description"), \
                f"calc_formulas['{key}'] has empty description"

    def test_latex_strings_look_like_latex(self, api_base):
        """LaTeX strings should contain backslash (LaTeX command marker)."""
        route = _build_route(api_base, proposal_id=312)
        result = _eval(api_base, route)
        latex_count = sum(
            1 for f in result["calc_formulas"].values()
            if "\\" in f.get("latex", "")
        )
        total = len(result["calc_formulas"])
        assert latex_count >= total * 0.8, \
            f"Only {latex_count}/{total} calc_formulas contain backslash (LaTeX)"

    def test_calc_steps_reference_known_formula_keys(self, api_base):
        """Every formula_key in calc_steps must exist in calc_formulas."""
        route = _build_route(api_base, proposal_id=313)
        result = _eval(api_base, route)
        known_keys = set(result["calc_formulas"].keys())
        for step in result["summary"]["per_day"]["calc_steps"]:
            assert step["formula_key"] in known_keys, \
                f"calc_step uses unknown formula_key '{step['formula_key']}'"

    def test_calc_steps_result_consistent_with_inputs(self, api_base):
        """For revenue steps: result ≈ places_sold × avg_price."""
        route = _build_route(api_base, proposal_id=314)
        result = _eval(api_base, route)
        for step in result["summary"]["per_day"]["calc_steps"]:
            if step["formula_key"] == "revenue_per_class":
                inp = step["inputs"]
                expected = inp.get("places_sold", 0) * inp.get("avg_price", 0)
                assert step["result"] == pytest.approx(expected, rel=1e-3), \
                    f"revenue_per_class step: {inp} → {step['result']} ≠ {expected}"

    def test_tac_calc_step_consistent(self, api_base):
        """TAC step: result ≈ distance_km × tac_eur_train_km."""
        route = _build_route(api_base, proposal_id=315)
        result = _eval(api_base, route)
        for step in result["summary"]["per_day"]["calc_steps"]:
            if step["formula_key"] == "track_access_charge":
                inp = step["inputs"]
                expected = inp.get("distance_km", 0) * inp.get("tac_eur_train_km", 0)
                assert step["result"] == pytest.approx(expected, rel=1e-3), \
                    f"track_access_charge step inconsistent: {inp}"

    def test_energy_calc_step_consistent(self, api_base):
        """Energy step: result ≈ energy_kwh × energy_price_eur_kwh."""
        route = _build_route(api_base, proposal_id=316)
        result = _eval(api_base, route)
        for step in result["summary"]["per_day"]["calc_steps"]:
            if step["formula_key"] == "energy_cost":
                inp = step["inputs"]
                expected = inp.get("energy_kwh", 0) * inp.get("energy_price_eur_kwh", 0)
                assert step["result"] == pytest.approx(expected, rel=1e-3), \
                    f"energy_cost step inconsistent: {inp}"


# ---------------------------------------------------------------------------
# Model versions
# ---------------------------------------------------------------------------

class TestModelVersions:

    def test_model_versions_has_route_builder(self, api_base):
        route = _build_route(api_base, proposal_id=320)
        for trip in route["trips"]:
            mv = trip["model_versions"]
            assert "route_builder" in mv, f"Missing route_builder in {mv}"

    def test_model_versions_has_energy_calc(self, api_base):
        route = _build_route(api_base, proposal_id=321)
        for trip in route["trips"]:
            mv = trip["model_versions"]
            assert "energy_calc" in mv, f"Missing energy_calc in {mv}"

    def test_model_versions_are_semver_strings(self, api_base):
        """Version strings should look like X.Y.Z."""
        import re
        route = _build_route(api_base, proposal_id=322)
        for trip in route["trips"]:
            for key, ver in trip["model_versions"].items():
                assert re.match(r"^\d+\.\d+\.\d+$", ver), \
                    f"model_versions['{key}'] = '{ver}' is not semver"

    def test_eval_result_has_model_versions(self, api_base):
        route = _build_route(api_base, proposal_id=323)
        result = _eval(api_base, route)
        assert "model_versions" in result
        assert len(result["model_versions"]) > 0

    def test_git_sha_injected_in_ci(self):
        """
        GIT_SHA should be injected by CI — not 'unknown'.
        This test is skipped locally but enforced in CI via GITHUB_SHA env var.
        """
        import os
        if not os.environ.get("GITHUB_SHA"):
            pytest.skip("Not running in CI — GIT_SHA injection not required locally")

        from models.route.version    import GIT_SHA as ROUTE_SHA
        from models.energy.version   import GIT_SHA as ENERGY_SHA
        from models.evaluation.version import GIT_SHA as CALC_SHA

        expected = os.environ["GITHUB_SHA"]
        assert ROUTE_SHA  == expected, f"route/version.py GIT_SHA not injected: '{ROUTE_SHA}'"
        assert ENERGY_SHA == expected, f"energy/version.py GIT_SHA not injected: '{ENERGY_SHA}'"
        assert CALC_SHA   == expected, f"evaluation/version.py GIT_SHA not injected: '{CALC_SHA}'"