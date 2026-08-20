"""Batch 1 ETL — build the demand-model zone frame.

Reads the batch-1 downloads in ``calib/raw/01_zones`` and writes a single
GeoParquet artifact to ``calib/out``. See ``docu/DEMAND_MODEL_CONCEPT.md`` §3
for the inventory, ``docu/SOURCES.md`` for provenance, and
``calib/exploration/01_zone_exploration.ipynb`` for why the steps look the way
they do.

Run from anywhere in the repository::

    uv run --project backend python backend/models/demand/calib/etl/step1_zones.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from rasterio.windows import transform as window_transform
from shapely.geometry import MultiPolygon

# --- standard values --------------------------------------------------------

NUTS_VERSION = "2021"
CENSUS_YEAR = 2021
GRID_CELL_M = 1000
CODE_SEP = "-"  # NUTS codes contain no hyphen; border cells join codes with it
OUT_CRS = 4326
WORK_CRS = 3035

# Routing scope, not data availability: Norway has complete data and is still
# Tier 2. Revisit here when a country becomes routable.
# fmt: off
TIER_1_COUNTRIES = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES",  # EU-27
    "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
    "NL", "PL", "PT", "RO", "SE", "SI", "SK",
    "CH",                                    # EFTA, already routable
})
# fmt: on

STATUS_FLAGS = {"EU_STAT": "EU", "EFTA_STAT": "EFTA", "CC_STAT": "candidate"}

OUT_NAME = "01_zones.parquet"


def _paths() -> tuple[Path, Path]:
    """Locate ``calib/raw/01_zones`` and ``calib/out`` from any working directory."""
    here = Path(__file__).resolve()
    calib = next(p for p in here.parents if p.name == "calib")
    out = calib / "out"
    out.mkdir(parents=True, exist_ok=True)
    return calib / "raw" / "01_zones", out


# --- extract ----------------------------------------------------------------


def extract(raw: Path) -> dict:
    """Load every batch-1 input. No transformation beyond parsing."""
    nuts3 = gpd.read_file(raw / f"NUTS_RG_01M_{NUTS_VERSION}_3035_LEVL_3.geojson")
    nuts0 = gpd.read_file(raw / f"NUTS_RG_01M_{NUTS_VERSION}_3035_LEVL_0.geojson")
    nuts3_24 = gpd.read_file(raw / "NUTS_RG_01M_2024_3035_LEVL_3.geojson")
    units = json.loads(
        (raw / f"nuts-{NUTS_VERSION}-units.json").read_text(encoding="utf-8")
    )

    grid = pd.read_parquet(
        next(raw.glob("*grid*1km*.parquet")),
        columns=[
            "X_LLC",
            "Y_LLC",
            "CNTR_ID",
            f"TOT_P_{CENSUS_YEAR}",
            f"NUTS{NUTS_VERSION}_3",
        ],
    )
    ghs_path = next(raw.glob("GHS_POP_*.tif"))

    return {
        "nuts3": nuts3,
        "nuts0": nuts0,
        "nuts3_24": nuts3_24,
        "units": units,
        "grid": grid,
        "ghs_path": ghs_path,
    }


# --- transform: zone attributes --------------------------------------------


def _polygonal(geom):
    """Keep only polygonal parts; make_valid can return a GeometryCollection."""
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    parts = [
        g for g in shapely.get_parts(geom) if g.geom_type in ("Polygon", "MultiPolygon")
    ]
    return shapely.union_all(parts) if parts else geom


def repair_geometry(zones: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Repair invalid rings before anything depends on them.

    Self-intersections break ``within`` and ``overlay``, so this runs ahead of
    centroid assignment and the crosswalk rather than being caught by
    ``validate``. GISCO's 1:1M layer carries occasional slivers, and how many
    surface depends on the shapely version — an ETL that fails on one machine
    and passes on another is worse than one that repairs and reports.
    """
    invalid = ~zones.is_valid
    if not invalid.any():
        return zones

    before = zones.loc[invalid].area
    zones = zones.copy()
    zones.loc[invalid, "geometry"] = (
        zones.loc[invalid, "geometry"].make_valid().apply(_polygonal)
    )
    drift = ((zones.loc[invalid].area - before).abs() / before).max()

    print(
        f"repaired {invalid.sum()} invalid geometries: {sorted(zones.index[invalid])}"
    )
    print(f"  max area change {drift:.4%}")
    assert drift < 0.01, (
        "repair changed a zone's area by more than 1% — inspect before trusting"
    )
    return zones


def _country_group(row: pd.Series) -> str:
    """Membership label from the GISCO status flags; the UK carries none."""
    return next(
        (label for col, label in STATUS_FLAGS.items() if row[col] == "T"), "other"
    )


def build_zones(nuts3: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Zone identity, membership, tier and geometric attributes."""
    zones = nuts3.rename(
        columns={
            "NUTS_ID": "zone_id",
            "CNTR_CODE": "country",
            "NAME_LATN": "name_latin",
            "NUTS_NAME": "name_local",
            "URBN_TYPE": "urbn_type",
            "MOUNT_TYPE": "mount_type",
            "COAST_TYPE": "coast_type",
        }
    ).copy()

    zones["nuts_version"] = NUTS_VERSION
    zones["country_group"] = zones.apply(_country_group, axis=1)
    zones["tier"] = np.where(zones["country"].isin(TIER_1_COUNTRIES), 1, 2)
    zones["area_km2"] = zones.area / 1e6

    # representative_point is guaranteed inside the polygon; centroid is not.
    geom_pt = zones.representative_point()
    zones["geom_centroid_x"] = geom_pt.x
    zones["geom_centroid_y"] = geom_pt.y

    keep = [
        "zone_id",
        "nuts_version",
        "country",
        "country_group",
        "tier",
        "name_latin",
        "name_local",
        "area_km2",
        "urbn_type",
        "mount_type",
        "coast_type",
        "geom_centroid_x",
        "geom_centroid_y",
        "geometry",
    ]
    return zones[keep].set_index("zone_id").sort_index()


# --- transform: census-grid centroids ---------------------------------------


def census_covered_countries(grid: pd.DataFrame) -> set[str]:
    """Countries the census round actually counted, read from the grid itself.

    Derived rather than hardcoded so it stays correct across grid versions: a
    country is covered when its own single-country cells carry population.
    Border cells are excluded from the test, since their population may have
    been counted by either neighbour.
    """
    pop_col = f"TOT_P_{CENSUS_YEAR}"
    own = grid["CNTR_ID"].ne("") & ~grid["CNTR_ID"].str.contains(CODE_SEP, regex=False)
    totals = grid[own].groupby("CNTR_ID")[pop_col].sum()
    return set(totals.index[totals > 0])


def resolve_grid_cells(
    grid: pd.DataFrame, zones: gpd.GeoDataFrame, covered: set[str]
) -> pd.DataFrame:
    """One cell, one zone, and only where the census counted the people.

    Two problems, and only one of them is geometric. Codes are attributed to
    every cell intersecting or lying within roughly 1.5 km of a region, so
    border cells carry hyphen-joined codes; those are resolved by
    point-in-polygon on the cell centre. That settles *which zone* a cell
    belongs to, and is why the source decision downstream must come after this
    step.

    It does not settle *who counted the population*. A cell straddling the
    Irish border whose centre falls on the UK side is legitimately a UK cell,
    and still carries population only Ireland's census counted — geometry
    cannot distinguish the two. Cells resolving into countries outside the
    census round are therefore dropped, and those zones fall through to
    GHS-POP.
    """
    pop_col, nuts_col = f"TOT_P_{CENSUS_YEAR}", f"NUTS{NUTS_VERSION}_3"
    half = GRID_CELL_M / 2

    cells = grid.loc[grid[nuts_col].ne("") & grid[pop_col].gt(0)].copy()
    cells["x"] = cells["X_LLC"] + half
    cells["y"] = cells["Y_LLC"] + half
    cells["pop"] = cells[pop_col]

    single = cells[~cells[nuts_col].str.contains(CODE_SEP, regex=False)]
    single = single.assign(zone_id=single[nuts_col])

    multi = cells[cells[nuts_col].str.contains(CODE_SEP, regex=False)]
    if len(multi):
        pts = gpd.GeoDataFrame(
            multi[["x", "y", "pop"]],
            geometry=gpd.points_from_xy(multi["x"], multi["y"]),
            crs=WORK_CRS,
        )
        joined = gpd.sjoin(pts, zones[["geometry"]], how="inner", predicate="within")
        multi = joined.rename(columns={"index_right": "zone_id"}).drop(
            columns="geometry"
        )
    else:
        multi = pd.DataFrame(columns=["x", "y", "pop", "zone_id"])

    resolved = pd.concat(
        [single[["x", "y", "pop", "zone_id"]], multi], ignore_index=True
    )
    return resolved[resolved["zone_id"].str[:2].isin(covered)]


def _weighted_xy(df: pd.DataFrame, geom=None) -> pd.Series:
    """Population-weighted centroid of a set of cells, snapped inside ``geom``.

    Annular zones — a Landkreis ringing a city, Středočeský around Prague,
    Halle-Vilvoorde around Brussels — put the weighted mean in the hole, which
    is the neighbouring city. That point is not merely outside the zone: it
    sits next to a main station where none of the zone's population lives, so
    DM1b would compute a flattering access time for precisely the commuter-belt
    zones where access is the interesting question. Snapping to the nearest
    *populated* cell keeps the point both inside the zone and inhabited.
    """
    total = float(df["pop"].sum())
    x = float(np.average(df["x"], weights=df["pop"]))
    y = float(np.average(df["y"], weights=df["pop"]))

    snapped = False
    if geom is not None and not shapely.Point(x, y).within(geom):
        d2 = (df["x"].to_numpy() - x) ** 2 + (df["y"].to_numpy() - y) ** 2
        nearest = df.iloc[int(np.argmin(d2))]
        x, y, snapped = float(nearest["x"]), float(nearest["y"]), True

    return pd.Series({"x": x, "y": y, "population": total, "snapped": snapped})


def census_centroids(cells: pd.DataFrame, zones: gpd.GeoDataFrame) -> pd.DataFrame:
    """Population-weighted centroid per zone, restricted to its most populous part.

    Archipelago zones — the Azores, the Greek and Danish islands, later the
    Scottish ones — otherwise get a centroid in open water between the islands,
    which has no road or rail access and would silently poison the DM1b access
    matrix.
    """
    multipart = set(zones.index[zones.geom_type == "MultiPolygon"])
    geoms = zones["geometry"]

    simple = cells[~cells["zone_id"].isin(multipart)]
    out = simple.groupby("zone_id").apply(
        lambda d: _weighted_xy(d, geoms.loc[d.name]), include_groups=False
    )

    rows = {}
    for zone_id in sorted(multipart & set(cells["zone_id"])):
        sub = cells[cells["zone_id"] == zone_id]
        parts = gpd.GeoSeries(list(zones.loc[zone_id, "geometry"].geoms), crs=WORK_CRS)
        pts = gpd.GeoDataFrame(
            sub[["x", "y", "pop"]],
            geometry=gpd.points_from_xy(sub["x"], sub["y"]),
            crs=WORK_CRS,
        )
        tagged = gpd.sjoin(
            pts, gpd.GeoDataFrame(geometry=parts), how="inner", predicate="within"
        )
        if tagged.empty:
            continue
        best = tagged.groupby("index_right")["pop"].sum().idxmax()
        rows[zone_id] = _weighted_xy(
            tagged[tagged["index_right"] == best], parts.iloc[best]
        )

    if rows:
        out = pd.concat([out, pd.DataFrame(rows).T])
    return out.sort_index()


# --- transform: GHS-POP fallback --------------------------------------------


def ghs_centroid(
    ghs, geom, buffer_m: float = 2_000.0
) -> tuple[float, float, float, bool] | None:
    """Population-weighted centroid of one geometry, in the raster's CRS.

    The transform is affine, so the weighted mean of cell coordinates equals
    the transform applied to the weighted mean of cell indices. Reducing to
    marginal sums first avoids materialising coordinates for every cell, which
    matters: a large zone's window on a 100 m global raster is tens of millions
    of cells.
    """
    minx, miny, maxx, maxy = geom.bounds
    win = from_bounds(
        minx - buffer_m,
        miny - buffer_m,
        maxx + buffer_m,
        maxy + buffer_m,
        ghs.transform,
    )
    arr = ghs.read(1, window=win, boundless=True, fill_value=0)
    if arr.size == 0:
        return None

    wt = window_transform(win, ghs.transform)
    inside = geometry_mask([geom], arr.shape, wt, invert=True)
    pop = np.where(inside & (arr > 0), arr, 0).astype("float64")

    total = pop.sum()
    if total <= 0:
        return None

    mean_row = float(pop.sum(axis=1) @ np.arange(arr.shape[0])) / total
    mean_col = float(pop.sum(axis=0) @ np.arange(arr.shape[1])) / total
    x, y = wt * (mean_col + 0.5, mean_row + 0.5)  # +0.5: cell centre, not corner

    # Same annular case as the census path: snap to the nearest populated cell
    # when the weighted mean falls outside the geometry.
    snapped = not shapely.Point(x, y).within(geom)
    if snapped:
        dr = (np.arange(arr.shape[0]) - mean_row)[:, None]
        dc = (np.arange(arr.shape[1]) - mean_col)[None, :]
        d2 = np.where(pop > 0, dr * dr + dc * dc, np.inf)
        row, col = np.unravel_index(int(np.argmin(d2)), d2.shape)
        x, y = wt * (col + 0.5, row + 0.5)

    return float(x), float(y), float(total), snapped


def ghs_centroids(
    ghs_path: Path, zones: gpd.GeoDataFrame, missing: list[str]
) -> pd.DataFrame:
    """Fallback centroids for zones the census grid does not reach."""
    rows = {}
    with rasterio.open(ghs_path) as ghs:
        moll = zones.loc[missing].to_crs(ghs.crs)
        for zone_id, geom in moll.geometry.items():
            parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
            best = max(
                (r for r in (ghs_centroid(ghs, p) for p in parts) if r),
                key=lambda r: r[2],
                default=None,
            )
            if best is None:
                continue
            rows[zone_id] = {
                "x": best[0],
                "y": best[1],
                "population": best[2],
                "snapped": best[3],
            }
        crs = ghs.crs

    if not rows:
        return pd.DataFrame(columns=["x", "y", "population", "snapped"])

    df = pd.DataFrame(rows).T
    pts = gpd.GeoSeries(
        gpd.points_from_xy(df["x"], df["y"]), index=df.index, crs=crs
    ).to_crs(WORK_CRS)
    return df.assign(x=pts.x, y=pts.y).sort_index()


# --- transform: crosswalk ---------------------------------------------------


def build_crosswalk(
    zones: gpd.GeoDataFrame, nuts3_24: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Map each 2021 zone onto its 2024 successors by geometric overlap.

    Code sets alone cannot tell a rename from a split from a coincidental
    reuse, so identity is established by area: a 2024 zone succeeds a 2021 zone
    where it covers a majority of it.
    """
    ids_24 = set(nuts3_24["NUTS_ID"])
    stable = zones.index.intersection(ids_24)

    changed = zones.index.difference(ids_24)
    rel = pd.Series("identical", index=zones.index, name="crosswalk_relation")
    succ = pd.Series(pd.NA, index=zones.index, dtype="object", name="nuts_2024")
    succ.loc[stable] = stable

    if len(changed):
        left = zones.loc[changed, ["geometry"]].reset_index()
        right = nuts3_24[["NUTS_ID", "geometry"]].rename(columns={"NUTS_ID": "id_24"})
        pairs = gpd.overlay(left, right, how="intersection", keep_geom_type=True)
        pairs["share"] = pairs.area / pairs["zone_id"].map(zones.area)
        pairs = pairs[pairs["share"] > 0.05]

        grouped = pairs.groupby("zone_id")["id_24"].apply(lambda s: sorted(set(s)))
        succ.loc[grouped.index] = grouped.apply(lambda v: ",".join(v))
        rel.loc[changed] = "discontinued"
        rel.loc[grouped.index] = grouped.apply(
            lambda v: "renamed" if len(v) == 1 else "split"
        )

    return pd.concat([succ, rel], axis=1)


# --- validate ---------------------------------------------------------------


def validate(frame: gpd.GeoDataFrame, units: dict, nuts0: gpd.GeoDataFrame) -> None:
    """Fail loudly rather than shipping a plausible-looking frame."""
    expected = {code for code in units if len(code) == 5}
    assert set(frame.index) == expected, (
        f"zone set differs from the units manifest: {sorted(set(frame.index) ^ expected)[:10]}"
    )
    assert frame.index.is_unique, "duplicate zone_id"

    invalid = frame.index[~frame.geometry.is_valid]
    assert invalid.empty, f"invalid geometry after repair: {sorted(invalid)[:10]}"

    empty = frame.index[frame.geometry.is_empty]
    assert empty.empty, f"empty geometry: {sorted(empty)[:10]}"

    # Row-wise: every zone either has a 2024 successor or is marked
    # discontinued. The 179 UK zones are legitimately the latter.
    orphan = frame.index[
        frame["nuts_2024"].isna() & frame["crosswalk_relation"].ne("discontinued")
    ]
    assert orphan.empty, (
        f"no 2024 successor and not discontinued: {sorted(orphan)[:10]}"
    )

    pts = gpd.GeoSeries(
        gpd.points_from_xy(frame["centroid_x"], frame["centroid_y"]),
        index=frame.index,
        crs=WORK_CRS,
    )
    # Guaranteed by construction after snapping, so a failure here means the
    # snap did not run, not that a zone is awkwardly shaped.
    outside = frame.index[~pts.within(frame.geometry)]
    assert outside.empty, f"centroid outside its own zone: {sorted(outside)[:10]}"

    gap = nuts0.union_all().difference(frame.geometry.union_all()).area / 1e6
    assert gap < 100, f"level-3 union leaves {gap:.1f} km2 uncovered against level 0"

    assert frame["centroid_source"].isin({"census_grid", "ghs_pop", "geometric"}).all()


# --- load -------------------------------------------------------------------


def load(frame: gpd.GeoDataFrame, out: Path) -> Path:
    path = out / OUT_NAME
    frame.reset_index().to_parquet(path, index=False)
    return path


# --- orchestration ----------------------------------------------------------


def run() -> Path:
    raw, out = _paths()
    src = extract(raw)

    zones = repair_geometry(build_zones(src["nuts3"]))

    covered = census_covered_countries(src["grid"])
    print(f"census-covered countries ({len(covered)}): {sorted(covered)}")
    cells = resolve_grid_cells(src["grid"], zones, covered)
    census = census_centroids(cells, zones)

    missing = sorted(set(zones.index) - set(census.index[census["population"] > 0]))
    ghs = ghs_centroids(src["ghs_path"], zones, missing)

    frame = zones.join(census.add_prefix("census_")).join(ghs.add_prefix("ghs_"))
    frame["centroid_source"] = np.select(
        [frame["census_population"].gt(0), frame["ghs_population"].gt(0)],
        ["census_grid", "ghs_pop"],
        default="geometric",
    )
    # Both paths snap; recording only one would silently under-report.
    frame["centroid_snapped"] = (
        frame["census_snapped"].fillna(frame["ghs_snapped"]).fillna(False).astype(bool)
    )
    frame["centroid_x"] = (
        frame["census_x"].fillna(frame["ghs_x"]).fillna(frame["geom_centroid_x"])
    )
    frame["centroid_y"] = (
        frame["census_y"].fillna(frame["ghs_y"]).fillna(frame["geom_centroid_y"])
    )
    frame["population"] = frame["census_population"].fillna(frame["ghs_population"])

    frame = frame.join(build_crosswalk(zones, src["nuts3_24"]))
    validate(frame, src["units"], src["nuts0"])

    # Publish in lon/lat; 3035 is a working projection, not an interchange one.
    ll = gpd.GeoSeries(
        gpd.points_from_xy(frame["centroid_x"], frame["centroid_y"]),
        index=frame.index,
        crs=WORK_CRS,
    ).to_crs(OUT_CRS)
    frame["centroid_lon"], frame["centroid_lat"] = ll.x, ll.y
    frame = frame.drop(
        columns=[
            c
            for c in frame.columns
            if c.startswith(("census_", "ghs_", "geom_centroid_"))
        ]
        + ["centroid_x", "centroid_y"]
    ).to_crs(OUT_CRS)

    path = load(frame, out)
    _report(frame, path)
    return path


def _report(frame: gpd.GeoDataFrame, path: Path) -> None:
    print(f"wrote {path}  ({len(frame)} zones)")
    print(f"\ncentroid source:\n{frame['centroid_source'].value_counts().to_string()}")
    snapped = frame.index[frame["centroid_snapped"]]
    print(f"\ncentroids snapped into annular zones: {len(snapped)}")
    if len(snapped):
        print(
            f"  by country: {pd.Series(sorted(snapped)).str[:2].value_counts().to_dict()}"
        )
    print(f"\ntier:\n{frame['tier'].value_counts().sort_index().to_string()}")
    print(f"\ncrosswalk:\n{frame['crosswalk_relation'].value_counts().to_string()}")
    fallback = frame[frame["centroid_source"] != "census_grid"]
    if len(fallback):
        print(
            f"\nfallback by country:\n{fallback.groupby(['country', 'centroid_source']).size().to_string()}"
        )


if __name__ == "__main__":
    run()
