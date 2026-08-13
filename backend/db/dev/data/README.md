# Seed data inputs (local cache — gitignored)

`ontd_seed_stops.csv` — every stop the existing-network (ONTD) snapshot
needs beyond `seed.py`'s curated catalog. Drive-hosted, not committed;
`seed.py` downloads it here when absent (file id
`ONTD_SEED_STOPS_FILE_ID`, defaulted in `seed.py`, env-overridable).
Regenerate with `backend/scripts/export_ontd_stop_seed.py` after an ONTD
refresh that adds stations, then upload to Drive as a new version of the
existing file (keeps the file id) and reseed. Column semantics and the
full rationale: `../../README.md` ("ONTD stop seed CSV") and
`../../ontd/README.md` ("Stop mapping & corridors").

`country_geoms.geojson.gz` — one border polygon per seeded country with a
rail network, covering land **and** maritime zones (Marine Regions "Union
of the ESRI Country shapefile and the Exclusive Economic Zones" v4,
Flanders Marine Institute 2024, https://doi.org/10.14284/698, CC-BY 4.0).
Built, not downloaded: `backend/scripts/export_country_geoms.py` runs
before `seed.py` in both container entrypoints, fetches the Drive-hosted
source zip (`EEZ_LAND_UNION_FILE_ID`) when this file is absent, converts
it, and does nothing when it is already here. Force a rebuild with
`--force`. Why maritime zones are the whole point: `../../README.md`
("Country geometry artifact").
