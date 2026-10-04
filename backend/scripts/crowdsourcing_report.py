"""
crowdsourcing_report.py
=======================
Figures for the launch report of the documentation site
(docs-site/reports/<edition>.md): one JSON per edition with every number,
chart series and map position the page shows, so the page itself carries
prose and no figures (docs-site/reports/README.md).

Input is the read-only export sql/crowdsourcing_report_export.sql, either
run here against a database (--db, host-runnable like
scripts/purge_request_log.py) or saved from pgAdmin's grid as CSV
(--from-csv) — production has no shell, so the pgAdmin route is the one
that reaches it: sql/crowdsourcing_report_export_pgadmin.sql is the
single-statement variant of the same export and is GENERATED from the psql
file by --emit-pgadmin-sql. Edit the psql file, regenerate, commit both.

The report window is two dates, inclusive, in the database's own time
zone (Europe/Berlin, set by the export). Everything proposal-side is
filtered on the proposal's created_at; the usage sections (request log)
only reach back REQUEST_LOG_RETENTION_DAYS and are reported as exported.

Editorial constants of the report — the "typical night train" envelope
(must equal the gallery's preset, frontend/src/lib/typicalNightTrain.ts),
the corridor de-duplication thresholds and the map window — are the
module-level constants below. Hand-picked content (comment quotes, the
missing-station list) is NOT here: it sits in the page's own <script
setup>, next to the prose that refers to it.

The Europe basemap the map draws (docs-site/reports/data/europe-basemap.json,
projected SVG paths per country, shared by every edition) is rebuilt only
when --basemap-source names a Natural Earth 50 m admin-0 GeoJSON
(https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/
ne_50m_admin_0_countries.geojson, public domain); otherwise the committed
file is reused, which keeps the 24 MB source out of the repository.

Usage (from backend/):
  uv run python scripts/crowdsourcing_report.py --from-csv export.csv \\
      --edition 2026-10-launch --window 2026-09-22..2026-10-02
  uv run python scripts/crowdsourcing_report.py --db --edition 2026-10-launch \\
      --window 2026-09-22..2026-10-02
  uv run python scripts/crowdsourcing_report.py --emit-pgadmin-sql
  uv run python scripts/crowdsourcing_report.py --from-csv export.csv ... \\
      --basemap-source ne_50m_admin_0_countries.geojson
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import pycountry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.compositions.catalog import load_catalog  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger("crowdsourcing_report")

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parent
SQL_DIR = _BACKEND_ROOT / "scripts" / "sql"
PSQL_SQL = SQL_DIR / "crowdsourcing_report_export.sql"
PGADMIN_SQL = SQL_DIR / "crowdsourcing_report_export_pgadmin.sql"
REPORT_DATA_DIR = _REPO_ROOT / "docs-site" / "reports" / "data"
BASEMAP_PATH = REPORT_DATA_DIR / "europe-basemap.json"

# --- editorial constants ---------------------------------------------------

# "Typical night train", one way. The gallery's preset
# (frontend/src/lib/typicalNightTrain.ts) is the one the report must state,
# so a change there is a change here.
ENVELOPE_KM = (500, 2000)
ENVELOPE_H = (7, 21)
ENVELOPE_MIN_SPEED_KMH = 50

# Corridor de-duplication: termini within CITY_KM of each other are one
# city; two routes are one corridor from CORRIDOR_SIM Jaccard similarity of
# their city sets (see corridor_dedup()).
CITY_KM = 50
CORRIDOR_SIM = 0.6

# Map: Mercator over this window, WIDTH px wide; the height follows.
MAP_LON = (-10.5, 31.0)
MAP_LAT = (35.5, 69.5)
MAP_WIDTH = 760
# Basemap simplification, in projected pixels: Douglas–Peucker tolerance
# and the smallest island extent still drawn.
BASEMAP_TOLERANCE_PX = 0.8
BASEMAP_MIN_EXTENT_PX = 3
MAP_BUBBLES = 220
MAP_LABELS = 8

# Composition every proposal starts from (the builder's default).
DEFAULT_COMPOSITION_ID = "NEW-BAL-7"

# Station names that read better as the city on a chart label.
SHORT_NAMES = {
    "Paris Gare du Nord": "Paris",
    "Praha hlavní nádraží": "Praha",
    "Barcelona - Sants": "Barcelona",
    "Zürich Hauptbahnhof": "Zürich",
    "Malmö C": "Malmö",
    "Frankfurt (Main) Hauptbahnhof": "Frankfurt",
    "Berlin Hauptbahnhof": "Berlin",
    "Oslo S": "Oslo",
    "Milano Centrale": "Milano",
    "Venezia Mestre": "Venezia",
    "Roma Termini": "Roma",
    "Madrid-Puerta de Atocha-Almudena Grandes": "Madrid",
    "Wien Hauptbahnhof": "Wien",
    "Amsterdam Centraal": "Amsterdam",
    "Københavns Hovedbanegård": "København",
    "Stockholm Central": "Stockholm",
    "Bruxelles-Midi": "Bruxelles",
    "London St. Pancras International": "London",
    "Hamburg Hauptbahnhof": "Hamburg",
}

# Feedback categories as the page labels them; "Route or timetable" is
# reported by sub-category because it is the only category that splits.
FEEDBACK_LABELS = {
    "Missing stop / suggest new stop": "Missing stop",
    "Routing / track geometry": "Routing / track geometry",
    "Schedule / timetable / frequency": "Timetable",
    "Documentation": "Documentation",
    "Feature request": "Feature request",
    "Evaluation — calculation method": "Calculation method",
    "Evaluation — results / view": "Results / view",
    "Compositions": "Compositions",
}

# Histogram edges (one way, km / € per train-km); the last bucket is open.
DISTANCE_BUCKETS_KM = tuple(range(0, 3001, 500))
COST_BUCKETS_EUR = tuple(15 + 2.5 * i for i in range(8))


# --- export: load / run / emit -----------------------------------------------

_MARKER = re.compile(r"^\\echo '## (\w+)'\s*$", re.MULTILINE)


def split_psql_sections(text: str) -> list[tuple[str, str]]:
    """(name, sql) per `\\echo '## name'` block of the psql export, the
    statement without its trailing semicolon. The empty trailing 'done'
    marker and the preamble (`\\set`, `SET TIME ZONE`) are dropped."""
    parts = _MARKER.split(text)
    sections = []
    for name, body in zip(parts[1::2], parts[2::2]):
        lines = body.strip().splitlines()
        # Comment banners introducing the NEXT section follow the statement.
        while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith("--")):
            lines.pop()
        sql = "\n".join(lines).rstrip(";").strip()
        if sql and name != "done":
            sections.append((name, sql))
    return sections


def emit_pgadmin_sql(sections: list[tuple[str, str]]) -> str:
    """One statement, one row per section (name, jsonb array of rows):
    pgAdmin runs no `\\echo` and shows only the last result set."""
    header = """\
-- crowdsourcing_report_export_pgadmin.sql
-- ---------------------------------------------------------------------
-- GENERATED from crowdsourcing_report_export.sql by
--   uv run python scripts/crowdsourcing_report.py --emit-pgadmin-sql
-- Do not edit by hand.
--
-- pgAdmin variant of the crowdsourcing report export: ONE statement,
-- one result row per section (section name + JSON array of rows).
--
-- How to run in pgAdmin:
--   1. Open the Query Tool on the production database.
--   2. Paste this whole file, press F5 (Execute). Only the final SELECT
--      produces a grid; the SET line just fixes the timezone.
--   3. In the result grid toolbar choose "Save results to file"
--      (download icon) -> CSV. Keep the default quoting.
--   4. uv run python scripts/crowdsourcing_report.py --from-csv <that csv>
--
-- Read-only. No e-mails, no IP material, no OTP data are exported;
-- display names only where already public in the gallery (proposal and
-- comment authors). Feedback rows carry text but no author identity.
-- ---------------------------------------------------------------------

SET TIME ZONE 'Europe/Berlin';

"""
    blocks = []
    for name, sql in sections:
        indented = "\n".join("    " + line if line else "" for line in sql.splitlines())
        blocks.append(
            f"SELECT '{name}'::text AS section, (\n"
            f"  SELECT jsonb_agg(t) FROM (\n\n{indented}\n  ) t\n) AS data"
        )
    return header + "\nUNION ALL\n".join(blocks) + ";\n"


def load_sections_from_csv(path: Path) -> dict[str, list[dict]]:
    """The pgAdmin grid saved as CSV: columns `section`, `data` (JSON)."""
    csv.field_size_limit(sys.maxsize)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    # pgAdmin writes the header first; psql --csv may print a SET line before.
    start = next(i for i, row in enumerate(rows) if row == ["section", "data"])
    return {
        section: json.loads(data) if data else []
        for section, data in rows[start + 1 :]
        if section
    }


def load_sections_from_db(sections: list[tuple[str, str]]) -> dict[str, list[dict]]:
    """Run the export here, section by section, through the adapters' pool
    — the same jsonb_agg wrapping as the pgAdmin variant, so both routes
    hand back identical structures."""
    import dev_env

    dev_env.resolve_env()
    from adapters.db_pool import default_pool

    out: dict[str, list[dict]] = {}
    with default_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'Europe/Berlin'")
        for name, sql in sections:
            cur.execute(f"SELECT jsonb_agg(t) FROM ({sql}) t")
            out[name] = cur.fetchone()[0] or []
    return out


# --- figures -----------------------------------------------------------------


# Codes the basemap uses that ISO 3166 does not carry.
_EXTRA_COUNTRY_NAMES = {"XK": "Kosovo"}


def country_name(iso2: str) -> str:
    country = pycountry.countries.get(alpha_2=iso2)
    if country is None:
        return _EXTRA_COUNTRY_NAMES.get(iso2, iso2)
    return getattr(country, "common_name", None) or country.name


def relation_label(relation: str) -> str:
    return "–".join(country_name(c) for c in relation.split("__"))


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1 = map(math.radians, a)
    la2, lo2 = map(math.radians, b)
    x = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(x))


def one_way_km(p: dict) -> float:
    # proposal_summaries.total_distance_km / total_time_h sum BOTH directions
    # (models/evaluation/summary.py::_route_metrics); the report is one way.
    return float(p["total_distance_km"]) / 2


def one_way_h(p: dict) -> float:
    return float(p["total_time_h"]) / 2


def in_envelope(p: dict) -> bool:
    return (
        ENVELOPE_KM[0] <= one_way_km(p) <= ENVELOPE_KM[1]
        and ENVELOPE_H[0] <= one_way_h(p) <= ENVELOPE_H[1]
        and float(p["avg_speed_kmh"]) >= ENVELOPE_MIN_SPEED_KMH
    )


def bucket_index(value: float, edges: tuple[float, ...]) -> int:
    """Index of the bucket [edges[i], edges[i+1]); the last bucket is open
    upwards, the first open downwards."""
    for i in range(len(edges) - 1, -1, -1):
        if value >= edges[i]:
            return i
    return 0


def histogram(values: list[float], edges: tuple[float, ...], fmt) -> dict:
    counts = Counter(bucket_index(v, edges) for v in values)
    labels = [fmt(e) for e in edges]
    labels[-1] += "+"
    return {"labels": labels, "values": [counts.get(i, 0) for i in range(len(edges))]}


def corridor_dedup(
    typical: list[dict], coords: dict, names: dict, cities: dict, gallery: str
) -> dict:
    """Three-level de-duplication of the typical night trains.
    Level 1: unordered terminus pair. Level 2: terminus cities (stations
    within CITY_KM merged, greedily by frequency). Level 3: corridors —
    greedy assignment to the best-matching representative (same city pair,
    or ≥ CORRIDOR_SIM of cities in common, or one route contained in the
    other sharing a terminus); deliberately no transitive merging, which
    chained unrelated corridors through hubs."""
    stop_lists = {p["proposal_id"]: p["stop_ids"] for p in typical}
    freq = Counter(s for stops in stop_lists.values() for s in stops)
    centres: list[str] = []
    city: dict[str, str] = {}
    for stop, _ in freq.most_common():
        for centre in centres:
            if (
                stop in coords
                and centre in coords
                and haversine_km(coords[stop], coords[centre]) <= CITY_KM
            ):
                city[stop] = centre
                break
        else:
            centres.append(stop)
            city[stop] = stop
    city_sets = {pid: {city[s] for s in stops} for pid, stops in stop_lists.items()}
    city_pair = {
        pid: frozenset((city[stops[0]], city[stops[-1]]))
        for pid, stops in stop_lists.items()
    }
    pair_freq = Counter(city_pair.values())

    def similarity(a: int, b: int) -> float:
        if city_pair[a] == city_pair[b]:
            return 1.0
        inter = len(city_sets[a] & city_sets[b])
        jaccard = inter / len(city_sets[a] | city_sets[b])
        smaller = min(len(city_sets[a]), len(city_sets[b]))
        shares_terminus = bool(city_pair[a] & city_pair[b]) and smaller >= 4
        containment = inter / smaller if shares_terminus else 0
        return max(jaccard, containment)

    representatives: list[int] = []
    member: dict[int, int] = {}
    ordered = sorted(
        typical,
        key=lambda p: (
            -pair_freq[city_pair[p["proposal_id"]]],
            -len(city_sets[p["proposal_id"]]),
        ),
    )
    for p in ordered:
        pid = p["proposal_id"]
        best, best_score = None, 0.0
        for rep in representatives:
            score = similarity(pid, rep)
            if score > best_score:
                best, best_score = rep, score
        if best is not None and best_score >= CORRIDOR_SIM:
            member[pid] = best
        else:
            representatives.append(pid)
            member[pid] = pid
    variants = Counter(member.values())
    by_id = {p["proposal_id"]: p for p in typical}

    def label(pair: frozenset) -> str:
        return " – ".join(
            sorted(SHORT_NAMES.get(names.get(c, c), names.get(c, c)) for c in pair)
        )

    def pair_href(a: str, b: str) -> str:
        # The gallery's city tab (OSM place ids) covers every station of both
        # cities; without city ids in the export, the two centre stations.
        if cities.get(a) and cities.get(b):
            return f"{gallery}?tab=city&kind=fromTo&a={cities[a]}&b={cities[b]}"
        return f"{gallery}?tab=station&kind=fromTo&a={a}&b={b}"

    top_pairs = []
    for pair, n in pair_freq.most_common(10):
        a, b = sorted(pair, key=lambda c: names.get(c, c))
        members = [by_id[pid] for pid, cp in city_pair.items() if cp == pair]
        top_pairs.append(
            {
                "label": label(pair),
                "value": n,
                "authors": len({m["author"] for m in members}),
                # Intermediate stops of the shortest and longest variant.
                "min_via": min(m["n_stops"] for m in members) - 2,
                "max_via": max(m["n_stops"] for m in members) - 2,
                "href": pair_href(a, b),
            }
        )
    same_author_dups = len(typical) - len(
        {(cp, by_id[pid]["author"]) for pid, cp in city_pair.items()}
    )
    return {
        "pairs": len(pair_freq),
        "corridors": len(representatives),
        "max_variants": max(variants.values()),
        "top_pairs": top_pairs,
        "same_author_dups": same_author_dups,
    }


class Projection:
    """Mercator over the map window, MAP_WIDTH px wide."""

    def __init__(self) -> None:
        self.scale = MAP_WIDTH / math.radians(MAP_LON[1] - MAP_LON[0])
        self.y_top = self._merc(MAP_LAT[1])
        self.height = round((self.y_top - self._merc(MAP_LAT[0])) * self.scale)

    @staticmethod
    def _merc(lat: float) -> float:
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        lat = max(min(lat, 84), -84)
        x = math.radians(lon - MAP_LON[0]) * self.scale
        return x, (self.y_top - self._merc(lat)) * self.scale

    def contains(self, lon: float, lat: float) -> bool:
        return MAP_LON[0] <= lon <= MAP_LON[1] and MAP_LAT[0] <= lat <= MAP_LAT[1]


def _rdp(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    d_max, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        if length:
            d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / length
        else:
            d = math.hypot(x - x0, y - y0)
        if d > d_max:
            d_max, idx = d, i
    if d_max > eps:
        return _rdp(pts[: idx + 1], eps)[:-1] + _rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def simplify_ring(pts: list[tuple[float, float]], eps: float) -> list:
    """Douglas–Peucker on a closed ring: split at the point farthest from
    the start so neither half degenerates to its own end points."""
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    far = max(
        range(len(pts)),
        key=lambda i: math.hypot(pts[i][0] - pts[0][0], pts[i][1] - pts[0][1]),
    )
    return _rdp(pts[: far + 1], eps)[:-1] + _rdp(pts[far:] + [pts[0]], eps)[:-1]


def build_basemap(source: Path, proj: Projection) -> dict:
    """Natural Earth admin-0 GeoJSON → one SVG path per ISO-3166 alpha-2
    inside the map window, simplified to BASEMAP_TOLERANCE_PX."""
    with open(source, encoding="utf-8") as fh:
        collection = json.load(fh)
    margin = 5
    paths: dict[str, str] = {}
    for feature in collection["features"]:
        props = feature["properties"]
        iso = props.get("ISO_A2_EH") or props.get("ISO_A2")
        if not iso or iso == "-99":
            continue
        geometry = feature["geometry"]
        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        d = []
        for polygon in polygons:
            ring = polygon[0]
            if not any(
                MAP_LON[0] - margin < lon < MAP_LON[1] + margin
                and MAP_LAT[0] - margin < lat < MAP_LAT[1] + margin
                for lon, lat in ring
            ):
                continue
            pts = [proj(lon, lat) for lon, lat in ring]
            xs, ys = [x for x, _ in pts], [y for _, y in pts]
            if (
                max(xs) - min(xs) < BASEMAP_MIN_EXTENT_PX
                and max(ys) - min(ys) < BASEMAP_MIN_EXTENT_PX
            ):
                continue
            pts = simplify_ring(pts, BASEMAP_TOLERANCE_PX)
            if len(pts) >= 3:
                d.append("M" + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        if d:
            paths[iso] = "".join(d)
    return {
        "source": "Natural Earth 50m admin 0 countries (public domain)",
        "window": {"lon": MAP_LON, "lat": MAP_LAT},
        "width": MAP_WIDTH,
        "height": proj.height,
        "names": {iso: country_name(iso) for iso in sorted(paths)},
        "paths": paths,
    }


def build_figures(
    data: dict[str, list[dict]],
    window: tuple[dt.date, dt.date],
    edition: str,
    gallery: str,
    proj: Projection,
) -> dict:
    start, end = window
    days = [
        (start + dt.timedelta(n)).isoformat() for n in range((end - start).days + 1)
    ]
    day_labels = [str(dt.date.fromisoformat(d).day) for d in days]

    def per_day(section: str, key: str) -> list[int]:
        by_day = {row["day"]: row[key] for row in data[section]}
        return [by_day.get(d, 0) for d in days]

    proposals = [
        {**p, "stop_ids": p["stop_ids"].split("|")}
        for p in data["proposals_list"]
        if days[0] <= p["created_at"][:10] <= days[-1]
    ]
    if not proposals:
        raise SystemExit("No proposals in the window — check --window.")
    typical = [p for p in proposals if in_envelope(p)]
    coords = {
        r["stop_id"]: (float(r["stop_lat"]), float(r["stop_lon"]))
        for r in data["stop_coords"]
    }
    # city_osm_id is in the export since 2026-10-04; older exports link pairs
    # by station instead of by city.
    cities = {
        r["stop_id"]: r["city_osm_id"]
        for r in data["stop_coords"]
        if r.get("city_osm_id")
    }
    if not cities:
        logger.warning("Export carries no city ids; city-pair links use stations.")
    stop_names = {r["stop_id"]: r["stop_name"] for r in data["stops_frequency"]}
    catalog = load_catalog()
    catalog.raise_for_errors()
    places = {c.composition_type_id: c.places for c in catalog.compositions}

    def station_href(stop_id: str) -> str:
        return f"{gallery}?tab=station&kind=via&a={stop_id}"

    def station_rows(counter: Counter, n: int) -> list[dict]:
        return [
            {
                "label": stop_names.get(stop_id, stop_id),
                "value": count,
                "href": station_href(stop_id),
            }
            for stop_id, count in counter.most_common(n)
        ]

    # 01 · people
    registered_per_day = per_day("users_per_day", "registered")
    guests_per_day = per_day("users_per_day", "guests")
    merged = data["users_totals"][0]["guests_merged_into_accounts"]
    active_per_day = per_day("usage_per_day", "distinct_users")
    people = {
        "total": sum(registered_per_day) + sum(guests_per_day) - merged,
        "registered": sum(registered_per_day),
        "guests": sum(guests_per_day) - merged,
        "day_one_active": active_per_day[0],
        "returned": data["usage_per_user_profile"][0]["users_returned_2plus_days"],
        "active_per_day": active_per_day,
    }

    # 02 · built
    authors = len({p["author"] for p in proposals})
    edited = sum(1 for p in proposals if p["proposal_version"] > 1)
    built = {
        "total": len(proposals),
        "authors": authors,
        "max_by_one_author": max(Counter(p["author"] for p in proposals).values()),
        "single_route_authors_share": (
            sum(1 for n in Counter(p["author"] for p in proposals).values() if n == 1)
            / authors
        ),
        "edited_share": edited / len(proposals),
        "republishes": sum(p["proposal_version"] - 1 for p in proposals),
        "max_versions": max(p["proposal_version"] for p in proposals),
        "per_day": per_day("proposals_per_day", "published"),
    }

    # 03 · where
    countries = Counter(
        c for p in proposals for c in p["countries"].split("|") if c != "UNK"
    )
    domestic = sum(1 for p in proposals if "|" not in p["countries"])
    stations = Counter(s for p in proposals for s in p["stop_ids"])
    termini = Counter(
        s for p in proposals for s in (p["stop_ids"][0], p["stop_ids"][-1])
    )
    # Served country relations (models/evaluation/summary.py::country_relations),
    # per proposal in the export since 2026-10-04. Older exports only carry the
    # whole-table ranking, which also counts the pre-launch trial proposals.
    if "country_relations" in proposals[0]:
        relations = Counter(
            rel for p in proposals for rel in p["country_relations"].split("|") if rel
        )
    else:
        logger.warning("Export predates per-proposal relations; ranking is all-time.")
        relations = Counter(
            {r["relation"]: r["proposals"] for r in data["country_relations_frequency"]}
        )
    top_countries = countries.most_common(2)
    bubbles = []
    for stop_id, n in stations.most_common(MAP_BUBBLES):
        if stop_id not in coords:
            continue
        lat, lon = coords[stop_id]
        if not proj.contains(lon, lat):
            continue
        x, y = proj(lon, lat)
        bubbles.append(
            {
                "id": stop_id,
                "name": stop_names.get(stop_id, stop_id),
                "value": n,
                "x": round(x, 1),
                "y": round(y, 1),
                "href": station_href(stop_id),
            }
        )
    where = {
        "cross_border_share": 1 - domestic / len(proposals),
        "domestic_share": domestic / len(proposals),
        "median_countries": statistics.median(
            len(p["countries"].split("|")) for p in proposals
        ),
        "countries": len(countries),
        "stations": len(stations),
        "top_countries": [
            {"iso": iso, "name": country_name(iso), "share": n / len(proposals)}
            for iso, n in top_countries
        ],
        "top_relations": [
            {"label": relation_label(rel), "value": n}
            for rel, n in relations.most_common(3)
        ],
        "most_used_station": station_rows(stations, 1)[0],
        "top_terminus": station_rows(termini, 1)[0],
        "stations_most_used": station_rows(stations, 8),
        "termini_most_used": station_rows(termini, 8),
        "map": {
            "countries": {
                iso: {"value": n, "href": f"{gallery}?tab=country&kind=via&a={iso}"}
                for iso, n in countries.items()
            },
            "bubbles": bubbles,
            "labelled": [b["id"] for b in bubbles[:MAP_LABELS]],
        },
    }

    # 04 · how far
    one_way = [one_way_km(p) for p in proposals]
    longest = max(proposals, key=one_way_km)
    shortest = min(proposals, key=one_way_km)
    distance_hist = histogram(one_way, DISTANCE_BUCKETS_KM, lambda e: f"{e:.0f}")
    distance_hist["highlight"] = [
        i
        for i, e in enumerate(DISTANCE_BUCKETS_KM)
        if ENVELOPE_KM[0] <= e < ENVELOPE_KM[1]
    ]
    distance = {
        "total_km": sum(one_way),
        "equator_laps": sum(one_way) / 40_075,
        "median_km": statistics.median(one_way),
        "median_h": statistics.median(one_way_h(p) for p in proposals),
        "longest": {
            "name": longest["name"],
            "km": one_way_km(longest),
            "nights": round(one_way_h(longest) / 24),
        },
        "shortest": {"name": shortest["name"], "km": one_way_km(shortest)},
        "two_stop": sum(1 for p in proposals if p["n_stops"] == 2),
        "histogram": distance_hist,
    }

    # 05 · funnel
    dedup = corridor_dedup(typical, coords, stop_names, cities, gallery)
    funnel = {
        "typical": len(typical),
        "typical_share": len(typical) / len(proposals),
        "too_short": sum(1 for k in one_way if k < ENVELOPE_KM[0]),
        "too_long": sum(1 for k in one_way if k > ENVELOPE_KM[1]),
        "too_slow": sum(
            1 for p in proposals if float(p["avg_speed_kmh"]) < ENVELOPE_MIN_SPEED_KMH
        ),
        "over_time": sum(1 for p in proposals if one_way_h(p) > ENVELOPE_H[1]),
        "under_time": sum(1 for p in proposals if one_way_h(p) < ENVELOPE_H[0]),
        "pairs": dedup["pairs"],
        "corridors": dedup["corridors"],
        "max_variants": dedup["max_variants"],
        "rows": [
            {"label": "Proposals published", "value": len(proposals)},
            {"label": "Typical night trains", "value": len(typical)},
            {"label": "Distinct city pairs", "value": dedup["pairs"]},
            {"label": "Corridors", "value": dedup["corridors"]},
        ],
    }

    # 06 · agree
    top_pair = dedup["top_pairs"][0]
    agree = {
        "top_pair": top_pair,
        "duplicate_share": 1 - dedup["pairs"] / len(typical),
        "same_author_dups": dedup["same_author_dups"],
        "pairs": dedup["top_pairs"],
    }

    # 07 · supply (typical night trains only, supply side only)
    def seat_km(p: dict) -> float:
        # The export carries the summary's own figure since 2026-10-04; the
        # catalogue product is the fallback for older exports.
        if p.get("available_place_km_per_year") is not None:
            return float(p["available_place_km_per_year"])
        return float(p["train_km_per_year"]) * places.get(p["composition_id"], 0)

    costs = [float(p["cost_eur_per_train_km"]) for p in typical]
    supply = {
        "train_km": sum(float(p["train_km_per_year"]) for p in typical),
        "departures": sum(float(p["departures_per_year"]) for p in typical),
        "seat_km": sum(seat_km(p) for p in typical),
        "trainsets": sum(float(p["trainsets_physical"]) for p in typical),
        "trainsets_nightly": sum(
            float(p["trainsets_physical"]) * p["operating_days_per_year"] / 366
            for p in typical
        ),
        "cost_median": statistics.median(costs),
        "cost_histogram": histogram(costs, COST_BUCKETS_EUR, lambda e: f"{e:g}"),
    }

    # 08 · composition
    comp = Counter(p["composition_id"] for p in typical)
    op_days = Counter(p["operating_days_per_year"] for p in typical)
    comp_rows = [
        {"label": cid, "value": n, "share": n / len(typical)}
        for cid, n in comp.most_common(5)
    ]
    other = len(typical) - sum(r["value"] for r in comp_rows)
    comp_rows.append({"label": "other", "value": other, "share": other / len(typical)})
    composition = {
        "default_id": DEFAULT_COMPOSITION_ID,
        "default_places": places[DEFAULT_COMPOSITION_ID],
        "default_coaches": next(
            c.n_coaches
            for c in catalog.compositions
            if c.composition_type_id == DEFAULT_COMPOSITION_ID
        ),
        "default_share": comp[DEFAULT_COMPOSITION_ID] / len(typical),
        "catalogue_size": len(catalog.compositions),
        "every_night_share": op_days[366] / len(typical),
        "three_nights_share": op_days[157] / len(typical),
        "rows": comp_rows,
    }

    # 09 · talk
    engagement = data["engagement_totals"][0]
    talk = {
        "likes": sum(p["likes"] for p in proposals),
        "comments": sum(p["comments"] for p in proposals),
        "likers": engagement["distinct_likers"],
        "commenters": engagement["distinct_commenters"],
    }

    # 10 · feedback
    feedback_rows_in = [
        f for f in data["feedback_list"] if f["created_at"][:10] >= days[0]
    ]
    by_theme = Counter(
        f["sub_category"] if f["category"] == "Route or timetable" else f["category"]
        for f in feedback_rows_in
    )
    feedback = {
        "total": len(feedback_rows_in),
        "rows": [
            {"label": FEEDBACK_LABELS.get(theme, theme), "value": n}
            for theme, n in by_theme.most_common()
        ],
        "by_theme": {FEEDBACK_LABELS.get(t, t): n for t, n in by_theme.items()},
    }

    # footer
    endpoints = {r["endpoint"]: r for r in data["usage_by_endpoint"]}
    footer = {
        "calculations": sum(per_day("usage_per_day", "family_builds")),
        "median_calculation_s": endpoints["proposal_family.post_family"]["p50_ms"]
        / 1000,
        "server_errors": sum(per_day("usage_per_day", "server_errors")),
        "mobile_share": _mobile_share(data["usage_mobile_share"]),
    }

    return {
        "edition": edition,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "exported_at": data["meta_now"][0]["exported_at"],
        "window": {
            "start": days[0],
            "end": days[-1],
            "days": len(days),
            "day_labels": day_labels,
        },
        "envelope": {
            "km": ENVELOPE_KM,
            "h": ENVELOPE_H,
            "min_speed_kmh": ENVELOPE_MIN_SPEED_KMH,
            "city_km": CITY_KM,
        },
        "gallery": gallery,
        "people": people,
        "built": built,
        "where": where,
        "distance": distance,
        "funnel": funnel,
        "agree": agree,
        "supply": supply,
        "composition": composition,
        "talk": talk,
        "feedback": feedback,
        "footer": footer,
    }


def _mobile_share(rows: list[dict]) -> float:
    by_flag = {bool(r["is_mobile"]): r["requests"] for r in rows}
    total = sum(by_flag.values())
    return by_flag.get(True, 0) / total if total else 0.0


# --- main --------------------------------------------------------------------


def parse_window(text: str) -> tuple[dt.date, dt.date]:
    try:
        start, end = (dt.date.fromisoformat(part) for part in text.split(".."))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "window must be YYYY-MM-DD..YYYY-MM-DD"
        ) from exc
    if end < start:
        raise argparse.ArgumentTypeError("window end precedes its start")
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--from-csv", type=Path, help="pgAdmin grid saved as CSV")
    source.add_argument(
        "--db", action="store_true", help="run the export against the configured DB"
    )
    parser.add_argument("--edition", help="output name, e.g. 2026-10-launch")
    parser.add_argument(
        "--window", type=parse_window, help="inclusive report window, start..end"
    )
    parser.add_argument(
        "--gallery", default="/gallery", help="gallery URL the links point to"
    )
    parser.add_argument(
        "--basemap-source",
        type=Path,
        help="Natural Earth 50m admin-0 GeoJSON; rebuilds europe-basemap.json",
    )
    parser.add_argument(
        "--emit-pgadmin-sql",
        action="store_true",
        help="regenerate the single-statement pgAdmin variant of the export",
    )
    args = parser.parse_args()

    sections = split_psql_sections(PSQL_SQL.read_text(encoding="utf-8"))
    if args.emit_pgadmin_sql:
        PGADMIN_SQL.write_text(emit_pgadmin_sql(sections), encoding="utf-8")
        logger.info("Wrote %s (%d sections).", PGADMIN_SQL, len(sections))

    proj = Projection()
    if args.basemap_source:
        REPORT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        basemap = build_basemap(args.basemap_source, proj)
        BASEMAP_PATH.write_text(
            json.dumps(basemap, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote %s (%d countries).", BASEMAP_PATH, len(basemap["paths"]))

    if not (args.from_csv or args.db):
        if not (args.emit_pgadmin_sql or args.basemap_source):
            parser.error("one of --from-csv, --db, --emit-pgadmin-sql is required")
        return 0
    if not (args.edition and args.window):
        parser.error("--edition and --window are required with --from-csv/--db")
    if not BASEMAP_PATH.is_file():
        parser.error(f"{BASEMAP_PATH} is missing; pass --basemap-source once")

    data = (
        load_sections_from_csv(args.from_csv)
        if args.from_csv
        else load_sections_from_db(sections)
    )
    missing = {name for name, _ in sections} - set(data)
    if missing:
        logger.warning("Export lacks section(s): %s", ", ".join(sorted(missing)))
    figures = build_figures(data, args.window, args.edition, args.gallery, proj)

    REPORT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DATA_DIR / f"{args.edition}.json"
    out.write_text(
        json.dumps(figures, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    logger.info(
        "Wrote %s — %d proposals, %d typical night trains, %d corridors.",
        out,
        figures["built"]["total"],
        figures["funnel"]["typical"],
        figures["funnel"]["corridors"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
