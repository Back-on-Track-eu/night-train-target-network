<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import maplibregl, { type FilterSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { GalleryMapRoute } from '@/types/api'

// Draws every proposal route in the search results at once — the multi-route
// counterpart to MapView.vue (which is single-route with scope/hover). Same
// basemap and brand colour; lines are semi-transparent so overlaps read.
const PRIMARY = '#2271b3'
const EUROPE_BOUNDS: [number, number, number, number] = [-30, 27, 50, 73]
const ROUTES_SOURCE = 'gallery-routes'
const ROUTES_LAYER = 'gallery-routes-line'
// Invisible wide copy of the line layer — a 2.5px line is near-impossible to
// hover, so this is the hit target (MapLibre still hit-tests zero-opacity fills).
const ROUTES_HIT_LAYER = 'gallery-routes-hit'

const props = defineProps<{ routes: GalleryMapRoute[]; highlightedKey?: string | null }>()
const emit = defineEmits<{ hoverRoute: [key: string | null] }>()

const mapContainer = ref<HTMLDivElement | null>(null)
let map: maplibregl.Map | null = null
let mapLoaded = false
let hoveredKey: string | null = null
// The map lives in a flex/sticky column whose width settles after init;
// MapLibre doesn't watch its container, so resize it ourselves.
let resizeObserver: ResizeObserver | null = null

function routesFC() {
  const features = props.routes.flatMap((r) =>
    r.lines.map((line) => ({
      type: 'Feature' as const,
      geometry: { type: 'LineString' as const, coordinates: line },
      // key ties every leg back to its proposal so a hover can be reported.
      properties: { key: r.key },
    })),
  )
  return { type: 'FeatureCollection' as const, features }
}

// Frame all routes. Endpoint coordinates (route.stops) are enough to bound the
// view and far cheaper than walking every geometry vertex.
function fit() {
  if (!map || !mapLoaded) return
  const bounds = new maplibregl.LngLatBounds()
  let any = false
  for (const r of props.routes)
    for (const s of r.stops) {
      bounds.extend([s.lon, s.lat])
      any = true
    }
  if (any) map.fitBounds(bounds, { padding: 60, maxZoom: 9, duration: 600 })
}

function sync() {
  if (!map || !mapLoaded) return
  // Features are being replaced — clear any active isolation so a departed
  // route doesn't leave the others permanently hidden.
  hoveredKey = null
  setIsolate(null)
  ;(map.getSource(ROUTES_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData(routesFC())
  fit()
}

// Isolate the focused route: show only it and hide every other route (both the
// visible line and its hover hit-target). null shows them all again.
function setIsolate(key: string | null) {
  if (!map || !mapLoaded) return
  const filter = (key ? ['==', ['get', 'key'], key] : null) as FilterSpecification | null
  map.setFilter(ROUTES_LAYER, filter)
  map.setFilter(ROUTES_HIT_LAYER, filter)
}

function onRouteHover(e: maplibregl.MapLayerMouseEvent) {
  if (!map) return
  const raw = e.features?.[0]?.properties?.key
  const key = raw == null ? null : String(raw)
  map.getCanvas().style.cursor = key ? 'pointer' : ''
  if (key === hoveredKey) return
  hoveredKey = key
  setIsolate(key)
  emit('hoverRoute', key)
}

function onRouteLeave() {
  if (!map || hoveredKey === null) return
  map.getCanvas().style.cursor = ''
  hoveredKey = null
  setIsolate(null)
  emit('hoverRoute', null)
}

function initLayers() {
  if (!map) return
  map.addSource(ROUTES_SOURCE, { type: 'geojson', data: routesFC() })
  map.addLayer({
    id: ROUTES_LAYER,
    type: 'line',
    source: ROUTES_SOURCE,
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': PRIMARY, 'line-width': 2.5, 'line-opacity': 0.5 },
  })
  map.addLayer({
    id: ROUTES_HIT_LAYER,
    type: 'line',
    source: ROUTES_SOURCE,
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': PRIMARY, 'line-width': 16, 'line-opacity': 0 },
  })

  map.on('mousemove', ROUTES_HIT_LAYER, onRouteHover)
  map.on('mouseleave', ROUTES_HIT_LAYER, onRouteLeave)
}

onMounted(() => {
  if (!mapContainer.value) return
  map = new maplibregl.Map({
    container: mapContainer.value,
    style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    center: [13, 48],
    zoom: 4,
    maxBounds: EUROPE_BOUNDS,
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
  map.on('load', () => {
    mapLoaded = true
    initLayers()
    fit()
  })
  resizeObserver = new ResizeObserver(() => map?.resize())
  resizeObserver.observe(mapContainer.value)
})

watch(() => props.routes, sync, { deep: true })

// Card-driven highlight: hovering a card in the list thickens its route here,
// mirroring the map→card direction.
watch(
  () => props.highlightedKey,
  (k) => setIsolate(k ?? null),
)

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="mapContainer" style="width: 100%; height: 100%; min-height: 480px" />
</template>
