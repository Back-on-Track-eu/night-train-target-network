"""
Step 7 — export the qualified catalog in the shape db/dev/seed.py consumes.

Unions the current step 5 output (Tier 1: current night train stops) with the
step 6 selection (the manually chosen metropolitan, tourism and ferry stops)
and writes a CSV matching seed.py's _ONTD_SEED_CSV_COLUMNS contract exactly.

Step 6 was built by hand on top of an earlier, lossy step 5 run. Treating it as
the manual-additions layer and unioning here — keyed on OSM id — means a
step 5 re-run flows straight into the catalog without redoing that manual
work: recovered stops come from step 5, the additions stay from step 6, and a
stop present in both is written once.

Two corrections happen here rather than upstream:

country
    Taken from the ONTD export via the step 4 join, not from step 6's own
    column. ONTD is curated national data; step 6's column disagrees on ten
    stops and is wrong on every one checked (Crimean stations coded RU against
    ONTD's UA, Narva coded RU though it is in Estonia, Santander coded NO,
    Lichkov coded PL). Rows with no ONTD counterpart — the hand-picked step 6
    additions — keep their step 6 country, which is correct for those.

stop_timezone
    Derived from the country, not from step 6's integer column. That column
    holds a bare UTC offset, which cannot express DST and is wrong for Ireland
    (marked +1). The schema and the rest of the catalog use IANA names.

stop_charge_eur is deliberately absent: seed.py inserts NULL, which resolves
through the country/global default (currently 11.28 EUR). Writing a placeholder
here would override that fallback and make "which stops still need real charge
data?" unanswerable — step 7's real charge work replaces the NULLs later.

Run from this directory:

    uv run python step7_export_seed_stops.py
"""

from __future__ import annotations

import csv

from data_sources import DATA_DIR, ensure_local

OUTPUT_PATH = DATA_DIR / "stop_seed_catalog.csv"
REPORT_PATH = DATA_DIR / "step7_country_corrections.csv"

# seed.py::_ONTD_SEED_CSV_COLUMNS — keep in lockstep.
SEED_COLUMNS = [
    "stop_id",
    "stop_name",
    "country_code",
    "stop_timezone",
    "stop_lat",
    "stop_lon",
]

# One IANA zone per country. Derived from the country rather than a UTC offset
# so DST is handled by the zone database instead of being frozen into the data.
COUNTRY_TIMEZONES = {
    "AL": "Europe/Tirane",
    "AT": "Europe/Vienna",
    "BA": "Europe/Sarajevo",
    "BE": "Europe/Brussels",
    "BG": "Europe/Sofia",
    "BY": "Europe/Minsk",
    "CH": "Europe/Zurich",
    "CZ": "Europe/Prague",
    "DE": "Europe/Berlin",
    "DK": "Europe/Copenhagen",
    "EE": "Europe/Tallinn",
    "ES": "Europe/Madrid",
    "FI": "Europe/Helsinki",
    "FR": "Europe/Paris",
    "GB": "Europe/London",
    "GR": "Europe/Athens",
    "HR": "Europe/Zagreb",
    "HU": "Europe/Budapest",
    "IE": "Europe/Dublin",
    "IT": "Europe/Rome",
    "LT": "Europe/Vilnius",
    "LU": "Europe/Luxembourg",
    "LV": "Europe/Riga",
    "MD": "Europe/Chisinau",
    "ME": "Europe/Podgorica",
    "MK": "Europe/Skopje",
    "NL": "Europe/Amsterdam",
    "NO": "Europe/Oslo",
    "PL": "Europe/Warsaw",
    "PT": "Europe/Lisbon",
    "RO": "Europe/Bucharest",
    "RS": "Europe/Belgrade",
    "RU": "Europe/Moscow",
    "SE": "Europe/Stockholm",
    "SI": "Europe/Ljubljana",
    "SK": "Europe/Bratislava",
    "TR": "Europe/Istanbul",
    "UA": "Europe/Kyiv",
    "XK": "Europe/Belgrade",
}

# OSM ids whose step 4 match is junk — the OSM station is an unnamed or
# single-letter object hundreds of kilometres from the ONTD stop it was matched
# to. Excluded rather than seeded with a wrong location.
EXCLUDED_STOP_IDS = {
    "osm:n4896717721",  # ONTD Dağkadı Hızlı Tren İstasyonu -> OSM "tren", 2743 km
    "osm:n8515238217",  # ONTD Tekučica -> OSM "A", 355 km
    "osm:n9553124517",  # ONTD Közép-Garadna -> OSM "Arad", 222 km
}


def parse_float(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_ontd_countries() -> dict[str, str]:
    """OSM stop id -> ONTD country code, from the step 4 join."""
    path = ensure_local("step4_MatchingONTDtoOSM.csv")
    countries = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            osm_id = (row.get("osm_stop_id") or "").strip()
            country = (row.get("ontd_country") or "").strip().upper()
            if osm_id and country:
                countries.setdefault(osm_id, country)
    return countries


def iter_candidates():
    """(source, stop_id, stop_name, source_country, lat, lon) from step 5 then
    step 6. Step 5 first so its ONTD-backed row wins when both have the stop."""
    step5_path = ensure_local("step5_JoinedNTStops.csv")
    with open(step5_path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            yield (
                "step5",
                (row.get("osm_stop_id") or "").strip(),
                (row.get("osm_stop_name") or row.get("ontd_name") or "").strip(),
                (row.get("ontd_country") or "").strip().upper(),
                parse_float(row.get("osm_lat")),
                parse_float(row.get("osm_lon")),
            )
    step6_path = ensure_local("step6_metropol.csv")
    with open(step6_path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            yield (
                "step6",
                (row.get("stop_id") or "").strip(),
                (row.get("stop_name") or "").strip(),
                (row.get("country") or "").strip().upper(),
                parse_float(row.get("stop_lat")),
                parse_float(row.get("stop_lon")),
            )


def main() -> None:
    ontd_countries = load_ontd_countries()

    rows, corrections, unknown_tz = [], [], []
    skipped: dict[str, str] = {}
    seen_ids = set()
    per_source = {"step5": 0, "step6": 0}

    for source, stop_id, stop_name, source_country, lat, lon in iter_candidates():
        if not stop_id or stop_id in seen_ids:
            continue
        if stop_id in EXCLUDED_STOP_IDS:
            skipped.setdefault(stop_id, stop_name)
            continue
        seen_ids.add(stop_id)
        per_source[source] += 1

        country = ontd_countries.get(stop_id, source_country)
        if source_country and country != source_country:
            corrections.append(
                {
                    "stop_id": stop_id,
                    "stop_name": stop_name,
                    "source": source,
                    "source_country": source_country,
                    "ontd_country": country,
                }
            )

        timezone = COUNTRY_TIMEZONES.get(country)
        if timezone is None:
            unknown_tz.append((stop_id, country))
            continue

        if lat is None or lon is None:
            skipped[stop_id] = f"{stop_name} (missing coordinates)"
            continue

        rows.append(
            {
                "stop_id": stop_id,
                "stop_name": stop_name,
                "country_code": country,
                "stop_timezone": timezone,
                "stop_lat": f"{lat:.7f}",
                "stop_lon": f"{lon:.7f}",
            }
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SEED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    with open(REPORT_PATH, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "stop_id",
                "stop_name",
                "source",
                "source_country",
                "ontd_country",
            ],
        )
        writer.writeheader()
        writer.writerows(corrections)

    print(
        f"wrote {len(rows)} stops to {OUTPUT_PATH.name} "
        f"({per_source['step5']} from step 5, {per_source['step6']} added by step 6)"
    )
    print(
        f"country corrected from ONTD on {len(corrections)} stops "
        f"(see {REPORT_PATH.name})"
    )
    if skipped:
        print(f"skipped {len(skipped)}: {skipped}")
    if unknown_tz:
        raise SystemExit(
            f"no timezone mapping for {sorted({c for _, c in unknown_tz})} — "
            "add it to COUNTRY_TIMEZONES"
        )


if __name__ == "__main__":
    main()
