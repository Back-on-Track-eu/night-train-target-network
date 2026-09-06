# Station charges — see `../HANDOVER.md`

**Owner:** Josua · superseded 2026-09-01

The task list for the station charges lives in `stops/HANDOVER.md` §3,
together with the stop work it depends on: the country table there is
recomputed from the current catalog, Germany is re-opened (its rows never
reached the catalog, and the September stop closure adds 23 DE stations),
and UA/TR/MD/MK are seeded now — the "not needed" list that stood here was
wrong.

The contract for the country files is unchanged: `sources/TEMPLATE.md`
(twelve columns), `sources/de_station_charges.csv` as the worked example,
`01_source_extraction.ipynb` for the register, `02_station_charges.ipynb`
for the reader, `../step10_export_seed_stops.py` to join it onto the
catalog.
