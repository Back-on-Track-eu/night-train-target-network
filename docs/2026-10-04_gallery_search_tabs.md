# Gallery search: station / city / country × via / from → to (2026-10-04)

Backend 0.5.15 (one new filter, no migration, no data task) + frontend.
Deploy the api image first — see `DEPLOY_HANDOVER.md` §24b.

## What changed for the reader

The four search tabs (From A to B, By Station, By Country, Between
Countries) become **three places × two kinds**:

- Tabs: **By station · By city · By country** (the city tab is new; icon
  `mdiCityVariantOutline`).
- A switch inside the search pill: **Via** (one field — routes that call
  there) or **From → to** (two fields — routes that call at both places).
  The same switch on every tab, so what used to be four tabs is now one
  grid.
- A one-line hint under the pill says what the kind means. "From → to" is
  *both places touched, in either direction, not only as end points* — the
  gallery's meaning since A→B existed (the backend has no ordering
  predicate), now stated instead of assumed. Decided 2026-10-04.
- Each tab keeps its own picks while another tab is active.
- The map's top-left chip now names the search on every tab, with the tab's
  icon: "via Berlin Hbf", "Germany ↔ Spain" (↔ on purpose — the filter is
  both places in either direction; the switch's → is the control's label).
- The map fit pads the frame by the overlays' measured size (legend,
  chip stack, zoom control) plus a label allowance, so the legend no
  longer covers the end of a route and stop names at the frame's edge are
  whole (`fitPadding()` in `GalleryMap.vue`; capped at two thirds of the
  map per axis for phone widths).
- Selected countries are tinted **teal** (`COUNTRY_COLOR`, fill 22 % / 12 %
  with a 1.2 px outline of the same colour) instead of route blue: a blue
  country border was taken for a proposal line (review 2026-10-04). A
  city search pins the city once at its centroid, a step larger than a
  station pin; the hovered route's own stop in that city keeps its dot.
  The legend row says "Searched city".

## Layout and defaults (same day, after review)

- The source switch (now segmented: All routes / Proposals / Existing, no
  dropdown) and the ownership switch (All / Mine) moved out of the result
  column into a **"Show" strip** under the search pill, above the Range
  filters row — with the other controls that narrow the list. The result
  column opens with the count and the sort only.
- Defaults: **Proposals**, all owners, typical-night-train preset, base
  scenario, **newest created first** (`created_at desc`; was distance desc).
  Existing-only still falls back to distance, which is the one sort both
  sources carry.
- URL: `?src=all|existing` only when off the default; links without it mean
  proposals. `?sort&dir` unchanged.

## The city filter — backend 0.5.15

Why backend: "calls at any stop of city A **and** any stop of city B" is not
expressible with `stop_ids` (`mode: 'all'` asks for specific stops; a city
has several). So `POST /api/proposals` gains `cities`:

- Values are OSM place-node ids — `StopCity.osm_id` in the stops payload,
  the stable key behind the localized city names
  (`input_params.stop_infrastructures.city_osm_id`).
- Same shape as the array filters: a plain list is `"any"`,
  `{"values": [...], "mode": "all"}` requires every city.
- Resolved through the catalogue at query time — `EXISTS (SELECT 1 FROM
  input_params.stop_infrastructures si WHERE si.city_osm_id = … AND
  si.stop_id = ANY(stop_ids))`, one EXISTS for "any", one per city AND-joined
  for "all". Nothing stored on `proposal_summaries`, no migration. The
  catalogue is snapshot-versioned; EXISTS absorbs the duplicate rows.
- Reaches existing (ONTD) rows too — same stop-id namespace.
- Validation: integers only (`"Berlin"` → 400, bool excluded), unknown
  mode → 400. Not sortable (not a column).
- Stops without a resolved city (rural halts, or a row that never got one)
  are not reachable by city; they remain reachable by station.

## Files

### Backend

| File | Change |
| --- | --- |
| `backend/adapters/proposal/filter_builder.py` | `CITIES_KEY`, in `ALL_FILTER_KEYS`; `_build_cities_clause()` (+ `_CITY_EXISTS`); module docstring. |
| `backend/api/helpers/proposal_serialize.py` | `_validate_array_filter()` takes a `value_type` (int for cities); `cities` validated in `_validate_filters()`. |
| `backend/api/proposals.py` | Docstring names the filter. |
| `backend/api/README.md`, `backend/adapters/proposal/README.md` | §7.1 filter table / rule and the request example. |
| `backend/tests/test_52_proposals_gallery_api.py` | `TestCityFilter`: any, all, spans sources, rejects non-integers; `_city_of()` reads the id from the catalogue rather than pinning one. |
| `backend/pyproject.toml` | 0.5.14 → 0.5.15 (`uv lock` after extracting). |

### Frontend

| File | Change |
| --- | --- |
| `frontend/src/lib/gallerySearch.ts` | **New.** `GallerySearchTab`/`Kind`, `CityOption` + `cityOptions()` (group the stops store by `city.osm_id`, localized name, every-language search text, centroid), `activePicks()`, `searchFilter()` (the tab × kind → filter table), `anchorStopIds()`. |
| `frontend/src/lib/gallerySearch.test.ts` | **New.** Grouping, the filter table incl. the half-filled pair and the self-pair, anchors. |
| `frontend/src/lib/proposalPrefill.ts` | Seed is the new picks shape (`EMPTY_SEED`); URL is `?tab&kind&a&b` with the legacy `?mode…` shape still read; `resolvePrefillStops()` handles cities (capital-listed stop of the city, else its first). |
| `frontend/src/lib/proposalPrefill.test.ts` | **New.** Round-trips per tab, slot handling, legacy links, prefill resolution. |
| `frontend/src/lib/majorStops.ts` | Accepts `readonly Stop[]`. |
| `frontend/src/lib/galleryMap.ts` (+ test) | `GalleryStopMarker.city`, `ANCHOR_CITY_RADIUS`, `anchorCollection()` carries the flag. |
| `frontend/src/components/OptionSelect.vue` | **New** (from `CountrySelect.vue`): generic option picker — `options: {key, label, subtitle?, haystack?}`, `placeholder`, `emptyText`. |
| `frontend/src/components/CountrySelect.vue` | **Deleted** — replaced by `OptionSelect.vue` (see rollout). |
| `frontend/src/components/Gallery.vue` | `tab`/`kind` + six pick refs replace `mode` + seven refs; tabs from `SEARCH_TABS`; kind switch and the two generic fields in the pill; hint line; `searchFilter()` in `buildFilter()`; `searchLabel` for the map chip; city markers for the pins; URL hydration via the new seed. |
| `frontend/src/components/GalleryMap.vue` | `searchSummary` prop (icon + text) replaces the country-only chip; countries in `COUNTRY_COLOR`; city pins drawn larger; legend row "Searched city". |
| `frontend/src/components/SearchField.vue`, `MapShareBar.vue`, `src/style.css` | Comments: CountrySelect → OptionSelect. |
| `frontend/src/types/api.ts` | `ProposalsFilter.cities`, `ProposalsCitiesFilter`. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `gallery.tabs.{station,city,country}` (old four removed), `gallery.kind.*` (label, via, fromTo, hint.via, hint.fromTo), `gallery.search.*` (city, cityPlaceholder, noCities, toLower; the A→B/relation-specific keys removed), `gallery.map.legend.city`, `gallery.map.highlight.{via,pair}` (replace `relation`). |
| `frontend/README.md` | Gallery section: the search bar, the chip and city pin, the vocabulary note; project structure. |
| `docs/DEPLOY_HANDOVER.md` | §24b. |

## Rollout

```powershell
Remove-Item .\frontend\src\components\CountrySelect.vue
cd backend; uv lock; cd ..
cd frontend; npm run ci; npm run build; cd ..
```

Backend integration: `uv run pytest tests/test_52_proposals_gallery_api.py
-k "CityFilter or FilterKinds"` against the dev stack. The city tests read
the catalogue's `city_osm_id` for the two fixture stops and skip if the
seeded catalogue carries none — on a seed without cities the frontend's
city tab is simply empty.

Order on staging/production: api image (0.5.15) before the frontend image.

## Verified on the delivered tree

- Frontend: `vue-tsc`, `eslint`, `prettier --check`, `vitest run` (432
  tests, 40 files), `vite build` — all green (the build with stubbed Mark
  Pro font files, as before; the fonts are not in the snapshot).
- Backend: `ruff format --check` and `ruff check` (0.15.21) green on the
  four touched files; the clause builder exercised standalone for both
  modes. The integration tests were not run here (no database); please run
  the two test classes above before merging.
- Not exercised here: the live map against the CARTO basemap and the
  pickers in a browser — one pass over the three tabs × two kinds on your
  stack, including a shared pre-change link (`?mode=aToB&from=…&to=…`).

## Open point

A city's representative stop for the "Suggest a new route" prefill is its
capital-listed stop or else its first stop in catalogue order; a stop
importance tier (STOP_CLASSIFICATION.md) would make that choice better.
