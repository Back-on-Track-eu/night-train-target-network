# Gallery — "Typical night trains" toggle (2026-10-03)

Backend 0.5.12 (one small, generic filter extension; no migration) +
frontend. Supersedes the first cut of this zip from earlier today.

## What

One toggle next to the ownership pill, **on by default**, applying the
position paper's yardstick the launch report counted with: proposals of one
way 500–2 000 km, 7–16 h and **at least 50 km/h** on average (lowered from
60 after looking at the existing catalogue: 205 real trains, median right
around 60 km/h, 70 of them below it). The app's ⓘ overlay (`InfoHint`, the
same component the route builder's KPIs use) names the bounds and what the
toggle leaves alone. Off shows every proposal.

**Existing trains always stay listed.** The sieve is asked of proposals only:
of production's 205 real night trains, 126 fall outside the envelope
(27 without figures, 70 under 60 km/h, 58 over 16 h — Adria, Bosphor
Express, Balkan Express, Prietenia among them), and hiding them would hide
exactly the real-world comparison the gallery exists for.

## Backend — range `scope` (0.5.12)

Every `{min, max}` range filter of `POST /api/proposals` (numeric and
datetime) accepts an optional `"scope": "proposal"`, compiled as
`(source <> 'proposal' OR (col >= … AND col <= …))` — the bounds apply to
proposal rows only, every existing row passes unexamined, NULLs on the
existing side no longer matter. Generic by design: nothing in the backend
knows the position paper's numbers; those live in the frontend's one file.
Any other scope value is a `400 validation_error`.

## Frontend

- Bounds in `frontend/src/lib/typicalNightTrain.ts`; the overlay text is
  rendered from them, so a changed bound cannot leave the copy behind.
- URL: `typical=0` only when off. Links shared before today carry no key and
  open with the sieve on.
- A change of the toggle reloads the cards AND the corridor map (it changes
  the proposal result set).

## Also in this zip: phase 1 restored in `Gallery.vue`

The mobile-layout round's `Gallery.vue` and `frontend/README.md` were
written against the file **before** phase 1 (split loading). On your disk,
`Gallery.vue` had lost `fetchMapCorridors` / `loadCorridors()` / the corridor
status chip wiring / resume-on-return — committing it would have brought the
gallery timeout back; the README had lost the "Two requests per query"
paragraph. This zip's `Gallery.vue` is a three-way merge (pre-phase-1 base,
phase 1, mobile layout — two trivial conflicts: the import line and the
`<GalleryMap>` tag) with the toggle on top, so it carries all three rounds.
Check: `Select-String fetchMapCorridors frontend\src\components\Gallery.vue`
finds it; narrowing the window below `lg` still gives the single column.

## Files

- `backend/adapters/proposal/filter_builder.py` — `RANGE_SCOPES`,
  `_range_clauses()` (one place for both range kinds), `build_where()` uses it.
- `backend/api/helpers/proposal_serialize.py` — validation accepts `scope`,
  rejects unknown values.
- `backend/tests/test_52_proposals_gallery_api.py` —
  `test_scoped_range_lets_existing_rows_through`, `test_unknown_range_scope_rejected`.
- `backend/pyproject.toml` — 0.5.11 → 0.5.12 (`uv lock` moves `uv.lock`).
- `backend/api/README.md` — §7.1 range `scope`.
- `frontend/src/lib/typicalNightTrain.ts` (new) — `TYPICAL_NIGHT_TRAIN`, `typicalNightTrainFilter()` (scoped).
- `frontend/src/lib/typicalNightTrain.test.ts` (new).
- `frontend/src/types/api.ts` — `ProposalsRange` (+ `scope`); the three range keys on `ProposalsFilter`.
- `frontend/src/components/Gallery.vue` — phase 1 ∪ mobile layout ∪ the toggle:
  `typicalOnly` (default true), hint from the constants, `buildFilter()` merge,
  URL sync (`typical=0`), hydrate, in the query watcher; the toggle + `InfoHint`
  in the ownership row (owner pill, toggle and ⓘ grouped so the count keeps the
  right edge).
- `frontend/src/i18n/locales/en.json`, `de.json` — `gallery.filter.typical`,
  `gallery.filter.typicalHint`.
- `frontend/README.md` — toggle paragraph; the phase-1 paragraph restored.

## Gates

Frontend: eslint, prettier, vue-tsc, vitest 388/388, `vite build` — green, on
the merged file. Backend: ruff clean; the scoped `WHERE` fragment rendered
and parsed. Integration tests NOT run here (Docker stack).

## Your run

```powershell
cd backend; uv lock; uv run ruff format; uv run ruff check; uv run pytest tests/test_52_proposals_gallery_api.py -q; cd ..
cd frontend; npm run ci; npm run build; cd ..
```

Then `/gallery` (api rebuilt): two `POST /api/proposals` on a cold load
(phase 1 is back); with source "All" the count is typical proposals + all
existing trains; "Existing" alone is unchanged by the toggle; off lifts the
sieve and the URL gains `typical=0`. Hover the ⓘ for the bounds.
