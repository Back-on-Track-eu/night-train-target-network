# Route-cache precompute on a laptop — overnight run, manual upload

*2026-09-21 · audience: whoever runs the batch (David) and whoever has
pgAdmin on the target server (David, Giovanni)*

The normal path for `route_cache` is §7a of `DEPLOY_HANDOVER.md`: run
`scripts/precompute_route_segments.py` on the server, through the
`migrate` service, and let `--load` write straight into Postgres. This
runbook is the other path — **route on a laptop over one or several
nights, then upload the CSV by hand with pgAdmin**, which is what you
want when the machine with spare CPU at night is not the machine with
database access.

Everything below uses the same script and produces the same rows. The
only differences are the phases at the end (`--export-upload` instead of
`--load`) and the fact that a laptop closes, sleeps and loses Wi-Fi —
which is what `--stop-after-h`, the resume logic and the retry rounds are
there for.

---

## 0. Before the first night

| Check | Command / where |
|---|---|
| Stack up | `cd backend\docker; docker compose up -d postgres openrailrouting-infra-2026` |
| Catalog seeded | `docker compose logs postgres \| Select-String "seed"` — the stop catalog the batch pairs comes from the local DB |
| Dependencies | `cd backend; uv sync --extra dev` |
| Disk | Geometry costs ~160 bytes per routed km (measured 2026-09-21), so at `--cap-km 300` the CSV is several GB and the `.gz` roughly a third of that; the upload parts are another full copy. Leave 3× the expected CSV free |
| Sleep off | `powercfg /change standby-timeout-ac 0` and `powercfg /change hibernate-timeout-ac 0` — a sleeping laptop pauses the batch, it does not corrupt it, but you lose the night. Restore your old values afterwards |

**The one check that actually matters** is that your graph is the server's
graph. A cached row is only valid for the GraphHopper import it was routed
against:

```powershell
# Laptop
(Invoke-RestMethod "http://localhost:8989/info").import_date
```

```sql
-- Server, in pgAdmin
SELECT * FROM route_cache.graph_state;
```

If the two differ, the rows you produce do not belong on that server —
re-import the same graph cache locally first. The merge SQL the script
generates refuses the load in that case rather than seeding routes for the
wrong network, but finding out before the night rather than after is
cheaper.

---

## 1. Measure (minutes)

```powershell
cd C:\Users\david\PycharmProjects\night-train-target-network\backend
uv run python scripts/precompute_route_segments.py --graph infra_2026 --measure-only
```

Prints pair counts per distance cap, the custom-model variants for this
graph (expect **3** — more means a scenario carries mixed per-country
`hsr_allowed`, stop and check), a latency probe, and the resulting
worker-hours per cap. Pick `--cap-km` and `--workers` from that table, not
from an estimate. On a laptop `--workers 4` is a sane start: the routing
container is CPU-bound and the JVM has 3 GB.

---

## 2. The overnight batch

```powershell
uv run python scripts/precompute_route_segments.py `
  --graph infra_2026 --cap-km 800 --workers 4 --stop-after-h 9
```

- The stops are snapped first — one call per stop per gauge profile,
  cached in `route_segments_infra_2026.snapped.csv`, so later nights skip
  this.
- `--stop-after-h 9` ends the run cleanly in the morning. Leave it off to
  run until finished.
- Progress is one line, refreshed in place:

```
  routing  [########................]  34.2%  256,400/750,000   12.7/s  elapsed 5h 36m  ETA 10h 47m (finish ~Tue 07:31)  482 failed
```

  Piped into a file (`| Tee-Object run.log`) it becomes one timestamped
  line every five minutes instead, so the log stays readable.
- Ctrl-C stops cleanly: in-flight calls finish, the file is flushed, and
  the summary tells you to rerun.

Output files, all next to `--out` (default `backend/scripts/data/`):

| File | What it is |
|---|---|
| `route_segments_infra_2026.csv` | the routed segments — the artefact |
| `…​.snapped.csv` | snapped stop coordinates, reused by every rerun |
| `…​.failures.csv` | what is still missing and why, rewritten at the end of every run |

---

## 3. Resuming

Rerun the exact same command. The script

- truncates a half-written final row (the normal shape of a killed run) —
  no repair by hand, ever;
- reads the keys already in the CSV and skips them;
- reuses the snapped coordinates;
- prints `… already done, … to route now` before starting.

If you already have segments elsewhere — an earlier run under a different
name, the `.csv.gz` from a previous graph batch, or a CSV exported from
the server's table — hand them over and they count as done without being
re-exported:

```powershell
uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 `
  --resume-from D:\backups\route_segments_infra_2026.csv.gz
```

`--resume-from` also takes a directory (every `route_segments*.csv[.gz]`
in it) and several paths at once. Those rows are **not** copied into
`--out`: what the server already has stays off the upload.

Exporting the server's rows for exactly that purpose, in pgAdmin's Query
Tool:

```sql
COPY (SELECT stop_lo, stop_hi, variant_key, distance_m, country_distance_m,
             country_driving_ms, countries, passages, geometry
      FROM route_cache.route_segments
      WHERE routing_graph_key = 'infra_2026')
TO STDOUT WITH (FORMAT csv, HEADER true);
```

---

## 4. Failures

A pair that fails never stops the batch. Failures are split into

- **transient** — timeout, HTTP 5xx, dropped connection: the container
  under load, worth another attempt;
- **permanent** — no route between the points, point off the network:
  usually a stop with defective coordinates (the ten gauge-NULL stops are
  the usual suspects).

After the main pass the script runs `--retry-rounds` (default 2) more
passes over the transient ones, 60 s apart. What is still missing at the
end lands in `route_segments_infra_2026.failures.csv`:

```
stop_lo,stop_hi,profile,variant_key,attempts,transient,error_type,error_message,last_attempt_utc
```

The file is rewritten from scratch on every run, so it always answers
"what is missing now", never "what raised last week". Unsnappable pairs
are in it too, as `NotSnapped`, with the stop that could not be snapped
and GraphHopper's reason in `error_message`.

**Snapping.** Each stop is snapped once per gauge profile by routing it to
a helper stop. Helpers are the nearest catalog stops that carry that
gauge (up to eight are tried), so a stop whose nearest neighbour sits
across a gauge break or on a cut-off branch still snaps. A stop is only
reported unsnappable when GraphHopper cannot place the stop itself
(`Cannot find point 0`) or every helper fails.

**What the first 300 km run showed (2026-09-21)** — all 204 routing
failures were legitimate: 45 Finland–Estonia pairs (no rail link across
the Gulf, and the land route runs through Russia) and 23 pairs between
occupied and Ukrainian-controlled Donbas / Azov stops (no through
connection in the graph). Neither is worth retrying.

To work only on that list later — e.g. after restarting the routing
container:

```powershell
uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 `
  --retry-failures-only --retry-all
```

`--retry-all` includes the permanent ones. A few hundred permanent
failures on a full run is normal; a pair that is absent from the cache
simply routes live once, exactly as today. Anything systematic —
thousands, or all of them sharing one stop id — is worth a look before
uploading.

---

## 5. Finalize

```powershell
uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --finalize
```

Writes `route_segments_infra_2026.csv.gz` and `…​.meta.json` (graph,
import date, cap, stop count, segment count, remaining failures). One
sequential read of the CSV, counting and compressing together, with a
progress line in MB — a few minutes per 10 GB. **Not needed for the
pgAdmin path**: `--export-upload` works from the CSV directly, so finalize
can run afterwards, or later, while the upload is under way. Keep
both: they are the fast way back after any `route_cache` wipe, and the
`.gz` + `.meta.json` pair is also what `db/dev/seed.py` picks up from
`backend/db/dev/data/` on a dev reseed — and what to upload to Drive as
`ROUTE_SEGMENTS_FILE_ID_INFRA_2026` so the rest of the team gets a warm
cache locally.

---

## 6. The upload kit

```powershell
uv run python scripts/precompute_route_segments.py --graph infra_2026 --export-upload --split-mb 250
```

Creates `backend/scripts/data/upload_infra_2026/`:

| File | Purpose |
|---|---|
| `route_segments_infra_2026_partNN.csv` | the data, in ≤250 MB pieces (leave `--split-mb` off for one file) |
| `01_create_staging.sql` | the staging table, typed from `db/schema.py` |
| `02_merge.sql` | import guard + merge into `route_cache.route_segments` |
| `03_drop_staging.sql` | cleanup |
| `README.md` | the same steps, next to the files |

Splitting is worth it: a pgAdmin import that drops halfway then costs one
part, not the whole upload.

**Why staging rather than importing into the table directly.** The CSV
deliberately carries neither `routing_graph_key` nor `source` — one file
is one graph, named at load time — and a direct import would abort on the
first pair the server has already routed live. The merge adds both columns
and uses `ON CONFLICT DO NOTHING`, which makes the load idempotent and
safe to repeat.

---

## 7. pgAdmin steps on the server

1. **Query Tool** on the target database → run `01_create_staging.sql`.
2. **Browser → route_cache → Tables → `route_segments_staging` →
   right-click → Import/Export Data…**
   - Import, Filename: the part file
   - Format `csv`, Header `Yes`, Delimiter `,`, Quote `"`, Encoding `UTF8`
3. **Query Tool** → run `02_merge.sql`. It aborts if the server's graph
   import differs from the file's, merges, empties staging and prints the
   row counts per graph and source.
4. Repeat 2–3 per part (staging stays small), or import every part first
   and run `02_merge.sql` once — the result is identical.
5. Run `03_drop_staging.sql`.

No API restart is needed; lookups read the table live.

**Verification**

```sql
SELECT routing_graph_key, source, COUNT(*) FROM route_cache.route_segments
GROUP BY 1, 2 ORDER BY 1, 2;
SELECT * FROM route_cache.graph_state;
```

`source = 'precompute'` counts what you uploaded, `'runtime'` what traffic
routed. The `graph_state` row must match that instance's `/info`
`import_date` — if it does not, the API purges the graph's rows at its
next start and the upload was for nothing.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No URL configured for graph 'infra_2032'` | Set `OPENRAILROUTING_URL_INFRA_2032` (and its host port) in `backend/docker/.env` |
| `Missing required environment variable(s) for DB connection` | Run from `backend/`, with `docker/.env` present — `dev_env.py` reads it |
| `password authentication failed for user …` | The credentials in `backend/docker/.env` are not the ones the local Postgres was created with. Check `POSTGRES_USER`/`POSTGRES_PASSWORD` there against the running container (`docker compose exec postgres env \| Select-String POSTGRES`); a container seeded under older credentials keeps them until its volume is recreated |
| Rate far below the probe, ETA growing | Container CPU-bound: lower `--workers`, or close whatever else is eating cores |
| `snapping: N stop/profile combination(s) unsnappable` | Stops far from track or with bad coordinates — their pairs are listed as `NotSnapped`, nothing else is affected |
| Thousands of transient failures in one stretch | The routing container fell over (JVM OOM): `docker compose restart openrailrouting-infra-2026`, then rerun with `--retry-failures-only` |
| `stopped early` in the summary | `--stop-after-h` or Ctrl-C — expected; rerun to continue |
| `MISMATCH, investigate` | Routed + failed ≠ predicted with nothing stopped — the run was cut in a way the script did not see; rerun, which re-derives everything from the file |
| pgAdmin import fails on a `duplicate key` | You imported into `route_segments` instead of `route_segments_staging` |
| `Graph import mismatch for infra_2026` | The server's graph moved since you routed. Re-import the graph locally to match, or rerun the batch |

---

## 9. Command reference

```powershell
cd backend

# measure
uv run python scripts/precompute_route_segments.py --graph infra_2026 --measure-only

# batch (repeatable, resumable)
uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --workers 4 --stop-after-h 9

# only what failed
uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --retry-failures-only --retry-all

# artefacts
uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --finalize

# upload kit
uv run python scripts/precompute_route_segments.py --graph infra_2026 --export-upload --split-mb 250

# where the database IS reachable, all of the above collapses into
uv run python scripts/precompute_route_segments.py --graph infra_2026 --load
```
