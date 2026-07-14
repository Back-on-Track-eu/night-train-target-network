# Stop Classification Pipeline — Design & Handoff Notes

Status: **design draft, not implemented**
Location (planned): `backend/models/infrastructure/stop_classification/`
Owner: TBD (implementation handed off)

---

## 1. Purpose

The raw OSM extract contains *all* railway stations (e.g. ~5,700 for Germany alone),
while only a small subset are plausible night train stops. This pipeline classifies
every OSM railway stop against a set of qualification signals and produces a single
CSV that marks, per stop, whether it qualifies and **which signal(s)** qualified or
rejected it.

Design goals:

- **Non-destructive:** every input stop appears in the output. Filtering happens at
  import time based on the classification columns, never by dropping rows here.
- **Auditable:** each stop carries the full list of signals it matched, so
  "why is station X (not) in the catalog?" is answerable from the CSV alone.
- **Recall-biased:** a false negative (missing candidate) is expensive — the stop can
  never be routed to, suggested by `auto_stop_addition="suggest"`, or picked manually.
  A false positive merely sits unused in the catalog. Borderline stops stay **in**.
- **Country-extensible:** signals differ per country; new countries are onboarded by
  adding an adapter, not by touching the core.

## 2. Scope / non-goals

In scope:
- Classification of OSM railway stops into qualified / not-qualified with provenance.
- Per-country signal adapters with a defined fallback chain.
- Manual include/exclude overrides.

Explicitly out of scope (for now):
- Platform length / technical suitability checks (OSM platform data too patchy;
  tracked as future TODO, see §9).
- Writing into the versioned stop catalog. The CSV is the *input* to the existing
  seed/import path; import stays a separate, versioned step.
- Demand estimation. Qualification is about infrastructure plausibility, not ridership.

## 3. Pipeline overview

```
OSM extract (downloaded, untracked)
        │
        ▼
[0] Parse & normalize stops ──────────────► base row per stop
        │
        ▼
[1] Tier 1: current night train whitelist ─► signal: current_night_train
        │
        ▼
[2] Tier 2: GTFS long-distance presence ───► signal: gtfs_long_distance:<feed>
        │        (per-country adapter)
        ▼
[3] Tier 3: importance signals ────────────► signal: station_category:<country>
        │        (per-country enrichment,             population:<threshold>
        │         population fallback)
        ▼
[4] Manual overrides (include/exclude) ────► signal: manual_include / manual_exclude
        │
        ▼
[5] Resolve qualification + tier ──────────► qualified, candidate_tier
        │
        ▼
classified_stops.csv (one row per input stop, nothing dropped)
```

Qualification rule: `qualified = (any positive signal matched) AND (no manual_exclude)`.
Signals are independent; a stop can match several. `manual_exclude` always wins,
`manual_include` qualifies unconditionally otherwise.

## 4. Input

1. **OSM railway stops** — the downloaded OSM data (Geofabrik extracts), **untracked**,
   same treatment as `models/compositions/calib/data/`. Expected under
   `backend/models/infrastructure/stop_classification/data/` (gitignored).
2. **Current night train stop list** — the existing list of all current night trains
   with stops (Tier 1 whitelist source). Format/location to confirm with David.
3. **GTFS feeds** — one per onboarded country (Germany: DELFI). Downloaded, untracked.
4. **Override file** — `stop_overrides.csv`, **tracked in git** (it is curated content,
   not bulk data). Columns: `stop_ref`, `action` (`include`/`exclude`), `reason`.
   Reasons are mandatory — this file doubles as the stakeholder-facing answer to
   "why is X (not) included?".
5. **Optional country enrichment data** — e.g. DB Preisklassen list for DE,
   GeoNames/Wikidata population data for the fallback. Untracked.

## 5. Pipeline stages in detail

### Stage 0 — Parse & normalize

- Extract railway stops from the OSM data (`railway=station` / `railway=halt`;
  exact tag set to be decided during implementation — document the choice in the
  script header and this file).
- Normalize into one row per stop: OSM id, name, country (ISO-2), lat/lon, raw
  OSM tags of interest (kept as a JSON column for debugging).
- **Matching key problem (the hard part of the whole pipeline):** Tier 1/2 sources
  identify stations by name or national IDs (IBNR/UIC, GTFS `stop_id`), not OSM ids.
  Matching strategy, in order of preference:
  1. UIC/IBNR reference tags on the OSM object where present (`uic_ref`, `railway:ref`).
  2. Name match + distance threshold (suggest ≤ 1 km) as fallback.
  - Log every fallback match with its distance so ambiguous matches can be reviewed.
  - Unmatched external stops (e.g. a night train stop we cannot find in OSM) must be
    written to a separate `unmatched_report.csv` — silently dropping them would create
    exactly the false negatives we are trying to avoid.

### Stage 1 — Current night train whitelist (Tier 1)

- Match stops against the current night train stop list.
- Signal on match: `current_night_train`.
- Highest-precision signal; proven night-train infrastructure. Floor, not ceiling.

### Stage 2 — GTFS long-distance presence (Tier 2)

- Per-country adapter interface (conceptually):
  - `applicable(country) -> bool`
  - `qualify(stops) -> {stop: [signals]}`
- For GTFS-based adapters: filter feed to `route_type = 2` (rail), then apply a
  **per-country long-distance classifier** (agency / route short-name patterns —
  e.g. for DE: ICE/IC/EC/NJ/FLX prefixes) since "long distance" is not uniformly
  encoded across feeds. The pattern list lives in the adapter and must be documented
  per country.
- Signal on match: `gtfs_long_distance:<feed_name>` (e.g. `gtfs_long_distance:DELFI`).
- First country: **Germany (DELFI)** as proof of the adapter pattern; then extend to
  countries with the noisiest OSM stop sets.

### Stage 3 — Importance signals (Tier 3)

- **Per-country enrichment where a good national signal exists:**
  - DE: DB station category (Preisklasse); suggested inclusion threshold: classes 1–3,
    class 4 to be reviewed against Tier 2 overlap before deciding.
  - Signal: `station_category:DE:<class>`.
- **Portable fallback for countries without adapter or usable feed:** nearest-city
  population (GeoNames or Wikidata) above a threshold (initial suggestion: 100k;
  tune after inspecting output sizes).
  - Signal: `population:<threshold>`.
- Fallback chain per country: GTFS adapter → national category signal → population.
  A country with nothing onboarded still gets Tier 1 + population, so no country
  ends up completely empty.

### Stage 4 — Manual overrides

- Apply `stop_overrides.csv`.
- `include` → signal `manual_include` (qualifies unconditionally).
- `exclude` → signal `manual_exclude` (rejects unconditionally, overriding all
  positive signals).
- Primary use cases: tourism-driven stops that fail every automatic filter
  (ski resorts, coastal destinations — classic night train stops precisely because
  they are small), and quick response to stakeholder "why is X missing?" questions
  without a pipeline change.

### Stage 5 — Resolution

- `qualified` per the rule in §3.
- `candidate_tier` = lowest tier number among matched positive signals
  (1 = current night train, 2 = GTFS long distance, 3 = category/population,
  4 = manual include only). Purely informational for downstream consumers.

## 6. Output

`classified_stops.csv` — one row per input OSM stop, no rows dropped.

| Column | Type | Description |
|---|---|---|
| `osm_id` | str | OSM object id (with type prefix, e.g. `n123456`) |
| `name` | str | Station name from OSM |
| `country` | str | ISO-2 country code |
| `lat`, `lon` | float | Coordinates from OSM |
| `uic_ref` | str? | UIC/IBNR ref if present in OSM tags |
| `qualified` | bool | Final in/out decision |
| `candidate_tier` | int? | 1–4 as per §5; empty if not qualified |
| `signals` | str | Semicolon-separated signal list, e.g. `current_night_train;gtfs_long_distance:DELFI` |
| `signals_negative` | str | e.g. `manual_exclude` |
| `match_notes` | str | Fallback-match distances / ambiguity flags from Stage 0 |

Secondary output: `unmatched_report.csv` (external source entries with no OSM match).

Both outputs go to `backend/models/infrastructure/stop_classification/data/` and are
gitignored (consistent with `backend/scripts/data/*_output.json` convention).

## 7. Integration with the versioned stop catalog

- The CSV is consumed by the existing stop import/seed path; only `qualified = true`
  rows are imported.
- Recommendation: carry `candidate_tier` and `signals` (as `qualification_sources`)
  into the stop table so provenance survives into the catalog. This means a **new
  infrastructure table version** and scenario re-pinning — needs David's sign-off
  (open decision, see §8).
- Because stop tables are full-snapshot versioned, a stricter vs. looser filter is
  simply two catalog versions that scenarios can pin — an expanded stop set can be
  A/B-compared as a scenario.
- Side benefits: shrinks the `auto_stop_addition` candidate search (fewer
  per-candidate mini-reroutes) and reduces exposure to the known coordinate-quality
  issues in the raw source data.

## 8. Open decisions (confirm before/at implementation start)

1. **Stop table schema extension** (`candidate_tier`, `qualification_sources`):
   approved? Implies new table version + re-pinning.
2. **Target catalog size sanity check:** for Germany, ~300–500 qualified stops is the
   expected order of magnitude. If the pipeline lands far outside this, revisit
   thresholds before importing.
3. **Format/location of the current night train stop list** (Tier 1 input).
4. **GTFS feed sourcing per country** — reuse anything from the demand-modelling
   research where possible; otherwise sourcing is part of onboarding each country.
5. **DE Preisklasse 4:** include or not — decide after checking overlap with Tier 2.

## 9. Deferred / future work

- **Platform length constraint** from OSM platform geometries (night trains are long;
  data too patchy today) — add to `OPEN_TODOS` in `version.py` when implementation
  starts, e.g. `OPEN_TODOS["stop_classification_platform_length"]`.
- Additional country adapters beyond DE.
- Periodic re-runs when OSM / GTFS sources update; consider recording source data
  timestamps in the CSV header or a sidecar metadata file.

## 10. Implementation conventions (project standard, for the implementer)

- Standalone script(s) under `backend/models/infrastructure/stop_classification/`;
  runnable independently of the API (like `db/dev/seed.py`, avoid hard imports where
  a cross-reference comment suffices).
- Python 3.12, Black formatting, meaningful comments only — longer explanations go
  into this README, not block comments.
- Reuse existing helpers/patterns before writing new ones (check `api/helpers/` and
  existing infrastructure modules first).
- Bulk input data untracked; curated `stop_overrides.csv` tracked.
- Tests: integration-style against a small real OSM extract fixture, numbered per
  the existing `test_NN_` layer convention.
