# Stop Classification Pipeline — Implementation Suggestion

Status: **design suggestion, not implemented.** This document describes *one
possible way* to solve the problem. Feel free to deviate where you find a
better or simpler approach — but please document deviations here.

Planned location: `backend/models/infrastructure/stop_classification/`

---

## 1. The problem

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

## 2. Prerequisites

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

## 3. Suggested pipeline

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

### Stage A — Real railway stations vs. subway/tram

Don't expect one perfect tag query — OSM tagging is inconsistent. Suggested:
simple rules plus an explicit "undecided" bucket.

Take all objects with `railway=station`, `railway=halt`, or
`public_transport=station`, then classify:

- **Heavy rail (keep):** has `train=yes`, **or** has a `uic_ref` tag
  (subway stops almost never have UIC references — strong signal),
  **or** has no subway/tram indicators at all.
- **Urban transit (drop from further evaluation):** `station=subway`,
  `station=light_rail`, or `subway=yes`/`tram=yes` *without* `train=yes`.
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

### Stage B — Matching external data to OSM stops

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
`unmatched_report.csv`, never silently dropped. An unmatched night train stop
is always a data problem worth fixing — either bad source coordinates (a known
issue) or missing/mistagged OSM data. Bonus: since *every* current night train
stop should find a match, this list is a free test — use it to tune the
thresholds in step 2 and 3.

### Stage C — Qualification signals (three tiers)

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

### Stage D — Manual overrides

A tracked file `stop_overrides.csv` with columns `stop_ref, action, reason`
(`action` = `include` or `exclude`; `reason` is **mandatory**).

- `include` qualifies a stop no automatic rule caught — e.g. small tourist
  stations (ski resorts, coastal towns) that are classic night train stops
  *precisely because* they are small.
- `exclude` always wins over every positive signal.
- The reason strings double as the ready-made answer when stakeholders ask
  "why is X (not) on the list?" — one file edit instead of a pipeline change.

Unlike the bulk data, this file **is tracked in git** — it is curated content.

### Stage E — Resolve

`qualified = (any positive signal) AND (no manual exclude)`, plus
`candidate_tier` = best (lowest) tier among matched signals
(1 = night train, 2 = GTFS long-distance, 3 = category/anchor-based,
4 = manual include only).

## 4. Output

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

Plus `unmatched_report.csv` (external stops without OSM match) — this one does
not need to follow the GTFS format since it never feeds downstream tooling.

Both outputs live next to the input data and are gitignored.

**Sanity check:** for Germany, expect roughly **300–500 qualified** stops. If
the number lands far outside that range, revisit thresholds before importing —
and do a visual pass in QGIS either way.

## 5. Downstream integration

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

## 6. Open decisions (check with David before/while implementing)

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

## 7. Deferred ideas

- Platform length check from OSM platform geometry (night trains are long;
  OSM data too patchy today). Add `OPEN_TODOS["stop_classification_platform_length"]`
  to `version.py` when starting implementation.
- More country adapters beyond Germany.
- Re-run strategy when OSM/GTFS sources update; record source timestamps in a
  small metadata sidecar file.

## 8. Project conventions (short version)

- Standalone script(s), runnable without the API. Python 3.12, Black formatting.
- Meaningful comments only; longer explanations belong in this file, not in
  code blocks.
- Check for existing helpers before writing new ones.
- Bulk data untracked; `stop_overrides.csv` tracked.
- Tests: integration-style against a small real OSM fixture, numbered per the
  existing `test_NN_` convention.