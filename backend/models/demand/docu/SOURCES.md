# Demand model — source register

Provenance and licence record for every external file used by the demand
calibration notebooks. One entry per downloaded artifact, written **at
download time**, not reconstructed afterwards.

Home: `backend/models/demand/docu/SOURCES.md`.

Scope of this revision: **batch 1 (zone frame, DM1a)** only, including the
Tier 2 fallback source added 2026-08-20. Batches 2–8 are
appended as they are acquired; the section skeleton at the bottom is there
so the file grows by filling in, not by restructuring.

Downloads land in `calib/raw/01_zones/`. Everything marked `TODO` needs a value that cannot be looked up remotely —
retrieval date, file size, hash, and which optional files were actually
taken. Everything else is pre-filled and should only be corrected if a
download deviated from the recipe.

Hashes, from the directory the files were downloaded into:

```powershell
Get-ChildItem -File | Get-FileHash -Algorithm SHA256 |
  Select-Object @{n='File';e={Split-Path $_.Path -Leaf}}, Hash |
  Format-Table -AutoSize
```

---

## Summary

| ID | Artifact | Publisher | Licence | Redistributable via Drive |
|---|---|---|---|---|
| B1-01 | NUTS 2021 regions, level 3 | Eurostat GISCO | free reuse, attribution + © EuroGeographics | yes, with attribution |
| B1-02 | NUTS 2021 regions, level 0 | Eurostat GISCO | as B1-01 | yes, with attribution |
| B1-03 | NUTS 2024 regions, level 3 | Eurostat GISCO | as B1-01 | yes, with attribution |
| B1-04 | NUTS 2021 units / code list | Eurostat GISCO | free reuse, attribution | yes |
| B1-05 | NUTS 2024 units / code list | Eurostat GISCO | free reuse, attribution | yes |
| B1-06 | NUTS release notes 2021 + 2024 | Eurostat GISCO | free reuse, attribution | yes |
| B1-07 | GISCO 1 km grid incl. population | Eurostat GISCO / EFGS / JRC | **special rules on population attributes** | TODO — settle before upload |
| B1-08 | Non-EU regional units | — | — | **not required**, resolved by coverage check |
| B1-09 | Country land geometries | Marine Regions | already in repo | already handled |
| B1-10 | GHS-POP R2023A global population grid | EC JRC (GHSL) | free reuse, acknowledgement | yes, with acknowledgement |

---

## B1-01 — NUTS 2021 regions, level 3

- **Publisher**: Eurostat GISCO (Geographic Information System of the Commission)
- **Dataset**: NUTS 2021, regions (`RG`), 1:1 million, EPSG:3035, level 3
- **URL**: `https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_3035_LEVL_3.geojson`
- **Index page**: `https://gisco-services.ec.europa.eu/distribution/v2/nuts/`
- **File**: `NUTS_RG_01M_2021_3035_LEVL_3.geojson`
- **Vintage**: NUTS 2021 (the pinned `nuts_version`, see concept §2.1)
- **Format / CRS**: GeoJSON, ETRS89-LAEA (EPSG:3035)
- **Retrieved**: 2026-08-20 (confirm if downloaded earlier)
- **Size**: 26 471 025 bytes
- **SHA-256**: `64cb81a6ecd3780aa506bfdb50069a1d3534e98d088b0123dfa95de730884290`
- **Licence**: Eurostat reuse policy — free reuse with attribution. Administrative
  boundaries carry an additional EuroGeographics condition.
- **Required attribution**: see the attribution block at the end of this file.
- **Naming convention**: `theme_spatialtype_resolution_year_projection_subset.format`;
  `RG` = regions (polygons), `BN` = boundaries (lines), `LB` = label points.
- **Notes**: 1:1M chosen deliberately over 1:3M / 1:20M — generalised boundaries
  misassign points near borders, and stops and airports are placed by
  point-in-polygon against this layer. Verified 2026-08-20: 1 514 features,
  all `LEVL_CODE == 3`, CRS EPSG:3035 as declared, no invalid or empty
  geometries.
  - Carries per-zone `MOUNT_TYPE`, `URBN_TYPE` and `COAST_TYPE`, propagated
    into the zone frame rather than re-derived downstream.
  - Carries `EU_STAT` / `EFTA_STAT` / `CC_STAT` per feature, so country
    membership is read from the data instead of a hand-maintained list that
    would drift as candidate status changes.
  - ⚠️ Name columns: `NAME_LATN` and `NUTS_NAME` are the **region** names (the
    latter in local script; they differ for 115 zones, Greek and Bulgarian).
    `NAME_ENGL`, `NAME_FREN` and `NAME_GERM` are **country** names joined onto
    each region — `HR064` carries `NAME_ENGL = "Croatia"`. Easy trap when
    picking a label column.
  - GeoJSON taken; Parquet has been published for these datasets since
    2026-05-11 (B1-06) and is preferable for anything larger.
- **Consumed by**: `calib/etl/step1_zones.py`

## B1-02 — NUTS 2021 regions, level 0

- **URL**: `https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_3035_LEVL_0.geojson`
- **File**: `NUTS_RG_01M_2021_3035_LEVL_0.geojson`
- **Retrieved**: 2026-08-20 (confirm if downloaded earlier)
- **Size**: 10 444 460 bytes
- **SHA-256**: `6de9874dc12cdb94a20e6f842238acf7d49c61c81056f7a83be7459a3935028a`
- **Licence / attribution**: as B1-01
- **Notes**: country layer, used only for the gap-check assertion (union of
  level-3 zones against level-0 within tolerance).
- **Consumed by**: `calib/etl/step1_zones.py`

## B1-03 — NUTS 2024 regions, level 3

- **URL**: `https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2024_3035_LEVL_3.geojson`
- **File**: `NUTS_RG_01M_2024_3035_LEVL_3.geojson`
- **Retrieved**: 2026-08-20 (confirm if downloaded earlier)
- **Size**: 25 252 837 bytes
- **SHA-256**: `b1ed128fdd2c5b369c2dff9bdc5ea2d1ca5ccae1f925dd981dd5584b779b6eda`
- **Licence / attribution**: as B1-01
- **Notes**: not the pinned vintage. Held solely to build and validate
  the crosswalk columns of `calib/out/01_zones.parquet`, so the `nuts_version`
  pin can be moved later without re-deriving the zone frame.
  - Diff computed 2026-08-20: 1 514 zones in 2021, 1 345 in 2024, 1 283
    stable. The raw diff (231 discontinued, 62 new) is dominated by one
    structural fact — **the UK is absent from NUTS 2024** — and Kosovo (XK,
    7 zones) appears only in 2024.
  - Genuine restructuring, i.e. countries present in both vintages, is only
    six countries and roughly 50 codes: DE 7→6, FI 9→9, LV 4→3, NL 15→15,
    NO 3→7, PT 14→15.
  - The UK finding is a second, independent argument for the NUTS 2021 pin
    (concept §2.1): pinning 2024 would leave no UK geometry at all, so Tier 2
    could never be activated without a separate ONS acquisition.
- **Consumed by**: `calib/etl/step1_zones.py` (crosswalk cell)

## B1-04 / B1-05 — NUTS units manifest

- **Index page**: `https://gisco-services.ec.europa.eu/distribution/v2/nuts/`
  (`datasets.json` lists, per vintage, the `files`, `units`, `packages` and
  `documentation` entries)
- **Files**: `nuts-2021-units.json` (1 703 338 bytes), `nuts-2024-units.json`
  (1 670 146 bytes)
- **Retrieved**: 2026-08-20 (confirm if downloaded earlier)
- **SHA-256**:
  - `ddfa5c4a6641696e014615a9f822b25e5fded419ba895e0402f16fcd97ee5a9a` (2021)
  - `4a0c651669d9226fcc01bf9bbd8c29848639ebafcb7fc261ca2963c3203da5b1` (2024)
- **Licence**: Eurostat reuse policy — free reuse with attribution
- **Notes**: **not** a code list with attributes, despite the name. It maps
  each NUTS code to the 18 per-unit geometry files GISCO publishes for it
  (5 resolutions × 3 projections, plus label points). Region names are not in
  this file; they come from `NAME_LATN` / `NUTS_NAME` on B1-01.
  - Useful here for one thing: the key set is an independently distributed
    authority for the expected unit count per level and per country. Level and
    parent are recoverable from code width (2 = country, 3 = NUTS-1,
    4 = NUTS-2, 5 = NUTS-3).
  - Cross-check result 2026-08-20: 2 010 entries — 37 at level 0, 125 at
    level 1, 334 at level 2, 1 514 at level 3. The level-3 key set is
    identical to B1-01 with no orphans in either direction, and per-country
    counts match exactly.
- **Consumed by**: `calib/exploration/01_zone_exploration.ipynb`, `calib/etl/step1_zones.py`

## B1-06 — NUTS release notes, 2021 and 2024

- **Files**: `nuts-2021-release-notes.txt` (1 131 bytes),
  `nuts-2024-release-notes.txt` (592 bytes)
- **Retrieved**: 2026-08-20 (confirm if downloaded earlier)
- **SHA-256**:
  - `493941e1be8642f397bc296f04a89efbf4c16e3a441f7b87b5606e12f7bf8885` (2021)
  - `607832e17637451586dbb817857ed09f4f20ab3ca2e756f45b5f7e40320018d4` (2024)
- **Licence**: as B1-04
- **Notes**: needed to classify each crosswalk row as identical / renamed /
  split / merged / new / discontinued — code lists alone cannot distinguish a
  rename from a coincidental code reuse. Read with `utf-8-sig`; both files
  carry BOM characters mid-file.
  - Entries bearing on this batch: Jan Mayen and Svalbard were folded into
    Norway's statistical regions (2020-11-18), so `NO0B2 Svalbard` is a
    NUTS-3 zone of 63 084 km² with a population around 2 500 and no rail —
    expect it as a grid-coverage edge case and a legitimate Tier 2 exclusion,
    not a bug. `MOUNT_TYPE` / `URBN_TYPE` / `COAST_TYPE` were corrected for a
    number of NUTS 2021 records (2022-09-01) and tiny inter-zone gaps were
    reprocessed out (2024-07-22), both of which matter for the gap-check
    assertion. Parquet was added for these datasets on 2026-05-11.
  - NUTS 2024 only: Ukraine is available at level 0 only; Bosnia and
    Herzegovina was added at level 2 (2025-03-11). Neither reaches NUTS-3, so
    BA / UA remain gaps for any future Balkan or Ukrainian scope.
- **Consumed by**: `calib/etl/step1_zones.py` (crosswalk cell), manually read

## B1-07 — GISCO 1 km grid including population

- **Publisher**: Eurostat GISCO; population figures from the GEOSTAT project
  (EFGS) and, for modelled years, JRC / DG REGIO
- **Landing page**: `https://ec.europa.eu/eurostat/web/gisco/geodata/grids`
- **Metadata**: `https://gisco-services.ec.europa.eu/grid/GISCO_grid_metadata.pdf`
- **Version**: 1.4 (03/07/2025) — adds NUTS 2024 codes and updates the 2021
  population
- **Resolution / format**: 1 km, Parquet (`grid_1km.parquet`). The source
  archive `Eurostat_Census-GRID_2021_V3.zip` is also held in `calib/raw/01_zones/`.
- **Retrieved / Size / SHA-256**: TODO
  - ⚠️ If the file was converted locally from CSV, the hash must be of the file
    **as GISCO served it**, with the conversion recorded as a processing step.
    A hash of a locally written Parquet verifies nothing about the source.
- **Licence**: mixed, and this is the one entry where that matters.
  **Specific download rules apply to the population attributes**
  (`TOT_P_2006`, `TOT_P_2011`, `TOT_P_2018`, `TOT_P_2021`), varying by year
  and country; the remaining attributes fall under the general Eurostat
  copyright and licence provisions.
  - **Redistribution decision**: TODO — settle before anything derived from
    `TOT_P_2021` reaches Drive.
- **Attributes used**: `GRD_ID`, `X_LLC`, `Y_LLC`, `TOT_P_2021`,
  `NUTS2021_3`, `CNTR_ID`, `LAND_PC`. Also carries NUTS 2016 and 2024 codes at
  all four levels, `TOT_P_2006/2011/2018`, `DIST_COAST` and `DIST_BORD`.
  2006 and 2018 are model-based and are not used.
- **Verified 2026-08-20**: 7 055 226 cells; 455 671 735 total 2021 population.
  - ⚠️ `X_LLC` and `Y_LLC` are the **lower-left corner** of the cell in
    EPSG:3035, not its centre. Weighting on them raw puts every centroid 500 m
    southwest of where it belongs; add 500 to each.
  - ⚠️ Unassigned cells carry an **empty string**, not `NaN` — `isna()` finds
    nothing against 1 092 389 (15.5 %) unassigned cells.
  - ⚠️ Border cells carry **hyphen-joined codes** (`AL011-AL012`, and
    `CNTR_ID` likewise as `BA-HR-RS`), because codes are attributed to every
    cell intersecting or lying within roughly 1.5 km of a region. Splitting on
    `-` is unambiguous, since NUTS codes contain none. Distribution: 5 689 308
    cells with one code, 269 768 with two, 3 745 with three, 16 with four.
    **17 491 568 people — 3.84 % of the total — sit in multi-code cells**, so
    the resolution rule is material and carries its own assertion in
    `calib/etl/step1_zones.py`.
  - **Population coverage is 30 countries: EU-27 + CH, NO and LI.** AL, IS,
    ME, MK, RS, TR and UK carry cells with zero population throughout; the
    2021 census round did not cover them. 1 199 of 1 514 zones are weightable
    from the census grid, and every Tier 1 zone is among them. See `IMPLEMENTATION_DOCU.md` F14–F16 for
    the full breakdown and the treatment of the four uncovered buckets.
  - ⚠️ 27 zones in uncovered countries nevertheless show non-zero census
    population, drawn entirely from border cells shared with a covered
    neighbour. The source decision must therefore be taken **after**
    point-in-polygon resolution, not from the raw attribution — see
    `IMPLEMENTATION_DOCU.md` F21.
- **Consumed by**: `calib/exploration/01_zone_exploration.ipynb`, `calib/etl/step1_zones.py`

## B1-08 — Non-EU regional units *(not required)*

Resolved 2026-08-20 by the country-coverage check on B1-01: the GISCO NUTS
2021 distribution carries 37 level-0 units, so no ONS, BFS or SSB download is
needed and the zone frame is built entirely from B1-01. Membership per the
`EU_STAT` / `EFTA_STAT` / `CC_STAT` flags:

| Group | Countries | NUTS-3 zones |
|---|---|---|
| EU | AT BE BG CY CZ DE DK EE EL ES FI FR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK | 1 166 |
| EFTA | CH IS LI NO | 42 |
| Candidate | AL (12) ME (1) MK (8) RS (25) TR (81) | 127 |
| Other (no flag) | UK | 179 |

- UK geometries are retained by GISCO for continuity although the UK left the
  NUTS regulation; they are absent from NUTS 2024 (B1-03).
- ⚠️ **Geometry coverage does not imply attribute coverage.** Eurostat regional
  statistics (batch 2) will not carry the UK, and candidate-country series are
  patchy and lagged; IS and LI are thin at NUTS-3. Expect the zone frame to
  hold 1 514 zones while batch 2 populates roughly 1 350–1 400 of them. That
  is the expected shape of the coverage report, not a defect.
- Not covered at NUTS-3 in either vintage: BA (level 2 only), UA (level 0
  only), XK (2024 only), MD, GE. "Balkan coverage" therefore means AL, ME, MK
  and RS — 46 zones. Routes touching BA, XK or UA would need national sources
  and a zone-frame extension.

## B1-09 — Country land geometries

- **Dataset**: Marine Regions, EEZ land union, v4
- **Status**: already in the repository, Drive-hosted
- **Drive file id**: `1bEqIfs8F4q7B36lsc2OZfJVx19dDEvOT`
- **Notes**: not re-fetched for the demand model. Listed here so the zone
  frame's dependency on it is visible in one place.

## B1-10 — GHS-POP R2023A global population grid

- **Publisher**: European Commission, Joint Research Centre (GHSL)
- **Dataset**: GHS-POP R2023A, GHS population grid multitemporal (1975–2030)
- **DOI / PID**: `10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE` ·
  `http://data.europa.eu/89h/2ff68a52-5b5b-4a22-8f40-c41da8332cfe`
- **Landing page**: `https://human-settlement.emergency.copernicus.eu/`
- **Epoch / resolution / CRS**: held as
  `GHS_POP_E2030_GLOBE_R2023A_54009_100_V1_0.tif` — epoch 2030, 100 m,
  World Mollweide (ESRI:54009), 64.9 billion cells.
  - **TODO — replace with epoch 2020 at 1 km before batch 2.** Adequate for
    centroids, since a uniform growth factor does not move a weighted mean of
    positions; not adequate once batch 2 uses it as the *only* population
    value for UK and Turkish zones, where a 2030 projection as a base-year
    figure is an error. See `IMPLEMENTATION_DOCU.md` F17.
- **Retrieved / Size / SHA-256**: TODO
- **Licence**: EC JRC open and free data; reuse authorised provided the source
  is acknowledged.
- **Required citation**: Schiavina M., Freire S., Carioli A., MacManus K.
  (2023): *GHS-POP R2023A — GHS population grid multitemporal (1975–2030)*.
  European Commission, Joint Research Centre.
- **Why this source**: the GEOSTAT census grid (B1-07) covers 30 countries
  only, leaving 315 zones unweighted. GHS-POP is global, so one file closes
  every gap — UK (202 zones), the candidate countries, IS, LI, and the French
  DOM, which no EPSG:3035 product reaches at all. The UK-only alternative
  would be ONS, NRS and NISRA on three different output-area geographies,
  before touching the Balkans.
- **Method note**: population is disaggregated from census and administrative
  units onto the grid using built-up distribution, density and classification
  from the GHSL built-up layers. It is **modelled, not counted**, so it is a
  fallback and never a replacement: GEOSTAT wins wherever it exists, the two
  are never mixed within a zone, and `centroid_source` records which was used.
  The displacement between the two methods was measured across 246 zones where
  both exist: median 0.4 km, 90th percentile 1.3 km, maximum 12.0 km — noise
  against a 90-minute access cap. All 315 uncovered zones resolved; none fell
  back to a geometric centroid.
- **Consumed by**: `calib/exploration/01_zone_exploration.ipynb`,
  `calib/etl/step1_zones.py`

---

## Batch 1 output

All of the above is consumed by `calib/etl/step1_zones.py`, which writes one
artifact: `calib/out/01_zones.parquet` — 1 514 zones with identity,
membership, tier, geometry, population-weighted centroid, centroid source and
the NUTS 2021↔2024 crosswalk, in EPSG:4326.

---

## Attribution block

The following must appear in `models/demand/README.md` and in anything
published from the zone frame (gallery, proposal documents, the DG MOVE
submission).

> Contains Eurostat data. Administrative boundaries: © EuroGeographics.
> Population grid: Eurostat GISCO, based on the GEOSTAT project (EFGS).
> Fallback population weighting: GHS-POP R2023A, European Commission,
> Joint Research Centre.

No ONS/OS wording is needed: the coverage check on B1-01 removed the UK
national download (B1-08).

---

## Batches 2–8 — to be filled as acquired

- **Batch 2 — zone attributes**: Eurostat `demo_r_pjangrp3`, `nama_10r_3gdp`,
  `nama_10r_3popgdp`, `nama_10r_3empers`, `tour_occ_nin3`, `nama_10r_2hhinc`
- **Batch 3 — nodes and networks**: OurAirports, OpenFlights, Eurostat airport
  code list, Geofabrik OSM extract *(⚠️ ODbL share-alike propagates to every
  derived matrix — record the implication, not just the licence name)*
- **Batch 4 — background OD flows**
- **Batch 5 — growth factors**
- **Batch 6 — level of service**
- **Batch 7 — choice parameters**
- **Batch 8 — back-cast targets**
