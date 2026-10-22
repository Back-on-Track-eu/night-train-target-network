/**
 * maplibreWorker.ts — point MapLibre at its worker file, once, for the whole
 * app.
 *
 * Vite 8 production builds corrupted the worker MapLibre v5 assembled from its
 * own bundled code (maplibre-gl-js#7339): GeoJSON sources then failed inside
 * the worker ("<name> is not defined") and route lines never rendered, while
 * dev builds were unaffected. v5 was pointed at its prebuilt CSP worker.
 *
 * MapLibre v6 is ESM-only and ships the worker as its own module
 * (dist/maplibre-gl-worker.mjs, which imports a sibling shared chunk). The
 * `?worker&url` query is the upstream-documented Vite setup: it routes the file
 * through Vite's worker pipeline and emits a self-contained chunk. A plain
 * `?url` would copy the file without its sibling and the worker would fail on
 * its first import.
 *
 * Why this lives in its own module rather than in a map component:
 * `setWorkerUrl` is global state on the maplibregl module, and it only takes
 * effect if the module that calls it is evaluated BEFORE the first Map is
 * constructed. With route-level code splitting that is not guaranteed —
 * GalleryMap.vue carried no such call, so opening /gallery first spawned the
 * corrupt worker and every later map in the same SPA session inherited it
 * (observed on production 2026-08-17: lines rendered on a direct /proposal/:id
 * load, and never when the same page was reached via the gallery).
 *
 * Imported for its side effect from main.ts, so it runs before any component
 * mounts, and from each map component, so a component used in isolation still
 * gets it. ES modules execute once, so importing it repeatedly is free.
 */

import * as maplibregl from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

maplibregl.setWorkerUrl(maplibreWorkerUrl)

export {}
