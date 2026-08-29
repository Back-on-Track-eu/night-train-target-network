# The current graph-cache pipeline

How the `graph-cache/` that OpenRailRouting serves is produced today, before
any of `osm_pipe` touches it. This is the baseline the new pipeline replaces
stages of — read it first, because two of its properties (the missing rail
pre-filter, and the silent lifecycle-tag gate) are the entire reason `osm_pipe`
exists.

Everything below is stated against files in this repository. Where a claim is
about GraphHopper or OpenRailRouting *internals* rather than something this
repo configures, it is marked **[engine]** and the evidence is named.

---

## Two ways a developer actually gets a cache

Worth separating, because almost nobody runs the import.

### 1. The prebuilt zip — what happens on a normal `docker compose up`

`backend/models/route/routing/docker/entrypoint.sh:23-35`:

```bash
if [ -f "$GRAPH_CACHE_MARKER" ]; then      # /app/graph-cache/properties.txt
    echo "[entrypoint] Graph cache found — skipping download."
else
    curl -L "$DOWNLOAD_URL" -o "$ZIP_PATH"
    unzip -o "$ZIP_PATH" -d "$GRAPH_CACHE_DIR"
fi
exec java -jar /app/railway_routing.jar server /app/config.yml
```

The cache is a 5–10 GB zip on Google Drive, id `GRAPH_CACHE_FILE_ID` (default
literal at `entrypoint.sh:18`). The marker is **`properties.txt`** — one file's
presence is the whole test. Drop any valid cache directory at that path and the
download is skipped; that is the hook `osm-pipe install` uses.

CI does the same thing by hand: `.github/workflows/backend-tests.yml:209-227`
caches `backend/models/route/routing/docker/graph-cache` keyed on
`hashFiles(config.yml)`, and on a miss greps the file id straight out of
`entrypoint.sh`.

The host path is fixed at `backend/docker/docker-compose.yml:66` and is
deliberately *not* an env var — it used to be `GRAPH_CACHE_PATH`, holding a
container-side `/app/...` value that bind-mounted an empty root-owned directory
on Linux and failed outright on macOS. Removed 2026-08-24.

### 2. The import — what produced that zip

`backend/models/route/routing/README.md:88-106`:

```powershell
docker compose run --rm openrailrouting `
  java -Xmx24g -Xms1g -jar railway_routing.jar import config.yml
```

**24 GB RAM, 20–40 minutes, ~5–10 GB of output.** Success is the line
`INFO com.graphhopper.GraphHopper - flushed graph`.

---

## The import, stage by stage

Config throughout is `backend/models/route/routing/docker/config.yml`, baked
into the image by the Dockerfile (so changing it needs a rebuild *and* a
re-import).

### ① Read the OSM file

```yaml
datareader.file: /app/data/europe-latest.osm.pbf
```

The full Geofabrik Europe extract, ~30 GB, downloaded by hand into
`docker/data/` (README step 1). Both `data/` and `graph-cache/` are gitignored.

### ② "Filter to rail" — but *not* before reading

This is the stage worth being precise about, because the shape of it is what
makes the import expensive.

**There is no rail pre-filter in this pipeline.** The reader ingests all 30 GB
and indexes every node in Europe — roughly half a billion — and railway
selection happens *inside* the import, per way, as the ways are parsed.

**[engine]** `RailAccessParser` grants access only to `railway` values `rail`,
`light_rail`, `tram`, `subway`, `narrow_gauge`; anything else returns
`WayAccess.CAN_SKIP` and the way is dropped. (Source: OpenRailRouting
`src/main/java/.../parsers/RailAccessParser.java`, cited in
`doc-jasper/future-network-routing.md:22-26`.)

Two consequences:

- The 24 GB / 20–40 min cost is paid almost entirely on data that is discarded.
  `osm_pipe` stage ① does the discarding first with `osmium tags-filter`,
  leaving ~0.26 GB, and the same import then fits in ~6 GB and ~3 minutes.
- **`railway=construction` and `railway=proposed` ways are not imported at
  all.** They are not "in the graph but unweighted" — they are absent, and no
  custom model can bring them back. This is the constraint the whole of
  `osm_pipe` follows from.

One line reliably causes confusion here:

```yaml
import.osm.ignored_highways: footway,construction,cycleway,path,steps
```

That `construction` is **`highway=construction`**. It has nothing to do with
railways and is not what blocks planned track.

### ③ Build the base graph, encode edge values

```yaml
graph.encoded_values: gauge,voltage,electrified,frequency,road_environment,max_speed,rail_access,rail_average_speed,railway_class,railway_service,preferred_direction
graph.dataaccess.default_type: RAM_STORE
```

**[engine]** Each name is a tag parser writing a few bits per edge —
`OSMGaugeParser` reads `gauge`, `OSMElectrifiedParser` reads `electrified`, and
so on. They read the **bare** keys only; none of them knows about
`construction:gauge`. That is why promoting `railway` alone is not enough, and
why `osm_pipe`'s promotion lifts the whole lifecycle namespace.

The encoded values that actually land are recorded in the built cache. From
`properties.txt` of a real cache: `gauge` 11 bits (max 1435), `max_speed` 7
bits × 2 directions, `railway_class`/`railway_service` 3 bits each, plus
several GraphHopper defaults not in the list above (`road_class`, `roundabout`,
`car_access`, `ferry_speed`) and one synthesised per profile,
`night_train_subnetwork`.

Turn costs are per profile:

```yaml
profiles:
  - name: night_train
    turn_costs:
      vehicle_types: [train]
      u_turn_costs: 300          # 5 min locomotive reversal
      enable_uturn_times: true
```

### ④ Apply the custom models, mark subnetworks

```yaml
    custom_model_files: [rail.json, night_train.json, preferred_direction.json]
```

Applied in order. `rail.json` and `preferred_direction.json` ship **inside the
JAR**; only `night_train.json` is ours (`custom_models/night_train.json`, and
the Dockerfile comment says so — "Only copy OUR custom models").

**[engine]** `rail.json` contains a second, independent gate:

```json
"priority": [
  { "if": "!rail_access || railway_class != RAIL", "multiply_by": "0" }
]
```

So even a hypothetical edge that survived ② with `railway_class = OTHER` is
weighted to zero. Two gates, both keyed on the same thing.

Ours:

```json
{
  "distance_influence": 0.2,
  "speed": [
    { "if":      "gauge != 0 && gauge != 1435",                        "multiply_by": "0.0" },
    { "else_if": "railway_service == YARD || railway_service == SPUR", "multiply_by": "0.0" },
    { "else_if": "true",                                              "limit_to": "200" }
  ]
}
```

Note `gauge != 0` — an *absent* gauge encodes as 0 and is therefore allowed.
Untagged mainline routes fine; a promoted way that lost its gauge to the
`construction:` namespace also routes fine, by luck rather than design.

Then subnetwork marking:

```yaml
prepare.min_network_size: 200
prepare.subnetworks.threads: 1
```

**[engine]** Any connected component below 200 edges is removed from the
routable graph. This is the silent one: a promoted line that fails to connect
becomes a small isolated component and is **deleted**, with the import log
reporting removed subnetworks and the routing API simply behaving as though the
work never happened. Debug it by temporarily setting this to 5 and re-importing
to confirm the edges exist at all.

### ⑤ Contraction Hierarchies, Landmarks, flush

```yaml
profiles_ch:
  - profile: night_train
profiles_lm:
  - profile: night_train
    maximum_lm_weight: 16
```

CH and LM are both prepared for the one profile and baked into
`graph.location: /app/graph-cache`. Timestamps land in `properties.txt`
(`prepare.ch.date.night_train`, `prepare.lm.date.night_train`).

CH answers unweighted-model requests fast; the backend disables it
(`"ch.disable": true`) whenever it sends a per-request custom model, which
`fullRouting` always does — see `backend/models/route/routing/rail_router.py`.

---

## What the cache does *not* record

From a real `properties.txt`:

```
datareader.import.date=2026-08-17T09:16:19Z
datareader.data.date=1970-01-01T00:00:00Z
profiles=night_train|431541742
```

`datareader.data.date` is **epoch zero**. Nothing in the cache says which OSM
extract produced it, when that extract was cut, or — once preprocessing exists
— which tag rewrites were applied. `profiles=night_train|431541742` is a hash
of the profile definition, not of the data.

A route computed on a modified graph is therefore not reproducible from the
stored request alone: the network has become an input, and `ROUTE_BUILDER_VERSION`
does not know it changed. `osm_pipe` writes a `network.json` manifest beside
each cache it builds to close this; wiring that into stored route provenance is
a backend change and has **not** been done.

---

## What invalidates a cache

A full re-import, never a restart (`README.md:212-233`):

- `config.yml` changes — profiles, encoded values, `min_network_size`
- `custom_models/night_train.json` changes
- the OSM input changes — including **any** preprocessing step `osm_pipe` adds

CH and LM are baked in, so there is no incremental path. Geofabrik refreshes
`europe-latest.osm.pbf` weekly.

---

## Summary against David's five steps

| David | In this repo | Note |
| --- | --- | --- |
| 1. read `europe-latest.osm.pbf` (~30 GB) | `datareader.file` | hand-downloaded into `docker/data/` |
| 2. filter to rail | **inside** the import, per way | no pre-filter; the 30 GB is fully read and indexed first, which is where the 24 GB and 20–40 min go |
| 3. build base graph, encode edge values per profile | `graph.encoded_values` + `profiles:` | parsers read bare tag keys only — lifecycle namespaces are invisible |
| 4. apply `custom_model_files`, mark subnetworks | `rail.json` → `night_train.json` → `preferred_direction.json`; `prepare.min_network_size: 200` | two independent gates drop non-`RAIL` track; sub-200-edge components are deleted silently |
| 5. build CH/LM, flush | `profiles_ch`, `profiles_lm`, `graph.location` | ~5–10 GB out; no record of the input |

The two facts `osm_pipe` is built on: **rail selection happens too late to be
cheap**, and **it happens before anything a custom model could influence**. So
the only lever on a future network is the `.pbf` handed to step 1.
