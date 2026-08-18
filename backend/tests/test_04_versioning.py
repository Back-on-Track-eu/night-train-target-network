"""
test_04_versioning.py
=====================
Tests for the scenario versioning system and parameter provenance —
full-table snapshot resolution, default value handling, param_versions
structure, scenario pinning, and CI model-version injection.

Fixture values relied on (see db/dev/seed.py):
  - DE track infra exists at three snapshot versions: v2 tac=5.40 (base
    scenario's pinned version) and v1 tac=3.10 (pinned by the historical
    scenario '2026-baseline').
  - SE tac_eur_train_km is NULL at every version → resolves from the
    EU-average default row (is_default=True).
  - osm:n25948183 stop_charge_eur is NULL → resolves from the global
    stop default; osm:n3856100103 has an explicit charge.
"""

import os

import pytest

from models.params import (
    ENERGY_PRICE_FIELD_NAMES,
    FACILITY_FIELD_NAMES,
    TAC_COMPONENT_FIELD_NAMES,
)

# =============================================================================
# Version isolation — loader loads exactly the scenario-pinned snapshot
# =============================================================================


class TestVersionIsolation:
    def test_loader_uses_base_pinned_version(self, loader):
        """Loader with no scenario_id resolves to the base scenario and
        returns DE's v2 value (tac=5.40) — not the older snapshot."""
        de = loader.build_all_tracks().get("DE")
        assert de is not None
        assert de.tac_eur_train_km == pytest.approx(5.40, rel=1e-3)

    def test_loader_pinned_to_historical_returns_old_snapshot(
        self, loader, historical_scenario
    ):
        """Loader pinned to the 2026 Base Line scenario returns DE's v1
        value (tac=3.10) — exact-match resolution on the pinned version,
        no fallback to 'latest'."""
        de = loader.build_all_tracks(historical_scenario["scenario_id"]).get("DE")
        assert de is not None
        assert de.tac_eur_train_km == pytest.approx(3.10, rel=1e-3)

    def test_db_has_all_three_de_versions(self, db_cur):
        """All three DE snapshot rows exist — confirms the fixture the two
        tests above depend on is actually in place."""
        db_cur.execute("""
            SELECT track_infra_version FROM input_params.track_infrastructures
            WHERE country_code = 'DE' ORDER BY track_infra_version
            """)
        versions = [r["track_infra_version"] for r in db_cur.fetchall()]
        assert versions == [1, 2, 3]

    def test_full_table_snapshot_invariant(self, db_cur):
        """Every track_infrastructures version is a COMPLETE snapshot — the
        same set of countries at every version (the full-table-snapshot
        write contract). A version that dropped or gained a country partway
        would break exact-match resolution."""
        db_cur.execute("""
            SELECT track_infra_version, COUNT(DISTINCT country_code) AS n_countries
            FROM input_params.track_infrastructures
            GROUP BY track_infra_version
            """)
        counts = {r["track_infra_version"]: r["n_countries"] for r in db_cur.fetchall()}
        assert len(set(counts.values())) == 1, (
            f"Snapshot invariant broken — country count differs by version: {counts}"
        )

    def test_param_version_number_matches_db(self, loader, base_scenario):
        """A param_versions entry's version equals the scenario's pinned
        table version — provenance points at the row actually loaded."""
        tracks = loader.build_all_tracks()
        entry = tracks.param_versions.get("track_infra:DE:tac_eur_train_km")
        assert entry is not None
        assert entry.version == base_scenario["track_infrastructures_version"]


# =============================================================================
# param_versions structure and default provenance (loader level)
# =============================================================================


class TestParamProvenance:
    def test_param_versions_key_format(self, loader):
        """Every key follows 'table_short:entity_id:field_name'."""
        tracks = loader.build_all_tracks()
        for key in tracks.param_versions.entries:
            assert len(key.split(":")) == 3, (
                f"param_versions key '{key}' does not follow 'table:entity:field'"
            )

    def test_param_versions_entries_complete(self, loader):
        """Every entry carries a non-None value and a positive int version.

        Two component groups are the documented exceptions, for the same
        reason: an empty value states that the country does not levy that
        term, so None there is data rather than a gap.

        - The track access components
          (models/infrastructure/tac/calib/TAC_CALIBRATION.md).
        - The energy price terms beyond the day rate
          (models/infrastructure/energy_pricing/calib/
          ENERGY_PRICING_CALIBRATION.md) — twenty-five of twenty-eight
          countries charge one electricity rate around the clock, and
          roughly half levy no catenary charge.
        - The service-facility terms
          (models/infrastructure/facility/calib/FACILITY_CALIBRATION.md) — a
          country prices a stabling occupation in exactly one unit, so the two
          rate columns for the units it does not use are NULL by construction.

        Every other track parameter is always resolved, either from the
        country's own row or from the EU-average default, and a None among
        them would mean the loader dropped one.
        """
        tracks = loader.build_all_tracks()
        nullable = (
            set(TAC_COMPONENT_FIELD_NAMES)
            | set(ENERGY_PRICE_FIELD_NAMES)
            | set(FACILITY_FIELD_NAMES)
        )
        for key, entry in tracks.param_versions.entries.items():
            field = key.split(":")[-1]
            if field not in nullable:
                assert entry.value is not None, f"param_versions['{key}'].value is None"
            assert isinstance(entry.version, int) and entry.version > 0, (
                f"param_versions['{key}'].version = {entry.version!r}"
            )

    def test_tac_component_group_resolves_whole_or_not_at_all(self, loader):
        """A country either has its own tariff or is priced entirely from
        the EU median — never a mixture. The group-null rule in
        DBDataLoader._row_to_track is what a lone 'not levied here' NULL
        depends on to survive resolution intact."""
        tracks = loader.build_all_tracks()
        for country_code in tracks.all():
            flags = {
                tracks.param_versions.get(
                    f"track_infra:{country_code}:{field}"
                ).is_default
                for field in TAC_COMPONENT_FIELD_NAMES
            }
            assert len(flags) == 1, (
                f"{country_code}: TAC components resolved inconsistently — "
                "the component group must default as a whole"
            )

    def test_field_descriptions_populated(self, loader):
        """Track infra field descriptions (from DB column comments) are
        captured once per collection — the params API serves them from here."""
        tracks = loader.build_all_tracks()
        with_desc = [f for f, d in tracks.descriptions.fields.items() if d]
        assert len(with_desc) > 0, "No track_infra field descriptions found"

    def test_explicit_value_is_not_default_and_has_source(self, loader):
        """DE tac is explicitly seeded — is_default=False, with a populated
        source object."""
        tracks = loader.build_all_tracks()
        de_tac = tracks.param_versions.get("track_infra:DE:tac_eur_train_km")
        assert de_tac is not None
        assert de_tac.is_default is False
        assert de_tac.source is not None
        assert de_tac.source.source_description

    def test_null_value_resolves_from_default(self, loader, db_cur, base_scenario):
        """SE tac is NULL in the DB — is_default=True, and the resolved
        value equals the pinned default row's value."""
        tracks = loader.build_all_tracks()
        se_tac = tracks.param_versions.get("track_infra:SE:tac_eur_train_km")
        assert se_tac is not None
        assert se_tac.is_default is True

        db_cur.execute(
            "SELECT track_tac_eur_train_km FROM input_params.track_infrastructure_defaults "
            "WHERE track_infra_default_version = %s",
            (base_scenario["track_infrastructure_defaults_version"],),
        )
        default_val = float(db_cur.fetchone()["track_tac_eur_train_km"])
        assert float(se_tac.value) == pytest.approx(default_val, rel=1e-3)

    def test_stop_null_charge_resolves_from_global_default(
        self, loader, db_cur, base_scenario
    ):
        """osm:n25948183 stop_charge is NULL — is_default=True and the value
        equals the global default row's charge."""
        stops = loader.build_all_stops()
        se_charge = stops.param_versions.get("stop_infra:osm:n25948183:stop_charge_eur")
        assert se_charge is not None
        assert se_charge.is_default is True

        db_cur.execute(
            "SELECT stop_charge_eur FROM input_params.stop_infrastructure_defaults "
            "WHERE country_code IS NULL AND stop_infra_default_version = %s",
            (base_scenario["stop_infrastructure_defaults_version"],),
        )
        default_val = float(db_cur.fetchone()["stop_charge_eur"])
        assert float(se_charge.value) == pytest.approx(default_val, rel=1e-3)

    @pytest.mark.xfail(
        reason="no stop carries an explicit stop_charge_eur yet: the curated "
        "catalog that held the thirteen negotiated charges was retired when the "
        "stop classification pipeline took over the catalog, and the pipeline "
        "seeds every charge NULL until step 7b lands real station charge data. "
        "Un-xfail by pinning a stop that has one, once they exist.",
        strict=True,
    )
    def test_stop_explicit_charge_is_not_default(self, loader):
        """A stop with an explicit stop_charge reports is_default=False.

        The is_default=True path is covered by
        test_stop_null_charge_resolves_from_global_default above; this is the
        other half of the provenance contract, and it has no subject in the
        catalog today."""
        stops = loader.build_all_stops()
        explicit = [
            entry
            for key, entry in stops.param_versions.items()
            if key.endswith(":stop_charge_eur") and entry.is_default is False
        ]
        assert explicit, "no stop has an explicit stop_charge_eur"


# =============================================================================
# Model version injection (CI only)
# =============================================================================


def test_git_sha_injected_in_ci():
    """In CI, GIT_SHA must be injected into all three model version files
    (see .github/workflows/backend-tests.yml). Skipped locally."""
    if not os.environ.get("GITHUB_SHA"):
        pytest.skip("Not running in CI — GIT_SHA injection not required locally")

    from models.energy.model import GIT_SHA as ENERGY_SHA
    from models.evaluation.model import GIT_SHA as CALC_SHA
    from models.route.model import GIT_SHA as ROUTE_SHA

    expected = os.environ["GITHUB_SHA"]
    assert ROUTE_SHA == expected, (
        f"route/version.py GIT_SHA not injected: '{ROUTE_SHA}'"
    )
    assert ENERGY_SHA == expected, (
        f"energy/version.py GIT_SHA not injected: '{ENERGY_SHA}'"
    )
    assert CALC_SHA == expected, (
        f"evaluation/version.py GIT_SHA not injected: '{CALC_SHA}'"
    )
