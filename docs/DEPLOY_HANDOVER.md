# Deploy handover — David → Giovanni

**Living document.** Everything the server side needs to know from the
backend, in one place. Supersedes `deploy/HANDOVER.md` (2026-08-10),
`deploy/HANDOVER-2026-08-31-scenario-routing.md` and
`docs/STAGING_DEPLOY_NOTES.md` — all three are folded in here and should be
deleted.

Updated after each change that touches deploy, capacity or server data.
Last update 2026-08-31 (route segment cache precompute runbook, §7a.3).

**If you read one section:** §3 is the deploy currently queued for staging,
§4 is a mandatory cache wipe that comes with it, and §7 is the capacity work
that is genuinely yours to schedule.

| | |
|---|---|
| §1 | What is shipping now |
| §2 | Why your compose files need no edits |
| §3 | Deploy order for this batch |
| §4 | Wipe the routing graph cache — required |
| §5 | Standing gotchas on every staging deploy |
| §6 | How deploy relates to the backend `.env` |
| §7 | **Capacity: routing under batch load** |
| §7a | **Route segment cache — shipped; the full precompute runbook** |
| §8 | When the 2032 graph lands |
| §9 | Older open items |
| §10 | Questions back to you |

---

## 1. What this batch does

Scenarios now pin the **routing graph** they route on, not just their five
`input_params` version snapshots. `scenario.scenarios` gains
`routing_graph_key`; the backend holds one `RailRouter` per configured
graph and picks it per request from that pin. This is the groundwork for
the 2032 upgraded-network scenarios — Jasper's OSM file is not here yet,
so **nothing new runs on the servers**: one routing instance, exactly as
today.

Alongside it, the scenario set was rebuilt. The old "2026 Base Line" /
"2032 Base Line" naming is gone ("2032" named a price year, which became
confusing once the network itself is a scenario axis). Three selectable
scenarios, all on today's network:

| key | |
|---|---|
| `infra-2026` | today's network, no high-speed access — the live base |
| `infra-2026-hsr` | + night trains allowed on high-speed lines |
| `infra-2026-hsr-opt-tt` | + optimised timetables (reduced schedule supplement) |

Plus one superseded revision on the `infra-2026` key
(`is_current_scenario = FALSE`) holding the pre-correction German track
access rates, so evaluations published before that correction stay
reproducible. Not user-selectable.

---

## 2. Why your compose files need no edits

The dev stack moved to per-graph environment variables
(`OPENRAILROUTING_URL_INFRA_2026` and friends). Your `api` services set the
**unsuffixed** `OPENRAILROUTING_URL=http://targetnetwork-routing:8989`, and
that is still honoured — deliberately, as the compatibility path for stacks
that know nothing about graph keys. Resolution order is: the default
graph's suffixed variable, then the unsuffixed one, then localhost
(`models/route/routing/rail_router.py`, `default_base_url()`).

So `bot-server-app/docker-compose.yml` works as-is. If you ever want to be
explicit, rename that one line to `OPENRAILROUTING_URL_INFRA_2026` — same
result, no rush.

**Per §1 of the first handover**, the variables added on the backend side
are absent from your `environment:` blocks. I checked each: none is needed
for a boot or a request path on the servers today. Nothing to backfill.

---

## 3. Staging deploy — order matters

Staging deploys itself: merged PR → branch push → Actions
(`deploy-staging.yml`) → `deploy.sh` → build → **migrations applied before
the api may start** → `migrate.py --check` → health check. So step 1 below
happens on its own. Steps 2–4 do not, and their order is not negotiable.

**Step 0 — wipe the graph cache. Required for this deploy.** See §4; the
profile set changed at `ROUTE_BUILDER_VERSION` 0.9.28 and the routing
container will restart-loop against the old graph. Do this before or
alongside the merge, not after the api starts failing.

**Step 1 — schema (automatic).** `db/migrate.py` applies
`2026-08-29_scenario_routing_graph.sql`: adds `routing_graph_key`,
backfills every existing row to `'infra_2026'`, sets NOT NULL. Existing
scenarios keep working — they all route on today's network.

**Step 2 — scenario data (manual).**

```bash
cd /opt/targetnetwork-staging/deploy/bot-server-app
docker compose run --rm migrate python scripts/migrate_scenarios_2026.py --install --dry-run
docker compose run --rm migrate python scripts/migrate_scenarios_2026.py --install
```

Writes the three new snapshots and scenario rows, moves the base, truncates
the compute cache. Reads `db/dev/seed.py`'s own data structures rather than
hardcoding values into SQL, so the calibration stays single-sourced. New
snapshots are appended above the existing maximum version, so server
version numbers will not match a fresh dev seed — cosmetic, since
`scenario_id` is the handle every consumer uses.

**If you reseed staging instead** (`Reseed staging` workflow), steps 2–4
are unnecessary: `seed.py` produces the new scenario set directly. Given
staging is still reseeded from scratch (§5), that is the simpler path here
— the migration script exists for **production**, which is never reseeded
and carries real volunteer submissions.

**Step 3 — refresh proposals (manual).**

```bash
docker compose run --rm migrate python scripts/refresh_proposals.py
```

Recomputes every published proposal against the new base and repoints its
`scenario_id`.

**Step 4 — delete the old scenarios (manual).**

```bash
docker compose run --rm migrate python scripts/migrate_scenarios_2026.py --delete-old --dry-run
docker compose run --rm migrate python scripts/migrate_scenarios_2026.py --delete-old
```

**Never run step 4 before step 3.** `proposals.proposals.scenario_id` has
**no foreign key**, so deleting a scenario row does not error — it strands
every proposal pinning it, because reads rebuild `input.parameters` through
that pin and resolution raises on a missing row. The script refuses while
any proposal, summary or cache row still references a retired scenario, but
the ordering is the real protection.

**Rollback.** Steps 1–3 are additive; the old scenario rows are still there
and moving the base back is one `UPDATE`. After step 4 there is no
rollback, so leave a soak period between 3 and 4 if you want one.

---

## 4. Wipe the routing graph cache before this deploy — from 0.9.28 on

**Required for this deploy.** On the server the graph cache is a Docker
named volume, not a directory:

```bash
cd /opt/targetnetwork-app/deploy/bot-server      # wherever the shared stack lives
docker compose stop targetnetwork-routing
docker volume rm tn_graphcache                   # entrypoint re-downloads from Drive
docker compose up -d targetnetwork-routing
```

Renaming beats deleting when you can: `docker volume create tn_graphcache_old`
plus a copy, so a failed download leaves you a working graph to move back.
Reload takes ~2 min and **both environments share this container** — staging
and production both lose routing while it reloads. Schedule accordingly.

**Why.** The graph is built per *profile*, and the profile set is baked in at
import time. `ROUTE_BUILDER_VERSION` 0.9.28 changed it: 1520 and 1524 mm
became one gauge family, so `night_train_1524` was removed and
`night_train_1520`'s custom model changed to accept both tags. GraphHopper
compares the config's profile hashes against the graph's at startup and
refuses to run when they differ:

```
java.lang.IllegalStateException: Profiles do not match:
Graphhopper config: night_train|…,night_train_1520|209904841,…
Graph:              night_train|…,night_train_1520|722514490,night_train_1524|…
Change configuration to match the graph or delete /app/graph-cache/
```

The container then restart-loops and the API never comes up, because it
waits on the routing service being healthy.

The cache is **not in git** — a ~213 MB zip on Drive, fetched by
`entrypoint.sh` when the graph-cache directory is empty. The file id does not
change between versions; a new graph is uploaded as a *new version of the
same file*. So the fix is always "delete the local copy and let it
download", never an id change.

**When this stops applying:** never entirely. It applies to any deploy
crossing a change to `config.yml` or `custom_models/` — the only two inputs
to the profile hash. If a release note says the graph was re-imported, wipe
the cache.

**Dev-side note:** the local directories were renamed this batch, so the
equivalent there is `graph-cache-infra-2026/`, not `graph-cache/` (one
directory per routing graph). Server volumes are unchanged.

---

---

## 5. Standing staging gotchas

Merged in from `docs/STAGING_DEPLOY_NOTES.md`, which this document replaces.
These apply to every staging deploy, not just this batch. Each says when it
stops applying.

### The database is fully reseeded, so schema changes need no migration — for now

`db/dev/seed.py` drops and rebuilds `input_params` and `scenario` from
scratch, and staging currently runs that path via the `Reseed staging`
workflow. That is why 0.9.28's `gauge_evidence` CHECK change (adding
`'override'`) shipped without a migration.

**When this stops applying:** the moment staging stops being reseeded — at
the first stable release. From then on every schema change in
`backend/db/schema.py` needs a matching migration, and the stop catalogue
needs a new `stop_infra_version` rather than an in-place edit, because
scenario-pinned versions are immutable (`adapters/proposal/README.md` §4.2).
This entry is the reminder to make that switch deliberately rather than
discovering it.

Note that **production is already past that line** — never reseeded, real
volunteer submissions since the 18-08 test party. That asymmetry is why this
batch ships both a migration and a data-migration script even though staging
would not need either.

### The stop catalogue comes from Drive, not from git

`stop_seed_catalog.csv` is downloaded at seed time. Publishing a catalogue
change means uploading a new *version of the same Drive file*, then
reseeding. A deploy that seems to ignore a catalogue change is usually a
catalogue that was never uploaded.

The seed log states the count it actually loaded:

```
downloaded stop_seed_catalog.csv (1050 stops).
```

Check that number against the release note — the fastest confirmation that
staging is running the catalogue you think it is.

*Two corrections to the note this replaces:* the variable `seed.py` reads is
**`STOP_SEED_FILE_ID`**, not `ONTD_SEED_STOPS_FILE_ID` (that one belongs to
`scripts/export_ontd_stop_seed.py`, a different artifact — the ONTD seed
stops CSV). And the catalogue is written by
**`step10_export_seed_stops.py`**; the pipeline grew past step 7.

### Expected log noise, not errors

```
TrackInfrastructure[BY]: no row in track_infrastructures — using EU-average default for every field.
TrackInfrastructure[RU]: no row in track_infrastructures — using EU-average default for every field.
```

Belarus and Russia are in `input_params.countries` **solely** to hold the
border polygons the routing exclusion is built from (`BLOCKED_COUNTRIES`,
`models/route/model.py`). They deliberately have no track-infrastructure
rows, so that if the routing block ever failed, the country-coverage check
would still reject the route rather than silently price Belarusian
kilometres. The warning is that design working. Do not "fix" it by adding
rows.

```
2 catalog stops skipped — country not modelled (XK 2).
```

Kosovo is not in the country list yet. Two catalogue stops are dropped at
seed time as a result. Known, tracked, harmless.

### New this batch: expected scenario counts

After a reseed, `scenario.scenarios` holds **4** rows — three selectable
plus the superseded revision. `GET /api/scenarios` returns 1 base, 2
current, 1 historical. All four carry `routing_graph_key = 'infra_2026'`.
Anything else means the seed or the migration did not complete.

---

---

## 6. How deploy relates to the backend `.env` (context, no action)

`deploy/bot-server-app/docker-compose.yml` enumerates every variable the
`api` service needs in its own `environment:` block. It does **not** use
`env_file:`, and it does not read `backend/docker/.env`.

That separation is deliberate and I'd keep it: `backend/docker/.env.example`
carries working *dev defaults* (`POSTGRES_PASSWORD=devpassword`,
`AUTH_EMAIL_DEV_MODE`, a Drive graph-cache id), and CI copies it verbatim.
None of that belongs on a server. The rule is now written down in AGENTS.md
("Parameter placement"): one dev-side `.env`; server stacks enumerate their
environment explicitly.

The trade-off is that a variable added on the backend side is silently
absent on staging/production until someone adds it to your `environment:`
block. I checked every one currently unset — none break a boot or a request
path today (they all have code defaults, and the ONTD ones are moot because
of §3 below). So there is nothing to backfill right now. This is just the
mechanism to know about when reviewing future backend PRs.

If you'd rather not track it by hand, the alternative is a small
`deploy/bot-server-app/.env.defaults` committed to git (non-secret
operational values only) listed *before* `.env` in an `env_file:` array
(last file wins), with the secret ones staying in `.env`. Your call — I'm
not proposing it, just noting it exists.

---

## 7. Capacity findings — routing under batch load

Context: proposal computes are becoming batch-shaped (one `/calc` fanning
out to many route requests). `apply_auto_stop_addition()` already does
this. These are the four ceilings, and what I would do about each. All
yours to schedule — none blocks this deploy.

**Correction first.** I previously told David two graphs would be a RAM
problem. The startup log says otherwise: `edges: 2,976,018 (117MB), nodes:
2,653,477 (41MB), geo (69MB), name (10MB)` — about **240 MB resident per
graph**. The 5–10 GB figure is the on-disk cache, not the heap. Two
instances are cheap in memory. The contention is CPU.

**(a) Gunicorn workers — the binding limit.** `--workers 2` on the servers,
sync. One `/calc` holds one worker for its entire batch, so concurrent
users cap at 2 regardless of how well the batch parallelises internally.
The proper fix is WP14 (per-request DB connections from a pool) followed by
`--threads`, because a calc is I/O-bound waiting on GraphHopper, not
CPU-bound in Python. WP14 is currently marked "not gating anything" —
that stops being true once batch calcs are normal. Until then, the VPS
upsize makes `--workers 4` viable. **Watch out:** `api/limiter.py` stores
rate-limit state per process, so the effective ceiling is (limit ×
workers). Going 2 → 4 silently doubles every rate limit. Either move the
limiter to shared storage or re-tune the numbers.

**(b) The 120s gunicorn timeout** caps batch size hard (per-route timeout
is 30s, but the whole calc must finish inside 120s or the worker is
killed). My recommendation is an explicit maximum batch size with a clean
422 past it, rather than raising the timeout — a long-held sync worker is
exactly problem (a). Asynchronous jobs only if real batches genuinely
exceed a sane cap.

**(c) Two-pass routing doubles the call count.** `fullRouting` does a
snap pass then a custom-model pass, so N trips is 2N HTTP calls. The snap
pass is cacheable and shouldn't exist at request time at all: snapping
depends only on `(coordinates, gauge profile, graph)`, so it is
**per-stop, not per-trip**. Precomputing it once per stop per profile per
graph removes half the traffic outright. That is the cheapest large win
available and needs no API change.

**(d) CPU contention.** `config.yml` sets no `maxThreads`/`minThreads`, so
GraphHopper runs on Dropwizard's Jetty defaults — up to 1024 threads
against a CPU-bound workload, which thrashes under burst rather than
queueing. Worth setting an explicit thread ceiling near core count, and an
explicit `-Xmx` per instance before a second one ever runs.

**The gap behind all of it** was the missing per-segment route cache —
closed in §7a below (`ROUTE_BUILDER_VERSION` deliberately not in the key:
cached rows are raw physics, everything the version governs is applied
after). Remaining sequence: batch cap → WP14.

---

## 7a. Route segment cache — shipped; the full precompute is yours to run

Resolves the gap §7 names: routing is now served per stop pair from
`route_cache.route_segments` and only misses hit GraphHopper. Every
live-routed pair is stored back, so the table fills itself from traffic;
the precompute front-loads it so first users never pay a routing call.
Keyed per graph: `(routing_graph_key, stop_lo, stop_hi, variant_key)` —
each graph has its own snapped points and HSR resolution, nothing is
shared. This also delivers §7(c): the runtime snap pass only happens on a
miss.

**Stops applying:** never for the cache itself. The precompute runbook
(§7a.3) stops applying per graph once its batch has run against that
graph's final import — until the next re-import.

### 7a.1 Deploy (this batch)

1. Migration `2026-08-31_route_segment_cache.sql` is picked up by
   `db/migrate.py` like any other — lands the schema, no data.
2. No `.env` change required. `ROUTE_SEGMENT_CACHE_ENABLED` defaults to
   true; set it `false` only to diagnose (the API then routes live, as
   before). Nothing to add to the `environment:` block (§6) for the
   default graph.
3. Start the API and check the log for one line per graph:
   `Route segment cache [infra_2026]: 0 segment(s), graph import 2026-…`.
   From there, every `/calc` logs
   `segment cache [infra_2026]: N/M pair(s) served, K routed+stored`.

### 7a.2 Invalidation is automatic — but read this

`route_cache.graph_state` remembers the GraphHopper `import_date` each
graph's rows were routed against. At API start the live `/info` is
compared; on a change that graph's rows are **purged** and the log warns
`graph import changed … purged N cached segment(s)`. So: a graph
re-import (§4 wipes, Jasper's 2032 file, any profile change) empties that
graph's cache on the next API start, and the cache refills. Nothing to do
by hand — but expect the first hours after a re-import to route live, and
re-run the precompute afterwards. **This is a recurring cost per graph,
not one-off** — it belongs in the Sep 1st capacity estimate as such.

Rule of thumb for sequencing: **graph first, precompute last.** Never start
a batch while a re-import is still possible for that graph — the batch is
simply deleted on the next API start.

### 7a.3 Precompute runbook — the full collection

**What it does.** Routes every stop pair under a haversine cap, once per
routing variant, pass-2-only (each stop is snapped once per gauge profile
up front — half the calls of a runtime miss), writes a CSV, bulk-loads it.
Four phases, each independently runnable and resumable.

**Where it runs.** Through the `migrate` service, like
`refresh_proposals.py` — same network as `openrailrouting`, same database
credentials, no host Python needed. The default graph resolves through the
unsuffixed `OPENRAILROUTING_URL` the stack already sets. Two things the
`run --rm` container does not give you on its own:

- **Persistence.** The CSV must land on the host, or an interrupted run
  cannot resume and a finished one is lost when the container exits.
  Bind-mount a host directory and point `--out` into it. Everything the
  script writes (`.csv`, `.snapped.csv`, `.failures.csv`, `.csv.gz`,
  `.meta.json`) sits next to `--out`.
- **Survival.** A 15–30 h job must outlive your SSH session: run it
  detached and follow the container log.

```bash
cd /opt/targetnetwork-staging/deploy/bot-server-app
mkdir -p /opt/targetnetwork-staging/route-cache
export RC=/opt/targetnetwork-staging/route-cache
export OUT=/route-cache/route_segments_infra_2026.csv   # container-side path

# Phase 0 — measure (minutes). Do this first, every time.
docker compose run --rm -v $RC:/route-cache migrate \
  python scripts/precompute_route_segments.py --graph infra_2026 --measure-only

# Phase 0b — dry run of the whole pipeline (minutes): 50 pairs, then load them.
docker compose run --rm -v $RC:/route-cache migrate \
  python scripts/precompute_route_segments.py --graph infra_2026 --out $OUT --cap-km 300 --limit 50
docker compose run --rm -v $RC:/route-cache migrate \
  python scripts/precompute_route_segments.py --graph infra_2026 --out $OUT --finalize
docker compose run --rm -v $RC:/route-cache migrate \
  python scripts/precompute_route_segments.py --graph infra_2026 --out $OUT --load
rm $RC/route_segments_infra_2026.*        # start the real run clean

# Phase 1 — the batch (hours). Detached; the container keeps running after logout.
docker compose run -d --name precompute-infra-2026 -v $RC:/route-cache migrate \
  python scripts/precompute_route_segments.py --graph infra_2026 --out $OUT --cap-km 800 --workers 4
docker logs -f precompute-infra-2026            # progress every 500 segments: rate, ETA, failures

# Phase 2 — finalize (minutes): completeness check, gzip, meta.json
docker compose run --rm -v $RC:/route-cache migrate \
  python scripts/precompute_route_segments.py --graph infra_2026 --out $OUT --cap-km 800 --finalize

# Phase 3 — load (minutes): COPY into route_cache, ON CONFLICT DO NOTHING
docker compose run --rm -v $RC:/route-cache migrate \
  python scripts/precompute_route_segments.py --graph infra_2026 --out $OUT --load
docker rm precompute-infra-2026
```

**Reading `--measure-only`.** It prints four things; the batch decisions
come from them, not from the estimates in the meeting summary:

- *Pair counts per cap* (300 / 500 / 800 / uncapped) from the live
  catalog — the real numbers.
- *Custom-model variants* for this graph: expect **3** for `infra_2026`
  (the six REF compositions collapse to one 200 km/h model that always
  avoids HSR; the two NEW compositions give a 230 km/h model that avoids
  HSR under scenario 1 and one that does not under 2/3). More than 3 means
  a scenario carries mixed per-country `hsr_allowed` — stop and tell me
  before running. Broad-gauge pairs add one profile each on top; standard-
  gauge pairs add nothing.
- *Latency probe*: ~20 real calls, single-threaded, average ms/call.
- *Worker-hours per cap* extrapolated from that:
  `hours = pairs × variants × latency / workers / 3600`. Treat the
  extrapolation as an upper bound on scaling: one container does not scale
  linearly with workers (§7(d)). Confirm with the Phase 0b dry run's
  reported rate at your real `--workers` before believing the hours.

Order of magnitude if the probe lands near 300 ms and the container gives
you ~4 effective workers: 800 km ≈ 250k pairs × 3 ≈ 750k segments ≈ 16 h;
uncapped ≈ 500k pairs × 3 ≈ 1.5M segments ≈ 31 h. Both to be replaced by
the measured figures.

**Choosing the cap.** The cap trades batch hours against first-user
latency on long pairs — never correctness: a pair beyond the cap routes
live once and is stored like any other. Consecutive night-train stops are
mostly 100–400 km apart, but non-stop legs exist (Berlin–Paris is ~880 km
as the crow flies), so 800 km is the floor I'd accept; 1 000–1 200 km or
uncapped if the measured hours allow. Whatever you pick, pass the same
`--cap-km` to `--finalize` so `meta.json` records it.

**Workers and timing.** `--workers 4` is the safe start. The routing
container is shared with live users for the whole batch, and it is
CPU-bound — run overnight, and watch `/calc` latency on staging while it
runs. If you want the batch off the live instance entirely, a second
`openrailrouting` container on the *same* graph-cache directory
(read-only bind) plus `OPENRAILROUTING_URL_INFRA_2026=http://<that
container>:8989` in the `migrate` service's `environment:` block isolates
it completely — the graph key stays `infra_2026`, so the rows are the same
rows. Optional; the shared-instance path works, it is just slower for
everyone during the run.

**Interruptions.** Rerun the exact Phase 1 command (`docker rm` the old
container first). Already-routed keys are read from the CSV and skipped;
snapped coordinates come from `.snapped.csv`. Per-pair failures never stop
the batch — they go to `route_segments_infra_2026.failures.csv` with the
GraphHopper message. Expect a few hundred: unconnected islands, stops with
defective coordinates (the ten gauge-NULL stops are the usual suspects),
`PointNotFound` for stops far from any track. A failed pair is simply
absent from the cache and, if a user ever requests it, fails live with the
same 422 it fails with today. Anything systematic — thousands of failures,
or all failures sharing one stop id — send me the file.

**Verifying the load.** Before/after counts are printed by `--load`;
independently:

```sql
SELECT routing_graph_key, source, COUNT(*) FROM route_cache.route_segments
GROUP BY 1, 2;                                   -- precompute vs runtime rows per graph
SELECT * FROM route_cache.graph_state;           -- import_date the rows are valid for
```

No API restart is needed — lookups query the table live. The startup line
is just where the count is logged.

**Keep the artefacts.** `route_segments_infra_2026.csv.gz` + `.meta.json`
are the fast way back after any `route_cache` wipe (a reseed, a volume
loss) — `--load` again, minutes instead of hours. They are valid only for
the `import_date` in `meta.json`; `--load` checks that against the live
graph and refuses stale data by purging first. Expect roughly 1–2 GB
uncompressed for a full run, a few hundred MB gzipped. Upload the pair to
Drive as well: `ROUTE_SEGMENTS_FILE_ID_INFRA_2026` lets a dev reseed pull
it, which is how the rest of us get a warm cache locally.

**The 2032 graph.** Identical runbook with `--graph infra_2032`, once that
instance runs (§8) and `OPENRAILROUTING_URL_INFRA_2032` is in the
`migrate` service's `environment:` block — the script refuses a graph it
has no URL for rather than routing on the wrong one. Scenarios 5–7 pin it,
so the variant enumeration finds the same three models on its own. A
second full run, a second set of artefacts, a second recurring cost.

**When to rerun.** Whenever the API logs
`graph import changed … purged` for a graph, or `graph_state.import_date`
no longer matches that instance's `/info`. Until the rerun the cache
refills from traffic on its own, so nothing is broken — just slower.

**Troubleshooting.**

| Symptom | Cause / fix |
|---|---|
| `No URL configured for graph 'infra_2032'` | Add `OPENRAILROUTING_URL_INFRA_2032` to the `migrate` service environment |
| `Missing required environment variable(s) for DB connection` | The `migrate` service lacks a `POSTGRES_*` variable the api has |
| Rate far below the probe, ETA growing | Container CPU-bound — lower `--workers`, or the isolation setup above |
| `snap failed for <stop>` lines | Stop far from track / bad coordinates — its pairs are skipped, listed as unsnappable in the predict line |
| `MISMATCH, investigate` at the end | Routed+failed ≠ predicted — the run was cut short; rerun Phase 1 |
| `--load` prints `graph import changed` | The graph was re-imported after the batch — the file is stale; rerun |

### 7a.4 Capacity note

With the cache serving, a `/calc` is Postgres lookups + evaluation instead
of GraphHopper waits — §7(a)'s worker/thread reasoning shifts accordingly;
GraphHopper CPU (§7(d)) now matters mostly during a precompute batch, which
is also when a second instance would earn its keep.

---

## 8. When the 2032 graph lands

Not now, but so it's on your radar — a second graph is a compose service,
three environment variables, and scenario rows. No code.

- Service `openrailrouting-infra-2032` exists in the dev compose behind
  profile `infra-2032`, off by default. Server equivalent is yours to add.
- Own graph cache (separate Drive file, own id), own host directories,
  ports 8991/8992 in dev.
- **Precompute cost multiplies per graph** — every route/segment batch you
  run today runs once per graph. This is the main reason (c) and the
  segment cache matter before rather than after.
- A scenario pinning a graph with no configured URL fails loudly
  (`RoutingGraphNotConfiguredError`). Never a silent fallback to the wrong
  network — that would return plausible routes computed on the wrong
  infrastructure, which is the worst failure mode available to us.

---

## 9. Older open items

Carried from the 2026-08-10 handover. Still open, still yours to action or
discard.

### 9.1 `LOCAL_HTTP_PORT` missing from `.env.example`

`docker-compose.local.yml` reads `${LOCAL_HTTP_PORT:-8090}` for the local
Caddy's published port, but `deploy/bot-server-app/.env.example` does not
list it. Harmless — the default works — but someone whose 8090 is taken has
no way to discover the variable except by reading the compose file. A
commented line in the example would fix it.

### 9.2 ONTD reference data never loads on staging/production

`backend/docker/entrypoint.sh` runs `seed.py`, then `db/ontd/bootstrap.py`
in the background, then gunicorn. Your `api` service overrides it with an
explicit `command: [gunicorn, ...]` — correctly, since that entrypoint's
`seed.py` starts with `DROP SCHEMA … CASCADE` and must never run on a
long-lived database.

The side effect is that `bootstrap.py` does not run either, so
`ontd.route_summaries` stays empty and the gallery shows proposals only, with
no existing-night-train context.

If intentional, ignore. If the servers should show existing routes it needs
its own one-shot invocation (same shape as `migrate`), plus
`ONTD_WORKBOOK_ID` / `ONTD_COMPOSITIONS_ID` in the `environment:` block. The
routing engine must be reachable, and it re-routes ~205 routes, so it is not
a per-deploy step — more a manual `docker compose run --rm` after a schema
reset. CI does exactly that shape: `bootstrap.py --force --strict`.

**New reason this matters:** the schedule-supplement re-calibration
(`backend/models/scenarios/README.md`) reads `ontd.route_legs`. Until the
servers carry ONTD data, that calibration can only be run from a developer
machine.

### 9.3 Two legacy deploy directories

`deploy/bot-server/` and `deploy/bot-server-demo/` both predate
`bot-server-app` and, as far as I can tell, neither boots against current
`staging`: stale build-context paths in the former, no `JWT_SECRET` in
either (`check_auth_config()` raises at boot), and a schema description in
the demo README that predates the `scenario` schema entirely.

My read is these should be deleted rather than repaired. Your call — if
either is still serving something on the box, say so and I will leave them
documented.

*Note:* `deploy/bot-server/` is still where the shared
`targetnetwork-routing` container is defined, so check what actually runs
before deleting that one.

---

## 10. Questions back to you

1. VPS sizing after the upsize — how many cores, and are you comfortable
   with `--workers 4` plus the rate-limit doubling described in §7?
2. For staging: reseed (simpler, wipes accounts/proposals/likes/comments)
   or run the migration path (preserves them, more steps)? The reseed
   workflow already preserves the testing-gate access codes. I have no
   preference; production has no choice and takes the migration path.
3. Do you want a soak period between step 3 and step 4 of §3?
4. §9.2 — should the servers load ONTD reference data at all?
5. §9.3 — delete the two legacy deploy directories?

---

## Maintaining this document

One file, updated in the same PR as the change it describes. The rule that
keeps it useful: **every entry says when it stops applying.** A gotcha with
no expiry becomes folklore nobody dares remove.

When a section stops applying, delete it rather than marking it done — git
history is the archive. When a new capacity finding lands, it goes in §7
next to the others so the picture stays whole rather than scattered across
dated files.
