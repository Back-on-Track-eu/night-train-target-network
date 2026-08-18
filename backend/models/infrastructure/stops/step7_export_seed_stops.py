"""
Step 7 — export the qualified catalog in the shape db/dev/seed.py consumes.

Unions the current step 5 output (Tier 1: current night train stops) with the
step 6 manual additions and writes a CSV matching seed.py's
_ONTD_SEED_CSV_COLUMNS contract exactly. Keyed on OSM id, so a stop qualifying
both ways is written once and a step 5 re-run flows straight into the catalog
without touching the manual selection.

Which layer a stop came from is written alongside, to
stop_seed_provenance.csv: the catalog itself has to match seed.py's column
contract exactly, so the provenance can't ride in it. Without that sidecar
nothing on disk distinguishes a stop a night train serves today from one added
by hand.

country
    Taken from the ONTD export via the step 4 join where one exists, since ONTD
    is curated national data; otherwise the source layer's own value. Steps 5
    and 6 already apply the same preference, so this is a safety net rather
    than the place the correction happens — step 6 reports what it changed.

stop_timezone
    Derived from the country as an IANA name. The legacy step 6 file carried a
    bare UTC offset instead, which cannot express DST and was wrong for Ireland
    (marked +1); the schema and the rest of the catalog use IANA names.

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
PROVENANCE_PATH = DATA_DIR / "stop_seed_provenance.csv"

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
    """(source, stop_id, stop_name, source_country, lat, lon, reason) from
    step 5 then step 6. Step 5 first so its ONTD-backed row wins when a stop
    qualifies both ways."""
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
                f"night_train_stop:{(row.get('schedule_name') or '').strip()}",
            )
    step6_path = ensure_local("step6_manual_additions.csv")
    with open(step6_path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            yield (
                "step6_manual",
                (row.get("stop_id") or "").strip(),
                (row.get("stop_name") or "").strip(),
                (row.get("country") or "").strip().upper(),
                parse_float(row.get("stop_lat")),
                parse_float(row.get("stop_lon")),
                (row.get("reason") or "").strip(),
            )


def main() -> None:
    ontd_countries = load_ontd_countries()

    rows, unknown_tz = [], []
    skipped: dict[str, str] = {}
    seen_ids = set()
    per_source = {"step5": 0, "step6_manual": 0}
    provenance = []

    for (
        source,
        stop_id,
        stop_name,
        source_country,
        lat,
        lon,
        reason,
    ) in iter_candidates():
        if not stop_id or stop_id in seen_ids:
            continue
        if stop_id in EXCLUDED_STOP_IDS:
            skipped.setdefault(stop_id, stop_name)
            continue
        seen_ids.add(stop_id)
        per_source[source] += 1

        country = ontd_countries.get(stop_id, source_country)

        timezone = COUNTRY_TIMEZONES.get(country)
        if timezone is None:
            # No country means no timezone, and a stop written without one would
            # be wrong rather than merely incomplete — collected and raised below
            # so it can never disappear from the catalog unnoticed.
            unknown_tz.append((stop_id, stop_name, country))
            continue

        if lat is None or lon is None:
            skipped[stop_id] = f"{stop_name} (missing coordinates)"
            continue

        provenance.append(
            {
                "stop_id": stop_id,
                "stop_name": stop_name,
                "source": source,
                "reason": reason,
            }
        )
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

    with open(PROVENANCE_PATH, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["stop_id", "stop_name", "source", "reason"]
        )
        writer.writeheader()
        writer.writerows(provenance)

    print(
        f"wrote {len(rows)} stops to {OUTPUT_PATH.name} "
        f"({per_source['step5']} from step 5, "
        f"{per_source['step6_manual']} manual step 6 additions)"
    )
    unexplained = sum(
        1 for p in provenance if p["source"] == "step6_manual" and not p["reason"]
    )
    if unexplained:
        print(
            f"  {unexplained} manual additions carry no reason "
            f"— see step6_manual_additions.ipynb"
        )
    if skipped:
        print(f"skipped {len(skipped)}: {skipped}")
    if unknown_tz:
        countries = sorted({country for _, _, country in unknown_tz if country})
        blank = [(i, n) for i, n, country in unknown_tz if not country]
        raise SystemExit(
            f"{len(unknown_tz)} stop(s) dropped for want of a timezone.\n"
            + (
                f"  no mapping for {countries} — add to COUNTRY_TIMEZONES\n"
                if countries
                else ""
            )
            + (
                f"  no country at all: {blank} — fix upstream in step 6\n"
                if blank
                else ""
            )
        )


if __name__ == "__main__":
    main()
