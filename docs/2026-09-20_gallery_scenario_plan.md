# Gallery on a chosen scenario — plan (2026-09-20)

Two requests, one design:

1. **All figures follow the creator's last selection** — composition, prices,
   demand, schedule, timetable.
2. **A collapsible scenario panel on the gallery** — summaries and geometries
   shown for the scenario the viewer picks.

Status: **decided 2026-09-20; phases A, A.1, B and C implemented** — all that remains is the run on the live stack (see §5 and §6).
Decisions: separate table; synchronous variant rows at publish; phase B as
a debounced save on the cheap path described in §3; `scenario_variant_id`
as the axis.

## 1. What the code does today

| Concern                       | Today                                                                                                                                                                                                                            |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| What publish stores           | One member, computed server-side from `compute_request`; `scenario_id` forced to the current base (`api/helpers/publish_dispatch.py`, README §2.2 decision 4)                                                                    |
| When publish runs             | First Evaluate (`applyPlan(json, publish=true)`) and every Recalculate on an owned proposal (`recomputeWithSelection` → `applyPlan(json, ownsProposal)`)                                                                         |
| Composition / scenario switch | Served from the family document: `applyMemberFromFamily()` → `applyPlan(plan, false, true)` — **"a look, not an edit", never persisted**                                                                                         |
| Per-scenario figures          | Only inside the family document cache (`family.documents`, UNLOGGED, TTL, flushed on version bumps). Nothing persistent.                                                                                                         |
| Gallery projection            | `proposals.proposal_summaries`: one row per proposal, base scenario, one `geom_simplified` (§5.4)                                                                                                                                |
| Gallery query                 | `POST /api/proposals` → UNION CTE of `proposal_summaries` and `ontd.route_summaries` (`adapters/proposal/filter_builder.py`, `repository.py`); `map_lines` aggregates corridors, `map_routes` carries the listed rows' geometry  |
| Scenario axis in the family   | `scenario_variant_id` = scenario × measure set (`models/family/builder.py` `FamilyAxes.variants`); `GET /api/scenarios` lists variants; frontend switches map to `scenario_id` (`lib/scenarioAxes.ts`), measures are coming-soon |

So request 1 is a gap only for the family-served **composition** switch (prices,
demand, schedule and expert edits already reach the store through Recalculate),
and request 2 needs storage that does not exist.

## 2. Phase A — backend: per-scenario projections

### 2.1 Storage

New table, written in the same transaction as every publish and refresh:

```sql
CREATE TABLE proposals.proposal_scenario_summaries (
    proposal_id           INTEGER NOT NULL REFERENCES proposals.proposals(proposal_id) ON DELETE CASCADE,
    proposal_version      INTEGER NOT NULL,
    scenario_variant_id   INTEGER NOT NULL,
    scenario_id           INTEGER NOT NULL,
    measure_set_id        INTEGER NOT NULL,
    composition_id        TEXT    NOT NULL,
    route_builder_version TEXT    NOT NULL,
    calc_version          TEXT    NOT NULL,
    status                TEXT    NOT NULL,          -- 'ok' | 'error'
    error_code            TEXT,                      -- the member's code when status = 'error'
    -- §5.4 route metrics + financial + supply + demand columns, identical
    -- names and types, all nullable (an error member has none)
    ...
    geom_simplified       geometry(MultiLineString, 4326),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (proposal_id, scenario_variant_id)
);
CREATE INDEX idx_scenario_summaries_variant ON proposals.proposal_scenario_summaries (scenario_variant_id);
CREATE INDEX idx_scenario_summaries_geom    ON proposals.proposal_scenario_summaries USING GIST (geom_simplified);
```

`proposal_summaries` (§5.4) is **untouched**: still the base projection, still
what stats, compare and the load path read. The base variant's row is
duplicated into the new table so the gallery has one read path.

Declared in `db/schema.py` (source of truth), plus one migration
`db/dev/migrations/2026-09-2x_proposal_scenario_summaries.sql`.

### 2.2 Write path

`ProposalRepository.publish()` / `refresh_proposal()` today call
`compute_member()` for the presented member. Phase A adds, in the same
transaction:

1. Build a `FamilyRequest` from the resolved `compute_request` and a
   one-composition `FamilyAxes` (the creator's composition × every current
   variant) on a shared `FamilyContext`; `run_family()` with the base variant
   as `presented`. Reuse: the family builder is exactly what the builder UI
   just ran, and the routing memo / member cache make the base member warm.
2. Project each `ok` member through `projection.py` (pure, already exists) into
   a scenario row; write error members as `status = 'error'` with their code
   so the gallery can say "not computable on this scenario" rather than
   silently dropping the proposal.
3. Delete-then-insert the proposal's rows (variant set may change when the
   scenario catalogue moves).

Cost: one family of N variants per publish on a shared context — ~4 ms per
warm member; routing is per network, so the cold part is at most one extra
network. `scripts/refresh_proposals.py` gains the same step and a
`--scenario-summaries-only` backfill for existing rows; `outdated_trigger()`
adds "scenario rows missing or behind the variant catalogue".

### 2.3 Read path

`POST /api/proposals` body gains optional top-level `scenario_variant_id`
(validated against the current variants; default = the base scenario's
default-measure variant). The gallery CTE's proposal branch selects from
`proposal_scenario_summaries` for that variant (joined to `proposals` for
`user_id`, `name`, timestamps, and to likes/comments as today) instead of
`proposal_summaries`. `map_lines` and `map_routes` read the same rows, so
corridors and per-card geometry follow the scenario. `sources: ["existing"]`
rows are scenario-independent and unchanged. Summaries gain
`scenario_variant_id` and `status`; an error row carries `status: "error"` and
`error_code` with null KPIs (same convention as family members).

`GET /api/proposals/stats` and `POST /api/proposals/compare` are out of scope
(base only, as today).

### 2.4 Versions, docs, tests

- No `ROUTE_BUILDER_VERSION` / `CALC_VERSION` / `FAMILY_DOCUMENT_FORMAT`
  change: nothing existing changes shape or value. Backend package version
  patch bump.
- README §5.4a (new table), §4.2 (refresh trigger), §7.1 (request field,
  summary fields); `api/README.md` endpoint contract; `db/README.md`.
- Tests: `tests/test_2x_scenario_summaries.py` — rows written on publish and
  overwrite, one per current variant, base row equals `proposal_summaries`,
  error member stored as error, gallery filter by variant returns that
  variant's KPIs and geometry, ONTD rows unaffected, refresh backfill.

## 3. Phase B — builder: the creator's selection persists

- `applyMemberFromFamily()` on an **owned** proposal schedules a publish
  (overwrite) with the member's request, debounced (~1.5 s after the last
  switch) so arrowing through the catalogue costs one publish, not one per
  click. Someone else's proposal stays a private what-if, as today.
- **The cheap path (decision 3), measured 2026-09-20.** On 0.5.1 a warm
  overwrite-publish took 2.5–2.8 s, of which ~1.8 s was the variant rows —
  a catalog load per scenario on a fresh context, plus four Infra 2032
  variants that cannot compute on that stack at all. Phase A.1
  (`docs/2026-09-20_gallery_scenario_phase_A1_manifest.md`, backend 0.5.2)
  answers unservable variants from the router registry and reads the rows
  out of the family document the builder already wrote, so the phase-B
  save is the ordinary publish after all. The original reasoning, which
  A.1 makes true: The builder has just run the family for these
  stops, so the routing memo (`route_cache`) is warm for every network, and
  the member the user is looking at is in the member cache from the views
  fetch its switch triggered — so `compute_member()` in the publish is a
  cache hit and the phase-A `compute_scenario_rows()` family reuses cached
  legs. What remains is evaluation on a shared context (~4 ms per member)
  and the DB writes. Target: < 300 ms server-side on the request log; if
  a measurement on David's stack shows more, the fallback is a
  `PATCH /api/proposal/<id>/selection` that re-projects the variant rows
  from the cached family document and skips the GTFS rewrite. Decide on
  the number, not up front. **Status:** the first measurement said no —
  hence A.1; the endpoint stays unbuilt unless the re-measurement after
  A.1 still misses the target.
- Publish keeps `scenario_id: null` — the base rule (§2.2) holds. The scenario
  the creator was looking at is **not** stored: with phase A the gallery
  viewer's panel decides which scenario they see, so "last selection" means
  composition, prices, demand, schedule and timetable.
- Frontend only; the "switching is a look" comment in
  `ProposalViewport.vue` rewritten to say what is now true.
- **Delivered** as `docs/2026-09-20_gallery_scenario_phase_B_manifest.md`:
  `lib/selectionSave.ts` (the rule, 7 vitest cases) plus the timer in
  `ProposalViewport`, `doPublish(silent)`, and the cancels (edit,
  Recalculate, unmount).

## 4. Phase C — gallery scenario panel

**Delivered** as `docs/2026-09-20_gallery_scenario_phase_C_manifest.md`.

- `GalleryScenarioPanel.vue`: a collapsible row between the search bar and
  the results, reusing `ScenarioSwitches.vue` and `lib/scenarioAxes.ts`
  (measures still coming-soon, Infra 2032 still preview). Collapsed by
  default, so the one-screen height budget (`measureRow`) survives; the
  header line states the current scenario.
- The chosen variant goes into the proposals request — **only off the
  base**, since the default path is also the one that lists proposals
  without backfilled rows — into the query string as `scenario=<id>`, and
  into `store.pendingScenarioId` when a card is opened, which
  `ProposalViewport` applies once the proposal's family arrives.
- **Revised after David's review (0.5.3):** a scenario must never change
  which proposals a filter returns. The backend's variant path now LEFT
  JOINs the scenario row onto the base projection (identity and filterable
  columns from the base, figures from the variant; `"missing"` for rows not
  yet backfilled, with the base geometry), and the card list keeps every
  row — a card without figures shows one line saying why, and the panel
  header counts them.
- `frontend/src/types/api.ts`: the request field and the three row fields.

## 5. Decisions (taken 2026-09-20)

1. **Storage** — separate `proposal_scenario_summaries`; base row duplicated;
   `proposal_summaries` untouched.
2. **Publish cost** — synchronous: the variant rows are written in the
   publish transaction.
3. **Phase B mechanism** — debounced auto-save on the cheap path (§3);
   measured before any slimmer endpoint is added.
4. **Axis** — `scenario_variant_id`.

## 6. Phase A as built — deviations from §2

- The `status`/`error_code` columns and the three response fields landed as
  planned. One addition: a **`segments` JSONB** column on the scenario row —
  `map_lines` groups corridors from `proposals.segments`/`shapes`, which a
  non-base variant's route is not in, so its per-segment shapes are kept on
  the row (keyed `"A__B"`, direction-collapsed) and unnested in SQL at the
  same grain. Geometry is still fetched by reference in the aggregate, as on
  the base path.
- `outdated_trigger()` is unchanged: missing scenario rows do not trigger a
  whole-proposal refresh on load (that would recompute the route to fix a
  projection). The backfill (`--scenario-summaries`, `list_scenario_backfill()`)
  is the mechanism, and every publish/refresh rewrites the rows anyway.
- The default gallery request (no `scenario_variant_id`) keeps today's read
  path exactly — `proposal_summaries` + GTFS corridors — rather than reading
  the base row of the new table: proposals published before the backfill would
  otherwise vanish from the default gallery until the script had run.
- `map_stop_counts`/`map_country_counts` follow the variant too (they read the
  same CTE); stats and compare stay on the base, as planned.

Each phase is one zip, phase A followed by the integration-test run on the
live stack before B or C starts.
