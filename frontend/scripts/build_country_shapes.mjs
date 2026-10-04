/* global process, Buffer */
// Build src/assets/country_shapes.json — the LAND outline per country the
// gallery map tints when a country or country-pair filter is active.
//
// Why a second set of polygons: the backend's input_params.countries.country_geom
// is the Marine Regions EEZ + land union (backend/scripts/export_country_geoms.py),
// chosen so belt, strait and tunnel crossings attribute to a country instead of
// "UNK". That is the right shape for attribution and the wrong one for display —
// it would tint Germany out to the Dogger Bank. The gallery keeps FILTERING on
// the EEZ attribution (a route attributed to Denmark through the Øresund still
// lists under Denmark) and only DRAWS the land outline from here.
//
// Source: Natural Earth admin-0 countries at 1:50m, public domain, via the
// `world-atlas` npm package (TopoJSON). 50m rather than 110m because the map
// fits to the selected country, and at that zoom 110m coastlines of Denmark and
// the Netherlands look blobby.
//
// Run once and commit the output (it only changes when the country list or the
// source version does):
//
//     cd frontend
//     npm run build:country-shapes
//
// Derivation, mirroring the backend script where it matters:
//   - keep the catalogue's countries (_COUNTRY_CODE_TO_ISO3 in
//     backend/scripts/export_country_geoms.py) plus Kosovo, which ONTD rows
//     can carry, so an existing-only country still highlights
//   - clip every ring to the backend's clip bbox (Sutherland–Hodgman against
//     the four edges): drops French Guiana, the Canaries, Azores, Madeira and
//     Svalbard, and cuts Russia at 45° E the way the backend does
//   - drop islets below MIN_RING_AREA_DEG2 unless they are all a country has
//   - quantise to QUANTUM degrees and collapse repeated vertices
// Keyed by ISO 3166-1 alpha-2 in `properties.country`, the vocabulary the
// gallery filters already use.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { feature } from 'topojson-client'

const require = createRequire(import.meta.url)
const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(HERE, '../src/assets/country_shapes.json')

// backend/scripts/export_country_geoms.py::_CLIP_BBOX — west, south, east, north.
const CLIP_BBOX = [-25.0, 34.0, 45.0, 72.0]
const QUANTUM = 0.02
const MIN_RING_AREA_DEG2 = 0.01

// ISO 3166-1 numeric (world-atlas feature id) -> alpha-2. Natural Earth gives
// Kosovo no numeric code, hence the name fallback below.
const NUMERIC_TO_ALPHA2 = {
  '008': 'AL',
  '040': 'AT',
  '056': 'BE',
  '070': 'BA',
  100: 'BG',
  112: 'BY',
  191: 'HR',
  203: 'CZ',
  208: 'DK',
  233: 'EE',
  246: 'FI',
  250: 'FR',
  276: 'DE',
  300: 'GR',
  348: 'HU',
  372: 'IE',
  380: 'IT',
  428: 'LV',
  438: 'LI',
  440: 'LT',
  442: 'LU',
  498: 'MD',
  499: 'ME',
  528: 'NL',
  578: 'NO',
  616: 'PL',
  620: 'PT',
  642: 'RO',
  643: 'RU',
  688: 'RS',
  703: 'SK',
  705: 'SI',
  724: 'ES',
  752: 'SE',
  756: 'CH',
  792: 'TR',
  804: 'UA',
  807: 'MK',
  826: 'GB',
}
const NAME_TO_ALPHA2 = { Kosovo: 'XK' }

// Natural Earth draws de-facto control; the backend's Marine Regions union
// follows the ISO/UN assignment, under which Crimea is Ukraine. The filter
// attributes by the backend's polygons, so the tint has to agree with it:
// any Russian polygon whose outer ring sits inside this box moves to UA.
const REASSIGN = [{ from: 'RU', to: 'UA', bbox: [32.0, 44.0, 37.0, 46.5] }]

// Clip one ring to the bbox, one edge at a time (Sutherland–Hodgman). A ring
// entirely outside comes back empty; one entirely inside comes back as is.
const clipRing = (ring) => {
  const edges = [
    (p) => p[0] >= CLIP_BBOX[0],
    (p) => p[1] >= CLIP_BBOX[1],
    (p) => p[0] <= CLIP_BBOX[2],
    (p) => p[1] <= CLIP_BBOX[3],
  ]
  const cross = (a, b, i) => {
    // Intersection of segment a→b with the bbox edge `i` (west, south, east, north).
    const axis = i % 2
    const value = CLIP_BBOX[i]
    const t = (value - a[axis]) / (b[axis] - a[axis])
    return axis === 0 ? [value, a[1] + t * (b[1] - a[1])] : [a[0] + t * (b[0] - a[0]), value]
  }
  // Russia's mainland ring crosses the antimeridian; clipped as is, the jump
  // from 180° to −180° becomes a band across the whole bbox. Nothing we keep
  // lies west of −30°, so anything there is the far east wrapped around.
  let out = ring.map(([lon, lat]) => [lon < -30 ? lon + 360 : lon, lat])
  edges.forEach((inside, i) => {
    const input = out
    out = []
    for (let j = 0; j < input.length; j++) {
      const a = input[(j + input.length - 1) % input.length]
      const b = input[j]
      if (inside(b)) {
        if (!inside(a)) out.push(cross(a, b, i))
        out.push(b)
      } else if (inside(a)) {
        out.push(cross(a, b, i))
      }
    }
  })
  return out
}

const ringBboxArea = (ring) => {
  let w = Infinity,
    s = Infinity,
    e = -Infinity,
    n = -Infinity
  for (const [lon, lat] of ring) {
    if (lon < w) w = lon
    if (lon > e) e = lon
    if (lat < s) s = lat
    if (lat > n) n = lat
  }
  return (e - w) * (n - s)
}

const quantise = (ring) => {
  const out = []
  for (const [lon, lat] of ring) {
    const p = [Math.round(lon / QUANTUM) * QUANTUM, Math.round(lat / QUANTUM) * QUANTUM].map((v) =>
      Number(v.toFixed(2)),
    )
    const last = out[out.length - 1]
    if (!last || last[0] !== p[0] || last[1] !== p[1]) out.push(p)
  }
  // A ring stays closed: first and last vertex equal.
  const [f, l] = [out[0], out[out.length - 1]]
  if (f && (f[0] !== l[0] || f[1] !== l[1])) out.push([f[0], f[1]])
  return out.length >= 4 ? out : null
}

const topology = JSON.parse(readFileSync(require.resolve('world-atlas/countries-50m.json'), 'utf8'))
const countries = feature(topology, topology.objects.countries).features

const ringInside = (ring, [w, s, e, n]) =>
  ring.every(([lon, lat]) => lon >= w && lon <= e && lat >= s && lat <= n)

// Polygons per code, after the reassignments above.
const polygonsByCode = new Map()
for (const f of countries) {
  const code = NUMERIC_TO_ALPHA2[f.id] ?? NAME_TO_ALPHA2[f.properties.name]
  if (!code) continue
  const polygons = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates
  for (const poly of polygons) {
    const rule = REASSIGN.find((r) => r.from === code && ringInside(poly[0], r.bbox))
    const target = rule ? rule.to : code
    if (!polygonsByCode.has(target)) polygonsByCode.set(target, [])
    polygonsByCode.get(target).push(poly)
  }
}

const features = []
for (const [code, polygons] of polygonsByCode) {
  // Clip first, then judge size on what is left: a polygon whose outer ring
  // vanishes takes its holes with it.
  let kept = polygons
    .map((poly) => poly.map(clipRing).filter((ring) => ring.length >= 3))
    .filter((poly) => poly.length)
  const large = kept.filter((poly) => ringBboxArea(poly[0]) >= MIN_RING_AREA_DEG2)
  if (large.length) kept = large
  const coordinates = kept
    .map((poly) => poly.map(quantise).filter(Boolean))
    .filter((poly) => poly.length)
  if (!coordinates.length) {
    console.warn(`  ${code}: nothing left inside the clip bbox — skipped`)
    continue
  }
  features.push({
    type: 'Feature',
    properties: { country: code },
    geometry: { type: 'MultiPolygon', coordinates },
  })
}
features.sort((a, b) => a.properties.country.localeCompare(b.properties.country))

const missing = [...Object.values(NUMERIC_TO_ALPHA2), ...Object.values(NAME_TO_ALPHA2)].filter(
  (code) => !features.some((f) => f.properties.country === code),
)
if (missing.length) {
  console.error(`country_shapes: no source polygon for ${missing.join(', ')}`)
  process.exitCode = 1
}

mkdirSync(dirname(OUT), { recursive: true })
writeFileSync(OUT, JSON.stringify({ type: 'FeatureCollection', features }))
const kb = Math.round(Buffer.byteLength(readFileSync(OUT)) / 1024)
console.log(`country_shapes: ${features.length} countries, ${kb} kB -> ${OUT}`)
