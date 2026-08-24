# Energy model calibration

Traction energy consumption for a passenger night train, calibrated against
Deutsche Bahn's Trassenfinder API across the German network.

## Layout

```
energy/calib/
├── 01_source_extraction.ipynb   the Trassenfinder collection
├── 02_energy_calibration.ipynb  the fit, and the seed export
├── data_sources.py              resolves inputs, Drive-syncing what is missing
├── sources/                     committed — the inputs a collection needs
│   ├── routes_ontd.csv
│   ├── routes_synthetic.csv
│   └── compositions.csv
├── data/                        generated — gitignored, Drive-backed
│   ├── samples_ontd.csv
│   ├── samples_synthetic.csv
│   ├── samples_all.csv
│   ├── failures_ontd.csv
│   └── failures_synthetic.csv
├── seed/                        generated — gitignored
│   └── energy_coefficients.csv
└── exploration/                 frozen — the record of what was tried
    └── 2026-07_trassenfinder_api_exploration.ipynb
```

`sources/` is the calibration record and `seed/` is what the database reads.
`data/` sits between them: written by `01`, read by `02`.

## Where this deviates from the other calib packages

Everywhere else, `db/dev/seed.py` regenerates a domain's seed CSVs by running
both notebooks when they are absent. **Here it can only run `02`.** `01` makes
roughly 1,560 HTTP calls to an external API over 30–50 minutes; that cannot
happen at container start, and a machine with no network to Trassenfinder could
never seed at all.

So the collected samples travel through Drive instead of being rebuilt.
`data_sources.ensure_local()` fetches them on first use, mirroring the ONTD seed
pattern — a local file always wins, and the sync only fills gaps. Put the folder
id in `backend/docker/.env`:

```
ENERGY_DRIVE_FOLDER_ID=<folder id>
```

Without it, `02` fails with a message pointing at `01`. That is the intended
degradation: no silent fallback to a stale or partial sample.

Two helpers, deliberately different:

- `ensure_local(name)` — comes from outside this machine. Downloaded when absent.
- `local_input(name, produced_by)` — written by an earlier step here. Never
  downloaded, because a stale Drive copy could override what `01` just wrote.
- `source_input(name)` — a committed input under `sources/`.

## Regenerating

**Normal case — the samples already exist.** Run `02` only. `ensure_local()`
pulls `samples_*.csv` from Drive if this machine has never collected them.

**After changing route lists, compositions or request settings.** Run `01`, then
upload the new `data/samples_*.csv` to the Drive folder, then run `02`. `01` is
not idempotent against the API: Trassenfinder's network state moves between
infrastructure versions, so two runs months apart will not agree exactly.

Everything under `data/` and `seed/` is generated — **never hand-edit it**, the
next run overwrites the change silently. To change a value, change the notebook.

## The two route sources

| Source | Routes | What it is |
|---|---|---|
| `ontd` | 95 | Real German night-train segments from the ONTD workbook |
| `synthetic` | 100 | Generated station pairs, sampled for geographic and length diversity |

ONTD segments are short by construction — real night trains stop often, median
78 km — which leaves the long-distance range thin. The generated pairs extend
it and act as an out-of-sample check on whether the fit describes moving a
train or how night trains happen to be routed. They are kept in separate files
with a `source` column so pooling stays a deliberate choice.

### What the 2026-08-24 run showed

The two samples agree. Fitting `E = a·m + d·(b + c·m)` separately:

| sample | samples | routes | `a` | `b` | `c` | R² |
|---|---|---|---|---|---|---|
| ontd | 760 | 95 | 0.0673 | 2.0314 | 0.007309 | 0.986 |
| synthetic | 424 | 53 | 0.1066 | 2.0612 | 0.007586 | 0.993 |
| pooled | 1,184 | 148 | 0.0453 | 2.0547 | 0.007621 | 0.991 |

The per-km terms agree within 1.5% and 3.8%, a source indicator on the distance
term is not significant (p = 0.21), and fleet-weighted kWh/km per composition
matches within 1% for all eight. Cross-prediction costs −3.5% bias one way and
+5.1% the other. **The samples are poolable**, and pooling is what supplies the
400–941 km range where ONTD has only 80 samples and no coverage past 817 km.

### Why 47 of the 100 generated routes fail

Worth understanding before anyone tries to "fix" it.

| kind | routes |
|---|---|
| `Es konnte keine Route … gefunden werden` | 38 |
| `Ungültige Betriebsstelle` (dropped in the pre-flight) | 7 |
| `kein zulässiger Halteplatz` (Oppendorf) | 2 |

All eight compositions fail identically on every failed route, which rules out
anything train-dependent — mass, length, `v_max` — and puts the cause in the
fixed request settings or the network itself.

The routing failures track station category sharply: 22% for long-distance to
long-distance, 58% mixed, 71% regional to regional. A `D4` locomotive-hauled
train frequently cannot reach a branch-line station under these settings, and
`streckenklasse: "D4"` with `knotenbahnhoefe_meiden: True` are the likely
constraints. `D4` is over-specified for a night train — roughly 1.9 t/m against
the 8.0 t/m the class demands — so relaxing it would open lower-class lines.

**That relaxation has not been made, deliberately.** A lower line class lets the
40/30/30 optimiser pick different routes, including on ONTD segments that route
fine today, so it would invalidate the existing samples and require a full
re-run. There is also a reading in which the failures are correct: these pairs
are not usable by a locomotive-hauled night train, which is what the tool
models. The consequence to carry is that the 53 surviving generated routes are
biased towards main-line pairs — a selection, not a random draw.

## Two things the collection gets wrong if you are not careful

**`mutter` is a property of the station, not a request option.** Trassenfinder
rejects a Mutterbetriebsstelle sent as a child and a child sent as a mother,
both with HTTP 400 and no indication which end is at fault. Hard-coding
`mutter: True` cost 40 of 96 ONTD segments, biased towards short ones. `01`
resolves the flag once per station in a pre-flight pass before any collection
starts, so an invalid DS100 costs one request instead of eight.

**Response bodies must survive the failure path.** `raise_for_status()` inside a
bare `except` discards the API's message, which is the only thing that says
which station was rejected. `TrassenfinderError` carries it.

**An unresolvable station is dropped, not warned about.** With no `mutter` flag
its requests fall back to the default and return HTTP 400 — eight wasted calls
per route, and a failure table in which the genuine routing failures are buried.

## Known data-quality issues in the ONTD extract

Report upstream rather than patching in the notebook:

- Lörrach Autoreisezug Terminal has no `start_ds100` — the segment is dropped
- Köln Süd is exported as `KKSU`, not a valid Betriebsstelle; corrected to `KKS`
  via `DS100_CORRECTIONS` in `01`
- Düsseldorf Hbf → Köln Süd has no `travel_duration_min`

## Open

`02_energy_calibration.ipynb` is the exploratory fit carried over unchanged —
only its paths were repointed. Its outputs come from the 448-sample dataset
collected before the `mutter` fix, and its final cell raises `NameError` without
persisting the centering constants its exported coefficients depend on. It needs
rewriting against `samples_all.csv` before anything here reaches the backend.

Seven S-Bahn and local stops in `sources/routes_synthetic.csv` are not
Betriebsstellen — `MURB`, `RBSS`, `BSAL`, `ADT`, `AOH`, `BWSS`, `AKWS`. The
pre-flight drops them every run; removing them from the route list would save
the probe requests.

No terrain coefficient is estimable from either source: both are Germany-only,
so `terrain_score` has no variance. Austrian and Swiss routes are a separate
collection.
