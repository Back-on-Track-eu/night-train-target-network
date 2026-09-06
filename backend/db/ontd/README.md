# ONTD (Open Night Train Database) integration

Import and projection pipeline for the ONTD workbook (adapters/proposal/README.md
§5.5, decisions 23–27): `loader.py` fetches the public Sheets export and
fills the REFRESHED tables (dropped + recreated each half-yearly run);
the composition catalog and `stop_mappings` are CURATED (imported once /
built automatically, then hand-maintained, never truncated by a
refresh); `projection.py` rebuilds `route_summaries` (gallery/map),
`route_legs` (buffer calibration dataset) and `route_corridors`
(gallery-map corridor pieces).

`route_summaries.country_relations` is derived here too, by the same
definition the proposal side uses: a country pair counts only where the
earlier stop can be boarded and the later one alighted — the ONTD
timetable's own `no_entry`/`no_exit` flags plus the route builder's
night-window classification (`models/route/timetable.py`'s
`classify_stop_type()`, imported rather than restated). That keeps
existing trains and proposals on one ranking dimension for
`GET /api/proposals/stats`. Stops with unusable times fall back to the
operationally neutral case rather than dropping out, so a patchy
timetable loses precision instead of losing relations.

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
`AUTO_STOP_ANALYTIC_DETOUR_M`, `models/route/model.py`)
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

**After a stop-catalog change** (new Drive CSV with removed or re-pointed
stop ids), the bootstrap repairs itself: `seed.py` DROPs `input_params`
on every start, so a reseeded catalog can leave this schema's derived
mappings pointing at ids that no longer exist. `bootstrap.py` detects
exactly that (`stale_stop_mappings()`) and re-runs the projection step
alone — the timetable and the curated composition catalog do not depend
on the stop catalog, so nothing is re-downloaded or re-routed
unnecessarily. A normal `docker compose up --build` is enough.

The same self-repair covers an **unrouted projection**
(`unrouted_projection()`): step 1 writes `route_summaries` with
straight-line placeholders (`geometry_routed = FALSE` everywhere) that
step 3 replaces. If step 3 never ran — router down, or the bootstrap
aborted before it — the placeholder would otherwise count as "loaded"
forever and every existing train would stay a dashed line on the gallery
map. A projection with no routed row now re-runs step 3 at the next
start; if the router is still down it simply tries again next time.

Step 2 (`composition_loader.py`) is **skipped** when the curated tables
already hold data — it refuses to overwrite hand-maintained tables, and
a populated catalog is the end state the bootstrap wants. Until
2026-09-06 that refusal was read as a failure, so on every persisted
database (dev volume, staging, production) the bootstrap stopped before
routing; the gallery's all-dashed map was this, not a routing problem.
`plan_steps()` holds the decision table; `tests/test_81` pins it.

The mapping stage then re-matches every active ONTD stop against the new
snapshot and warns about manual/verified rows stranded on removed ids
(those must be re-pointed or un-verified by hand — protection cuts both
ways). `test_38`'s `test_no_mapping_targets_removed_stops` asserts the
end state.

The mapping is also what gives an ONTD stop its **gauge**: ONTD carries
none, so `projection.py` builds the mapping before routing and routes
each stop on its catalog stop's `gauges_mm` (`catalog_gauges()`).
Unmapped stops route gauge-unknown, which does not constrain the trip.
Without this every existing train was routed on the standard-gauge
profile and the Finnish, Ukrainian and Baltic ones could not snap.

Every route left on straight lines is listed at the end of a projection
run grouped by `routing_status` with the router's message — the first
place to look when a gallery route is dashed. `snap_failed` on a stop far
from any track is usually an ONTD coordinate defect (the unmatched-stop
report above names the same stops); `gauge_mismatch` means the mapped
catalog stops span two networks; `no_connection` is a real answer about
the graph (Sicily until the ferry edge lands).

The detection is one-directional: it catches mappings left on removed
stops, not a catalog that merely *added* stops which previously
unmatched ONTD stops could now match. Those keep their raw ONTD ids
until a full reload:

```bash
docker exec night-train-api python db/ontd/bootstrap.py --force
```

(`--force` re-runs steps 1 and 3; step 2 is still skipped while the
curated tables hold data — use `composition_loader.py --replace`
deliberately if the catalog itself must be re-imported.)

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
