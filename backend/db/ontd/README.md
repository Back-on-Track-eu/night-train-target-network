# ONTD (Open Night Train Database) integration

Import and projection pipeline for the ONTD workbook (adapters/proposal/README.md
§5.5, decisions 23–27): `loader.py` fetches the public Sheets export and
fills the REFRESHED tables (dropped + recreated each half-yearly run);
the composition catalog and `stop_mappings` are CURATED (imported once /
built automatically, then hand-maintained, never truncated by a
refresh); `projection.py` rebuilds `route_summaries` (gallery/map),
`route_legs` (buffer calibration dataset) and `route_corridors`
(gallery-map corridor pieces).

**Related documentation:** design doc — `adapters/proposal/README.md`
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
until the harmonized OSM-id stop list replaces both (interim): each
active-route ONTD stop is coordinate-matched (≤500 m) against the
current base scenario's pinned `input_params.stop_infrastructures`
snapshot. The catalog is **complete at seed time** (revised 2026-08-07):
every stop the ONTD snapshot needs is part of `db/dev/seed.py`'s stop
data, derived once by `backend/scripts/export_ontd_stop_seed.py` into
the Drive-hosted `ontd_seed_stops.csv` (downloaded to `db/dev/data/` at
seed time when absent — `db/README.md`) using the module's own
id convention (`{CC}_{TRANSLITERATED_NAME}` in the curated style — Latin
diacritics, Cyrillic, and Greek all fold to the same Latin id namespace,
`transliterate()`; `stop_charge_eur` NULL so the country/global default
resolves, provenance in `change_log`). These are ordinary catalog
entries — plannable in proposals, and (per `AUTO_STOP_BUFFER_M`/
`AUTO_STOP_ANALYTIC_DETOUR_M`, `models/route/version.py`)
auto-insertable by `auto_stop_addition`.

This replaces the earlier **runtime mint**, which inserted missing stops
into every `stop_infra_version` during the bootstrap. Retired because
mutating pinned snapshot versions at runtime broke the compute cache's
scenario-pin key invariant (adapters/proposal/README.md §2.3 — a result
computed pre-mint kept being served post-mint for the cache TTL), and
because minted rows never survived a reseed anyway (`seed.py` DROPs
`input_params` while the guarded `ontd` schema keeps the bootstrap from
re-running — leaving `stop_mappings` pointing at stops that no longer
existed). An ONTD stop with no catalog row within 500 m is now
**reported and left unmapped** (`route_summaries` keeps its raw ONTD id)
— expected to be rare; the remedy is regenerating the seed CSV and
reseeding, never a runtime write. `test_02_db_seed.py`'s
`test_stop_catalog_snapshots` asserts the resulting invariant: all three
snapshot versions carry the identical, seed-defined stop set.

Results live in `ontd.stop_mappings` (curated lifecycle — survives
refreshes; `match_method='manual'` or `verified=TRUE` rows are never
overwritten, so hand-corrections stick; pre-2026-08-07 rows may still
carry `match_method='minted'`). Stops without coordinates or without a
catalog match stay unmapped and keep raw ONTD ids — reported by
`build_stop_mappings()` and queryable as the gap between active ONTD
stops and mapping rows.

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
legs and corridors together. A database reseed recreates the full stop
catalog from the seed data (curated + ONTD CSV), so nothing needs
restoring afterwards — mappings reference seeded ids that come back
identically.
