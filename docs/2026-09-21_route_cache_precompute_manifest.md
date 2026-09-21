# Manifest — route-cache precompute: overnight runs and manual upload

*2026-09-21 · `backend/scripts/precompute_route_segments.py` and its docs.
No API, schema or model change; frontend unaffected.*

## Why

The precompute script assumed the friendly case: a server that can reach
both the routing container and Postgres, and a run that finishes. The
request was the other case — route on a laptop over one or several nights,
then upload the result through pgAdmin. That needs four things the script
did not have: progress you can plan a night around, failures that do not
end the batch and get retried, a resume that survives a kill mid-write,
and an output that a human can actually load into
`route_cache.route_segments` (the CSV carries neither `routing_graph_key`
nor `source`, and a direct import would abort on the first pair the server
already routed live).

## Changes by file

- **`backend/scripts/precompute_route_segments.py`** — the whole change.
  - `ProgressReporter`: one line with share done, throughput, elapsed, ETA
    and wall-clock finish time, refreshed in place on a terminal; ETA from
    a five-minute rolling window rather than the run average. Redirected
    output degrades to one timestamped line every five minutes, so
    `| Tee-Object` and `docker logs` stay readable.
  - Failure handling: `is_transient()` splits timeouts / HTTP 5xx /
    dropped connections from "no route" and "point off the network";
    `--retry-rounds` (default 2, `--retry-delay-s` apart) reattempts the
    transient ones after the main pass, `--retry-all` includes the rest,
    `--retry-failures-only` works the report in a later run.
  - `<out>.failures.csv` is now rewritten from scratch each run and
    carries `profile`, `attempts`, `transient`, `error_type`,
    `error_message`, `last_attempt_utc`, plus unsnappable pairs as
    `NotSnapped` — it answers "what is missing now", not "what raised".
  - Resume hardening: `repair_partial_tail()` truncates the half-written
    final row a killed run leaves behind (output CSV and snapped sidecar);
    the csv field limit is raised, since a long route's geometry exceeds
    the module's 128 kB default and would otherwise break resume on the
    script's own output; `--resume-from` accepts further CSV/`.csv.gz`
    files or directories whose keys count as done and are deliberately
    **not** re-exported.
  - `--stop-after-h` ends a run cleanly on a clock (checked inside the
    chunk, not only between chunks); Ctrl-C does the same on demand, and
    the summary says `stopped early` instead of the old spurious
    `MISMATCH`.
  - `--export-upload [--split-mb N]` writes `data/upload_<graph>/`: CSV
    parts, `01_create_staging.sql` (typed from `db/schema.py`
    `ROUTE_CACHE_TABLES`, so it cannot drift from the real table),
    `02_merge.sql` (import-date guard, `ON CONFLICT DO NOTHING` merge,
    `graph_state` insert-if-missing, truncate staging), a
    `03_drop_staging.sql` and a README with the pgAdmin click-path.
  - Snapping gained the same progress line and one automatic retry round.
  - Module docstring rewritten around the five phases and the
    resume/failure/progress contract.
- **`backend/tests/test_84_precompute_units.py`** — new; 10 pure tests
  (no stack): resume reader, partial-tail repair, geometry beyond the csv
  field cap, gzip resume source, transient/permanent split (the "no route"
  message contains the word *connection* — classification must not key on
  it), failure report rewrite, CSV split keeps a header per part, staging
  DDL mirrors the declared schema.
- **`docs/2026-09-21_route_cache_precompute_laptop_runbook.md`** — new;
  the end-to-end PowerShell runbook: pre-flight (including the graph
  import-date check against the server), measure, overnight batch, resume,
  failures, finalize, upload kit, pgAdmin steps, verification queries,
  troubleshooting table, command reference.
- **`docs/DEPLOY_HANDOVER.md`** — §7a.3 updated (five phases, the new
  progress line, interruptions and failures rewritten), two troubleshooting
  rows corrected, new §7a.5 on off-site batches and the manual upload.
- **`backend/models/route/routing/README.md`** — front-loading paragraph
  now mentions resume/retry/stop-after and `--export-upload`, and links the
  runbook.
- **`backend/db/README.md`** — `route_cache` section names the pgAdmin
  path alongside `--load` and states that both are additive.
- **`.gitignore`** — ignores `backend/scripts/data/route_segments_*` and
  `backend/scripts/data/upload_*/`. These were **not** ignored before, so
  the default `--out` would have put a multi-gigabyte CSV in
  `git status`.

## Behaviour unchanged

Row contract (`CSV_COLUMNS`), `--measure-only`, `--finalize`, `--load`,
the seed path in `db/dev/seed.py`, and what a cached row means. A CSV
produced by the old script resumes and loads under the new one, and vice
versa.

## Before applying

The snapshot this was built from is a working tree, not necessarily
`backend-dev` head. Per the 2026-09-13 lesson, before extracting:

```powershell
git --no-pager diff --stat backend-dev -- backend/scripts backend/tests backend/db/README.md backend/models/route/routing/README.md docs .gitignore
```

If anything there is non-empty, re-apply the edits onto the head files
rather than overwriting.

## Pipeline

1. Extract, then `cd backend`
   - `uv run ruff format .` and `uv run ruff check .` — both clean as
     shipped.
   - `uv run --extra dev pytest tests/test_84_precompute_units.py -v`
     (pure, seconds). Full suite as usual against the live stack:
     `uv run --extra dev pytest tests/ -v`.
2. CI: no version bump needed — the version gate in
   `.github/workflows/backend-tests.yml` covers `backend/models/**` only,
   and no model file is touched. `ruff-check` and `backend-tests` are the
   two gates this change passes through.
3. Smoke the new phases before trusting a night to them:
   ```powershell
   uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 300 --limit 50
   uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 300 --limit 50 --finalize
   uv run python scripts/precompute_route_segments.py --graph infra_2026 --export-upload --split-mb 5
   ```
   Then delete `backend/scripts/data/route_segments_infra_2026.*` and
   `upload_infra_2026/` before the real run.
4. Handover: deployment → `docs/DEPLOY_HANDOVER.md` §7a.5 and the runbook
   (Giovanni only needs them if he runs the batch server-side; the pgAdmin
   steps are self-contained in the generated `upload_<graph>/README.md`).
   Frontend → nothing; no endpoint, payload or version changed.

## Commits

```
feat(scripts): overnight-safe precompute — progress/ETA, retry rounds, resume, pgAdmin export
test(scripts): unit cover resume, failure classification and the upload kit
docs(route-cache): laptop runbook, deploy handover §7a.3/§7a.5, README and gitignore updates
```
