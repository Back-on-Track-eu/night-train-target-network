# Staging deploy notes

**Audience:** whoever redeploys staging (Giovanni) · **Applies while staging is
still reseeded from scratch on every deploy**, i.e. until the first stable
release.

Things that are not obvious from `docker compose up` and have bitten us on
`backend-dev`. Each entry says what to do, and why — so it is clear when the
entry stops applying.

---

## Wipe the routing graph cache before reseeding — from 0.9.28 on

**Do this on the next staging reseed:**

```bash
cd backend/models/route/routing/docker
docker compose down
rm -rf graph-cache/          # or: mv graph-cache graph-cache-old
docker compose up -d         # entrypoint downloads the current cache from Drive
```

**Why.** The routing graph is built per *profile*, and the profile set is
baked into the graph at import time. `ROUTE_BUILDER_VERSION` 0.9.28 changed
it: 1520 and 1524 mm became one gauge family, so `night_train_1524` was
removed and `night_train_1520`'s custom model changed to accept both tags.
GraphHopper compares the config's profile hashes against the graph's at
startup and refuses to run when they differ:

```
java.lang.IllegalStateException: Profiles do not match:
Graphhopper config: night_train|…,night_train_1520|209904841,…
Graph:              night_train|…,night_train_1520|722514490,night_train_1524|…
Change configuration to match the graph or delete /app/graph-cache/
```

The container then restart-loops and the API never comes up, because it
waits on the routing service being healthy.

**The cache is not in git** — it is a ~213 MB zip on Drive, fetched by
`entrypoint.sh` when `graph-cache/` is empty, keyed by `GRAPH_CACHE_FILE_ID`
in `backend/docker/.env`. The file id does not change between versions; a new
graph is uploaded as a *new version of the same file*. So the fix is always
"delete the local directory and let it download", never an id change.

**When this stops applying:** never entirely — it applies to any deploy that
crosses a change to `config.yml` or `custom_models/`. Those are the only two
inputs to the profile hash. If a release note says the graph was re-imported,
wipe the cache.

**Renaming beats deleting** if disk allows (`mv graph-cache graph-cache-old`):
if the download fails you still have a working graph to move back.

---

## The database is fully reseeded, so schema changes need no migration — for now

`db/dev/seed.py` drops and rebuilds `input_params` and `scenario` from
scratch on every container start, and staging currently runs the same path.
That is why 0.9.28's `gauge_evidence` CHECK change (adding `'override'`)
ships without a migration.

**When this stops applying:** the moment staging stops being reseeded — at
the first stable release. From then on every schema change in
`backend/db/schema.py` needs a matching migration, and the stop catalogue
needs a new `stop_infra_version` rather than an in-place edit, because
scenario-pinned versions are immutable (`adapters/proposal/README.md` §4.2).
This section is the reminder to make that switch deliberately rather than
discovering it.

---

## The stop catalogue comes from Drive, not from git

`stop_seed_catalog.csv` is downloaded at seed time
(`ONTD_SEED_STOPS_FILE_ID`). Publishing a catalogue change means uploading a
new *version of the same Drive file*, then reseeding. A deploy that seems to
ignore a catalogue change is usually a catalogue that was never uploaded.

The seed log states the count it actually loaded:

```
downloaded stop_seed_catalog.csv (1050 stops).
```

Check that number against the release note — it is the fastest confirmation
that staging is running the catalogue you think it is.

---

## Expected log noise, not errors

```
TrackInfrastructure[BY]: no row in track_infrastructures — using EU-average default for every field.
TrackInfrastructure[RU]: no row in track_infrastructures — using EU-average default for every field.
```

Belarus and Russia are in `input_params.countries` **solely** to hold the
border polygons that the routing exclusion is built from
(`BLOCKED_COUNTRIES`, `models/route/model.py`). They deliberately have no
track-infrastructure rows, so that if the routing block ever failed, the
country-coverage check would still reject the route rather than silently
price Belarusian kilometres. The warning is that design working. Do not
"fix" it by adding rows.

```
2 catalog stops skipped — country not modelled (XK 2).
```

Kosovo is not in the country list yet. Two catalogue stops are dropped at
seed time as a result. Known, tracked, harmless.
