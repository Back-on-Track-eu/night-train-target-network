# Frontend handover — David → Bjarne

**Living document.** Backend changes that reach the API contract or change
what the UI should show, in one place. Updated after each change.

Last update 2026-09-05. Covers 2026-08-17 → 2026-09-05:
`ROUTE_BUILDER_VERSION` 0.9.23 → 0.9.31, `CALC_VERSION` 0.9.22, plus the
scenario restructure.

**If you read one section:** §6 is the only one with a decision in it. §1–§5
are mostly "this field now exists, show it if you want".

| | | Action |
|---|---|---|
| §1 | New stop catalog and the search it needs | done your side, one gap |
| §2 | Layover, and what parking now costs | optional display |
| §3 | Standard composition + field order | needs your call |
| §4 | Track gauge routing | new field + new error code |
| §5 | Scenarios and two routing graphs | new field, names changed |
| §6 | `api.ts` audit — the actual to-do list | **start here** |
| §7 | `uic_ref` can hold more than one code | no type change |
| §8 | Routes now prefer electrified track | no type change, results move |

---

## 1. New stop catalog and the search it needs

**Backend: `ROUTE_BUILDER_VERSION` 0.9.25 (2026-08-18), extended since.**

The stop catalog was replaced wholesale. `db/dev/seed.py`'s 58 curated stops
and the ONTD-derived seed CSV both gave way to the stop classification
pipeline's export (`backend/models/infrastructure/stops`), which is now
roughly a thousand stops keyed on OSM ids.

Two consequences you already felt:

**Stop ids changed shape.** `DE_BERLIN_HBF` became `osm:n3856100103`. Any
stored id — in a bookmark, a share link, a test fixture — predates the
catalog and no longer resolves.

**The list got big enough that a dropdown stopped working.** That is what
`StopSelect.vue` now solves, and the approach there is right: one lowercase
haystack per stop built once per load, covering display name, Latin/ASCII
transliterations, and city and country names in *every* catalog language.
That last part matters — a German user typing "Prag" and a Czech user typing
"Praha" both need to find the same station.

The `status` prop distinguishing loading / failed / genuinely-empty is the
detail I would have got wrong, and it is worth keeping that discipline
elsewhere: an empty array means three different things.

**The one gap:** stops carry `gauges_mm` (see §4) and a `provenance`
category the catalog exposes but the UI never surfaces. Not urgent — flagged
because gauge is now the reason some stop pairs are unroutable, and a user
who cannot see it has no way to understand the error in §4.

**Ongoing:** the catalog is Drive-hosted, republished as a new version of
the same file, and the seed log prints the count it loaded. If a stop you
expect is missing, the catalog version is the first thing to check, not the
API.

---

## 2. Layover, and what parking now costs

**Backend: `ROUTE_BUILDER_VERSION` 0.9.23 (2026-08-17).**

A route now reports its **scheduled layover** — the gap between the arrival
that ends one trip at a terminal and the departure that starts the next,
wrapped forward a day where the return departs earlier in clock terms than
the inbound arrived.

The route always knew this and never reported it. The facility calibration
needs it because Europe prices stabling per started hour, per started 24h
period, or per occupation — and because a free allowance longer than the
layover zeroes the charge entirely. So layover is not a display curiosity;
it is an input that visibly moves the parking cost line.

Where it appears: each entry in `route.parkings[]` carries `hours`.

Two behaviours worth knowing before you render it:

- A route with no second trip to depart again reports `0.0` rather than a
  guess. Zero means "nothing to stable", not "missing data".
- Payloads stored before 0.9.23 carry no layover at all. Those stay
  evaluable and simply price no stabling — understated, and visibly so.

If you show a parking breakdown, showing the layover hours next to it makes
the number explicable. Optional, but it is the difference between "€340" and
"€340, because the train sits for 9 hours in Oslo".

---

## 3. Standard composition and the field order

**This one needs your judgement, not just an implementation.**

The composition picker currently sits high in `ComputeInputsPanel.vue`,
above the fold, with equal visual weight to the stops. That ordering made
sense when there were two trains and picking one was half the exercise.

It no longer matches how people actually use the tool. From the InnoTrans
testing sessions, users think about *where the train goes* first and *what
train it is* second — and most never change the composition at all. Having
it high implies a decision they do not want to make yet, and the interviews
suggested it reads as a required step rather than an optional refinement.

**What I would like:**

1. A **standard composition** — one sensible default, preselected, so a
   proposal computes without touching the picker at all.
2. The composition field **moved down**, below the route inputs, framed as a
   refinement rather than a prerequisite.

**The backend piece is not done yet.** There is no `is_standard` flag on
`input_params.compositions` today. Before I add one, I would rather know
which shape helps you: a boolean on each composition, or a single
`standard_composition_id` alongside the list. The boolean is more flexible;
the single id is harder to get into an inconsistent state. Your call, since
you consume it.

Until then you can hardcode a default id, but tell me and I will treat the
flag as blocking rather than nice-to-have.

---

## 4. Track gauge routing

**Backend: `ROUTE_BUILDER_VERSION` 0.9.27 and 0.9.28 (2026-08-29).**

Routes are now gauge-aware. Each trip resolves **one** track gauge from its
stops' `gauges_mm` and routes on that gauge's own routing profile.

**What newly works.** Broad-gauge trips that used to fail as opaque snap
errors now route: Rovaniemi–Helsinki, Kyiv–Lviv, Dublin–Cork,
Madrid–Lisboa. If you have test fixtures asserting those fail, they are now
wrong in the good direction.

**New field.** `general_parameters.track_gauge_mm` on each trip — which
profile carried it. It is 1435 across the whole network west of the
break-of-gauge lines, so it is informative exactly where routes were
impossible before. Worth showing on Iberian, Irish, Finnish and Ukrainian
routes; noise everywhere else.

**New error you must handle: `422 gauge_mismatch`.** When a stop pairing no
single gauge can serve is requested, it fails *before* any router call and
names every stop's gauges in the response. This is a domain answer, not a
failure — "Helsinki and Berlin cannot be one train" is true and the UI
should say so in those terms rather than showing a generic routing error.
It is the one error in the system where the right message is an explanation,
not an apology.

**Resolution rules**, so your message can be accurate: the gauge is the set
intersection of the stops' gauges; a stop with unknown gauge does not
constrain the trip; ties prefer 1435. Auto-added stops are filtered to the
trip's gauge, and gauge-unknown stops are never auto-added.

**One naming quirk.** 1520 and 1524 mm are treated as one family — 4 mm
apart, historically the same gauge, interoperable in practice, but tagged
separately in OSM. Finnish trips therefore report `1520`, not `1524`. If you
label gauges, label that one carefully; a Finnish user seeing "1520" will
notice.

**Also, quietly:** Belarus and Russia are excluded from routing entirely.
That is a political decision, not a technical one. No route will cross them
in any mode.

---

## 5. Scenarios and two routing graphs

**Backend: 2026-08-31.**

### The scenario names changed

The old set is gone. "2032 Base Line" was misleading — "2032" named the
price year, not the network, which became untenable once the network itself
became a choice. Three scenarios now, all on today's network:

| key | name |
|---|---|
| `infra-2026` | Infra 2026 — the live base |
| `infra-2026-hsr` | + night trains on high-speed lines |
| `infra-2026-hsr-opt-tt` | + optimised timetables |

Your store already reads `current_base` + `current_scenarios` and ignores
`historical_scenarios`, which is exactly right — there is now a superseded
revision in that group that must not appear in the picker.

**Each scenario has a `description`** written for someone who has just
opened the platform, and the picker currently shows only `scenario_name`.
Those descriptions are the difference between three cryptic labels and a
comprehensible choice; surfacing them (tooltip, subtitle, info popover — your
call) is the highest-value small change on this list.

**What actually differs when a user switches:**

- *+ NT on HSR* changes routing — but only if the selected composition's own
  `hsr_allowed` is true. On a 160 km/h loco-hauled rake the two scenarios
  return identical routes. That looks like a bug and is not, so the UI
  should probably not promise a difference it cannot deliver.
- *+ optimised timetables* changes **durations, not geometry**. The map is
  identical; the journey time drops by roughly 2–5% depending on country. If
  you are diffing scenarios visually, diff the times, not the shape.

**Unchanged:** publish still requires the base scenario. Computing and
comparing under scenarios 2 and 3 works; publishing them returns
`422 scenario_not_base`, by design.

### Two routing graphs

Scenarios now pin which routing graph they run on
(`routing_graph_key`, e.g. `infra_2026`). A second graph — the 2032 upgraded
network from Jasper — is prepared but not running yet.

**Nothing to build now.** It is on this list so the eventual six-scenario
picker is not a surprise: the same three operating conditions on two
networks. When the 2032 graph lands, that becomes a two-axis choice
(network × conditions) and the picker probably needs to stop being a flat
list. Worth thinking about before it arrives rather than after.

---

## 6. `api.ts` audit — the actual to-do list

Checked `frontend/src/types/api.ts` against the current backend. Already
present and correct: `gauges_mm` on stops, `composition_id`,
`suggested_stops`. Missing:

| Field | Where | Why |
|---|---|---|
| `general_parameters` | per trip | Whole object absent from the types. Carries `trip_km`, `route_duration_min`, `average_speed_kmh`, `track_gauge_mm`, `timetable_warnings`. |
| `track_gauge_mm` | inside above | §4 |
| `timetable_warnings` | inside above | Derived quality annotations, e.g. `fixed_night_stretch_slow`. Empty for most trips. |
| `hours` | `parkings[]` | §2, the layover |
| `routing_graph_key` | `Scenario` | §5. Additive; harmless at runtime, but it belongs in the type. |

Also worth a look, though not a type change: the `422 gauge_mismatch`
handler (§4), and whether `provenance` on stops is worth surfacing (§1).

---

## 7. `uic_ref` can hold more than one code

**Backend: schema only, no version bump — 2026-09-05.**

`stop.uic_ref` is OSM's tag copied verbatim, and that tag is multi-valued:
a station registered in two referentials carries both codes in one string,
semicolon-separated. Paris CDG 2 TGV returns `"8727149;8700147"` — the
first is the SNCF code, the second the one Transilien uses for the same
platform.

**No type change.** It stays `string | null` in `api.ts`; nothing to do
unless the UI treats the value as a single code. One stop in the current
catalogue of 783 coded stops is affected, so this is a display edge case,
not a data model change: if you ever render or link on `uic_ref`, split on
`;` and take the first code rather than showing the raw string.

The column was `VARCHAR(12)` and this value aborted the seed; it is now
`VARCHAR(120)`. Whether multi-value eventually becomes a real array
(`string[]`) is deferred to the station-charge calibration, which is the
first thing that will actually join on the code — if it does, it arrives
as one contract change in a §6 batch rather than on its own.

---

## 8. Routes now prefer electrified track

**Backend: `ROUTE_BUILDER_VERSION` 0.9.31 — 2026-09-05. OUTPUT CHANGE, no
contract change.**

Every routing request now penalizes track that OSM tags
`electrified=no`. Background: the router was free to send a night train
down unelectrified branch lines, which is unrealistic and also mispriced —
every locomotive in the catalog is electric, and the energy model bills
catenary electricity on every kilometre.

It is a 10x priority penalty, not a block. An unelectrified alignment
loses to any reasonable electrified alternative, but is still used where
the alternative is absurd or does not exist — so no trip that routed
before starts failing. Track with **no** `electrified` tag is not
penalized at all: unknown is not treated as forbidden.

**Nothing in `api.ts` changes.** No new field, no removed field, no changed
type. What changes is the numbers behind the existing ones.

**What you will see.** On affected trips, geometry, `trip_km`,
`route_duration_min` and therefore every cost and revenue figure move. The
map line moves too. Fully electrified corridors — most of the flagship
routes — are unaffected; the movement is concentrated on regional and
branch alignments and on routes through less-electrified networks.

**One thing to check your side:** any golden-file or snapshot test that
pins a routed distance, duration or geometry will fail and needs
re-baselining. Same for screenshots in the gallery if you compare them
pixel-wise.

**Stored proposals.** They keep their stored numbers until refreshed, as
always — `scripts/refresh_proposals.py` on the backend side. A proposal
computed before 0.9.31 and one computed after can legitimately differ for
the same input; the version is on the payload if you need to explain it to
a user.

---

## Maintaining this document

One file, updated in the same PR as the backend change. Each entry says
which version introduced it, so you can tell whether a stored proposal
predates it.

When something here is done on your side, delete the entry rather than
marking it done — git history is the archive, and a list of completed items
buries the live ones.

The version constants are the anchor: `ROUTE_BUILDER_VERSION` and
`CALC_VERSION` both carry a full changelog in
`backend/models/route/model.py` and `backend/models/evaluation/model.py`.
Anything marked OUTPUT CHANGE there is something a stored proposal will
compute differently after — which is usually the moment the frontend needs
to know.
