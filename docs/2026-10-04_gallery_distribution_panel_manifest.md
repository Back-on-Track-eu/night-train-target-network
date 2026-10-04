# Gallery — distribution panel (2026-10-04)

Backend 0.5.14 (one new `include` section, no migration, no data task) +
frontend. Implements the sketch agreed on 2026-10-04: one histogram at a
time above the map, the range set by dragging, typing or the
typical-night-train preset, all four ranges persisting as chips.

## Backend

- `backend/adapters/proposal/repository.py` — `_DISTRIBUTION_MEASURES`
  (fixed axes: 0–4 000 km / 100, 0–48 h / 1, 0–160 km/h / 5, 2–26 stops / 1)
  and `distributions(filters, scenario_variant_id)`: one `width_bucket`
  aggregate per measure over the gallery union, split by source, counted on
  the filter **minus the measure's own range**; open last bin, `unknown`
  bucket for NULLs. `RANGE_COLUMNS` import.
- `backend/api/proposals.py` — section wired into `_list_response`;
  docstring.
- `backend/api/helpers/proposal_serialize.py` — `"distributions"` accepted
  in `include`.
- `backend/tests/test_52_proposals_gallery_api.py` — `TestDistributions`
  (4): fixed axes and open last bin; bins + unknown sum to the filtered
  total per source; the published proposal lands in its one-way bin on all
  four measures; each measure ignores its own range while the others
  reflect it, existing side whole under `scope: "proposal"`.
- `backend/adapters/proposal/README.md` §7.1, `backend/api/README.md`
  gallery section — the section documented, example response.
- `backend/pyproject.toml` — 0.5.14 (`uv lock` after extracting).

## Frontend

- `frontend/src/components/GalleryDistribution.vue` — **new**: measure
  dropdown (PrimeVue `Select`, `selectPillPt`), min/max inputs, preset pill
  with `InfoHint`, SVG histogram (proposals blue, existing orange on top,
  2 px gap, dimmed outside the range), two draggable handles (snap to bin
  edges, arrow keys, `role="slider"`), hover tooltip per bin, chips with ×,
  legend, "N existing trains without figures". Drag commits on release
  only. ViewBox 900 wide from `sm` up, 460 below, so the chart is readable
  on a phone.
- `frontend/src/lib/galleryRanges.ts` — **new**: `GalleryRanges`,
  `typicalNightTrainRanges()`, `normalizeRanges`, `sameRanges`,
  `isTypicalNightTrain`, `rangesToFilter` (adds `scope: 'proposal'`),
  `rangesToQuery` / `rangesFromQuery` (`km`, `h`, `kmh`, `stops` as
  `min-max`; `typical=0` for none; nothing for the preset).
- `frontend/src/lib/galleryRanges.test.ts` — **new** (8 tests); replaces
  `typicalNightTrain.test.ts` (**deleted**).
- `frontend/src/lib/typicalNightTrain.ts` — constants only;
  `typicalNightTrainFilter()` moved to `galleryRanges.ts` as the preset.
- `frontend/src/components/Gallery.vue` — `ranges` replaces `typicalOnly`;
  `loadDistributions()` beside `loadCorridors()` (own abort slot, resumed
  after a teardown like the corridors); URL sync via `rangesToQuery` /
  `rangesFromQuery`; the toggle leaves the control row; the right column
  is now panel + map. `await nextTick()` before lifting the hydration
  guard — a link that set any field loaded the gallery twice.
- `frontend/src/lib/proposalsApi.ts` — `fetchDistributions()`.
- `frontend/src/types/api.ts` — `n_stops` range on `ProposalsFilter`,
  `'distributions'` section, `DistributionBin` / `DistributionMeasure` /
  `DistributionsSection`.
- `frontend/src/composables/useMediaQuery.ts` — `SM_MEDIA_QUERY`.
- `frontend/src/i18n/locales/en.json`, `de.json` — `gallery.distribution.*`.
- `frontend/README.md` — "Three requests per query", "The distribution
  panel" (replaces the toggle paragraph).

## Docs

- `docs/FRONTEND_HANDOVER.md` §26, `docs/DEPLOY_HANDOVER.md` §24a.

## Checks run here

- ruff 0.15.21 format + check on the four backend files: clean.
- Backend SQL assembled against a fake cursor: the distance query carries
  no distance range, the duration query carries it; bucket 0 / n+1 / NULL
  fold into first bin / open bin / unknown. The DB tests need your stack.
- vitest: 394 passed. prettier: clean. eslint on the touched files: clean.
  vue-tsc: the error count is unchanged (pre-existing in my copy).
- Rendered against a mocked API with Playwright at 1280 and 400 px: panel
  draws, drag moves the lower handle to 1 100 km, the pill goes quiet, the
  URL reads `km=1100-2000&h=7-21&kmh=50-`, three requests per query.

## After extracting

```powershell
Remove-Item frontend\src\lib\typicalNightTrain.test.ts
cd backend; uv lock; cd ..
```

Then rebuild the api image (new backend code) and run
`test_52_proposals_gallery_api.py` plus the full suite.
