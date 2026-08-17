/**
 * maplibreWorker.ts — point MapLibre at its self-contained CSP worker, once,
 * for the whole app.
 *
 * Vite 8 production builds corrupt the worker MapLibre assembles from its own
 * bundled code (maplibre-gl-js#7339): GeoJSON sources then fail inside the
 * worker ("<name> is not defined") and route lines never render, while dev
 * builds are unaffected. Pointing MapLibre at the prebuilt CSP worker keeps the
 * worker independent of how the main bundle was chunked or minified.
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

import maplibregl from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-csp-worker.js?url'

maplibregl.setWorkerUrl(maplibreWorkerUrl)

export {}
