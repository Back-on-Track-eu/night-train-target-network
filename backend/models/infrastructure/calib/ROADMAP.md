# Infrastructure Calibration — Implementation Roadmap

Getting the infrastructure calibration from the repasted standalone state
(calib notebooks + `calc_tac.py`) to a fully seeded, fully wired
implementation on the fresh staging base. Structured by parameter domain;
the **Shared groundwork** section comes first because every domain depends
on it.

Snapshot state, verified 2026-08-08:

- Survived the repaste: `models/infrastructure/calib/**` (all notebooks,
  all domain `data/`, narrative MDs, `resolution.py`, README) and
  `models/infrastructure/calc_tac.py`, plus
  `tac/data/passage_geometries.geojson`.
- Lost with the merge-conflicted branch (must be recreated or salvaged
  from the dead branch's history): the TAC migration, all `params.py` /
  loader / `trip.py` / router / serializer / `calc.py` integration,
  `seed.py` consumption of `seed/*.csv`, and
  `tests/test_72_calc_tac_units.py`.
- `calc_tac.py` currently fails to import — `PassageChargeCollection`,
  `band_overlap_min` and the TAC component fields do not exist on this
  base.

---

## 0. Shared groundwork (before any domain)

**0.1 Salvage check — RESOLVED 2026-08-08.** The `calib-infra` branch was
deleted from GitHub the same day; the local clone (`...-calib-infra`
folder) was also gone, but a **zipped snapshot of that folder** turned up
in the Windows recycle bin (`project-snapshot-calib-infra.zip`) and was
inspected. Findings:

- No `.git` in the zip — working-tree files only, no history. Doesn't
  matter: content is what §1 needs, not commits.
- **Every item on the original salvage list is present as real file
  content**: the TAC migration
  (`2026-07-28_tac_calibration.sql`, 149 lines), `params.py`
  TAC-component fields + `PassageCharge`/`PassageChargeCollection`,
  `utils.band_overlap_min`, `Segment.countries`/`Segment.passages` in
  `trip.py`, `PassageIndex` in `rail_router.py`, the route-serializer
  round-trip incl. pre-0.9.13 fallback, `calc.py`'s
  `calc_segment_tac()` wiring, the `_row_to_track` group-NULL resolution
  in the loader, `seed.py`'s `_ensure_infra_seed_csvs()` +
  `_read_infra_csv()` consuming `sources.csv`/`track_tac.csv`/
  `passage_charges.csv`, and `tests/test_72_calc_tac_units.py`
  (499 lines). `create_input_params_schema.sql` mirrors the migration.
- `passage_geometries.geojson` is **not** in this zip either (same
  extraction miss as the first snapshot) — not a salvage concern, David
  confirmed he has it separately; just needs to be placed back into
  `tac/data/` when we get to §1.2/§1.4.
- **This is the mid-conflict working state, not a clean pre-conflict
  commit** — 9 files still carry unresolved `<<<<<<< HEAD` /
  `=======` / `>>>>>>> origin/staging` markers:
  `data_loader_from_db.py`, `api/helpers/dependencies.py`,
  `evaluation/version.py`, `route/route_factory.py`, `route/version.py`,
  `tests/README.md`, `tests/test_02_db_seed.py`,
  `tests/test_30_evaluation_content.py`, `tests/test_71_auth_units.py`.
  Severity varies — logged and resolved file-by-file as each is pulled
  into the working snapshot (see §1.4 below); most are small
  (`data_loader_from_db.py` is a single trivial import-order conflict,
  the actual `_row_to_track` logic is untouched).
- **Decision:** keep this zip as-is (not extracted into the working
  repo) until each piece is needed per the phase-by-phase steps below —
  pull, resolve any conflict markers against current staging, then
  integrate. Do not bulk-restore.

**0.2 Version reassignment — RESOLVED 2026-08-08.** Current staging truth
checked directly (fresh snapshot, not the salvaged zip): the standalone
`version.py` files no longer exist — since the `model.py`/formula-legend/
`schema.py` refactor, `ROUTE_BUILDER_VERSION` and `CALC_VERSION` now live
as constants inside each domain's `model.py`.

- `ROUTE_BUILDER_VERSION = "0.9.18"` — `backend/models/route/model.py`
- `CALC_VERSION = "0.9.14"` — `backend/models/evaluation/model.py`

Both have moved past every number seen so far: past the roadmap's earlier
guess (0.9.17 / 0.9.12), and past what the salvaged zip's *own*
conflict markers showed (`route/version.py` mid-conflict between
`0.9.13`/`0.9.16`; `evaluation/version.py` calib-side at `0.9.11`) —
staging kept advancing through WP-series work while `calib-infra` sat
parked.

**Decision: land one version up from current staging** —
TAC work targets **`ROUTE_BUILDER_VERSION = "0.9.19"`** and
**`CALC_VERSION = "0.9.16"`**.

> **Superseded in part, 2026-08-11.** `CALC_VERSION = "0.9.15"` was
> consumed by the roster-efficiency work (§0.4c) and merged to `calib`,
> so TAC takes the next patch, **0.9.16**. `ROUTE_BUILDER_VERSION` is
> untouched by that change and **0.9.19** still stands — but re-check
> both against `route/model.py` and `evaluation/model.py` at the moment
> TAC lands rather than trusting this line, since staging keeps moving.

These numbers get set when the salvaged
`route/model.py` and `evaluation/model.py` changes are pulled in and
resolved against the refactored file layout in §1.4 — the salvaged
`calc_segment_tac()` wiring and serializer round-trip logic transplants
into `model.py` (not a recreated `version.py`), and the changelog entries
follow the same relocated pattern the refactor established. Every earlier
mention of `0.9.17`/`0.9.12` in this document is superseded by this
entry.

**0.3 Sources to Google Drive.**

Inventory taken directly from both registers (salvaged infra zip +
current staging compositions folder — compositions is untouched by the
merge conflict, so its register is already the live one):

| Register | Data rows | Real named files to gather | Generic web/press citations (no file) | Blocked (`TO_FILL`/`TO_VERIFY`) |
|---|---|---|---|---|
| `infrastructure/calib/data/sources_register.csv` | 51 | 48 | ~2 (`ECB-FX`, `SKAT-DK-VAT` — live URLs, plus a couple of "via IRG TAC survey"/"...rates page" citations that aren't standalone files) | 1 (`NOX-MODEL`) |
| `compositions/calib/data/sources_register.csv` | 39 | 10 (`sources/*.pdf`) | ~27 (`web`, `press`, `oebb.at`, `bundesanzeiger.de`, etc. — citation-only, nothing to store) | 2 (`S12 fr_tet_audit`, `S16 cnl_takeover`) |

Neither register currently ships any of the underlying documents in git —
`url_or_file` is a filename/URL reference only; the PDFs/XLSX themselves
live solely on David's machine (or need re-fetching). This is the actual
scope of "gather the documents."

Steps:

**0.3.1 Gather.** For every row naming a real file, locate the document
on disk. **Infra: 45**, not the 48 first counted — four rows cite a live
page or a survey extract rather than a filename (`DK-BEK-2024`,
`EE-TTJA-2026`, `EUROSTAT-NRG-PC-205-C` and, as pure URLs, `ECB-FX` /
`SKAT-DK-VAT`), so there is nothing to store for them.
`SE-NS-2027` *does* name a PDF, with a page reference appended, and is
gathered. See `INFRA_SOURCES_CHECKLIST.md` for the tickable list.
**Compositions: DONE 2026-08-11** — 19 files gathered (10 register
rows plus nine that were not yet registered, now added as S42–S46 and
friends); sync check clean, zero orphans, zero missing. **Infra: 48
files still to gather.** Two
rows are cross-domain duplicates of the *same* file — `NOX-MODEL`
(infra) and `S01 nox_model` (compositions) both cite
`nox_model.xlsx` — gather once, don't collect it twice.

**0.3.2 Synchronization check** (Claude does this once files are staged
in a folder David points to): for each register, verify (a) every named
`url_or_file` has a matching gathered file — flag any row whose file is
missing, and any gathered file with no matching row (orphan); (b) no
silent filename mismatches (the register already has drift worth
watching for — e.g. `AT-SNNB-2026` → `SNNB_2026.pdf` vs `AT-SNNB-2027` →
`SNNB 2027.pdf`, underscore vs space for a near-identical source name);
(c) the `NOX-MODEL`/`S01` duplicate resolves to one file, one Drive
location, referenced from both CSV rows.

**0.3.3 Naming convention — SETTLED 2026-08-11.** The rule is that the
stored filename must be **derivable from the register**, so no extra
column is needed. It expands differently per domain because the id
schemes carry different information:

| Domain | Filename | Example |
|---|---|---|
| Compositions | `{source_id}_{short_id}.{ext}` | `S17_bvwp_update_2024.pdf` |
| Infrastructure | `{source_id}.{ext}` | `AT-SNNB-2027.pdf` |

Compositions ids are opaque sequence numbers, so the short_id is what
makes the file recognisable. Infra ids already encode country, document
and year — appending the short_id would restate all three, which it does
for 41 of the 45 files (`AT-SNNB-2027_at_snnb27.pdf`). `source_id` is
unique across the register and at most 21 characters, so it stands alone.

Consequence to expect: `NOX-MODEL` and compositions' `S01` are the same
underlying file stored under two names, one per domain folder. That is
the rule working, not a duplicate — gather once, reference twice.

Original reasoning below.

**0.3.3 (original note).** The
register's current filenames are inconsistent — spaces vs underscores,
original-publisher naming, a couple of description-as-filename entries
(`"via IRG TAC survey"`, `"TTJA rates page"`, `"nrg_pc_205_c custom
extract"` — these aren't files at all, they're citation notes, exclude
from the gather list). Recommend: rename on upload to
`{source_id}_{original-filename}` (keeps the source_id as an unambiguous
sort/search key, keeps the original name for human recognition,
eliminates the space/underscore drift going forward) — **confirm with
David before renaming anything**, since the register's `url_or_file`
column would then need a documented mapping to the Drive name (either
update the column to the new name, or add a `drive_name` column — decide
which).

**0.3.4 Upload & folder structure.** One Drive folder per register
(`infra-calib-sources/`, `compositions-calib-sources/`), flat (58 files
total across both — doesn't need subfolders by domain-within-domain).
Set sharing to link-viewable, verify a logged-out fetch doesn't hit an
auth wall (same check as any Drive-hosted asset in this project).

**0.3.5 Link into READMEs.** Add both folder links to the respective
calib `README.md` Provenance sections. Per the original decision, code
never downloads these — human-only reference, so no `*_FILE_ID` env var
needed here (contrast with §0.4's CSVs, which code *does* download).

**0.3.6 Backlog — cannot gather yet.** Three rows stay open regardless of
this pass: `NOX-MODEL`/`S01` (publisher unresolved, "TO_VERIFY (Nox
Mobility?)"), `S12 fr_tet_audit` (ART/Cour des comptes report, `TO_FILL`
throughout), `S16 cnl_takeover` (2016 CNL-fleet acquisition, needs a
primary source located to replace the secondary press citation). Track
these as their own follow-up, not blockers for the other 55 files landing
in Drive.

**0.4 Calibration data files — SUPERSEDED 2026-08-11 (no Drive hosting
needed).** Inspection of both domains established that **every** calib
data file is notebook-generated, so there is nothing to host: the
2026-08-08 Drive-zip decision below is void.

- Writer map, verified: compositions `01` writes all five `data/` CSVs
  (self-contained — every row a hardcoded tuple, no external reads);
  infra `01` writes `sources_register.csv`; each infra domain notebook
  (`tac/02`, `electricity/03`, `facility/04`, `route_context/05`) writes
  its own `data/` CSVs via the `emit()`/`write_data()` helpers —
  **including `passage_geometries.geojson`** (so the §0.1 note about
  manually re-placing it is moot).
- `seed.py` is unaffected: its stdlib-only exec of notebook 02 never
  reads `data/` — the calibrated values are constants in the compute
  cells, which only write `seed/*.csv`.
- **Consequence:** `INFRA_CALIB_DATA_FILE_ID`,
  `COMPOSITIONS_CALIB_DATA_FILE_ID`, the `calib_data.py` download helper
  and the zip-per-domain mechanism are all dropped from this roadmap.
  Instead: gitignore the generated outputs and regenerate from the
  notebooks (01 before 02 — 02's pandas cells read what 01 writes).
- **Gitignore additions — CORRECTED 2026-08-11.** Only the observation
  CSVs are ignored. `CALIBRATION.md` and `figures/` stay **tracked**:
  `docs/MODEL.md` is generated by `scripts/generate_model_docs.py` and
  committed, and that is the house precedent — a public advocacy repo
  should show the calibration document and its figures on GitHub rather
  than an empty directory and broken image links. The churn cost is
  accepted (matplotlib output is not byte-deterministic, so figures show
  as binary diffs on every regeneration).

  Paths are repo-root-relative — the `.gitignore` lives at the repo root,
  so the `backend/` prefix is required. An earlier draft of this block
  omitted it and the patterns silently matched nothing.

  ```gitignore
  # Calibration observation tables — generated by the calib notebooks
  # (01_source_extraction.ipynb / 02_calibration.ipynb, per domain).
  # Re-run the notebooks to regenerate; never hand-edit.
  backend/models/compositions/calib/data/
  backend/models/infrastructure/calib/data/
  backend/models/infrastructure/calib/*/data/
  ```

- **Open item:** the infra `calib/**/data/` CSVs were committed with the
  §0.1 restore before this rule existed, so the gitignore entries above
  do not untrack them. Clear them when §1 next touches those files:

  ```powershell
  git rm --cached -r backend/models/infrastructure/calib/data `
                     backend/models/infrastructure/calib/*/data
  ```

- Drive remains in scope **only** for §0.3's source documents (the
  gathered PDFs/XLSX), which genuinely are irreplaceable inputs.

**0.4b Compositions full synchronization — DONE 2026-08-11.** Decided and
implemented: notebooks are the single source of truth for *everything*
derived — data CSVs, figures, `CALIBRATION.md` and the seed CSVs; the
"Generated by 02" claim in the doc is now true.

- `01_source_extraction.ipynb`: register widened to 13 columns
  (`used`, `downloaded`; Excel note column folded into
  `reliability_note`), S42–S46 added, URLs researched and filled
  (9 honest `MISSING`s remain: S03, S12, S22–S24, S26, S27, S33, S34),
  `REGISTER_REVIEWED` date constant, cited-but-Not-Used integrity
  assert. S13 kept (19 provenance references depend on it). Drive
  filename convention settled by the gathered files themselves:
  `{source_id}_{short_id}.{ext}` — derivable, no extra column.
- `02_calibration.ipynb`: new figure cell regenerates all **12** figures
  referenced by the doc (previously: 2 reproducible, 2 orphaned on disk,
  8 missing); new generator cell holds the full document as a tokenised
  template (judgment prose verbatim) and injects every computed value —
  tables, fleet averages, and a **full sensitivity recomputation engine**
  (availability capped at 1.0, revenue-side rows analytic). Guards:
  unsubstituted-token assert, referenced-figures-exist assert; matplotlib
  reference keeps the cell out of seed.py's stdlib exec (verified: seed
  path executes cells [2,5,6,7,9,11,13,15,22], produces all 7 seed CSVs,
  doc untouched).
- Match check generated-vs-old: **6 changed lines of 765** — the
  generation date; the review-box maintenance value 1.05 → 1.30 (stale,
  predated the 2026-07-21 price-basis escalation); and two arithmetic
  errors in the old doc now corrected by exact recomputation
  (var-overhead +0.98% → **+0.99%**; EBIT ±50% +6.94% → **+6.49%** =
  0.82/0.77 − 1). Two stale-prose items flagged for David's review, kept
  verbatim: the results-section crew-staffing sentence
  ("0.25 attendants per seat coach") vs the workbook's actual per-coach
  factors, and the "Reading the fleet" paragraph naming retired catalog
  ids (NEW-DD-12, REF-SEAT-13).
- Old §0.4 text kept below for the record; its mechanism items no longer
  apply:

- **Bundle per domain, not per file.** 20 individual CSVs (11 infra + 9
  compositions) would mean 20 env vars; instead each domain's `data/`
  tree is zipped as one Drive file, relative paths preserved inside:

  | Domain | Drive file | Env var | Extracts to |
  |---|---|---|---|
  | Infra calib | `infra_calib_data.zip` | `INFRA_CALIB_DATA_FILE_ID` | `calib/data/`, `tac/data/` (incl. `passage_geometries.geojson`), `electricity_pricing/data/`, `facility_calibration/data/`, `route_context/data/` |
  | Compositions calib | `compositions_calib_data.zip` | `COMPOSITIONS_CALIB_DATA_FILE_ID` | `compositions/calib/data/` |

- **Figures dropped from git.** `compositions/calib/figures/*.png` (4
  files, notebook outputs, not sources) are removed from the repo
  entirely and regenerated by re-running `02_calibration.ipynb`'s display
  cells — no Drive hosting needed, they're derived twice over.
- **Shared helper.** Generalize `seed.py`'s `_download_ontd_seed_stops()`
  into one reusable function, new `backend/db/dev/calib_data.py`, reusing
  `drive_download_url()` from `db/ontd/xlsx_utils.py` rather than
  duplicating the URL logic: download zip → validate it's actually a zip
  (not an HTML permission-error page — same failure mode ONTD already
  guards against) → extract → same soft-fail warning banner if
  missing/broken, so a Drive outage doesn't take `seed.py` down under its
  `set -e` entrypoint.
- **Trigger point.** Must run *before* `_ensure_calib_seed_csvs()` /
  the future `_ensure_infra_calib_seed_csvs()` — those exec the
  notebooks' stdlib cells against the domain `data/` files, which have to
  exist locally first.
- **Gitignore.** `backend/models/infrastructure/calib/**/data/` and
  `backend/models/compositions/calib/data/` +
  `backend/models/compositions/calib/figures/` — notebooks, `resolution.py`,
  READMEs and `*.md` narratives stay tracked.
- **Status:** mechanism to be built in step 3 below (infra) — David
  uploads both zips and supplies the two file ids when we reach that
  point; ids are not yet available, do not block earlier steps on them.

**0.4c Roster efficiency + branch reconciliation — DONE 2026-08-11.**
Landed alongside the compositions work, since it changes the same seeded
rates:

- **Dienstplanwirkungsgrad is now a model variable, not a constant.**
  `operator_driver_costs_eur_h` / `operator_crew_costs_eur_h` hold RAW
  productive-hour wages (54.16 / 48.75); five new `operators` columns
  carry the roster parameters (`_driver_max_duty_h` 8.0,
  `_crew_max_duty_h` 10.0, `_driver_roster_eff_ref` 0.60,
  `_crew_roster_eff_ref` 0.70, `_relief_allowance_h` 2.5). Evaluation
  computes efficiency **per trip** — driver basis is driving time
  (Directive 2005/47/EC caps a night shift at 8 h), crew basis is time on
  train — and each relief adds a fixed unproductive allowance, so
  efficiency sawtooths: down at each duty boundary, recovering as the
  allowance amortises. `CALC_VERSION → 0.9.15`. Short routes are
  unaffected (a 6 h-driving trip still prices the driver at 90.27, the
  old flat figure); the reference night route rises ~17% on both rates.
  Thresholds are per-operator DB columns, not hardcoded — both seeded
  operators simply share the same values today.
- **Crew factor corrections:** refurbished seat coaches gain 0.25
  attendants (legacy stock has no door sensors, so despatch needs a
  visual check and seat coaches otherwise carry nobody); `WLABee`
  corrected 0.00 → 1.00 to match every other sleeper type. New stock
  unchanged at 0. Fleet average 36.58 → 38.90 €/train-km.
- **`operator_driver_overhead_h` / `_crew_overhead_h`:** the open
  follow-up to drop them was already satisfied by migration
  `2026-07-21_calibration_v2.sql`. Only stale documentation remained,
  now corrected — including the two step-3 justifications that argued
  the columns were zeroed to avoid double-counting standby and
  positioning, which the roster model now prices explicitly.
- **Branch reconciliation:** `calib` was nine commits behind staging and
  predated the `version.py → model.py` rename, which is why seeding
  failed silently (`seed_example_proposal()` swallows exceptions; it was
  hitting `No module named 'models.demand.model'`, leaving
  `proposals.*` empty and 19 tests failing). Merged
  `origin/staging`; `db/schema.py` and `evaluation/model.py` resolved
  add/add to the local copies (staging's files plus the roster
  additions, verified by diff), `STOP_CLASSIFICATION.md` resolved to
  staging's copy — the local deletion was collateral from the recovered
  snapshot, not a decision. **512 tests pass.**
- **Bjarne:** informational only, no `api.ts` change. Response keys are
  unchanged; the CALC formula legend gains entries (additive) and
  `driver_eur`/`crew_eur` change value. Worth flagging that
  `/params` `costs_per_hour` now reads lower because it is pre-roster.

**0.5 Source register seeding (shared by every domain).** Add
`_ensure_infra_calib_seed_csvs()` to `db/dev/seed.py`, cloned from the
compositions mechanism: exec the stdlib-only cells of
`06_seed_export.ipynb` when `calib/seed/` files are absent. Verify 06
still honours the stdlib-only contract (no pandas, no `resolution.py`
import) on this base. Insert `seed/sources.csv` into
`input_params.sources` with the `source_key`-prefix convention that the
per-country `_src` FK resolution relies on.

---

## 1. Track access charges (TAC)

The only domain with an implemented calc module. Order is bottom-up so
each layer is testable before the next builds on it.

### 1.1 Review

- Re-run `01_source_extraction.ipynb` and `tac/02_tac_calibration.ipynb`;
  confirm they execute cleanly against the committed `tac/data/` CSVs and
  reproduce the reference numbers in `TAC_MODEL.md`.
- Re-read `TAC_CALC_DESIGN.md` against `calc_tac.py` line by line — it is
  the only surviving spec for the lost integration. Reconfirm the two
  judgement calls: active conservative peak defaults (AT/CH) and the DE
  accommodation band-widening.
- Verify `passage_geometries.geojson`: `crossing_id` properties must match
  `passage_charges.csv` (`STOREBAELT`, `OERESUND_DK`/`OERESUND_SE` sharing
  one `OERESUND` polygon, `CHANNEL_TUNNEL`).

### 1.2 Schema

Recreate `db/dev/sql/migrations/2026-07-28_tac_calibration.sql` (keep the
filename the docs cite, or redate and fix the doc references). Derive the
column set from `calc_tac.py`'s reads plus 06's `track_tac.csv` export:

- `track_infrastructures` **and** `track_infrastructure_defaults`:
  `track_tac_b_day`, `_b_night`, `_gamma`, `_seat_km`,
  `_fixed_per_train_km`, `_per_stop`, `_revenue_share`,
  `_peak_multiplier`, `_congestion_surcharge`; night-mode columns
  (`track_tac_night_mode`, band start/end,
  `track_tac_night_full_if_accommodation`); peak-band columns (two bands
  + `track_tac_peak_weekdays_only`). Flat `track_tac_eur_train_km` stays,
  display-only.
- New `input_params.passage_charges` — fifth scenario-versioned table,
  full-snapshot contract: `passage_id`, name, `charged_by`, per-train and
  per-passenger EUR components, PostGIS geometry, source FK.
- Mirror everything into `create_input_params_schema.sql` (fresh-DB path
  must equal migrated path).

### 1.3 Seeding

- Merge `seed/track_tac.csv` onto seed.py's canonical country rows,
  replacing the hardcoded flat values in `_TRACK_INFRA_CANONICAL_ROWS`.
  Preserve SE's NULL flat (is_default test fixture; its component group is
  seeded normally).
- Insert `seed/passage_charges.csv` via `ST_GeomFromGeoJSON`.
- Verify: fresh stack, empty DB → schema → seed; spot-check DE night
  mode, AT congestion surcharge, CH per-stop, Øresund's two rows on one
  polygon.

### 1.4 Model integration

1. `models/utils.py`: `band_overlap_min` (wrap-safe minute arithmetic).
2. `models/params.py`: TAC component fields on `TrackInfrastructure` +
   `DefaultTrackInfra`; `PassageCharge` / `PassageChargeCollection`;
   `Composition.has_night_accommodation` (any place class not
   Seat/Catering); confirm the gross-weight property name `calc_tac.py`
   expects (`total_gross_weight_t`) or align it with the existing
   `total_weight_t()`.
3. `adapters/data_loader_from_db.py`: load component columns; group-NULL
   resolution in `_row_to_track` (default substitution **only** when
   `b_day`, `b_night` and `gamma` are all NULL — a lone NULL is a
   documented "not levied", never missing data); load passage charges;
   extend field-source provenance mapping.
4. `models/route/trip.py`: `Segment.countries: list[str]` (routing path
   order) and `Segment.passages: list[str]`, both defaulting empty so old
   payloads stay constructible.
5. `models/route/routing/rail_router.py`: `PassageIndex` — load crossing
   polygons, intersect trip legs, attribute each crossing to exactly one
   segment per trip; populate `Segment.countries`.
6. `api/helpers/route_serialize.py`: round-trip `countries` and
   `passages`; fall back to `country_distance_shares.keys()` for
   pre-0.9.19 payloads (stale routes stay evaluable, clock placement
   approximated). Bump `ROUTE_BUILDER_VERSION → 0.9.19` (in
   `route/model.py`, per §0.2 — verify it is still free) + changelog.
7. `models/evaluation/calc.py`: replace the flat
   `tac_eur += km * share * tac_eur_train_km` loop in `_calc_segment_cost`
   with `calc_segment_tac(...)`; resequence so the traffic pre-pass
   (per-segment passengers/revenue) runs **before** segment costs —
   Channel Tunnel per-passenger fee and the CH Deckungsbeitrag plumbing
   need its outputs. Surface the `SegmentTac` breakdown into
   `SegmentCost` as far as views need. Bump `CALC_VERSION → 0.9.16`
   (in `evaluation/model.py`, per §0.2 — 0.9.15 is taken).

### 1.5 Tests

- Recreate `tests/test_72_calc_tac_units.py` from the worked examples
  pinned in `calc_tac.py`'s docstring and `TAC_MODEL.md`: the five DE
  night-band cases, gamma-only countries (FI), peak blending with
  `WEEKDAY_BLEND`, first-segment double-ended per-stop charging, passage
  attribution, the absurd-flat-999 999 guard proving the flat column is
  never read, SE is_default.
- Extend `test_30_evaluation_content.py`: TAC breakdown survives to the
  API response.

### 1.6 Docs

- Calib README (seed contract now real, Drive links), TAC_CALC_DESIGN.md
  (new version numbers), route/evaluation `version.py` changelogs,
  `AGENTS.md` if parameter-placement examples mention TAC.
- If the evaluation views gain new keys: add them to the **Bjarne
  coordination batch** for `frontend/src/types/api.ts`.

---

## 2. Traction electricity pricing

- Re-run `electricity_pricing/03_…` notebook; confirm against
  `ELECTRICITY_PRICING.md`.
- Schema: extend the migration with the price-mode columns 06 exports
  (check `electricity_price_modes.csv` for the exact shape — e.g. CH's
  22:00–06:00 band belongs here, not to TAC).
- Seeding: `energy_price_eur_kwh` (and mode columns) per country from
  `seed/track_infrastructures.csv`, replacing the hardcoded values.
- Model: decide whether `calc.py` prices a night/day electricity split
  where a country defines one, or keeps a single blended rate for now —
  decide once, document in ELECTRICITY_PRICING.md, and record it as a
  CALC changelog entry if behaviour changes. The existing per-country
  `energy_kwh × share × price` loop is the integration point.
- Tests: per-country price resolution incl. default fallback; blended vs.
  banded pricing if implemented.

## 3. Shunting & parking (facility charges)

- Re-run `facility_calibration/04_…`; confirm against
  `SHUNTING_PARKING.md` and `facility_reference_rotation.csv`.
- Schema/seeding: per-event shunting and parking columns from the calib
  export, replacing hardcoded values.
- Model: these are per rotation/terminal event, not per segment —
  integration point is the route-level fleet/rotation cost section of
  `calc.py`, not `_calc_segment_cost`. Map the reference rotation's event
  counts onto the model's trip-pair structure before writing code; settle
  that design in a short addendum to SHUNTING_PARKING.md first.
- Tests: event counting on a reference trip pair, per-country rates,
  default fallback.

## 4. Route context (terrain, buffer, dwell)

- Re-run `route_context/05_…`; confirm against `TERRAIN_AND_BUFFER.md`.
- These feed **routing** (buffer quotas, terrain speed context), not
  evaluation — verify against the existing country buffer-quota mechanism
  behind `Segment.buffer_time_min` before changing anything.
- Known flattening: `track_terrain_category` is constrained to
  Flat/Hilly/Mountainous — the five model bands map down, T2/T3 both
  become Hilly (already flagged in the calib README; keep flagged).
- Seeding: terrain/buffer/dwell columns from the calib export.
- Any behavioural change to routing → ROUTE_BUILDER patch bump with
  changelog; if none, seeding-only.

## 5. Stop/station charges — RESERVED

`calib/stops/` stays a placeholder. Do not fold station usage fees into
TAC (the CH Haltezuschlag is a path-capacity element and already lives in
TAC by design). Revisit after 1–4 land.

---

## 6. Wrap-up

- Full suite (`uv run --extra dev pytest tests/ -v`) against the live
  stack; fresh seed from an empty DB through migrations.
- Un-hardcode remaining `seed.py` infra values only as each domain's
  model consumption lands (README defers this deliberately).
- Commit split per domain: `feat` / `test` / `docs`.
- PR `backend-dev → staging`; frontend coordination table for any new
  API keys.

## Suggested execution order

| Step | Scope | Size |
|---|---|---|
| ~~0~~ | ~~§0.1 salvage, §0.2 versions, §0.4 data-file policy, §0.4b/c compositions + roster~~ — **DONE 2026-08-11** | — |
| 1 | §0.3 infra sources: gather 45 files, sync check, regenerate the register — **NEXT** | ½–1 day |
| 2 | §1.1 TAC review (re-run 01 + tac/02, verify geojson crossing_ids) | ½ day |
| 3 | §1.2–1.3 TAC schema + seeding (incl. untracking infra `calib/**/data/`, per §0.4) | 1–1.5 days |
| 4 | §1.4–1.6 TAC model integration + tests + docs | 2–3 days |
| 5 | §2 electricity | ½–1 day |
| 6 | §3 shunting/parking | 1 day |
| 7 | §4 route context | ½–1 day |
| 8 | §6 wrap-up + PR | ½ day |

**§0.3 moved to the front (David's call, 2026-08-11).** Technically the
sources gate nothing — they are provenance for values already captured in
the calibration CSVs, not inputs the notebooks read — but the register is
read constantly during §1.1–1.3, and hunting one document mid-review is
worse than hunting forty-five in a single pass. The blocked entries
(`NOX-MODEL`/`S01` duplicate, plus compositions' `S12`/`S16`) stay open
regardless and do not hold up the step.

The old step-2 entry built a Drive download mechanism for the calib CSVs;
§0.4 established there is nothing to host — every calib data file is
notebook-generated — so that work is dropped, not deferred.
