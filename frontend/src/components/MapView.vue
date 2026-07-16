<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { octilinearPath } from '@/utils/octilinear'

// Two sources/layers: the in-scope route (highlighted) and the out-of-scope
// route (dimmed grey). The dim layer is added first so the highlight draws on
// top of it at shared junctions.
const ROUTE_SOURCE = 'route'
const ROUTE_SOURCE_DIM = 'route-dim'
const ROUTE_LAYER = 'route-line'
const ROUTE_LAYER_DIM = 'route-line-dim'
const PRIMARY = '#2271b3'
const PRIMARY_LIGHT = '#eef4fb'
// A lighter tint of PRIMARY (not grey) for out-of-scope route parts and stops.
const DIMMED = '#9cc0e5'
// west, south, east, north — generous Europe + North Africa margin
const EUROPE_BOUNDS: [number, number, number, number] = [-30, 27, 50, 73]

interface MarkerStop {
  lat: number
  lon: number
  name: string
  highlighted: boolean
}

const props = defineProps<{
  stops: MarkerStop[]
  shape?: { type: string; coordinates: [number, number][] } | null
  // When provided, the route is drawn per-segment so out-of-scope parts can be
  // dimmed (highlighted=false). Falls back to `shape` (all highlighted) when
  // absent.
  segments?: { coordinates: [number, number][]; highlighted: boolean }[] | null
}>()

const mapContainer = ref<HTMLDivElement | null>(null)
let map: maplibregl.Map | null = null
let markers: maplibregl.Marker[] = []
let mapLoaded = false
let initialFitDone = false

function makeMarkerEl(isEndpoint: boolean, highlighted: boolean): HTMLDivElement {
  const el = document.createElement('div')
  const size = isEndpoint ? 14 : 10
  Object.assign(el.style, {
    width: `${size}px`,
    height: `${size}px`,
    background: highlighted ? PRIMARY : DIMMED,
    border: `2.5px solid ${PRIMARY_LIGHT}`,
    borderRadius: '50%',
    boxShadow: '0 1px 4px rgba(0,0,0,0.35)',
    cursor: 'pointer',
  })
  return el
}

function syncMarkers() {
  if (!map || !mapLoaded) return
  markers.forEach((m) => m.remove())
  markers = []
  const n = props.stops.length
  props.stops.forEach((stop, i) => {
    const isEndpoint = i === 0 || i === n - 1
    const marker = new maplibregl.Marker({ element: makeMarkerEl(isEndpoint, stop.highlighted) })
      .setLngLat([stop.lon, stop.lat])
      .setPopup(new maplibregl.Popup({ offset: 12 }).setText(stop.name))
      .addTo(map!)
    markers.push(marker)
  })
}

function lineFeature(coordinates: [number, number][]) {
  return {
    type: 'Feature' as const,
    geometry: { type: 'LineString' as const, coordinates },
    properties: {},
  }
}

function syncPolyline() {
  if (!map || !mapLoaded) return
  const src = map.getSource(ROUTE_SOURCE) as maplibregl.GeoJSONSource | undefined
  const srcDim = map.getSource(ROUTE_SOURCE_DIM) as maplibregl.GeoJSONSource | undefined
  if (!src || !srcDim) return

  if (props.segments && props.segments.length > 0) {
    const hi = props.segments.filter((s) => s.highlighted).map((s) => lineFeature(s.coordinates))
    const lo = props.segments.filter((s) => !s.highlighted).map((s) => lineFeature(s.coordinates))
    src.setData({ type: 'FeatureCollection', features: hi })
    srcDim.setData({ type: 'FeatureCollection', features: lo })
    return
  }

  // Real backend rail geometry (`shape`) is authoritative and drawn as-is. The
  // raw-stops fallback (edit mode, before a shape is computed) is rendered as a
  // schematic octilinear "train itinerary" connector instead of a straight line.
  const coords =
    props.shape?.coordinates ??
    octilinearPath(props.stops.map((s) => [s.lon, s.lat] as [number, number]))
  src.setData({ type: 'FeatureCollection', features: [lineFeature(coords)] })
  srcDim.setData({ type: 'FeatureCollection', features: [] })
}

function fitToStops(animate: boolean) {
  if (!map || !mapLoaded || props.stops.length === 0) return
  const duration = animate ? 900 : 0
  if (props.stops.length === 1) {
    map.flyTo({ center: [props.stops[0].lon, props.stops[0].lat], zoom: 9, duration })
  } else {
    const bounds = new maplibregl.LngLatBounds()
    props.stops.forEach((s) => bounds.extend([s.lon, s.lat]))
    map.fitBounds(bounds, { padding: 80, maxZoom: 10, duration })
  }
  initialFitDone = true
}

function initLayers() {
  if (!map) return
  for (const id of [ROUTE_SOURCE_DIM, ROUTE_SOURCE]) {
    map.addSource(id, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })
  }
  map.addLayer({
    id: ROUTE_LAYER_DIM,
    type: 'line',
    source: ROUTE_SOURCE_DIM,
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': DIMMED, 'line-width': 2.5, 'line-opacity': 0.9 },
  })
  map.addLayer({
    id: ROUTE_LAYER,
    type: 'line',
    source: ROUTE_SOURCE,
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': PRIMARY, 'line-width': 3, 'line-opacity': 0.95 },
  })
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
    syncMarkers()
    syncPolyline()
    fitToStops(false)
  })
})

// Stops/shape change → remarker, redraw, refit. Segments (scope) change →
// redraw only, so toggling scope doesn't reset the user's manual zoom.
watch(
  () => [props.stops, props.shape],
  () => {
    syncMarkers()
    syncPolyline()
    fitToStops(initialFitDone)
  },
  { deep: true },
)
watch(() => props.segments, syncPolyline, { deep: true })

onUnmounted(() => {
  markers.forEach((m) => m.remove())
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="mapContainer" style="width: 100%; height: 100%; min-height: 480px" />
</template>
