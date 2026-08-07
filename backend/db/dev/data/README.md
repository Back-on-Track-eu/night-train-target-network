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
