"""
export_country_geoms.py
=======================
Produce db/dev/data/country_geoms.geojson.gz — the country border polygons
db/dev/seed.py writes into input_params.countries.country_geom.

Runs automatically at container start (backend/docker/entrypoint.sh and the
db/dev seeder image), before seed.py, and is a no-op once the file exists —
same shape as the routing container's graph-cache download
(models/route/routing/docker/entrypoint.sh): check for the artifact, fetch
the source from Drive if it isn't there, carry on.

Source: Marine Regions "Union of the ESRI Country shapefile and the
Exclusive Economic Zones", version 4 (Flanders Marine Institute, 2024,
https://doi.org/10.14284/698, CC-BY 4.0), Drive-hosted as the .zip exactly
as downloaded. The zip is the unit because a shapefile is not one file: the
geometry (.shp), its index (.shx), the attribute table (.dbf) and the
projection (.prj) must travel together, and pyshp opens the archive
directly. Not committed (no large data in the repo), and not pre-converted
either: the conversion is deterministic and takes ~5s, so hosting the raw
source keeps one artifact instead of two and makes a source upgrade a
re-run rather than a re-upload.

Each feature covers a country's LAND AND ITS MARITIME ZONES, which is why
it replaced the Natural Earth admin-0 land polygons: at land-only
resolution every strait, belt and tunnel crossing fell outside all polygons
and was attributed to the "UNK" sentinel, taking real track on both
approaches with it (Fehmarn Belt, Storebælt, Øresund, Channel Tunnel). With
maritime zones included, the only unattributed water left is open ocean no
train ever reaches.

Manual runs (the automatic one needs no arguments):

    cd backend
    uv run python scripts/export_country_geoms.py             # download + convert
    uv run python scripts/export_country_geoms.py <path>      # convert a local copy
    uv run python scripts/export_country_geoms.py --force     # rebuild an existing artifact
    uv run python scripts/export_country_geoms.py --dry-run   # report only

<path> is the Marine Regions download, either the .zip as downloaded or the
extracted .shp (pyshp reads both).

Derivation:
  - keep the countries in _COUNTRY_CODE_TO_ISO3 — every country the tool
    models that has a rail network (Malta and Cyprus are deliberately
    absent: no railways, so no route can ever transit them)
  - keep only POL_TYPE "Union EEZ and country" / "Landlocked country".
    Joint-regime areas and overlapping claims are the sole source of
    overlapping polygons in the dataset; dropping them is what makes the
    point-in-polygon lookup single-valued
  - clip to _CLIP_BBOX, which drops the Azores, Canaries and Svalbard —
    railless, and their EEZs are larger than mainland Europe
  - merge each country's remaining features into one MultiPolygon
    (matching the column type) keyed by ISO 3166-1 alpha-2
"""

import argparse
import gzip
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import shapefile
from shapely.geometry import MultiPolygon, box, mapping, shape
from shapely.ops import unary_union

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT_PATH = _BACKEND_ROOT / "db" / "dev" / "data" / "country_geoms.geojson.gz"

# Overridable so the db/dev seeder image, which lays the tree out
# differently, can point at its own path without a code change. seed.py
# reads the same variable — one wiring value, one name.
OUT_PATH = Path(os.environ.get("COUNTRY_GEOMS_PATH", _DEFAULT_OUT_PATH))

# Configured via EEZ_LAND_UNION_FILE_ID in backend/docker/.env (see
# .env.example), alongside the other Drive ids. The literal below is only a
# fallback for stacks that do not inject it yet — same arrangement as
# GRAPH_CACHE_FILE_ID in the routing container's entrypoint.
EEZ_LAND_UNION_FILE_ID = os.environ.get(
    "EEZ_LAND_UNION_FILE_ID", "1bEqIfs8F4q7B36lsc2OZfJVx19dDEvOT"
)

# The usercontent endpoint with confirm=t bypasses Drive's virus-scan
# interstitial, which would otherwise be served instead of the file.
_DOWNLOAD_URL = "https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"

# ISO 3166-1 alpha-2 → alpha-3, for exactly the rail-network countries in
# db/dev/seed.py's COUNTRIES. Marine Regions keys its features by alpha-3
# (ISO_TER1); every other country code in the codebase is alpha-2, so the
# translation happens here, once, and the artifact ships alpha-2 only.
_COUNTRY_CODE_TO_ISO3 = {
    "AL": "ALB",
    "AT": "AUT",
    "BA": "BIH",
    "BY": "BLR",
    "BE": "BEL",
    "BG": "BGR",
    "CH": "CHE",
    "CZ": "CZE",
    "DE": "DEU",
    "DK": "DNK",
    "EE": "EST",
    "ES": "ESP",
    "FI": "FIN",
    "FR": "FRA",
    "GB": "GBR",
    "GR": "GRC",
    "HR": "HRV",
    "HU": "HUN",
    "IE": "IRL",
    "IT": "ITA",
    "LI": "LIE",
    "LT": "LTU",
    "LU": "LUX",
    "LV": "LVA",
    "MD": "MDA",
    "ME": "MNE",
    "MK": "MKD",
    "NL": "NLD",
    "NO": "NOR",
    "PL": "POL",
    "PT": "PRT",
    "RO": "ROU",
    "RS": "SRB",
    "RU": "RUS",
    "SE": "SWE",
    "SI": "SVN",
    "SK": "SVK",
    "TR": "TUR",
    "UA": "UKR",
}

# A territory can appear several times in the source: its own union polygon
# plus any joint regime it participates in. Only these two types are
# unambiguously "this country's area" — the rest overlap a neighbour's
# polygon, which would make the lookup order-dependent.
_SOURCE_POL_TYPES = frozenset({"Union EEZ and country", "Landlocked country"})

# (min_lon, min_lat, max_lon, max_lat) — continental Europe plus its shelf
# seas, sized to the rail network rather than to sovereignty.
_CLIP_BBOX = (-25.0, 34.0, 45.0, 72.0)

# Contract with seed.py's _COUNTRY_GEOMS_PROPERTY: the only property the
# seed reads, and its validation gate.
_PROPERTY = "country_code"


def download_source(destination: Path) -> None:
    """Fetch the Drive-hosted shapefile zip.

    Raises on anything that isn't a readable zip: a Drive permission error
    returns an HTML page, which would otherwise fail much later and far
    less legibly, inside the shapefile reader.
    """
    url = _DOWNLOAD_URL.format(file_id=EEZ_LAND_UNION_FILE_ID)
    print(f"  downloading EEZ land union from Drive (id={EEZ_LAND_UNION_FILE_ID})...")
    urllib.request.urlretrieve(url, destination)
    if not zipfile.is_zipfile(destination):
        raise ValueError(
            f"downloaded content is not a zip ({destination.stat().st_size} bytes) "
            "— wrong file id, or the Drive file is not shared publicly"
        )
    print(f"  downloaded {destination.stat().st_size / 1e6:.1f} MB.")


def _read_country_shapes(source: Path) -> dict[str, list]:
    """Group the source's polygons by alpha-2 code, clipped to the bbox.

    Invalid ring geometry is repaired with buffer(0) — the source has a few
    self-touching maritime rings that shapely rejects and PostGIS would
    too, so fixing them here keeps the artifact loadable.
    """
    iso3_to_alpha2 = {v: k for k, v in _COUNTRY_CODE_TO_ISO3.items()}
    clip = box(*_CLIP_BBOX)
    reader = shapefile.Reader(str(source))
    fields = [f[0] for f in reader.fields[1:]]

    by_country: dict[str, list] = {}
    for shape_record in reader.iterShapeRecords():
        record = dict(zip(fields, shape_record.record))
        iso3 = record["ISO_TER1"] or record["ISO_SOV1"]
        if iso3 not in iso3_to_alpha2 or record["POL_TYPE"] not in _SOURCE_POL_TYPES:
            continue
        geom = shape(shape_record.shape.__geo_interface__)
        if not geom.is_valid:
            geom = geom.buffer(0)
        clipped = geom.intersection(clip)
        if not clipped.is_empty:
            by_country.setdefault(iso3_to_alpha2[iso3], []).append(clipped)
    return by_country


def _vertex_count(geom) -> int:
    polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    return sum(
        len(p.exterior.coords) + sum(len(i.coords) for i in p.interiors)
        for p in polygons
    )


def build_feature_collection(source: Path) -> tuple[dict, list[str]]:
    by_country = _read_country_shapes(source)
    features, report = [], []
    for code in sorted(by_country):
        merged = unary_union(by_country[code])
        if merged.geom_type == "Polygon":
            merged = MultiPolygon([merged])
        features.append(
            {
                "type": "Feature",
                "properties": {_PROPERTY: code},
                "geometry": mapping(merged),
            }
        )
        report.append(
            f"    {code}  {len(merged.geoms):3d} polygons  "
            f"{_vertex_count(merged):7,d} vertices"
        )
    return {"type": "FeatureCollection", "features": features}, report


def convert(source: Path, dry_run: bool) -> int:
    collection, report = build_feature_collection(source)
    found = {f["properties"][_PROPERTY] for f in collection["features"]}
    missing = sorted(set(_COUNTRY_CODE_TO_ISO3) - found)
    payload = json.dumps(collection, separators=(",", ":"))

    print("\n".join(report))
    print(f"  {len(found)} countries, {len(payload) / 1e6:.1f} MB uncompressed")

    if missing:
        print(
            f"  ERROR: no source feature for {', '.join(missing)} — the source "
            "file is not the expected Marine Regions EEZ land union, or its "
            "POL_TYPE/ISO_TER1 fields have changed."
        )
        return 1
    if dry_run:
        print("  --dry-run: nothing written.")
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT_PATH, "wt", encoding="utf-8") as fh:
        fh.write(payload)
    print(f"  wrote {OUT_PATH} ({OUT_PATH.stat().st_size / 1e6:.1f} MB gzipped).")
    return 0


def run(source: Path | None, force: bool, dry_run: bool) -> int:
    if OUT_PATH.is_file() and not force and not dry_run:
        print(f"Country geometries found at {OUT_PATH} — skipping rebuild.")
        return 0

    if source is not None:
        if not source.exists():
            print(f"ERROR: source not found: {source}")
            return 1
        print(f"Building country geometries from {source} ...")
        return convert(source, dry_run)

    # No local source: fetch into a temp dir cleaned up either way — the
    # 26MB zip is an input, not something to leave behind in the image or on
    # a developer's disk.
    print("Building country geometries ...")
    with tempfile.TemporaryDirectory() as tmp:
        downloaded = Path(tmp) / "eez_land_union.zip"
        try:
            download_source(downloaded)
        except Exception as e:
            print(f"  ERROR: download failed ({type(e).__name__}: {e})")
            return 1
        return convert(downloaded, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build db/dev/data/country_geoms.geojson.gz from the Marine "
        "Regions EEZ land union (downloaded from Drive when no local source is "
        "given)."
    )
    parser.add_argument(
        "source",
        type=Path,
        nargs="?",
        help="local Marine Regions EEZ land union (.zip or .shp); omit to "
        "download it from Drive",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild even if the artifact already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written without writing it",
    )
    args = parser.parse_args()
    return run(args.source, args.force, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
