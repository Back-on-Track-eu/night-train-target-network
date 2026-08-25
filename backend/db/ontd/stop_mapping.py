"""
stop_mapping.py
===============
ONTD ↔ Target Network stop-id bridge (adapters/proposal/README.md §5.5,
WP10 step 6a) — the mechanism that lets ONTD gallery rows share one stop
namespace with proposals. The harmonized OSM-based stop catalog this was
written to await landed 2026-08 (stop ids "osm:n…"/"osm:w…"/"osm:r…" from
the stop classification pipeline); the bridge remains as the permanent
translation from ONTD's own ids, since ONTD stops and catalog stops can
legitimately be different OSM objects for the same station (ONTD's export
reads only railway=halt nodes).

One-pass resolution per ONTD stop appearing on an active route:
COORDINATE MATCH — nearest stop_infrastructures row of the current base
scenario's pinned snapshot within MATCH_RADIUS_M. Names are deliberately
not the matcher (ONTD says "Bruxelles-Midi", the curated row says
"Brussels Midi"); coordinates are what both sides agree on.

The catalog is COMPLETE AT SEED TIME (revised 2026-08-07): every stop the
ONTD snapshot needs is part of db/dev/seed.py's stop data — since 2026-08
the Drive-hosted stop_seed_catalog.csv from the stop classification
pipeline (mint_tn_stop_id and its {country}_{NAME} convention remain only
for legacy manual mapping rows predating the switch). This replaces the earlier runtime MINT pass, which
inserted missing stops into input_params.stop_infrastructures during the
bootstrap — mutating pinned snapshot versions at runtime, which (a) broke
the compute cache's scenario-pin key invariant
(adapters/proposal/README.md §2.3: a cached
result computed pre-mint kept being served post-mint) and (b) never
survived a container restart anyway (seed.py DROPs input_params while the
guarded ontd schema keeps the bootstrap from re-running). An ONTD stop
that matches nothing is now REPORTED and left unmapped — expected to be
rare; the remedy is regenerating the seed CSV and reseeding, not a
runtime write.

Results are upserted into ontd.stop_mappings (a CURATED table — survives
the half-yearly refresh TRUNCATE, same lifecycle as route_compositions).
Rows with match_method='manual' or verified=TRUE are never overwritten,
so a bad automatic match can be corrected by hand once and stays
corrected. The table is also exactly the harmonization deliverable the
alignment task (Giovanni ↔ David, 2026-06-22) needs as its seed.

Deliberately unmapped (absent from the table, route_summaries keeps the
raw ONTD id): stops without coordinates (nothing to match on) and stops
with no catalog row within MATCH_RADIUS_M (seed CSV out of date, or a
country outside input_params.countries that the exporter could not seed)
— all reported by build_stop_mappings() and queryable as the gap between
active ONTD stops and mapping rows.

Public interface:
  build_stop_mappings(cur)  → dict[str, str]  (ontd_stop_id → tn_stop_id
                                                for every mapped stop;
                                                writes mappings through
                                                `cur`, commit is the
                                                caller's)
  mint_tn_stop_id(country_code, stop_name) → str  (id convention — used
                                                by the seed-CSV exporter,
                                                scripts/
                                                export_ontd_stop_seed.py)
  transliterate(name) → str

Callers: db/ontd/projection.py's build_summaries() (before writing
route_summaries/route_corridors, so their stop ids come out translated).

OPERATIONAL NOTE: the ontd schema is bootstrap-guarded, so a reseed with a
changed stop catalog does NOT re-run this module by itself — mappings and
route_summaries keep referencing the old ids until the bootstrap is forced
(ONTD_BOOTSTRAP=force, stages 2-3). Required after any catalog change that
adds, removes or re-points stop ids; see db/ontd/README.md.
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


def _pinned_catalog(cur) -> list[dict[str, Any]]:
    """Stop rows of the current base scenario's pinned snapshot — the
    match target set. Since the ONTD-derived stops are part of the seed
    (db/dev/data/ontd_seed_stops.csv), this catalog already contains
    every stop the mapping should resolve to; the snapshot versions all
    hold identical stop sets by construction (seed.py builds each version
    from the same list — asserted by test_02's snapshot-invariant
    test)."""
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
    return [dict(row) for row in cur.fetchall()]


def _known_countries(cur) -> set[str]:
    """Kept for scripts/export_ontd_stop_seed.py — the seed exporter needs
    it to honour the NOT NULL FK into input_params.countries; the mapping
    itself no longer branches on country."""
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
    """Rebuild the automatic half of ontd.stop_mappings against the
    seeded stop catalog; return the full ontd→TN translation dict
    (protected manual rows included). Writes through `cur` without
    committing — transaction control stays with the caller, same as
    every other projection stage. Never writes to input_params: the
    catalog is complete at seed time (module docstring), so an ONTD stop
    without a match is a reported gap, not a trigger to create one."""
    ontd_stops = _active_ontd_stops(cur)
    catalog = _pinned_catalog(cur)
    protected = _protected_mappings(cur)

    mapping: dict[str, str] = dict(protected)
    matched = no_coords = 0
    # (ontd_id, name, nearest catalog distance in m) per unmatched stop —
    # printed below so a stale seed CSV is visible in the bootstrap log,
    # not just as quietly untranslated gallery ids.
    unmatched: list[tuple[str, str, float]] = []

    for stop in ontd_stops:
        ontd_id = stop["stop_id"]
        if ontd_id in protected:
            continue
        if stop["stop_lat"] is None or stop["stop_lon"] is None:
            no_coords += 1
            continue

        lat, lon = float(stop["stop_lat"]), float(stop["stop_lon"])
        nearest, distance = _nearest(lat, lon, catalog)
        if nearest is None or distance > MATCH_RADIUS_M:
            unmatched.append((ontd_id, stop["stop_name"], distance))
            continue

        matched += 1
        mapping[ontd_id] = nearest["stop_id"]
        cur.execute(
            """
            INSERT INTO ontd.stop_mappings (
                ontd_stop_id, tn_stop_id, match_method, distance_m
            ) VALUES (%s, %s, 'coordinate', %s)
            ON CONFLICT (ontd_stop_id) DO UPDATE SET
                tn_stop_id = EXCLUDED.tn_stop_id,
                match_method = EXCLUDED.match_method,
                distance_m = EXCLUDED.distance_m
            WHERE NOT ontd.stop_mappings.verified
              AND ontd.stop_mappings.match_method != 'manual'
            """,
            (ontd_id, nearest["stop_id"], round(distance, 1)),
        )

    # Manual/verified rows are never auto-overwritten, which also means a
    # catalog change can silently strand them on removed stop ids (the
    # 2026-08 pipeline restructure removed 21 duplicate stops). Automatic
    # rows self-heal on the next rebuild; protected rows only heal by hand,
    # so stranded ones are shouted about here.
    catalog_ids = {row["stop_id"] for row in catalog}
    stale_protected = {
        ontd_id: tn_id
        for ontd_id, tn_id in protected.items()
        if tn_id not in catalog_ids
    }
    if stale_protected:
        print(
            f"  WARNING: {len(stale_protected)} manual/verified mapping(s) "
            "target stop ids absent from the pinned catalog snapshot — "
            "route_summaries built from them carry dead ids. Re-point or "
            "un-verify these rows in ontd.stop_mappings:"
        )
        for ontd_id, tn_id in sorted(stale_protected.items()):
            print(f"    {ontd_id} -> {tn_id}")

    print(
        f"  stop mappings: {matched} coordinate-matched, "
        f"{len(unmatched)} unmatched, {no_coords} without coordinates, "
        f"{len(protected)} manual/verified preserved"
    )
    if unmatched:
        print(
            "  UNMATCHED ONTD STOPS — no catalog row within "
            f"{MATCH_RADIUS_M:.0f} m; route_summaries keeps their raw ONTD "
            "ids. If these are legitimate stations, regenerate the seed "
            "CSV (backend/scripts/export_ontd_stop_seed.py) and reseed:"
        )
        for ontd_id, name, distance in unmatched:
            print(f"    {ontd_id}  {name!r}  (nearest {distance:.0f} m)")

    return mapping
