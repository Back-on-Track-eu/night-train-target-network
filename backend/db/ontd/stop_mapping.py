"""
stop_mapping.py
===============
Interim ONTD ↔ Target Network stop-id bridge (PROPOSALS_DESIGN.md §5.5,
WP10 step 6a) — the mechanism that lets ONTD gallery rows share one stop
namespace with proposals until the real harmonized stop list (numeric
OSM-based identifiers, expected ~2 weeks out) replaces both id schemes.

Two-pass resolution per ONTD stop appearing on an active route:

  1. COORDINATE MATCH — nearest stop_infrastructures row of the current
     base scenario's pinned snapshot within MATCH_RADIUS_M. Names are
     deliberately not the matcher (ONTD says "Bruxelles-Midi", the
     curated row says "Brussels Midi"); coordinates are what both sides
     agree on.
  2. MINT — no curated stop nearby: a new stop_infrastructures row is
     created at the pinned version, id derived as
     {country}_{TRANSLITERATED_NAME} in the curated style (Ü→UE, ø→OE,
     ...), stop_charge_eur NULL (resolved against the country/global
     default like any other stop), change_log marking the provenance.
     Minted stops are ordinary catalog entries — plannable in proposals.

Results are upserted into ontd.stop_mappings (a CURATED table — survives
the half-yearly refresh TRUNCATE, same lifecycle as route_compositions).
Rows with match_method='manual' or verified=TRUE are never overwritten,
so a bad automatic match can be corrected by hand once and stays
corrected. The table is also exactly the harmonization deliverable the
alignment task (Giovanni ↔ David, 2026-06-22) needs as its seed.

Deliberately unmapped (absent from the table, route_summaries keeps the
raw ONTD id): stops without coordinates (nothing to match or mint a
NOT NULL lat/lon from) and stops in countries outside
input_params.countries (the NOT NULL FK cannot hold them) — both
queryable as the gap between active ONTD stops and mapping rows.

Public interface:
  build_stop_mappings(cur)  → dict[str, str]  (ontd_stop_id → tn_stop_id
                                                for every mapped stop;
                                                writes mappings + minted
                                                stops through `cur`,
                                                commit is the caller's)
  mint_tn_stop_id(country_code, stop_name) → str
  transliterate(name) → str

Callers: db/ontd/projection.py's build_summaries() (before writing
route_summaries/route_corridors, so their stop ids come out translated).
"""

from math import cos, radians, sqrt
from typing import Any, Optional

# A railway station's platforms alone span a few hundred metres;
# different sources also pin "the station" at different reference points.
# 500 m separates "same station, different pin" from "different station"
# for European main stations without known false positives at import time.
MATCH_RADIUS_M = 500.0

# Curated-style transliteration (the DE_*/CH_*/SE_* seed rows' own
# convention: Zürich → ZUERICH, not ZURICH), extended to the rest of the
# characters ONTD station names actually carry.
_TRANSLIT = str.maketrans(
    {
        "ä": "AE",
        "ö": "OE",
        "ü": "UE",
        "ß": "SS",
        "æ": "AE",
        "ø": "OE",
        "å": "AA",
        "à": "A",
        "á": "A",
        "â": "A",
        "ã": "A",
        "ā": "A",
        "ă": "A",
        "ą": "A",
        "ç": "C",
        "ć": "C",
        "č": "C",
        "è": "E",
        "é": "E",
        "ê": "E",
        "ë": "E",
        "ē": "E",
        "ė": "E",
        "ę": "E",
        "ě": "E",
        "ì": "I",
        "í": "I",
        "î": "I",
        "ï": "I",
        "ī": "I",
        "į": "I",
        "ð": "D",
        "ď": "D",
        "đ": "D",
        "ñ": "N",
        "ń": "N",
        "ň": "N",
        "ò": "O",
        "ó": "O",
        "ô": "O",
        "õ": "O",
        "ő": "O",
        "ō": "O",
        "ù": "U",
        "ú": "U",
        "û": "U",
        "ű": "U",
        "ū": "U",
        "ů": "U",
        "ý": "Y",
        "ÿ": "Y",
        "ł": "L",
        "ľ": "L",
        "ĺ": "L",
        "ś": "S",
        "š": "S",
        "ş": "S",
        "ș": "S",
        "ť": "T",
        "ţ": "T",
        "ț": "T",
        "ź": "Z",
        "ż": "Z",
        "ž": "Z",
        "ř": "R",
        "ŕ": "R",
        "ğ": "G",
        "ı": "I",
        "þ": "TH",
        # Cyrillic (BGN/PCGN-style, simplified) — Bulgarian stop names in
        # ONTD mint into the Latin id namespace like everything else
        # (fixes BG_ПОДУЯНЕ-style ids observed 2026-08-06); includes the
        # Serbian/Macedonian extras.
        "а": "A",
        "б": "B",
        "в": "V",
        "г": "G",
        "д": "D",
        "е": "E",
        "ж": "ZH",
        "з": "Z",
        "и": "I",
        "й": "Y",
        "к": "K",
        "л": "L",
        "м": "M",
        "н": "N",
        "о": "O",
        "п": "P",
        "р": "R",
        "с": "S",
        "т": "T",
        "у": "U",
        "ф": "F",
        "х": "H",
        "ц": "TS",
        "ч": "CH",
        "ш": "SH",
        "щ": "SHT",
        "ъ": "A",
        "ь": "",
        "ю": "YU",
        "я": "YA",
        "ы": "Y",
        "э": "E",
        "ё": "E",
        "ђ": "DJ",
        "ј": "J",
        "љ": "LJ",
        "њ": "NJ",
        "ћ": "C",
        "џ": "DZ",
        # Greek (simplified romanization).
        "α": "A",
        "β": "V",
        "γ": "G",
        "δ": "D",
        "ε": "E",
        "ζ": "Z",
        "η": "I",
        "θ": "TH",
        "ι": "I",
        "κ": "K",
        "λ": "L",
        "μ": "M",
        "ν": "N",
        "ξ": "X",
        "ο": "O",
        "π": "P",
        "ρ": "R",
        "σ": "S",
        "ς": "S",
        "τ": "T",
        "υ": "Y",
        "φ": "F",
        "χ": "CH",
        "ψ": "PS",
        "ω": "O",
        "ά": "A",
        "έ": "E",
        "ή": "I",
        "ί": "I",
        "ό": "O",
        "ύ": "Y",
        "ώ": "O",
        "ϊ": "I",
        "ϋ": "Y",
        "ΐ": "I",
        "ΰ": "Y",
    }
)


def transliterate(name: str) -> str:
    """Station name → curated-style id fragment: fold accents (German
    umlauts to two letters, everything else to base letters), uppercase,
    every run of non-alphanumerics to a single underscore."""
    folded = name.strip().lower().translate(_TRANSLIT).upper()
    parts = "".join(c if c.isalnum() else " " for c in folded).split()
    return "_".join(parts)


def mint_tn_stop_id(country_code: str, stop_name: str) -> str:
    return f"{country_code.upper()}_{transliterate(stop_name)}"


def _distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Equirectangular approximation — exact enough at station-matching
    distances (error < 0.1% under 1 km) and cheap enough for the full
    cross product of ~600 ONTD stops × ~200+ curated stops."""
    mean_lat = radians((lat_a + lat_b) / 2)
    dx = radians(lon_b - lon_a) * cos(mean_lat) * 6_371_000
    dy = radians(lat_b - lat_a) * 6_371_000
    return sqrt(dx * dx + dy * dy)


def _active_ontd_stops(cur) -> list[dict[str, Any]]:
    """Every distinct stop appearing on an active route's timetable —
    the same trip_stop population fetch_route_stops() walks, so the
    mapping covers exactly the stops the gallery projection will need."""
    cur.execute(
        """
        SELECT DISTINCT s.stop_id, s.stop_name, s.stop_country,
               s.stop_timezone, s.stop_lat, s.stop_lon
          FROM ontd.trip_stop ts
          JOIN ontd.trips t ON t.trip_id = ts.trip_id AND t.is_active
          JOIN ontd.stops s ON s.stop_id = ts.stop_id
        """
    )
    return [dict(row) for row in cur.fetchall()]


def _pinned_catalog(cur) -> tuple[int, list[dict[str, Any]], list[int]]:
    """(pinned version, stop rows of that version, every existing
    snapshot version). The pinned base-scenario version is the match
    target set (what a candidate is compared against); minted rows are
    inserted into EVERY existing version, not only the pinned one —
    stop_infrastructures is a full-table-snapshot table (§3.1: a version
    holds an identical stop set to every other version, resolution is
    always an exact version match), so minting into one version alone
    would silently break that invariant for the historical/HSR
    snapshots (caught by test_02's
    test_stop_infrastructure_values_unchanged_by_hsr_scenario,
    2026-08-06)."""
    cur.execute(
        "SELECT stop_infrastructures_version FROM scenario.scenarios "
        "WHERE is_current_base"
    )
    pinned_version = cur.fetchone()["stop_infrastructures_version"]
    cur.execute(
        "SELECT stop_id, stop_name, stop_lat, stop_lon "
        "FROM input_params.stop_infrastructures WHERE stop_infra_version = %s",
        (pinned_version,),
    )
    catalog = [dict(row) for row in cur.fetchall()]
    cur.execute(
        "SELECT DISTINCT stop_infra_version FROM input_params.stop_infrastructures"
    )
    all_versions = [row["stop_infra_version"] for row in cur.fetchall()]
    return pinned_version, catalog, all_versions


def _known_countries(cur) -> set[str]:
    cur.execute("SELECT country_code FROM input_params.countries")
    return {row["country_code"] for row in cur.fetchall()}


def _protected_mappings(cur) -> dict[str, str]:
    """Hand-made or verified rows — never overwritten by a rebuild."""
    cur.execute(
        "SELECT ontd_stop_id, tn_stop_id FROM ontd.stop_mappings "
        "WHERE match_method = 'manual' OR verified"
    )
    return {row["ontd_stop_id"]: row["tn_stop_id"] for row in cur.fetchall()}


def _nearest(
    lat: float, lon: float, catalog: list[dict[str, Any]]
) -> tuple[Optional[dict[str, Any]], float]:
    best, best_distance = None, float("inf")
    for stop in catalog:
        distance = _distance_m(
            lat, lon, float(stop["stop_lat"]), float(stop["stop_lon"])
        )
        if distance < best_distance:
            best, best_distance = stop, distance
    return best, best_distance


def build_stop_mappings(cur) -> dict[str, str]:
    """Rebuild the automatic half of ontd.stop_mappings and mint any
    missing Target Network stops; return the full ontd→TN translation
    dict (protected manual rows included). Writes through `cur` without
    committing — transaction control stays with the caller, same as
    every other projection stage."""
    ontd_stops = _active_ontd_stops(cur)
    version, catalog, all_versions = _pinned_catalog(cur)
    known_countries = _known_countries(cur)
    protected = _protected_mappings(cur)
    catalog_ids = {stop["stop_id"] for stop in catalog}

    mapping: dict[str, str] = dict(protected)
    minted = matched = skipped = 0

    for stop in ontd_stops:
        ontd_id = stop["stop_id"]
        if ontd_id in protected:
            continue
        if stop["stop_lat"] is None or stop["stop_lon"] is None:
            skipped += 1
            continue

        lat, lon = float(stop["stop_lat"]), float(stop["stop_lon"])
        nearest, distance = _nearest(lat, lon, catalog)
        if nearest is not None and distance <= MATCH_RADIUS_M:
            tn_id, method, match_distance = nearest["stop_id"], "coordinate", distance
        else:
            country = (stop["stop_country"] or "").strip().upper()
            if country not in known_countries:
                # The NOT NULL FK into input_params.countries cannot hold
                # this stop — left unmapped rather than minted into a
                # wrong country. Queryable as the gap between active ONTD
                # stops and mapping rows.
                skipped += 1
                continue
            tn_id = mint_tn_stop_id(country, stop["stop_name"])
            # Same-name-different-station collision (two distinct minted
            # stops, or a curated id whose station is verifiably >500 m
            # away): suffix rather than merge — a wrong merge corrupts
            # corridors, a suffix is merely ugly for two weeks.
            base_id, suffix = tn_id, 2
            while tn_id in catalog_ids or tn_id in mapping.values():
                tn_id = f"{base_id}_{suffix}"
                suffix += 1
            # Every existing snapshot version, not just the pinned one —
            # see _pinned_catalog()'s docstring for why.
            for insert_version in all_versions:
                cur.execute(
                    """
                    INSERT INTO input_params.stop_infrastructures (
                        stop_id, stop_name, country_code, stop_timezone,
                        stop_lat, stop_lon, stop_charge_eur, change_log,
                        stop_infra_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s)
                    ON CONFLICT (stop_id, stop_infra_version) DO NOTHING
                    """,
                    (
                        tn_id,
                        stop["stop_name"],
                        country,
                        stop["stop_timezone"] or "Europe/Brussels",
                        lat,
                        lon,
                        "minted from ONTD (db/ontd/stop_mapping.py) — interim "
                        "until the harmonized stop list lands; charge resolves "
                        "via country/global default",
                        insert_version,
                    ),
                )
            catalog_ids.add(tn_id)
            # Minted rows must also be match targets for later ONTD stops
            # (two ONTD ids for one physical station map to one TN stop).
            catalog.append(
                {
                    "stop_id": tn_id,
                    "stop_name": stop["stop_name"],
                    "stop_lat": lat,
                    "stop_lon": lon,
                }
            )
            method, match_distance = "minted", None
            minted += 1

        if method == "coordinate":
            matched += 1
        mapping[ontd_id] = tn_id
        cur.execute(
            """
            INSERT INTO ontd.stop_mappings (
                ontd_stop_id, tn_stop_id, match_method, distance_m
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (ontd_stop_id) DO UPDATE SET
                tn_stop_id = EXCLUDED.tn_stop_id,
                match_method = EXCLUDED.match_method,
                distance_m = EXCLUDED.distance_m
            WHERE NOT ontd.stop_mappings.verified
              AND ontd.stop_mappings.match_method != 'manual'
            """,
            (
                ontd_id,
                tn_id,
                method,
                round(match_distance, 1) if match_distance is not None else None,
            ),
        )

    print(
        f"  stop mappings: {matched} coordinate-matched, {minted} minted, "
        f"{skipped} unmapped (no coords / country outside input_params), "
        f"{len(protected)} manual/verified preserved"
    )
    return mapping
