"""
Unit tests for db/ontd/stop_mapping.py's pure functions —
transliteration, the stop-id convention (now consumed by
scripts/export_ontd_stop_seed.py, which derives the committed seed CSV),
and the distance approximation. No DB, no Docker: the integration path
(coordinate match against the seeded catalog, manual-row protection) is
exercised in test_52's union tests against the loaded ontd schema.
"""

import sys
from pathlib import Path

import pytest

# db/ontd is a script directory (its modules import each other bare, the
# same way loader.py/projection.py run), not a package under backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "db" / "ontd"))

from stop_mapping import (  # noqa: E402
    MATCH_RADIUS_M,
    _distance_m,
    mint_tn_stop_id,
    transliterate,
)


class TestTransliterate:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Berlin Hbf", "BERLIN_HBF"),
            # Curated style: umlauts fold to two letters, matching the
            # seed's own osm:n1236383343 / osm:n1305188216 convention.
            ("Zürich HB", "ZUERICH_HB"),
            ("Göteborg C", "GOETEBORG_C"),
            ("Malmö C", "MALMOE_C"),
            ("København H", "KOEBENHAVN_H"),
            ("Wien Hbf", "WIEN_HBF"),
            # Punctuation runs collapse to a single underscore.
            ("Bruxelles-Midi/Brussel-Zuid", "BRUXELLES_MIDI_BRUSSEL_ZUID"),
            ("Paris Gare de l'Est", "PARIS_GARE_DE_L_EST"),
            # Broader European accents fold to base letters.
            ("Gdańsk Główny", "GDANSK_GLOWNY"),
            ("Praha hl.n.", "PRAHA_HL_N"),
            ("București Nord", "BUCURESTI_NORD"),
            ("Málaga María Zambrano", "MALAGA_MARIA_ZAMBRANO"),
            ("  Roma Termini  ", "ROMA_TERMINI"),
            # Cyrillic and Greek fold into the Latin id namespace too —
            # the curated catalog is Latin-only by convention.
            ("Подуяне", "PODUYANE"),
            ("София", "SOFIYA"),
            ("Горна Оряховица", "GORNA_ORYAHOVITSA"),
            ("Велико Търново", "VELIKO_TARNOVO"),
            ("Θεσσαλονίκη", "THESSALONIKI"),
        ],
    )
    def test_folding(self, name, expected):
        assert transliterate(name) == expected

    def test_idempotent(self):
        once = transliterate("Zürich HB")
        assert transliterate(once) == once


class TestMintId:
    """The minting rule itself, not the catalog: these assert the shape
    mint_tn_stop_id() produces, which is unchanged. Note the ids it mints
    (COUNTRY_NAME) no longer share a namespace with the seeded catalog,
    which is now OSM-keyed — see the note in stop_mapping.py."""

    def test_shape(self):
        assert mint_tn_stop_id("de", "Berlin Hbf") == "DE_BERLIN_HBF"

    def test_folds_the_name_the_same_way_everywhere(self):
        """The minting rule is transliterate() plus a country prefix, so a
        minted id is reproducible from the name alone."""
        assert mint_tn_stop_id("CH", "Zürich HB") == "CH_ZUERICH_HB"
        assert mint_tn_stop_id("AT", "Wien Hbf") == "AT_WIEN_HBF"
        assert mint_tn_stop_id("FR", "Paris Est") == "FR_PARIS_EST"


class TestDistance:
    def test_known_pair(self):
        """Berlin Hbf → Dresden Hbf is ~167 km great-circle at the
        seed coordinates; the equirectangular approximation must land
        within 1%."""
        distance = _distance_m(52.525, 13.369, 51.040, 13.732)
        assert 165_000 < distance < 169_000

    def test_station_scale(self):
        """~350 m apart (two ends of one station) stays inside the match
        radius; ~5 km (two stations of one city, e.g. a Hbf and an
        Ostbahnhof) stays outside — the two behaviours the radius is
        calibrated to separate."""
        near = _distance_m(52.5250, 13.3690, 52.5250, 13.3742)
        far = _distance_m(52.5250, 13.3690, 52.5250, 13.4430)
        assert near < MATCH_RADIUS_M < far


class TestMappingTargetsCurrent:
    """Every mapping row must point into the pinned catalog snapshot —
    manual/verified rows survive catalog changes by design, which is
    exactly how they get stranded on removed ids (2026-08 restructure
    removed 21 duplicate stops). build_stop_mappings() warns; this test
    makes the warning a failure so it cannot be shipped past."""

    def test_no_mapping_targets_removed_stops(self, db_cur):
        db_cur.execute("""
            SELECT m.ontd_stop_id, m.tn_stop_id, m.match_method, m.verified
            FROM ontd.stop_mappings m
            WHERE NOT EXISTS (
                SELECT 1 FROM input_params.stop_infrastructures s
                JOIN scenario.scenarios sc
                  ON sc.stop_infrastructures_version = s.stop_infra_version
                WHERE sc.is_current_base AND s.stop_id = m.tn_stop_id
            )
            """)
        stale = db_cur.fetchall()
        assert stale == [], (
            "mapping rows target stop ids absent from the base snapshot "
            "(re-point or un-verify them, then force the ONTD bootstrap): "
            + ", ".join(f"{r['ontd_stop_id']}->{r['tn_stop_id']}" for r in stale)
        )
