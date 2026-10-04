# Gallery map highlights — manifest and handover (2026-10-04)

Frontend only. No backend, schema or API change; deployment is an ordinary
frontend image rebuild.

## What changed for the reader

1. **Hovering a card** now draws the row's stops as well as its line: a
   filled, bold-labelled dot at origin and terminus, hollow dots with regular
   labels at every intermediate stop (all labels shown, collisions resolved by
   MapLibre). The corridor overview dims to 25 % instead of disappearing. The
   map fits to the route — and to the searched station, if there is one. An
   existing (ONTD) route whose geometry is missing still shows its stops.
2. **A station search** (By Station, From A to B) pins the searched
   station(s): a sapphire ring-pin with a bold label, kept through hover; the
   pin replaces the route's own dot at that stop. The overview fit includes
   the pin.
3. **A country or country-pair search** tints the country's land outline in
   route blue (18 % fill, the second country of a pair 10 %) with a 1.5 px
   outline, names it in a chip at the top-left of the map ("Austria" /
   "Austria ↔ Germany"), and includes it in the overview fit.
4. The legend grows a row for each of these marks only while the mark is on
   the map ("Stops of the hovered route", "Searched station", "Selected
   country"; German equivalents added).

## Where the country shapes come from — and why not from the backend

`input_params.countries.country_geom` is the Marine Regions EEZ + land union
(`backend/scripts/export_country_geoms.py`), chosen so Fehmarn Belt,
Storebælt, Øresund and the Channel Tunnel attribute to a country instead of
`UNK`. `map_country_counts` serves exactly that geometry. It is right for
attribution and wrong for display: it would tint Germany out to the Dogger
Bank.

Decision (David, 2026-10-04): static land polygons on the frontend, the filter
keeps the EEZ attribution. A route that touches Denmark only through the
Øresund water lists under Denmark and Danish land gets tinted — the tint means
"routes attributed to this country", not "routes crossing this outline".

- Source: Natural Earth admin-0 countries, 1:50m, public domain, via the
  `world-atlas` npm package (TopoJSON, decoded with `topojson-client`). 50m
  rather than 110m because the map fits to the selected country and 110m
  coastlines of Denmark and the Netherlands look blobby at that zoom.
- Built once by `frontend/scripts/build_country_shapes.mjs`, output
  **committed** at `frontend/src/assets/country_shapes.json` (189 kB raw,
  51 kB gzipped, 40 countries: the catalogue's 39 plus Kosovo, which ONTD
  rows can carry). Every ring is clipped to the backend's clip bbox
  (−25, 34, 45, 72 — Sutherland–Hodgman; drops French Guiana, Canaries,
  Azores, Madeira, Svalbard and cuts Russia at 45° E, after shifting the
  far-east vertices of its antimeridian-crossing mainland ring out of the
  way), islets below 0.01 deg² are dropped, vertices quantised to 0.02°.
- Natural Earth draws de-facto control, the backend's Marine Regions union
  the ISO/UN assignment; the generator moves Crimea from RU to UA
  (`REASSIGN`) so the tint agrees with the filter's attribution.
- Loaded lazily (`lib/countryShapes.ts`, a dynamic `import()`) on the first
  country filter, so the main bundle does not grow; Vite emits it as its own
  chunk.
- `src/lib/countryShapes.test.ts` guards the contract: every catalogue code
  has an outline, codes are unique upper-case ISO-2, every vertex is inside
  the clip bbox.

## Files

| File | Change |
| --- | --- |
| `frontend/scripts/build_country_shapes.mjs` | **New.** Generator for the land-outline asset; documented at the top of the file. |
| `frontend/src/assets/country_shapes.json` | **New, generated, committed.** One `MultiPolygon` per country, `properties.country` = ISO-2. |
| `frontend/src/lib/countryShapes.ts` | **New.** `loadCountryShapes()` — one cached dynamic import. |
| `frontend/src/lib/countryShapes.test.ts` | **New.** Asset contract tests. |
| `frontend/src/lib/mapFonts.ts` | **New.** `MAP_FONT_BOLD` / `MAP_FONT_REGULAR`, the glyph stacks the Positron style serves; moved out of `MapView.vue` so both maps share them. |
| `frontend/src/lib/galleryMap.ts` | `CORRIDOR_DIM_FACTOR`, pin/stop/country styling constants; `GalleryStopMarker`, `stopMarkers()`, `routeStopsCollection()`, `anchorCollection()`, `selectedCountriesCollection()`, the country-shape types; `featureBounds()` generalised to points and polygons (one vertex walker for every grain). |
| `frontend/src/lib/galleryMap.test.ts` | Tests for the new helpers and the mixed-grain bounds. |
| `frontend/src/components/GalleryMap.vue` | New props `highlightedStops`, `anchorStops`, `highlightedCountries`; country fill + line layers (below the corridors), route-stop circle + label layers, anchor halo + pin + label layers (top); corridors dim via `line-opacity` instead of `visibility`; fit includes pins and countries; contextual legend rows; country chip in a top-left stack with the loading chip. |
| `frontend/src/components/Gallery.vue` | `highlightCountries`, `stopsById`, `hoveredSummary`, `hoveredStops`, `anchorStops`; the stops store is fetched on mount (awaited only when the URL names a stop, as before). |
| `frontend/src/components/MapView.vue` | Imports the font stacks from `lib/mapFonts.ts`; no behaviour change. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `gallery.map.legend.{stops,anchor,country}`, `gallery.map.highlight.relation`. |
| `frontend/package.json` | devDependencies `world-atlas`, `topojson-client`; script `build:country-shapes`. |
| `frontend/.prettierignore` | Ignores the generated asset (Prettier would expand the one-line JSON to megabytes and fail `format:check` otherwise). |
| `frontend/README.md` | Gallery section: hover stops, pins, country tint and the EEZ-vs-land decision; project structure; scripts table. |

## Rollout

```powershell
cd frontend
npm install            # two new devDependencies → updates package-lock.json, commit it
npm run ci             # lint, format:check, type-check, vitest — all green on the delivered tree
npm run build
```

Nothing to do on the backend or in the database. The asset is committed, so
CI does not need `world-atlas` at build time; `npm run build:country-shapes`
is only for regenerating it after a country-list or source change.

## Verified on the delivered tree

`vue-tsc`, `eslint`, `prettier --check`, `vitest run` (409 tests, 38 files)
and `vite build` pass. The build was run with stubbed Mark Pro font files
(the fonts are not part of the project snapshot) — only the font step was
stubbed, the bundle itself built normally with `country_shapes` as a separate
53 kB (gzipped) chunk. Not exercised here: the live map against the CARTO
basemap — please do the hover / station / country walk-through once on your
stack before merging.

## Open points for the next round

- Pin colour is sapphire (`#1d1e33`); a third accent is a one-constant
  change (`ANCHOR_COLOR` in `lib/galleryMap.ts`).
- A relation search tints both countries; emphasising the corridors that
  actually cross the pair would need `country_relations` on `map_lines`
  features (backend) and is not part of this round.
