# Handover — stops and station charges

**To:** Josh · **From:** David · **2026-09-01**
**Where:** `backend/models/infrastructure/stops/` — read `README.md` first
for how the pipeline fits together; this document is only the task list.

Three parts. The first is closed and you only need to know what happened.
The second is a review pass that is yours because it needs a railway
person's eye. The third wouzld be also your task.

---

## 1. Closed: the missing stops

We figured a couple stations not in the database like Berlin-Spandau, #
Berlin Ostbahnhof, Tallinn, Riga, Madrid and Bordeaux. Not having them in the 
database anymore meant, that we actually have a pipeline bad fix 
(as we had them in before).

**What went wrong.** Step 5 (current night train stops) went live against
the ONTD workbook on 2026-08-28, which changed which stations it qualifies.
Step 6 had been pruned four days earlier against the *old* step 5, so every
station that step 5 then lost, and step 6 no longer carried, left the
catalog silently — Berlin Gesundbrunnen and Spandau, Frankfurt (Main) Hbf,
Paris Est, København H, Madrid Atocha, London King's Cross, Lyon Part-Dieu,
Göteborg C, Lausanne, Genève, Luxembourg, Riga, and so on. Running the
frozen schedule export against the current catalog found **128 stations
that belong in it and were not** — 122 with no catalog stop within 2 km,
plus the big-city second stations that check hides (Paris Est is 490 m
from Gare du Nord, Frankfurt Hbf 1.8 km from Süd) and the Paris termini
that were never in any export.

**What was done.**

- `step6_gap_closure_2026-09.csv` (tracked, next to the notebook) is the
  record: 128 additions with a `reason` and `infra_versions` each, the 32
  stations deliberately *not* added with why, 3 marked for review, 2
  deferred (Rail Baltica stations not yet in OSM as stations).
- `step6a_resolve_candidates.py` turned that CSV into the step 6 lines,
  matching against step 3b the way step 5 matches the schedule (coordinate
  first, name second) and applying step 6's guards before printing. **The
  126 resolved lines are pasted into the notebook** under a
  `2026-09 gap closure` comment in each regional dict; every pick was
  read by eye (Atocha's mainline node, not the Cercanías object; the new
  Imperia station, not closed Oneglia; Uman's railway station, not its bus
  terminal). Steps 6, 7 and 10 were run: the catalog is **1,176 stops**
  (was 1,050), Germany's 105 charges are in it, and the illustrative
  placeholder charges are gone.
- Step 10 now writes `data/step10_dropped_stops.csv` on every run — every
  stop the previous catalog had that the new one lacks — so this class of
  loss can never be silent again.
- Every step 6 addition now says which **infrastructure version(s)** it
  belongs to (`infra-2026;infra-2032` default, `infra-2032` for Rail
  Baltica and the like, `infra-2026` for a station a 2032 upgrade
  bypasses), and the catalog carries it as `infra_versions`. Seed-side
  consumption is a later work package; today it is a tag.

You do not need to act on any of this. The only thing worth knowing is that
if ONTD later starts serving one of these stations again, step 6's
duplicate guard will refuse to run until that line is deleted — by design,
thirty seconds, and the guard tells you which line.

Two step 6 picks are now redundant and are yours to drop or re-reason when
you are in the notebook: **Росинка** (step 5 has Луцьк 1.5 km away) and
**Kırkikievler** (step 5 has İzmit 2.3 km away).

---

## 2. Yours: the expert review

The closure restored what the data said was missing. It cannot say what a
target network needs that no schedule ever had. That judgement is the
reason step 6 exists and it is yours. Try to fetch more stop data (manually)
that you think we need in there.

### 2.1 What to e.g. look at

Load `data/stop_seed_catalog.csv` in QGIS as a point layer (lat/lon are
WGS84), colour by `provenance`, and look with the target network in mind:

- **Corridors with no stop for 150+ km** where a night train would plausibly
  call — the classic gaps are junctions and second-tier cities on the
  routes between hubs, not the hubs.
- **Functional urban areas with nothing** — the GISCO FUA polygons are the
  honest reference (link in the README step table); 15 km around a
  qualified stop is the proxy the notebook uses.
- **Tourism destinations** night trains historically serve because they are
  small: Alpine resorts, coasts, lakes. Population-based picks miss them.
- **Border and interchange stations** on corridors you know cross a gauge or
  system boundary.
- **The wrong object**: a step 6 pick sitting on the S-Bahn/metro/bus
  object next to the mainline station. The guard blocks `urban_transit`,
  but `undecided` gets through and 41 % of step 3b is `undecided`.

`data/step6_overlap_review.csv` lists every `fua:` addition with a
qualified stop within 15 km — most are legitimate (Göteborg C next to
Mölndal), some are not. Worth a pass while you are at it.

Whatever tool you prefer is fine — QGIS, kepler, a printed map. The output
we need is a documented list, not a method.

### 2.2 How to add what you find

Do not look ids up by hand. Copy `step6_gap_closure_2026-09.csv` to a new
file, keep the header, and add one row per station:

| column | what |
|---|---|
| `name` | display name |
| `search_name` | what to look for in the OSM name — `Spandau`, `Коростень`; empty means use `name` |
| `osm_stop_id` | only if you already know it |
| `lat`, `lon` | where the station is |
| `coord_source` | `schedule` if you trust the coordinate (1.5 km search), `corrected` if typed from memory (2.5 km) |
| `region` | the `ADDITIONS_*` dict it belongs in — `GERMANY`, `FRANCE`, `IBERIA`, `ITALY`, `UNITED_KINGDOM`, `NORDICS`, `CENTRAL_EUROPE`, `BALTICS`, `SOUTH_EASTERN_EUROPE`, `EASTERN_EUROPE` |
| `country` | ISO-2 |
| `reason` | `fua:<city>`, `tourism:<region>`, `ferry:<port>`, `border`, `network`, `night_train_stop` — filled, never a placeholder |
| `infra_versions` | `infra-2026;infra-2032` unless the station does not exist yet (`infra-2032`) |
| `note` | why, in one line — it becomes the code comment |
| `decision` | `add` |

Then, from `backend/models/infrastructure/stops/`:

```
uv run python step6a_resolve_candidates.py my_batch.csv
```

It prints one block per regional dict — paste each into
`step6_manual_additions.ipynb`. Anything it could not resolve
unambiguously is listed at the end with the nearest OSM objects; pick by
hand and write the line yourself. Then the chain, none of it optional:

```
uv run --extra dev jupyter lab
#   step6_manual_additions.ipynb   → data/step6_manual_additions.csv
#   step7_enrich_stops.ipynb       names, city, languages for the NEW stops
#   step8_stop_gauges.ipynb        gauges (Overpass, append-mode)
uv run python step10_export_seed_stops.py
```

Step 10 aborts if step 7 was skipped — a new stop with empty enrichment
would be a quieter version of the same staleness. Check its
`dropped_stops` line and its "by infra_versions" line, then upload
`data/stop_seed_catalog.csv` to Drive as a new version of the same file
(id `1QfkYrX5Fc5N0JqFLx5FWEaaZ6z0YCM6c`), `uv run ruff format .` from
`backend/`, commit the notebook and your candidates CSV (data/ is
gitignored — notebooks and candidate files are the truth), and tell me so
I can reseed.

If a night train **demonstrably calls somewhere today** and it is not in
step 5, that is an ONTD gap: add it to step 6 as `night_train_stop`
*and* report it upstream. Step 6 is a patch over ONTD coverage debt, not a
fix for it.

---

## 3. The other task: station charges

Every stop in the catalog costs the same **11.28 EUR per call** in the cost
model, because no sourced station charge outside Germany has landed — and
Germany's have not landed either. Your task would be adding as many stop 
charges you can, one CSV per country, all in one shape.

### 3.1 Where it actually stands

`README.md` said Germany was finished. The DE source file
(`charges/sources/de_station_charges.csv`, 105 rows from *Stationspreisliste
2026*) is fine, but:

- **It never reached the catalog.** `charges/data/station_charges.csv` is a
  stale pre-template file from 18 August with 13 illustrative placeholder
  rows, and that is what the published catalog carries. 02 and step 10
  were not re-run after DE landed, and `charges/data/` is gitignored so
  nothing carried it.
- **It could not be loaded before the gap closure.** 21 of its 105 rows
  pointed at stations that had dropped out of the catalog — Frankfurt Hbf,
  the Berlin stations, Dortmund — and the reader raises on an unknown id
  rather than skipping. That is deliberate and it did its job: those 21
  ids are how the stations came back with the same identity.
- **Germany needs 11 more rows.** The closure adds 23 DE stops
  (Frankfurt Hbf, Dortmund, Regensburg, Bamberg, Lübeck, Passau, …); 21
  of them already have a row in the DE file — that is where their ids came
  from. **Rastatt and Timmendorfer Strand** need looking up in the
  Stationspreisliste. Nine DE stops that step 5 qualifies also have no row
  — Hanau, Bitterfeld, Bruchsal, Oberhausen, Baden-Baden, München Süd and
  Pasing, Frankfurt Flughafen Fernbahnhof, Lörrach Autoreisezug Terminal.
  Look them up too; the two München yards may legitimately not be in the
  price list, in which case leave them out and say so in the DE file's
  notes.

**Status after the closure run (2026-09-01):** 01, 02 and step 10 have
been run against the closed catalog — `105 station charges (0 still
illustrative)`. The DE file loads cleanly again (its 21 "unknown" ids were
exactly the restored stations), and the 13 illustrative placeholder rows
are gone for good. So the path works end to end; from here every run is
the one in §3.3, and a country file that raises is telling you something
real.

### 3.2 The gap, by country

Johanna investigated which countries levy a station charge at all. Her
finding was a list of 13 that levy **nothing** — **BE, CZ, DK, EE, FR, GR,
HR, IE, LU, LV, NO, PL, SE**. The notebook it came from has since been
deleted and it cites no documents, so treat it as **a hypothesis to test,
not a result to inherit**. If a country really levies nothing, that is a
tariff fact and it gets a file too — same template, empty
`charge_excl_vat_eur`, a `note` and `source_ref` naming the network
statement that says so. A missing file cannot be told apart from a country
nobody has looked at.

Stop counts are the current catalog plus the September closure. Order is
by coverage, which is why France and Poland come before Italy despite being
on Johanna's list — 178 stops ride on whether she was right.

| # | Country | Stops | Johanna: no charge? | Status / note |
|---|---|---|---|---|
| — | DE | 116 | | 105 rows sourced (`DE-DB-SPL-2026`), not landed; 11 stops to add — §3.1 |
| 1 | BG | 99 | | |
| 2 | FR | 95 | **yes** | verify from the SNCF Réseau / SNCF Gares & Connexions DRG; large |
| 3 | IT | 88 | | RFI PIR, station categories |
| 4 | RO | 83 | | CFR network statement |
| 5 | PL | 83 | **yes** | verify from the PKP PLK network statement; PKP SA runs the stations |
| 6 | UA | 71 | | **now seeded** — no longer skippable (was "not needed" in the old list) |
| 7 | GB | 58 | | Network Rail station long-term charge / station access conditions |
| 8 | ES | 53 | | Adif Declaración sobre la Red, station categories |
| 9 | AT | 49 | | Johanna had figures, **no source** — redo from ÖBB Infra SNNB |
| 10 | TR | 36 | | now seeded |
| 11 | SE | 35 | **yes** | verify from Trafikverket JNB; Jernhusen owns the stations |
| 12 | HU | 31 | | MÁV network statement |
| 13 | SK | 30 | | Johanna had figures, **no source** — redo from ŽSR |
| 14 | NL | 30 | | ProRail netverklaring |
| 15 | CH | 25 | | SBB Infra Leistungskatalog |
| 16 | NO | 23 | **yes** | verify from Bane NOR network statement |
| 17 | FI | 22 | | Väylävirasto |
| 18 | CZ | 20 | **yes** | verify from Správa železnic |
| 19 | DK | 16 | **yes** | verify from Banedanmark |
| 20 | BE | 15 | **yes** | verify from Infrabel |
| 21 | RS | 14 | | |
| 22 | HR | 13 | **yes** | verify from HŽ Infrastruktura |
| 23 | PT | 10 | | Johanna had figures, **no source** — redo from IP |
| 24 | ME | 9 | | |
| 25 | GR | 8 | **yes** | verify from OSE |
| 26 | EE | 7 | **yes** | verify from Eesti Raudtee |
| 27 | IE | 6 | **yes** | verify from Iarnród Éireann network statement |
| 28 | LT | 6 | | LTG Infra |
| 29 | SI, LV, MK, MD | 5, 5, 5, 4 | LV yes | |
| 30 | BA, AL, LU | 4, 2, 1 | LU yes | |
| — | XK | 2 | | not seeded — skip |

Publisher names in the last column are where I would start looking; they
are pointers, not sources. The source is the document you register.

### 3.3 The mechanism

```
network statement / station price list (PDF or XLSX, per country)
        │  ① register the document in 01_source_extraction.ipynb
        │  ② transcribe via AI (e.g. Claude) into the twelve-column template
        ▼
charges/sources/<cc>_station_charges.csv        ← your deliverable, CHECKED IN
        │  ③ one line in CHARGE_FILES in 02_station_charges.ipynb
        ▼
charges/data/station_charges.csv                 generated, gitignored
        │  ④ step10_export_seed_stops.py joins it onto the catalog
        ▼
data/stop_seed_catalog.csv → Drive → seed.py → the cost model
```

The template is `charges/sources/TEMPLATE.md` — twelve columns, read it
before writing a row. `de_station_charges.csv` is the worked example.

Per country:

1. Find the document. Put it in `charges/sources/` (gitignored).
2. Register it in `01_source_extraction.ipynb`: one tuple, same column order
   as the DE entry, `downloaded` = `x`, `price_basis_year` as printed.
   Every charge row must cite a `source_ref` that exists here, or 02 raises.
3. Transcribe into `charges/sources/<cc>_station_charges.csv`. Comma
   separated, UTF-8, `.` as decimal — convert the document's own `;` and
   `,` yourself. `stop_id` is the catalog id, resolved **by you, once, while
   transcribing** — filter `stop_seed_catalog.csv` by `country_code`.
4. One line in `CHARGE_FILES` in `02_station_charges.ipynb`.
5. Run 02, then `uv run python step10_export_seed_stops.py` from `stops/`.
6. `cd backend && uv run ruff format .`; commit the notebooks and your source
   CSV; upload the catalog to google drive as a new version of the same file.

The reader **raises rather than skips**: an id the catalog does not have,
a header off the template, a foreign `country_code`, or net × VAT ≠ gross
all stop the run. A skipped row would be a station quietly reverting to
11.28 EUR, which looks exactly like a station nobody has priced.

Rules that make the files comparable, all in `TEMPLATE.md`:

- **Only sourced values.** No estimates, no interpolating between a
  country's tariff classes for a station the document does not list. A stop
  with no defensible figure is left out and resolves through the default.
- **One charge per stop, one night train, one call.** Where a document
  prints several figures, take the one a night train pays and say which in
  `note` (Germany: SPFV, not SPNV).
- **Both money figures and the rate**, as printed, so the VAT check is a
  real check.
- **Published year as printed.** Escalation to 2032 happens once, later,
  across all countries.
- **Never hand-edit `charges/data/station_charges.csv`.** Notebooks are
  truth.

Two integration tests skip until one sourced charge outside Germany
exists — `test_04_versioning.py::test_stop_explicit_charge_is_not_default`
and `test_10_params_api.py::test_is_default_flags_via_api`. When they start
running, the whole path works.

### 3.4 Using an LLM to produce the CSVs

Fine for transcription — turning a price list into the twelve columns is
mechanical and the format is exactly what a model is good at. Two
conditions, not negotiable:

**Every figure must come from the document.** The failure mode on a tariff
table is not a garbled number, it is a *plausible* one: an interpolated
value for a station the document does not list, a category average
presented as a station's charge, last year's figure in this year's column.
None of those look wrong in the file. The discipline "only sourced values,
leave a station out rather than invent one" lives in your review, not in
the reader.

**The pipeline's checks are format checks, not truth checks.** They catch a
mistyped digit, an unknown id, a wrong header. They cannot catch a
well-formed invention. So:

- Have the model transcribe **both** money columns where the document
  prints both. If it computes gross from net, the VAT check becomes a
  tautology — and it is the cheapest error-catcher you have.
- **Spot-check ten rows per country by hand** against the PDF page, drawn
  from across the table. One wrong row means the file is redone, not
  patched: a model that invented one row invented others.
- `station_printed` is the name **exactly as printed**. It is what makes a
  figure findable again, and what lets anyone audit the file without you.
- **Never let a model pick the `stop_id`.** That is the step where a wrong
  answer is invisible and expensive — it charges the wrong station. You
  do it, from the catalog filtered by country.
- Which of several published figures a night train pays is **your**
  decision, recorded in `note`. Modelling judgement, not transcription.

A scanned document, or a table extraction that looks unreliable: transcribe
by hand with the page cited. A number someone can check beats a parsed one
nobody can.

---

## 4. Loose ends worth knowing

- `charges/HANDOVER.md` is now a pointer here; its §3 ("TR, UA, MD, MK, XK
  are not seeded — skip") was wrong since `seed.py` gained those countries.
  Only XK is still dropped at seed time.
- `infra_versions` in the catalog is **not** `stop_infra_version` in the
  DB — the latter is the integer snapshot number of the stop table. Do
  not conflate them if you are in `seed.py`.
- `data_sources.py` still lists a 7-column expected header for
  `stop_seed_catalog.csv`. Nothing calls `ensure_local` on that file, so it
  is dead — but it is wrong (36 columns), and it will bite whoever does.
- Three stations are marked `review` in the closure CSV — Poltava
  (the schedule called at Полтава-Південна, the main station; the catalog
  has Полтава-Київська 6 km away), Dobrich (a 10 km coordinate
  disagreement), Iași/Nicolina (both in, probably fine). Your call if you
  pass by.

Questions to me, especially before you re-point or delete anything.
