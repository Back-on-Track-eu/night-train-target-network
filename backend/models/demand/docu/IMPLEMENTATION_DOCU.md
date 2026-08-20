# Demand model — implementation log

Running record of what has been built, what was learned building it, and what
is next. Append-only: entries are dated and superseded rather than rewritten,
so the reasoning behind a decision survives the decision changing.

Home: `backend/models/demand/docu/IMPLEMENTATION_DOCU.md`.

**Division of labour between the demand-model documents.** Keeping these
separate is what stops any one of them turning into a dumping ground:

| Document | Answers |
|---|---|
| `DEMAND_MODEL_CONCEPT.md` | What the model is and why it is specified that way |
| `IMPLEMENTATION_DOCU.md` (this file) | What exists, what was learned, what is next |
| `docu/SOURCES.md` | Where each external file came from, and under what licence |
| `DEMAND_CALIBRATION.md` | What the calibrated values are and how they were derived |

Last updated: 2026-08-20 (batch 1 closed: acquired, explored, ETL run, output validated).

---

## 1. Status

Package definitions are in concept §4. Acquisition batches are concept §3.

| Package | State | Notes |
|---|---|---|
| DM0 — Concept | **done** | Revision 5; §3 replaced by the acquisition-ordered inventory |
| DM1a — Zone frame | **done** | 1 514 zones in `calib/out/01_zones.parquet`; see F29 |
| DM1b — Airport weighting & access matrix | not started | gated on batch 3 |
| DM2 — Background OD | not started | gated on batches 4–5 and on the base-year decision |
| DM3 — Segmentation | not started | |
| DM4 — Level of service | not started | gated on batch 6; two open source decisions |
| DM5 — Mode choice | not started | gated on batch 7 and the batch 0 correspondence |
| DM6 — Back-cast validation | not started | gated on batch 8 |
| DM7–DM9 | not started | |

### Acquisition progress

| Batch | State |
|---|---|
| 0 — external lead time | **not started** — nothing sent yet; these have the longest latency and gate DM5/DM6 |
| 1 — zone frame | **closed** — acquired, verified, ETL'd to `calib/out/01_zones.parquet` |
| 2 — zone attributes | not started |
| 3 — nodes and networks | not started |
| 4–8 | not started |

---

## 2. Findings

Numbered so decisions and code comments can cite them. Each records what was
observed, not what was inferred; consequences are drawn explicitly.

### 2026-08-20 — batch 1 exploration

**F1 — The GISCO NUTS 2021 distribution covers 37 countries, so no national
downloads are needed.** EU-27, EFTA (CH, IS, LI, NO), UK, and five candidate
countries (AL, ME, MK, RS, TR), totalling 1 514 NUTS-3 zones.
*Consequence*: entries B1-08/09/10 (ONS ITL3, BFS, SSB) are resolved as not
required; the zone frame is built from one source. The UK's presence is
notable — it left the NUTS regulation after Brexit, but GISCO retains the 2021
geometries for continuity.

**F2 — Country membership ships on every feature.** `EU_STAT`, `EFTA_STAT` and
`CC_STAT` are per-feature attributes.
*Consequence*: the hardcoded `EU27` / `EFTA` / `CAND` sets in the first draft
of the exploration notebook were removed. Membership is read from the data, so
nothing drifts as candidate status changes. `tier`, however, is **not**
derivable from these flags — Norway is EFTA but Tier 2 — so it stays an
explicit constant.

**F3 — `nuts-*-units.json` is a file manifest, not a code list.** Each value is
the 18 per-unit geometry files GISCO publishes for that code (5 resolutions ×
3 projections, plus label points). Region names are not in it.
*Consequence*: B1-04/05 rewritten. The file is still worth holding, for one
reason — see F4. Names come from `NAME_LATN` / `NUTS_NAME` on B1-01.

**F4 — The manifest/geometry cross-check passes exactly.** 2 010 entries: 37 at
level 0, 125 at level 1, 334 at level 2, 1 514 at level 3. The level-3 key set
is identical to the geometry layer with no orphans either direction, and
per-country counts match.
*Consequence*: two independently distributed files agree on the unit
inventory. This is provenance worth keeping — cheap to record now, expensive
to reconstruct at review time.

**F5 — The 2021→2024 crosswalk is much smaller than the raw diff suggests.**
1 514 zones in 2021, 1 345 in 2024, 1 283 stable. The raw 231-discontinued /
62-new diff is dominated by the UK's absence from 2024; Kosovo (XK, 7 zones)
is new. Genuine restructuring is six countries and roughly 50 codes: DE 7→6,
FI 9→9, LV 4→3, NL 15→15, NO 3→7, PT 14→15.
*Consequence*: the crosswalk is a day's work, not a week's. Most rows look
like clean n:n renumberings, but code sets alone cannot distinguish a rename
from a split from a coincidental reuse — the release notes decide that.

**F6 — The UK exists in NUTS 2021 and not in NUTS 2024.**
*Consequence*: a second, independent argument for the NUTS 2021 pin beyond
dataset coverage. Pinning 2024 would leave no UK geometry at all, so Tier 2
could never be activated without a separate ONS acquisition.

**F7 — The name columns are not what they look like.** `NAME_LATN` and
`NUTS_NAME` are region names (the latter in local script; they differ for 115
zones, Greek and Bulgarian). `NAME_ENGL`, `NAME_FREN` and `NAME_GERM` are
**country** names joined onto each region — `HR064` carries
`NAME_ENGL = "Croatia"`.
*Consequence*: the output takes `NAME_LATN` as `name_latin` and `NUTS_NAME`
as `name_local`. Documented in the notebook because it silently produces
plausible-looking wrong output.

**F8 — The release notes carry three things bearing on batch 1.** Jan Mayen and
Svalbard were folded into Norway's statistical regions (2020-11-18), so
`NO0B2 Svalbard` is a NUTS-3 zone of 63 084 km² with a population around 2 500
and no rail. `MOUNT_TYPE` / `URBN_TYPE` / `COAST_TYPE` were corrected for a
number of NUTS 2021 records (2022-09-01). Tiny inter-zone gaps were
reprocessed out (2024-07-22).
*Consequence*: Svalbard is an expected grid-coverage edge case and a
legitimate Tier 2 exclusion, not a bug. The gap reprocessing means the
level-3-against-level-0 gap assertion can use a tight tolerance.

**F9 — Ukraine and Bosnia do not reach NUTS-3 in either vintage.** From the
2024 release notes: UA is available at level 0 only; BA was added at level 2.
*Consequence*: BA, UA, MD, GE, and XK (2021) remain zone-frame gaps. Only
matters if Balkan or Ukrainian routes enter scope, at which point they need
national sources — logged rather than solved.

**F10 — The population grid carries the NUTS-3 code per cell.** GISCO grid v1.4
(03/07/2025) attributes `NUTS2021_3` and `NUTS2024_3` to each 1 km cell.
7 055 226 cells, 455 671 735 total 2021 population.
*Consequence*: the population-weighted centroid is a groupby, not a spatial
join, and no polygon layer or raster needs loading.

**F10a — Border cells join codes with a hyphen, and missing is an empty
string.** Codes are attributed to every cell intersecting **or within roughly
1.5 km** of a region, so border cells carry `AL011-AL012-AL014`-style values;
`CNTR_ID` behaves the same way (`BA-HR-RS`). Unassigned cells hold `""`, not
`NaN`. Distribution: 5 689 308 cells with one code, 269 768 with two, 3 745
with three, 16 with four; 1 092 389 (15.5 %) unassigned.
*Consequence*: split on `-` — NUTS codes contain no hyphen, so it is
unambiguous. **17 491 568 people, 3.84 % of the total, sit in multi-code
cells**, so the resolution rule is doing real work and needs its own assertion
in `calib/etl/step1_zones.py` rather than being waved through. Multi-code cells are
resolved by point-in-polygon on the cell **centre** (`X_LLC + 500`,
`Y_LLC + 500` — the columns are the lower-left corner, so using them raw puts
every centroid 500 m southwest of where it belongs).
- ⚠️ Process note: two successive checks missed this. `isna()` reported zero
  missing against 15.5 % empty strings, and a separator hunt over `,;| ` and a
  follow-up assertion over `[,;|]` both passed on a file full of hyphens. An
  earlier "1 512 / 1 514 zones covered" figure was right by accident —
  multi-code strings matched no single `NUTS_ID` and were silently dropped
  from the comparison. Assertions written from an assumed format confirm the
  assumption, not the data; the format has to be read off the file first.

**F11 — Parquet has been published for the NUTS datasets since 2026-05-11.**
*Consequence*: not worth re-fetching 15–26 MB GeoJSON files, but confirms
Parquet for the grid, where the size difference is material.

**F12 — LAU is not needed to place points in zones.** Point-in-polygon against
the NUTS-3 layer is direct; routing through municipalities would only add a
hop and a chance to drop records.
*Consequence*: LAU moved out of batch 1 into batch 4 as conditional, triggered
only if a chosen OD source is keyed on place names rather than coordinates.
This corrected an error in the first draft of concept §3.

**F13 — Geometry coverage is not attribute coverage.** The frame will carry
1 514 zones; Eurostat regional statistics will not cover the UK at all, and
candidate-country series are patchy and lagged, with IS and LI thin at NUTS-3.
*Consequence*: expect batch 2 to populate roughly 1 350–1 400 zones. That is
the expected shape of the coverage report, not a defect — but it needs stating
in advance so it is not mistaken for a join failure.

**F14 — Grid population coverage is EU-27 + CH + NO + LI.** Seven countries
carry cells with zero population throughout: AL, IS, ME, MK, RS, TR, UK.
- *Corrected 2026-08-20 (see F26).* This finding originally listed LI among
  the uncovered, read off a per-country table denominated in millions and
  rounded to two decimals, where Liechtenstein's ~37 000 people display as
  `0.00`. LI is covered; its zone total is 37 328 against roughly 39 000
  residents. Coverage is 30 countries, not 29.
*Consequence*: 287 zones have cells but no population, plus 2 with no cells at
all (F8). After the country-level coverage gate of F26 the final split is
1 199 weightable and 315 on the fallback. The gap maps onto the
scope decision precisely: **every Tier 1 zone has population**. The shortfall
is UK (174 zones, Tier 2), candidate countries (TR 79, RS 13, AL 9, MK 5), and
IS 2. Documented limitation, not a blocker, and no fallback data is warranted.
- The 287 figure is a **pre-resolution** diagnostic and will rise slightly once
  border cells are assigned: some zones in zero-population countries currently
  show population only because they share a border cell with a covered
  neighbour. LI and ME have no zones in the list for exactly this reason —
  their cells are shared with CH, AT and HR. The authoritative count comes
  after point-in-polygon resolution, and the two numbers should not be
  mistaken for a discrepancy.

**F15 — The French DOM lie outside the grid extent.** `FRY10` Guadeloupe,
`FRY20` Martinique, `FRY30` Guyane, `FRY40` La Réunion and `FRY50` Mayotte
carry cells but no population. EPSG:3035 is a continental European projection;
the DOM fall far outside its extent and pick up only clipped edge cells.
*Consequence*: a fourth failure mode, distinct from the other three — not
missing data, but zones the weighting source structurally cannot reach. Same
treatment as Svalbard: geometric centroid, `tier = 2`, no fallback sought.
They are not night-train relevant.

**F16 — Four distinct centroid outcomes, not two.** Combining F8, F14 and F15:

| Bucket | Zones | Treatment |
|---|---|---|
| Weightable (EU-27 + CH + NO + LI, continental) | 1 199 | population-weighted |
| Outside the 2021 census round (UK, TR, RS, AL, MK, IS) | ~282 | geometric |
| Outside the grid extent (FR DOM) | 5 | geometric, `tier = 2` |
| No cells at all (Jan Mayen, Svalbard) | 2 | geometric, `tier = 2` |

*Consequence*: `centroid_source` stays binary (`pop_grid` / `geometric`) and a
separate `centroid_fallback_reason` column carries the diagnosis. Keeping the
filter column two-valued and the explanation beside it avoids every downstream
consumer having to know four literals to answer one question.

### 2026-08-20 — Tier 2 acquisition

**F17 — GHS-POP closes every coverage gap from one file; the epoch matters
later, not now.** GHS-POP R2023A is global, so it reaches the UK, the
candidate countries, IS, LI **and** the French DOM that no EPSG:3035 product
can. It is modelled (census totals disaggregated by built-up volume), not
counted. *Consequence*: a fallback, never a replacement — the census grid wins
wherever it exists and the two are never mixed within a zone.
- *Revised 2026-08-20, superseding the first statement of this finding.* The
  file held is `GHS_POP_E2030_GLOBE_R2023A_54009_100_V1_0.tif` — epoch 2030,
  100 m. The original claim that this biases centroids was wrong: a centroid
  is a weighted mean of *positions*, and scaling every cell by a uniform
  growth factor leaves it unchanged. Only differential redistribution within a
  zone between 2020 and 2030 moves it, which is second order and far below the
  0.4 km median measured in F18. **For centroids, the file held is fine.**
- The epoch does bite one step later. Eurostat regional statistics cover
  neither the UK nor Türkiye, so for those zones GHS-POP is the *only*
  population source batch 2 will have. At that point it stops supplying
  positions and starts supplying values — zone attraction terms in DM2/DM3 —
  and a 2030 projection used as a base-year population is a plain error. Run
  totals bear out the inflation: UK 68.24 M against roughly 67 M observed for
  2020, TR 87.77 M against roughly 84 M.
- **Re-download epoch 2020 at 1 km as a batch 2 prerequisite**, not as an
  urgent fix. 1 km also cuts the work by two orders of magnitude: the 100 m
  global raster is 64.9 billion cells, for an answer good to 0.4 km.

**F18 — The fallback is validated: median displacement 0.4 km.** Zones needing
GHS-POP have no census grid to check against, so the displacement between the
two methods was measured across 246 covered zones where both exist. Median
0.4 km, 75th percentile 0.7 km, 90th percentile 1.3 km, maximum 12.0 km.
*Consequence*: against a 90-minute access cap this is noise, so the 179 UK
zones and the candidate-country zones rest on a method measured against census
truth rather than on an assurance. Every uncovered zone resolved — 315 in the
final run, after F26 — and none fell back to geometric.
- The tail behaves as predicted: `EE009` (12.0 km) and `EE004` (8.2 km) are
  large, sparse, predominantly rural zones where the two methods disagree
  about where thin population sits — and where the geometric alternative is
  worse still. The one urban zone in the tail, `NL33C Groot-Rijnmond` at
  2.4 km, is an oddly shaped port zone; six times the median, and 2.4 km in
  absolute terms.

**F19 — `calib/raw/` and `calib/out/` are not gitignored.** The root
`.gitignore` enumerates calibration directories path by path
(`.../calib/data/`, `.../calib/seed/`) and predates the demand tree, which
uses `raw/` and `out/` instead.
*Consequence*: roughly 2.3 GB of downloads — the GHS-POP raster and its
overview, the census grid archive, the grid Parquet, three GeoJSON layers —
are currently trackable in a public repository. Fixed by the `.gitignore`
patch shipped with this revision. This is the same class of oversight as
`backend/docker/.env.bak-preauth`, which is still tracked and still open.

**F20 — Zone counts corrected.** Earlier revisions of this log and of
`docu/SOURCES.md` carried per-group zone counts reconstructed from memory
rather than read off the run. Correct figures, from the coverage cell: EU
1 166, EFTA 42, candidate 127, UK 179 — total 1 514. Previously stated as
1 168 / 66 / 78 / 202.
*Consequence*: `SOURCES.md` B1-08 corrected. The related remark that 28 UK
zones carried census population was also wrong; it is 5, all on the Irish
border.

**F21 — The source decision must come after border resolution, not before.**
27 zones in countries the census grid does not cover nevertheless showed
non-zero census population: AL 3, MK 3, RS 12, TR 2, UK 5, plus ME and LI,
which never appeared in the uncovered set at all. Their only census cells are
border cells shared with a covered neighbour.
*Consequence*: an exploration-order artefact that would become a silent data
error in the ETL. Once point-in-polygon assigns each cell to one zone, that
population goes to the neighbour and those zones drop to zero — so
`step1_zones.py` resolves cells first and only then decides which zones need
GHS-POP. Deriving the source assignment from the exploration notebook's
pre-resolution figures would have left 27 zones weighted on their neighbours'
population, and nothing would have failed.

**F22 — Archipelago zones need the most populous part, not the whole zone.**
`PT200 Região Autónoma dos Açores` sits 4.6 km from its census counterpart
because a population-weighted centroid across scattered islands lands in the
water between them. Both methods do this; they only disagree about where.
*Consequence*: harmless for weighting, broken for DM1b — a centroid in open
sea has no road or rail access, so the access matrix would either fail to
route it or assign an absurd time. `step1_zones.py` therefore restricts the
centroid to the zone's most populous part for multipart geometries, and
asserts every centroid falls inside its own zone. Also affects Madeira, the
Canaries, the Greek and Danish islands, and the Scottish islands once Tier 2
lands.

**F23 — Ukraine and the western Balkans are not in the frame at all.** UA
reaches only NUTS level 0; BA only level 2; XK exists in 2024 only; MD and GE
not at all (F9).
*Consequence*: "Balkan coverage" means AL, ME, MK and RS — 46 zones between
them. Any route touching BA, XK or UA needs national sources and a zone-frame
extension, which is a Tier 2 scope question rather than a data gap to fill in
batch 1.

**F24 — Geometry validity is shapely-version-dependent, so the ETL repairs
rather than asserts.** `PL518 Wrocławski` carries a ring self-intersection in
the GISCO 1:1M 2021 layer — one zone of 1 514. It surfaced on David's shapely
and not in the container run of the same file.
*Consequence*: an ETL that fails on one machine and passes on another is worse
than one that repairs and reports, so `repair_geometry()` runs `make_valid()`
ahead of centroid assignment and the crosswalk — both `within` and `overlay`
break on self-intersecting rings, so the repair cannot wait for `validate()`.
It reports the zones repaired and asserts the area change stays under 1 %:
a sliver cleanup moves area by a rounding-level amount, whereas a repair that
resolved the intersection by discarding a real part of the polygon would not,
and would then silently break the level-3-against-level-0 gap check for a
reason unrelated to the source data. This is the same class of defect the
2021 release notes record fixing elsewhere in the layer (F8).

**F25 — Annular zones put the weighted centroid in the neighbouring city.**
The centroid-within-zone assertion failed on a large set of zones that ring a
city: `CZ020` Středočeský around Prague, `BE241` Halle-Vilvoorde around
Brussels, `AT313` Linz-Land around Linz, the DE11x/DE12x Landkreise around
Stuttgart and Karlsruhe, `PL518 Wrocławski` around Wrocław. For a
ring-shaped zone the population-weighted mean lands in the hole.
*Consequence*: the assertion was not wrong to fire, but the response is not to
relax it. The point is unusable rather than merely outside: it sits beside a
main station in a zone where nobody lives there, so DM1b would compute a
flattering access time for exactly the commuter-belt zones where access is the
interesting question — and it would look plausible.
- Both centroid paths now **snap to the nearest populated cell** when the
  weighted mean falls outside the geometry, keeping the point inside the zone
  and inhabited. `centroid_snapped` records it; the assertion stays as a hard
  invariant, now guaranteed by construction, so a future failure means the
  snap did not run rather than that a zone is awkwardly shaped.
- Worth noting the coincidence: `PL518` is both the one invalid geometry
  (F24) and an annular zone. A ring around a city with a boundary shared along
  its whole inner edge is where slivers are easiest to produce.
- The alternative of taking the most populous cell outright was rejected: it
  would silently redefine the centroid as "the largest town", changing the
  semantics for every zone rather than repairing the ones that need it.

**F26 — Border resolution fixed the wrong half of F21; census coverage is a
country-level property.** After point-in-polygon resolution, 14 zones in
countries outside the census round still carried census population: RS 8,
UK 5, LI 1. AL, MK, ME and TR closed as predicted.
*Consequence*: resolution answers *which zone a cell belongs to*. It cannot
answer *who counted the people in it* — a 1 km cell straddling the Irish
border whose centre falls on the UK side is legitimately a UK cell and still
holds population only Ireland's census counted. Geometry cannot separate the
two. `resolve_grid_cells()` therefore drops cells resolving into countries
outside the census round, and those zones fall through to GHS-POP.
- Coverage is **derived from the grid, not hardcoded**: a country counts as
  covered when its own single-country cells carry population, with border
  cells excluded from the test since their population may have come from
  either neighbour. That keeps the rule correct across grid versions instead
  of pinning a country list that would silently rot.
- Actual effect: `ghs_pop` 302 → 315, `census_grid` 1 212 → 1 199. UK and RS
  closed at 179 and 25. **Liechtenstein did not**, and correctly so: its own
  single-country cells do carry population, so the derived test returns it as
  covered. The prediction of 316 rested on reading `LI 38 0.00` off a
  per-country table in millions rounded to two decimals, where anything below
  5 000 people displays as zero — the test was right and the earlier reading
  of the display was wrong.
- Worth noting how this presented: nothing failed. Both runs produced a full
  frame, every assertion passed, and the defect was visible only by comparing
  per-country counts against what F21 predicted. Predicting the number before
  the run is what caught it.

**F27 — First full ETL run reconciles.** 1 514 zones written to
`calib/out/01_zones.parquet`. Crosswalk: 1 283 identical, 179 discontinued
(exactly the UK, per F6), 41 renamed, 11 split — the latter two summing to the
52 non-UK changed zones of F5. Tier 1 192 / 322 = EU-27 + CH against the rest.
45 centroids snapped, concentrated in DE (19), PL (5) and CH (3): commuter
belts around major cities, which is the expected shape for F25. Geometry
repair moved `PL518`'s area by 0.0000 %.

**F28 — `centroid_snapped` under-reported until both paths recorded it.** The
snapped count fell from 45 to 42 when RS and UK zones moved to GHS-POP. Not
because those zones stopped being annular: the GHS path snaps too, but only
the census path's flag was carried into `centroid_snapped`.
*Consequence*: a column documented as recording snapping was silently
incomplete for exactly the zones with the least other evidence behind them.
Both paths now return and record the flag. Same failure shape as F26 — nothing
raised, the number simply moved, and only a prior expectation caught it.

**F29 — Batch 1 closed.** `calib/out/01_zones.parquet`, 1 514 zones:
1 199 on the census grid, 315 on GHS-POP, none geometric. Fallback by country
AL 12, FR 5 (DOM), IS 2, ME 1, MK 8, NO 2 (Jan Mayen, Svalbard), RS 25, TR 81,
UK 179. Crosswalk 1 283 identical / 179 discontinued / 41 renamed / 11 split.
Tier 1 192 / 322.
*Small-country check, resolved 2026-08-20*: LI 37 328 against roughly 39 000
residents — a 4 % shortfall, consistent with a 1 km grid at a border where
some cells resolve to the Swiss or Austrian side. MT 497 329 across its two
zones against roughly 520 000; CY 917 722 for the government-controlled area.
All representative, so no zone is forced to GHS-POP and no country needs
special-casing. The concern that drove the check — that a country could pass
the coverage test on a handful of unrepresentative cells — did not
materialise, and the derived test handled every small country correctly.

---

## 3. Decisions

Concept §5 holds the authoritative list. Reproduced here with the
implementation-side rationale and the date it was taken.

| # | Decision | Rationale | Recorded |
|---|---|---|---|
| D1 | Zone level: NUTS-3 | NUTS-2 blurs catchments; LAU is unusable at European scale | concept §2.1 |
| D2 | NUTS vintage: **2021**, pinned as `nuts_version` inside `demand_version` | back-cast sources are on 2021 or older; Eurostat tables split across vintages; reinforced by F6 | concept §2.1, §5.10 |
| D3 | Centroid: population-weighted, geometric fallback, `centroid_source` recorded | geometric centroids are badly wrong precisely where access time decides catchment membership | concept §2.1, §5.11 |
| D4 | Scope: built wide (EU + EFTA + UK + candidates), filtered by `tier` | geometry is cheap; re-deriving the frame to add a country would invalidate every downstream pin | concept §2.1, §5.12 |
| D5 | Centroid weighting from the census population grid, **not** CORINE land cover | CORINE measures area, not people; class 122 (road and rail) would bias centroids toward corridors rather than settlements; the 25 ha MMU drops small settlements in exactly the rural zones where the choice matters | this log; concept §2.1 |
| D5a | *Amends D5, 2026-08-20.* Named fallback for uncovered zones is **GHS-POP**, not CORINE — and it is **deferred, not used** | Once F14 showed where the gaps actually fall, CORINE lost the fallback role too, for the same reasons it lost the primary one: GHS-POP is global (so it reaches UK, TR, the Western Balkans), is actual population rather than area, and is 100 m. But since the gap is entirely Tier 2 and out-of-scope zones, fetching a global raster to weight zones we are not routing is precision that buys no decision. Uncovered zones take a geometric centroid with a recorded reason; revisit only if Tier 2 activates | this log |
| D6 | DM1 split into DM1a (frame) and DM1b (airports, access matrix) | the airport layer is a batch 3 dependency; without the split DM1 would appear stalled while the frame is finished | concept §4, §5.13 |
| D7 | `demand.zones` written once, after batch 2, with attributes included | writing the table at the end of batch 1 would mean migrating it a week later | this log |
| D8 | `centroid_source` binary, diagnosis in `centroid_fallback_reason` | F16 found four outcomes; a four-valued filter column would force every consumer to know all four literals to answer one question | this log |
| D9 | *Supersedes D5a, 2026-08-20.* GHS-POP is **acquired and used**, not deferred | Tier 2 routing moved from "someday" to "very soon", so the 202 UK zones need a real weighting. One global file closes every gap — UK, candidates, IS, LI and the FR DOM — against a UK-only alternative of three agencies on three output-area geographies. `centroid_source` takes a third value, `ghs_pop` | this log |

### Open

| # | Question | Blocks | Note |
|---|---|---|---|
| O1 | Base year: 2019 vs ≥ 2023 | batch 4 | 2023 avoids the pre-COVID objection; 2019 has better completeness. Must be settled *before* batch 4 opens, since it fixes the vintage of every download in it |
| O2 | Air schedule source: Eurocontrol R&D archive vs. commercial | batch 6, DM4 | |
| O3 | Whether any open pan-European air fare source exists | batch 6, DM4 | currently assumed not |
| O4 | Car OD: observed or synthesised | batch 4, DM2 | depends on the batch 0 response re TRIMODE/TRUST |
| O5 | Traffic add-on: router-native vs. calibrated per-country factors | DM4 | |

---

## 4. Artifacts

Tree as of 2026-08-20: `etl/` holds the `.py` pipelines, `exploration/` the
notebooks that precede them, `raw/` the downloads, `out/` the generated
artifacts. Documents live in `docu/`.

| Path | State |
|---|---|
| `docu/DEMAND_MODEL_CONCEPT.md` | Revision 6 |
| `docu/IMPLEMENTATION_DOCU.md` | this file |
| `docu/SOURCES.md` | batch 1 complete bar the B1-07 / B1-10 redistribution TODOs |
| `docu/DEMAND_CALIBRATION.md` | not started |
| `calib/exploration/01_zone_exploration.ipynb` | complete, incl. GHS-POP |
| `calib/etl/step1_zones.py` | written |
| `calib/raw/01_zones/` | populated; GHS-POP epoch to re-download before batch 2 (F17) |
| `calib/out/01_zones.parquet` | **produced** — attributes, geometry, centroids, source, crosswalk |
| `db/schema.py` — `demand.zones` | not written (D7) |
| `README.md`, `calib/README.md` | refreshed 2026-08-20 |

---

## 4b. Working notes

Enough to pick this up cold in a new session.

**Commands** — run from `backend/`, where the `uv` environment lives:

```powershell
uv run python models/demand/calib/etl/step1_zones.py
uv run --extra dev --with jupyterlab jupyter lab --notebook-dir models/demand/calib
```

**Extra dependencies** beyond the usual `dev` extra: `pyarrow` (Parquet),
`rasterio` (the GHS-POP raster). Both added via
`uv add --optional dev <pkg>` — `--optional`, not `--group`, since the test
invocation uses `--extra dev`.

**Tree.** `calib/raw/<batch>/` downloads, `calib/exploration/` notebooks,
`calib/etl/` pipelines, `calib/out/` generated artifacts, `docu/` documents.
`raw/` and `out/` are gitignored; the entries were added to the root
`.gitignore` on 2026-08-20 (F19) and had been missing.

**Reading order for a fresh session.** `DEMAND_MODEL_CONCEPT.md` §3 for what
is acquired and what is next; this file §1 for state and §2 for the traps
found so far; `SOURCES.md` for where each file came from.

**The habit worth keeping.** Every defect in batch 1 was caught by predicting
a number before the run and comparing — never by an exception. The ETL
completed successfully and produced a plausible frame in all four of its
broken states. Batch 2 has the same shape: Eurostat coverage will be partial,
and the expectation to check against is already written down (F13, roughly
1 350–1 400 of 1 514 zones populated).

---

## 5. Risk register

Carried forward so the weak points are visible before they are discovered at
review time rather than after. Licence and redistribution exposure is tracked
in `docu/SOURCES.md` and deliberately not duplicated here.

| Risk | Severity | Note |
|---|---|---|
| No open pan-European air fare source | high | the weakest link in the air layer; likely a scraped-sample fare model with an explicit limitation statement |
| Car OD may have no observed basis | high | if batch 0 returns nothing on TRIMODE/TRUST, the car layer is synthetic gravity against national totals. This is the assumption a DG MOVE reviewer is most likely to probe |
| Eurostat ↔ ICAO airport crosswalk | medium | small, boring, and a silent single point of failure — a partial join produces plausible output. Needs an explicit coverage assertion, mirroring the earlier name-only stop matcher that dropped 267 of 610 schedule stops |
| Batch 0 latency | medium | nothing has been sent yet; these gate DM5/DM6 and are the longest pole |
| Tier 2 attributes are a second acquisition | medium | batch 1 for the UK is one file, but batch 2 is not: Eurostat carries no UK regional statistics, so population, GVA, employment and overnight stays all come from ONS on ITL3 with a different structure and release cycle. If Tier 2 routing is close, this needs planning now |
| Large binaries in a public repository | low, once patched | `calib/raw/` and `calib/out/` were untracked by `.gitignore` (F19) |

---

## 6. Next actions

1. **Open batch 0.** Nothing has been sent. It has the longest latency and
   gates the two validation packages; every day it waits is a day added to the
   critical path, and it costs an afternoon of emails.
2. Settle O1 (base year) — cheap now, expensive after batch 4 downloads begin.
3. Re-download GHS-POP at **epoch 2020, 1 km** and re-run the GHS-POP cells
   (F17). The current file is epoch 2030 at 100 m.
4. Write `calib/etl/step1_zones.py` per concept §4 DM1a.
4. Re-download GHS-POP at epoch 2020, 1 km — a batch 2 prerequisite (F17).
5. Batch 2 acquisition — including the ONS/ITL3 track if Tier 2 routing is
   confirmed; then `demand.zones` in `db/schema.py` (D7).
6. Apply the `.gitignore` patch before the next commit (F19).

Deferred: licence and redistribution decisions, including the B1-07 population
attributes. Open TODOs sit in `docu/SOURCES.md`; they gate publication and
any Drive upload of derived data, not the calibration work itself.
