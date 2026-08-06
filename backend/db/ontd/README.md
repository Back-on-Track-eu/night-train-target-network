# ONTD (Open Night Train Database) integration

Import and projection pipeline for the ONTD workbook (PROPOSALS_DESIGN.md
§5.5, decisions 23–27): `loader.py` fetches the public Sheets export and
fills the REFRESHED tables (dropped + recreated each half-yearly run);
the composition catalog and `stop_mappings` are CURATED (imported once /
built automatically, then hand-maintained, never truncated by a
refresh); `projection.py` rebuilds `route_summaries` (gallery/map),
`route_legs` (buffer calibration dataset) and `route_corridors`
(gallery-map corridor pieces).

**Related documentation:** design doc — `../../../docs/PROPOSALS_DESIGN.md`
(§5.5, §7.1) · schema — [`sql/create_ontd_schema.sql`](sql/create_ontd_schema.sql)
(lifecycle rules in the file header) · API reference —
[`../../api/README.md`](../../api/README.md)

Run order (from the API container):

```
python db/ontd/loader.py          # fetch + load the 11 canonical tables,
                                  # then build the projection
python db/ontd/projection.py      # projection only (e.g. after editing
                                  # curated tables); --no-geometry skips routing
```

---

## Stop mapping & corridors (WP10 step 6a)

`stop_mapping.py` bridges the ONTD and Target Network stop namespaces
until the harmonized OSM-id stop list replaces both (interim, ~2 weeks):
each active-route ONTD stop is coordinate-matched (≤500 m) against the
current base scenario's pinned `input_params.stop_infrastructures`
snapshot, or — where nothing is near — a new Target Network stop is
minted (`{CC}_{TRANSLITERATED_NAME}` in the curated style — Latin
diacritics, Cyrillic, and Greek all fold to the same Latin id namespace,
`transliterate()`, since ONTD carries station names in all three
scripts; `stop_charge_eur` NULL so the country/global default resolves,
provenance in `change_log`). Minted rows are inserted into **every**
existing `stop_infra_version`, not only the pinned one:
`stop_infrastructures` is a full-table-snapshot table (every version
holds an identical stop set — PROPOSALS_DESIGN.md §3.1), so minting into
one version alone silently broke that invariant for the historical/HSR
snapshots (caught by `test_02_db_seed.py`'s
`test_stop_infrastructure_values_unchanged_by_hsr_scenario`,
2026-08-06). Minted stops are ordinary catalog entries — plannable in
proposals, and (per `AUTO_STOP_BUFFER_M`/`AUTO_STOP_ANALYTIC_DETOUR_M`,
`models/route/version.py`) auto-insertable by `auto_stop_addition`.
Results live in `ontd.stop_mappings` (curated lifecycle — survives
refreshes; `match_method='manual'` or `verified=TRUE` rows are never
overwritten, so hand-corrections stick). Stops without coordinates or in
countries outside `input_params.countries` (NOT NULL FK) stay unmapped
and keep raw ONTD ids — queryable as the gap between active ONTD stops
and mapping rows.

Since WP10 step 6b, `route_summaries` and `route_corridors` are no
longer projection-only artifacts — they are the live `"existing"`
branch of `POST /api/proposals`' gallery union (summaries rows, corridor
merge in `map_lines`, stop/country counts), which is why the shared
stop-id namespace below matters beyond analytics.

The projection consumes the mapping in two places:
`route_summaries.stop_ids` is written in Target Network ids, and
`ontd.route_corridors` (refreshed) stores each route's per-stop-pair
geometry — the individual router leg, or the straight-line fallback —
with TN ids, direction-collapsed (`stop_a < stop_b`). That is the same
grain the gallery aggregates `proposals.segments` into, so existing
routes and proposals thicken shared corridors on one map layer
(map_lines union, step 6b).

Re-running `python db/ontd/projection.py` rebuilds mappings, summaries,
legs and corridors together; a database reseed that recreates the stop
catalog needs a projection re-run afterwards to restore minted stops.
