# Demand model — calibration

Data acquisition and preparation for the demand model. The concept, the
implementation log and the source register live one level up in
[`../docu/`](../docu/).

## Structure

```
calib/
├── raw/          # third-party downloads, by batch — gitignored
│   └── 01_zones/
├── exploration/  # notebooks: understand the data before writing the pipeline
├── etl/          # .py pipelines: extract, transform, load — the settled code
└── out/          # generated artifacts — gitignored
```

The split between `exploration/` and `etl/` is the point of this layout.
Notebooks are where a source is interrogated, assumptions are tested and
surprises are found; they print and assert, and they never write to `out/`.
Only what survives that scrutiny moves into `etl/` as a pipeline. The
notebooks then stay as the record of *why* the pipeline looks the way it does
— several of the findings in `../docu/IMPLEMENTATION_DOCU.md` exist because a
first attempt was wrong in a way that produced plausible output.

`raw/` and `out/` are both gitignored. `raw/` holds files we downloaded but do
not author, several of them large; `out/` holds files the ETL regenerates.
Everything in `raw/` is reproducible from `../docu/SOURCES.md`, which records
the URL, retrieval date, hash and licence of each file.

## Acquisition batches

Ordered by dependency in `../docu/DEMAND_MODEL_CONCEPT.md` §3. Each batch is
buildable once those above it exist, and each gets a `raw/` subdirectory.

| Batch | Contents | State |
|---|---|---|
| 01_zones | NUTS geometries, units manifests, release notes, census population grid, GHS-POP | **complete** |
| 02_attributes | Eurostat regional statistics | not started |
| 03_nodes | airports, network extracts | not started |
| 04–08 | OD flows, growth, level of service, choice parameters, back-cast targets | not started |

## Running the notebooks

From `backend/`:

```powershell
uv run --extra dev --with jupyterlab jupyter lab --notebook-dir models/demand/calib
```

The notebooks anchor on `calib/` by walking up from the working directory, so
they run from `exploration/`, from `calib/`, or from the repository root
without edits.

Extra dependencies beyond the usual `dev` extra: `pyarrow` (Parquet) and
`rasterio` (the GHS-POP raster).

## Batch 01 — zones

`exploration/01_zone_exploration.ipynb` covers the NUTS 2021 layer, the units
manifests, the 2021↔2024 differences, the census grid and GHS-POP. It writes
nothing; findings are recorded in `../docu/`.

`etl/step1_zones.py` then produces the batch's single artifact,
`out/01_zones.parquet`: 1 514 zones with identity, membership, tier,
geometry, population-weighted centroid, centroid source and the NUTS
2021↔2024 crosswalk, in EPSG:4326.

From `backend/`:

```powershell
uv run python models/demand/calib/etl/step1_zones.py
```

Four results worth knowing before reading either:

- The census grid covers **30 countries** — EU-27 plus CH, NO and LI. 315 of
  1 514 zones fall back to GHS-POP, which is global; none fall back to
  geometric. Displacement between the two methods, measured where both exist,
  has a median of 0.4 km.
- Border cells in the census grid carry **hyphen-joined** NUTS codes, and
  unassigned cells carry an **empty string** rather than a null. Both silently
  produce plausible-looking wrong output if missed.
- Zones in uncovered countries can appear to have census population, borrowed
  across a border. Resolving cells to single zones fixes only part of it: a
  cell straddling the Irish border whose centre falls on the UK side is a UK
  cell that still holds population only Ireland counted. Census coverage is
  therefore gated at country level, derived from the grid rather than
  hardcoded.
- Multipart zones take the centroid of their **most populous part**. A
  weighted centroid across an archipelago lands in open water, which would
  poison the DM1b access matrix rather than merely being imprecise.
- Zones that ring a city — Středočeský, Halle-Vilvoorde, Linz-Land, the
  Landkreise around Stuttgart — put the weighted mean in the hole, i.e. in the
  neighbouring city beside its main station. Those centroids are **snapped to
  the nearest populated cell** inside the zone.
