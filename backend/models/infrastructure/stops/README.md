# Stop classification pipeline

> **Handover:** the current task list for the people working on this
> pipeline is `HANDOVER.md` next to this file — stops (closed 2026-09-01,
> expert review open), station charges (the main open task), and the
> reasons for the manual additions. The August handover that used to sit
> here is folded into it.

Builds the catalog of railway stations that qualify as night train stop
candidates, starting from a raw OpenStreetMap (OSM) Europe extract. The
qualified list later drives the frontend station picker and the automatic
stop suggestion along routes — a station missing here is unselectable
everywhere in the app, which is why the pipeline never deletes rows: it marks
them, and every decision stays reviewable (see "Design background" below for
the full design and its principles).

![Pipeline sets](pipeline_sets.svg)

## The pipeline, step by step

| # | Step | Status | File |
|---|------|--------|------|
| 1 | Fetch OSM Europe data (`europe-latest.osm.pbf` from Geofabrik → `data/raw/`) | ✅ done | — (manual download) |
| 2 | Filter all station objects out of the raw extract | ✅ done | `step2_filter_stations.py` |
| 3a | Fetch center coordinates for station ways/relations | ✅ done | `step3a_fetch_missing_centers.py` |
| 3b | Classify "real" railway stations vs. urban transit | ✅ done | `step3b_classify_stations.ipynb` |
| 4 | Merge classified stations with the station register, topped up from ONTD where the register has no row (left join; inspect rows without an OSM match) | ✅ done | `step4_MatchingONTDtoOSM.ipynb` |
| 5 | Qualify stops via current night train stops (`stop_times`), then diagnose the unmatched (ONTD coverage check) | ✅ done | `step5_JoinNTStopsWithOSM.ipynb` |
| 6 | Add stations for [functional urban areas](https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/cities-functional-urban-areas) without a qualified stop, plus tourism regions, ferry hubs, border and corridor stations — guarded against duplicating step 5; each addition tagged with the infrastructure version(s) it belongs to (`infra_versions`) | ✅ done, reasons outstanding | `step6_manual_additions.ipynb` |
| 6a | Resolve a CSV of named candidates to OSM ids and print paste-ready step 6 lines (coordinate-first, name-second, step 6's guards applied) — the tool behind the 2026-09 gap closure and the way to add the next batch | ✅ done | `step6a_resolve_candidates.py`, `step6_gap_closure_2026-09.csv` |
| 7 | Enrich: Latin/ASCII names, UIC ref, country + city per stop, both in all member-organisation languages | ✅ done, place fetch per machine | `step7_enrich_stops.ipynb` |
| 8 | Tag night-train-capable track gauge(s) per stop from OSM `railway=rail` tracks, ≥ 1435 mm (a stop can carry several — e.g. 1435 + 1668 in Spain) | ✅ done | `step8_stop_gauges.ipynb` |
| 9 | Calibrate station charges from the countries' tariff documents — one CSV per country in `charges/sources/` following `charges/sources/TEMPLATE.md`, joined onto the catalog by step 10 | 🔄 Germany done (105 stops), rest handed over — see `charges/HANDOVER.md` | `charges/01_source_extraction.ipynb`, `charges/02_station_charges.ipynb` |
| 10 | Export the catalog for the DB seed — one CSV: seed contract columns, provenance category, enrichment, gauges | ✅ done | `step10_export_seed_stops.py` |

Numbering note: 9 is the charges sub-pipeline (its own directory, previously
"7b") and the export sits at 10, leaving room for further per-stop derivation
steps without renumbering everything again.

Steps 2 and 3 only need re-running when the OSM source data is refreshed.
Step 2 takes ~9 hours for all of Europe — do not re-run it casually; its
output is checked into `data/` handover packages instead.

## How to run

All commands from this directory (`backend/models/infrastructure/stop_classification/`):

```
uv run python step3a_fetch_missing_centers.py     # needs internet (Overpass API)
uv run jupyter lab                                # then run step3b, step4, step5 (first run
                                                  #   fetches the ONTD workbook), step6,
                                                  #   step7 (first run fetches place nodes
                                                  #   via Overpass), step8 (Overpass)
uv run python step6a_resolve_candidates.py <candidates.csv>
                                                  # optional: OSM ids for a batch of new
                                                  #   step 6 additions, paste the output
uv run python step10_export_seed_stops.py         # writes data/stop_seed_catalog.csv
                                                  #   (single file, all attributes) and
                                                  #   data/step10_dropped_stops.csv (what
                                                  #   the previous catalog had, this lacks)
```

Inputs resolve through `data_sources.py`, which draws a line between two kinds
of file:

- **`ensure_local(name)`** — comes from outside this machine, so it syncs the
  Drive folder into `data/` when the file is absent. That is the external
  station export (`bahnhoefe_stops_sorted.csv`) and the OSM-derived
  intermediates you cannot rebuild without the ~60 GB Europe extract, an
  osmium pass and hours of Overpass calls (steps 2, 3a, 3b). One folder id,
  `STOPS_DRIVE_FOLDER_ID` in `backend/docker/.env`, covers all of them;
  syncing uses `gdown` (in the `dev` extra), since Drive cannot list a folder
  over plain HTTP. The sync only fills gaps — a local file always wins, so a
  file a step just wrote is never overwritten.
- **`ontd_stops()`** — the stops a night train actually calls at, taken from
  the same workbook and emitted in the station register's own column shape.
  Step 4 concatenates the ones the register does not carry: it is a
  third-party OSM-derived list, and Sighișoara, Iași, Roma Ostiense, Veliko
  Tarnovo, Hässleholm C, Åre and Briançon are absent from all three of its
  name columns, so step 5 could not qualify them however good its own match
  was. Restricted to called stops rather than all ~28k ONTD stops — step 4
  bridges stops that could be qualified, and matching 28k against OSM to
  reach a few dozen would only slow it and swell its ambiguity reports.
- **`ontd_stop_times()`** — the night train schedule step 5 qualifies against,
  read from the ONTD workbook `db/ontd/loader.py` loads (`ONTD_WORKBOOK_ID`),
  and cached at `data/ontd_stop_times.csv` under the same local-file-wins
  rule. It used to be a hand-made Drive export, `B-o-T_DataBase_stop_times.csv`
  — correct on the day it was made, but nothing kept it level with the
  workbook, and the two drifted **in both directions**: of the 239 active ONTD
  stops with no catalog row, **224 were simply absent from that export**,
  while it still carried stops no active train serves. The catalog was built
  from one snapshot of ONTD while the app ran on another. Reading the same
  workbook removes the second snapshot instead of rescheduling its refresh.
- **`local_input(name, produced_by)`** — written by an earlier step of this
  pipeline, so it is never downloaded: a Drive copy could silently override
  what your own notebook just produced. Missing means that step has not been
  run, and the error says which one. **Step 4's output belongs here** and was
  misfiled as downloadable until 2026-08-28: step 4 wrote it to the notebook's
  working directory while step 5 read `data/`, where `ensure_local` had put a
  stale Drive copy — so a step 4 re-run changed nothing downstream and said
  nothing about it. Running step 5 now requires step 4 to have been run.

Nothing under `data/` is tracked in git. If the sync can't work (no id set,
`gdown` not installed, folder not shared), place the file in `data/` by hand —
the message names the file and the reason.

## Why this is not regenerated at seed time

`db/dev/seed.py` runs the calibration notebooks itself when their seed CSVs are
missing (`_ensure_seed_csvs`, used by `compositions/calib`, `tac/calib`,
`energy_pricing/calib`, `facility/calib` and `route_context/calib`). This
pipeline deliberately does not work that way, and the difference is worth
stating because it is the first thing anyone asks.

Those domains are **derivations**: given the source register in the repo, the
notebook recomputes the same values every time, in seconds, offline. A
container can reproduce them, so it does.

This pipeline is neither cheap nor fully deterministic:

- step 2 needs the ~60 GB OSM Europe extract, downloaded by hand from Geofabrik
- step 3a makes hours of calls to a public, rate-limited Overpass instance
- step 6 is a **human selection** — 379 stations chosen by judgement. The
  notebook is a record of those decisions, not a derivation of them, and
  re-running it cannot reproduce judgement it was never given

So it runs offline on a workstation, publishes exactly one artifact
(`stop_seed_catalog.csv`) to Drive, and `seed.py` downloads that. The rule:

> If a container can reproduce it from what is in the repo, `seed.py`
> regenerates it. If it needs external bulk data or human judgement, it runs
> offline and publishes one artifact.

The charge calibration in `charges/` is the near-miss: it *is* a derivation in
the calib mould and could follow that pattern. It does not, because step 10
joins its output into the catalog before upload — by the time `seed.py` sees
the CSV the charges are already in it, and a second path would mean two places
deciding a stop's charge.

## Data inventory

Everything under `data/` is gitignored (bulk data). What each file is:

| File | What it is | Needed by |
|------|-----------|-----------|
| `data/raw/europe-latest.osm.pbf` | Raw OSM Europe extract (~32 GB, Geofabrik). Only needed to re-run step 2. | step 2 |
| `data/step2_output_eu_stations.osm.pbf` | **The step 2 output.** Every OSM station object in Europe (98,944), with all tags. | steps 3a, 3b |
| `data/step3a_output_way_relation_centers.csv` | Step 3a output: center lat/lon per station way/relation. | step 3b |
| `data/step3b_output_osm_stations_classified.csv` | Step 3b output: all stations with `station_mode` classification. | steps 4, 5 |
| `data/step5_JoinedNTStops.csv` | Step 5 output: one row per qualified ONTD stop — step 4 columns plus schedule name, medoid coordinate, spread, distance, `match_confidence`, `name_score`. | steps 6, 7, 8, 10 |
| `data/unmatched_stops.csv` | Step 5 output: schedule stops with no accepted match — review, don't drop. | manual review |
| `data/step5_review_flagged.csv` | Step 5 output: `geo_only` / `ambiguous` / `name_coords_conflict` matches — review before trusting the run. | manual review |
| `data/step5_coord_conflicts_report.csv` | Step 5 output: schedule stops whose own coordinate reports disagree by more than GPS jitter. | manual review, upstream data fix |
| `data/step5_duplicate_matches_report.csv` | Step 5 output: ONTD stops claimed by more than one schedule name (alternate spellings). | manual review |
| `data/step5_ontd_coverage_gaps.csv` | Step 5 output: each unmatched schedule stop diagnosed — `station_absent_from_ontd` (the silent ONTD coverage debt), `osm_object_matched_to_other_ontd_row`, or `no_osm_station_within_radius`. | manual review, ONTD upstream fixes |
| `data/step6_manual_additions.csv` | Step 6 output: the hand-picked stops with `reason` and `infra_versions` (`infra-2026;infra-2032`, `infra-2032`, `infra-2026`). | steps 7, 8, 10 |
| `step6_gap_closure_2026-09.csv` | **Tracked.** Step 6a input for the September 2026 gap closure: every station the frozen schedule export had that the live catalog lost, with reason, `infra_versions`, and the stations deliberately not added. The template for the next batch. | step 6a |
| `data/step6_candidates_resolved.csv` | Step 6a output: the outcome per candidate — id found, ambiguous, no station in radius, already qualified. | manual review |
| `data/step10_dropped_stops.csv` | Step 10 output: stops the previous `stop_seed_catalog.csv` had and the new one lacks. Written on every run; non-empty means ONTD moved (usually fine) or a step 6 prune is now wrong (fix in step 6). | manual review |
| `data/step6_overlap_review.csv` | Step 6 output: `fua:` additions with a qualified stop within 15 km — judgement calls to re-reason or drop, written on every run. | manual review |
| `data/step7_place_nodes.csv` | Step 7 cache: OSM `place=city\|town` nodes per catalog country with population and `name:<lang>` tags, fetched once from Overpass. Delete to re-fetch. | step 7 |
| `data/step7_enriched_stops.csv` | Step 7 output: per catalog stop — Latin/ASCII name, UIC ref, country and city, each in all member-organisation languages. | step 10 |
| `data/step8_stop_gauges.csv` | Step 8 output: night-train-capable track gauge(s) per stop (`railway=rail`, ≥ 1435 mm — trams/Stadtbahn/narrow gauge are filtered out) with evidence level (`tagged` / `untagged_tracks` / `narrow_gauge_only` / `no_tracks_nearby`). Append-mode: re-running fills gaps. | step 10 |
| `data/stop_seed_catalog.csv` | Step 10 output, **the one published file**: the seven seed contract columns first, the charge provenance, a human-readable `provenance` category, `infra_versions`, then the step 7 name/city/language columns and step 8 gauges. `seed.py` validates the 36-column header as an **exact** match (`_STOP_SEED_CSV_COLUMNS`) — step 10 and seed.py move in lockstep. `infra_versions` is carried but not yet acted on at seed time. | DB seed |
| `charges/sources/<cc>_station_charges.csv` | Step 9 input, one per country: the transcribed tariff keyed by catalog `stop_id`, carrying the charge net, the VAT rate and the charge gross. Twelve columns, defined in `charges/sources/TEMPLATE.md`. Checked in — these are the record of what each document says. | step 9 |
| `charges/data/station_charges.csv` | Step 9 output, generated by `charges/02_station_charges.ipynb`: one charge per stop with its full provenance — VAT rate, gross figure, basis, price basis year, tariff class and source document, all of which step 10 joins onto the catalog beside the figure. A stop absent here is seeded NULL and resolves via the global default. Gitignored — the notebooks are the source of truth. | step 10 |
| `charges/data/sources_register.csv` | Generated by `charges/01_source_extraction.ipynb`: the tariff documents behind those charges. | `charges/02` |
| `data/bahnhoefe_stops_sorted.csv` | ONTD export (48,617 stations): names (real/Latin/ASCII), country code, timezone, lat/lon, and the ID linking to the old stop charge data. | step 4 |
| `data/B-o-T_DataBase_stop_times.csv` | `stop_times` export from the night train database — defines where night trains stop today. | step 5 |
| `data/eu_stations_{light_rail,subway,tram,train_yes,uic_name,uic_ref}.osm.pbf` | Exploration-only side outputs of the step 2 run. Each contains *every* OSM object with that tag (not just stations) — for QGIS tag-coverage analysis. **Not pipeline inputs**; safe to delete. | — |

access via: https://drive.google.com/drive/folders/1iAjxVKRn1qhgR-yhfczO91M41KIIIIVd?usp=sharing

Step 3b's why-a-centers-file explanation, the classification rules, and the
matching strategy are documented in the notebooks themselves and in the
"Design background" section below — read those in that order.

## Known open items

- **`infra_versions` is tagged but not consumed.** Step 6 says per stop
  whether it belongs to `infra-2026`, `infra-2032` or both, and step 10
  carries that into the catalog; `seed.py` reads the column for the header
  contract only and still seeds every stop into every snapshot version.
  Consuming it — so a Rail Baltica station cannot be selected against the
  2026 graph — is a seed-side work package that needs the stop table
  schema touched.
- **Step 6 was pruned against a step 5 that then changed.** Fixed for the
  August case (see the 2026-09 addendum in `step6_manual_additions.ipynb`)
  and guarded by step 10's dropped-stops report; the structural version —
  step 6 knowing *which* step 5 run it was reconciled against — is not
  built.

- **Country column is nearly empty after step 3b** (`addr:country` covers <1%
  of OSM stations). Filling it from coordinates is a prerequisite for step 4's
  within-country matching — use the project's existing `CountryIndex` helper
  rather than adding a new reverse-geocoding dependency.
- **`undecided` classification bucket is large (~41%)** — mostly minimal
  `railway=halt` objects. They stay in per the keep-it-in principle; the
  design doc's track-proximity second pass ("Design background" §3 Stage A) is
  the planned refinement if the bucket causes noise downstream.
- **Step 3a depends on the Overpass API**, which reflects current OSM (slightly
  newer than the extract). Objects deleted since the extract date come back
  without a center and are reported — expect a small handful. The public
  instance occasionally answers a batch with a transient server error; the
  script retries those automatically, and if a batch still fails it's skipped
  and listed in `<output>.failed_ids.csv` rather than aborting the whole run —
  just re-run the script to catch those up (Overpass is stateless per request,
  so this is cheap).
- **Gauge cross-validation against OpenRailRouting** — step 8 reads what OSM
  *tags* near the stop; the routing graph knows what the router will actually
  *use*. Comparing the two per stop is the planned second signal, and feeds
  the composition-level gauge filter in `custom_models/night_train.json`.
- **The step 6 fua-overlap check uses a 15 km radius as a proxy** for "same
  functional urban area". The honest test is the GISCO FUA polygons themselves
  (link in the step table) — point-in-polygon against the qualified stops
  would turn `step6_overlap_review.csv` from a heuristic into a verdict.
- Visual QA of the step 3b output in QGIS (load
  `data/step3b_output_osm_stations_classified.csv` as a point layer, color by
  `station_mode`) before anyone builds on it. Sanity anchor from the design
  doc: roughly 300–500 qualified stops expected for Germany at the end of the
  pipeline.

---

## Design background

The pipeline follows the design below, written before implementation started. Kept as-is for the reasoning and the open decisions (§6); deviations from it should be noted inline as they're made.

### 1. The problem

We need a catalog of stops that are realistic candidates for night trains.

Our source is OSM (OpenStreetMap). A raw OSM extract contains **every** station
object — heavy rail, subway, tram, light rail mixed together. For Germany alone
that is well over 5,700 objects once urban transit is included, while only a
few hundred are plausible night train stops.

So the task has two parts:

1. **Find the "real" railway stations** in the OSM data (and drop subway/tram).
2. **Decide which of those qualify** as night train stop candidates.

**Why this matters downstream:** the qualified list becomes the only set of
stations users can pick from at all — it drives two concrete things:

- **Frontend stop selection** (Bjarne's side): the station picker should only
  offer stops where a night train could realistically stop. Right now that
  picker effectively has access to the full unfiltered OSM list, so someone
  planning a route could select a random suburban halt or subway stop.
- **Automatic stop addition** (`auto_stop_addition="add"`/`"suggest"` on
  `POST /api/route/plan`): the candidate search that proposes extra stops along
  a route must search this same qualified set — not all ~5,700+ raw stations.
  This also directly shrinks the per-candidate mini-reroute cost that is the
  known bottleneck there (see `OPEN_TODOS["auto_stop_nuts1_prefilter"]`).

In short: this list *is* the definition of "a valid night train stop" for the
rest of the system. That is also why the keep-it-in-when-in-doubt principle
matters so much — a station missing here is not just "hidden" in an edge case,
it becomes permanently unselectable everywhere in the app until the catalog is
regenerated.

Suggested output: **one CSV with every station from the extract**, where each
row says whether the stop is in or out, and *which rule* decided that. Nothing
is deleted — filtering happens later at import, based on these columns.

Three principles behind this:

- **Non-destructive:** keep all rows, mark them. Makes every decision reviewable.
- **When in doubt, keep it in.** A wrongly excluded stop can never be routed to
  or suggested later. A wrongly included one just sits unused. Cheap mistake
  vs. expensive mistake.
- **Auditable:** "why is station X (not) included?" must be answerable from the
  CSV alone — also for external stakeholders.

### 2. Prerequisites

Things to have ready before starting:

1. **An OSM extract.** Download country extracts as `.osm.pbf` from Geofabrik
   (e.g. `germany-latest.osm.pbf`). Keep these files **untracked** (gitignored),
   like other bulk data in this repo.

   *How to list all stations from it?* Suggested approach: first shrink the file
   with the `osmium` command-line tool, then read it in Python:

   ```
   osmium tags-filter germany-latest.osm.pbf nwr/railway=station nwr/railway=halt nwr/public_transport=station -o stations_de.osm.pbf
   ```

   This cuts a multi-GB file down to a few MB. Then a small **pyosmium** script
   (already used in this project for OSM work) reads the small file into a
   pandas DataFrame: one row per station with id, name, lat/lon and all tags.
   For exploration and tuning, a **Jupyter notebook** on top of that DataFrame
   works well (same pattern as the calibration notebooks). The final pipeline
   should be a plain script, so it can be re-run when data updates.

   `step2_filter_stations.py` (same folder) does the shrinking step in pure Python
   instead of the CLI, so it stays reproducible without requiring the
   `osmium` CLI tool to be installed separately — only the `osmium`/`tqdm`/
   `psutil` Python packages, which are already project dependencies.

   Only the `station` filter (the default) feeds this pipeline. The script
   also supports further tag-based filters (`light_rail`, `subway`, `tram`,
   `train_yes`, `uic_name`, `uic_ref`) for exploratory QGIS analysis — note
   these match their tag on *any* object in the input, not just on stations.
   All selected filters run in a single shared pass over the input, since a
   continent-sized extract can take hours to scan:

   ```
   uv run python step2_filter_stations.py data/raw/europe-latest.osm.pbf -o data/step2_output_eu_stations
   uv run python step2_filter_stations.py data/raw/europe-latest.osm.pbf --filters all -o data/eu_stations
   ```

   `-o`/`--output` sets an output *prefix*, not a full filename — each
   selected filter writes `<prefix>_<filtername>.osm.pbf`. Default prefix is
   the input filename with `.osm.pbf` stripped. A continent-sized extract can
   take several hours, more so with multiple filters selected at once — the
   progress bar reports objects processed, total matches, and current RAM
   usage so a long run doesn't look stalled.

2. **The current night train stop list** as CSV in GTFS-like format:
   `stop_name, stop_country, stop_timezone, stop_lat, stop_lon`.
   Note: it has **no station IDs** (no UIC/IBNR), so matching to OSM must work
   via coordinates + names (see Stage B).

3. **GTFS feeds per country** (timetable data), used to detect where
   long-distance trains stop today. Start with Germany: the **DELFI** feed
   (free, registration required). Finding good feed sources for further
   countries is part of onboarding each country — check what the
   demand-modelling research already collected before searching from scratch.

4. **A map tool for visual checks — QGIS.** Load the output CSV as a point
   layer (it has lat/lon), color by classification, and check visually:
   Are the big hubs in? Are subway stations gone? QGIS is also the practical
   way to spot stops for the manual override list (see Stage D).

### 3. Suggested pipeline

```
OSM extract (.osm.pbf, untracked)
        │
        ▼
[A] Extract stations & drop urban transit ──► station_mode per row
        ▼
[B] Match external sources to OSM stops ────► match confidence per source
        ▼
[C] Qualification signals (3 tiers) ────────► signals per row
        ▼
[D] Manual overrides (include/exclude) ─────► final say
        ▼
[E] Resolve: qualified yes/no + tier ───────► classified_stops.csv
```

A stop qualifies if it matched **any** positive signal and is not manually
excluded. Signals are independent — a stop can match several, and all of them
are recorded.

#### Stage A — Real railway stations vs. subway/tram

Don't expect one perfect tag query — OSM tagging is inconsistent. Suggested:
simple rules plus an explicit "undecided" bucket.

Take all objects with `railway=station`, `railway=halt`, or
`public_transport=station`, then classify:

- **Heavy rail (keep):** has `train=yes`, **or** has a `uic_ref` tag
  (subway stops almost never have UIC references — strong signal),
  **or** has no subway/tram indicators at all.
- **Urban transit (drop from further evaluation):** `station=subway`,
  `station=light_rail`, or `subway=yes`/`tram=yes` *without* `train=yes`.
- **Ferry terminals (mark as `other`):** `amenity=ferry_terminal` without
  heavy-rail evidence — ferry piers carry `public_transport=station`
  surprisingly often and would otherwise flood the undecided bucket. Rows
  stay in the CSV (`mode_rule=ferry_terminal`), so the set remains
  retrievable later.
- **Mixed (keep):** big hubs often serve rail *and* metro under one OSM object.
  Rule of thumb: never drop because a subway tag is *present* — only because
  heavy-rail evidence is *absent*.
- **Undecided (keep for now):** everything else. Mark it, don't guess. If this
  bucket turns out large, a second pass can check whether the station lies near
  `railway=rail` tracks (needs track geometry, so only do this for the
  undecided bucket, not for everything).

Each row gets `station_mode` (`heavy_rail` / `mixed` / `urban_transit` /
`undecided`) and `mode_rule` (which rule fired), so the results can be checked
in QGIS and the rules tuned. Urban-transit rows stay in the CSV but skip the
following stages. (Base fields per row — `stop_id`, `stop_name`, `stop_lat`,
`stop_lon`, etc. — follow the GTFS `stops.txt` format described in §4.)

#### Stage B — Matching external data to OSM stops

Both the night train list and GTFS feeds name stations in their own way — they
don't know OSM ids. Matching them to OSM rows is **the trickiest part of the
whole pipeline**, so budget time for it.

Since the night train list has no IDs, match **coordinates first, names
second**:

1. Only compare within the same country (`stop_country`) — plus a small buffer
   across borders for border stations.
2. Find OSM stations within ~500 m of the source coordinate; if nothing found,
   widen to ~1.5 km (big stations can have their OSM center point far from the
   source coordinate).
3. If several candidates: compare **normalized names** — lowercase, remove
   accents, expand common abbreviations per country ("Hbf" ↔ "Hauptbahnhof",
   "Gare de …", "Centraal", "Główny"), then fuzzy string similarity
   (e.g. `rapidfuzz` token-set ratio). Best score wins; low score → mark
   as ambiguous instead of guessing.
4. Record per match: distance, name score, and a confidence label
   (`exact` / `geo_name` / `geo_only` / `ambiguous`). Low-confidence matches
   still count (keep-it-in principle) but go into a review report.

For GTFS feeds: use stable IDs where the feed has them (check per feed —
DELFI stop ids relate to IBNR), matched against `uic_ref` in OSM; otherwise
fall back to the same coordinates+name procedure. Write the matcher **once**
and reuse it for both sources.

**Important:** external stops with no OSM match must be written to
`unmatched_stops.csv` (or `step5_output_unmatched_report.csv` for the alt notebook), never silently dropped. An unmatched night train stop
is always a data problem worth fixing — either bad source coordinates (a known
issue) or missing/mistagged OSM data. Bonus: since *every* current night train
stop should find a match, this list is a free test — use it to tune the
thresholds in step 2 and 3.

#### Stage C — Qualification signals (three tiers)

**Tier 1 — stop of a current night train.** Matched via Stage B against the
night train list. Signal: `current_night_train`. Highest confidence, but by
design only covers today's network — it is the floor, not the ceiling.

**Tier 2 — long-distance trains stop there today.** From the GTFS feed: filter
to rail (`route_type = 2`), then keep only long-distance services. What counts
as "long distance" differs per feed — for Germany, filter by route names/agency
(ICE, IC, EC, NJ, FLX, …). This per-country filter list must be documented per
country. Signal: `gtfs_long_distance:<feed>`, e.g. `gtfs_long_distance:DELFI`.
This is the strongest general signal: if an IC stops there, platforms and
access are adequate.

**Tier 3 — importance signals.** Where a country has a good national signal,
use it directly: Germany's DB station categories (suggest classes 1–3;
whether class 4 adds anything — check overlap with Tier 2 first). Signal:
`station_category:DE:<class>`.

For everything else, use the same **anchor-first pattern** rather than a
per-station radius rule, and treat population as just the first of several
possible anchor types — the pattern generalizes:

- Take a list of "anchors" of a given kind (cities above a population
  threshold; known tourism regions/resorts; whatever else turns out useful —
  see below).
- For each anchor, find its nearest heavy-rail/mixed station (or its small
  number of best-connected stations, where picking one is clearly wrong —
  decide per anchor type during tuning).
- Only that station gets the signal, tagged with the anchor type, e.g.
  `population_city:<city_name>` or `tourism_area:<area_name>`.

Why anchor-first instead of radius-first: a naive "any station within X km of
[anchor]" rule over-qualifies — Berlin alone has 300+ stations, and a radius
rule around it would pull in nearly all of them, even though only a handful
are realistic long-distance/night-train candidates. Anchor-first also flips
the review question usefully: instead of "why did this random station
qualify?", you get a list of anchors with **no** station assigned — worth
checking whether that is a genuine gap or expected.

Anchor types worth adding, roughly in order of expected value:
1. **Population** (city ≥ threshold) — broadest coverage, easiest data
   (GeoNames/Wikidata), good default everywhere.
2. **Tourism areas** — ski resorts, coastal/lake regions, national parks:
   exactly the kind of small-population destinations that real night trains
   serve but population alone would miss (e.g. Alpine resort towns). No single
   clean European data source for this is known yet — likely needs a curated
   list per country/region rather than an automated feed; start small and
   extend as gaps are found via review.
3. **Others as they come up** — e.g. major border-crossing points, ferry/hub
   connections. Add as a new anchor type only when a concrete case justifies
   it, using the same pattern (anchor list → nearest station → signal).

Each anchor type is independent and additive — a station can be pulled in by
several anchors, all of them recorded in `signals` like any other tier.

Per country the chain is: GTFS signal → national category → anchor-based
signals. A country nobody onboarded yet still gets Tier 1 + population as the
default anchor type, so no country ends up empty.

**Documentation step6:**
Stops which lay in urban areas were selected manually, for every area 1-2 stops each. Furthermore Tourism areas & major ferry hubs were added.


#### Stage D — Manual overrides

A tracked file `stop_overrides.csv` with columns `stop_ref, action, reason`
(`action` = `include` or `exclude`; `reason` is **mandatory**).

- `include` qualifies a stop no automatic rule caught — e.g. small tourist
  stations (ski resorts, coastal towns) that are classic night train stops
  *precisely because* they are small.
- `exclude` always wins over every positive signal.
- The reason strings double as the ready-made answer when stakeholders ask
  "why is X (not) on the list?" — one file edit instead of a pipeline change.

Unlike the bulk data, this file **is tracked in git** — it is curated content.

#### Stage E — Resolve

`qualified = (any positive signal) AND (no manual exclude)`, plus
`candidate_tier` = best (lowest) tier among matched signals
(1 = night train, 2 = GTFS long-distance, 3 = category/anchor-based,
4 = manual include only).

### 4. Output

`classified_stops.csv` — **one row per station in the extract, nothing dropped.**

Suggested format: standard **GTFS `stops.txt`** columns, so the file can be fed
directly into GTFS-based tooling (and into the frontend/`params` endpoints
later without another mapping step), plus our own classification columns
appended at the end as an extension — this is a normal GTFS pattern.

| Column | GTFS standard? | Description |
|---|---|---|
| `stop_id` | yes | **OSM id used as the identifier**, type-prefixed (e.g. `osm:n123456`) so it's recognizable as OSM-sourced and won't collide with IDs from other sources later |
| `stop_code` | yes | `uic_ref` if tagged in OSM, else empty |
| `stop_name` | yes | Station name from OSM |
| `stop_lat`, `stop_lon` | yes | Coordinates from OSM |
| `stop_timezone` | yes | Derived from country (matches the format used in the night train list) |
| `location_type` | yes | `1` (station) for all rows here |
| — *(extension columns below, not part of GTFS spec)* | | |
| `country` | | ISO-2 code |
| `station_mode` | | `heavy_rail` / `mixed` / `urban_transit` / `undecided` |
| `mode_rule` | | Which Stage-A rule decided that |
| `qualified` | | Final in/out |
| `candidate_tier` | | 1–4, empty if not qualified |
| `signals` | | e.g. `current_night_train;gtfs_long_distance:DELFI` |
| `signals_negative` | | e.g. `manual_exclude` |
| `match_notes` | | Match confidence, distances, name scores |

Plus a report of external stops without an OSM match (`unmatched_stops.csv`
for the night train stop_times source — see "How to run" above) — this one
does not need to follow the GTFS format since it never feeds downstream tooling.

Both outputs live next to the input data and are gitignored.

**Sanity check:** for Germany, expect roughly **300–500 qualified** stops. If
the number lands far outside that range, revisit thresholds before importing —
and do a visual pass in QGIS either way.

### 5. Downstream integration

- The CSV feeds the existing stop import/seed path; only `qualified = true`
  rows get imported into the versioned stop catalog.
- Suggestion: carry `candidate_tier` and `signals` into the stop table (as
  `qualification_sources`) so provenance survives into the catalog. This means
  a new infrastructure table version and scenario re-pinning — **needs David's
  sign-off first.**
- Since stop tables are snapshot-versioned, a stricter and a looser filter are
  simply two catalog versions — scenarios can pin either, so filter variants
  can be compared like any other scenario difference.
- Side effects: a smaller catalog speeds up the `auto_stop_addition` candidate
  search and reduces exposure to the known coordinate-quality issues in the
  current stop source.

### 6. Open decisions (check with David before/while implementing)

1. Stop table schema extension (`candidate_tier`, `qualification_sources`) —
   implies a new table version.
2. Location/format of the current night train stop list.
3. GTFS feed sources per country (reuse demand-modelling research findings).
4. DE Preisklasse 4: in or out — decide after checking overlap with Tier 2.
5. Matching thresholds (500 m / 1.5 km, name-score cutoff) — tune using the
   night train list as the validation set.
6. Undecided `station_mode` bucket: let it into tier evaluation (default: yes,
   keep-it-in principle) or run the track-proximity pass first? Depends on size.
7. Anchor-based signals (§3, Stage C): one nearest station per anchor, or top
   few "best-connected" ones for larger anchors (e.g. Berlin, Paris)? Also:
   which anchor types beyond population are worth building first (tourism
   areas is the obvious next candidate) and where does a curated list for
   those come from?

### 7. Deferred ideas

- Platform length check from OSM platform geometry (night trains are long;
  OSM data too patchy today). Add `OPEN_TODOS["stop_classification_platform_length"]`
  to `model.py` when starting implementation.
- More country adapters beyond Germany.
- Re-run strategy when OSM/GTFS sources update; record source timestamps in a
  small metadata sidecar file.

### 8. Project conventions (short version)

- Standalone script(s), runnable without the API. Python 3.12, Black formatting.
- Meaningful comments only; longer explanations belong in this file, not in
  code blocks.
- Check for existing helpers before writing new ones.
- Bulk data untracked; `stop_overrides.csv` tracked.
- Tests: integration-style against a small real OSM fixture, numbered per the
  existing `test_NN_` convention.
