<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

const ROUTE_SOURCE = 'route'
const ROUTE_LAYER = 'route-line'
const PRIMARY = '#2271b3'
const PRIMARY_LIGHT = '#eef4fb'
// west, south, east, north — generous Europe + North Africa margin
const EUROPE_BOUNDS: [number, number, number, number] = [-30, 27, 50, 73]

interface MarkerStop {
  lat: number
  lon: number
  name: string
}

const props = defineProps<{
  stops: MarkerStop[]
  shape?: { type: string; coordinates: [number, number][] } | null
}>()

const mapContainer = ref<HTMLDivElement | null>(null)
let map: maplibregl.Map | null = null
let markers: maplibregl.Marker[] = []
let mapLoaded = false
let initialFitDone = false

function makeMarkerEl(isEndpoint: boolean): HTMLDivElement {
  const el = document.createElement('div')
  const size = isEndpoint ? 14 : 10
  Object.assign(el.style, {
    width: `${size}px`,
    height: `${size}px`,
    background: PRIMARY,
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
    const marker = new maplibregl.Marker({ element: makeMarkerEl(isEndpoint) })
      .setLngLat([stop.lon, stop.lat])
      .setPopup(new maplibregl.Popup({ offset: 12 }).setText(stop.name))
      .addTo(map!)
    markers.push(marker)
  })
}

function syncPolyline() {
  if (!map || !mapLoaded) return
  const source = map.getSource(ROUTE_SOURCE) as maplibregl.GeoJSONSource | undefined
  if (!source) return
  const geometry = props.shape ?? {
    type: 'LineString' as const,
    coordinates: props.stops.map((s) => [s.lon, s.lat]),
  }
  source.setData({ type: 'Feature', geometry, properties: {} })
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
  map.addSource(ROUTE_SOURCE, {
    type: 'geojson',
    data: {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [] },
      properties: {},
    },
  })
  map.addLayer({
    id: ROUTE_LAYER,
    type: 'line',
    source: ROUTE_SOURCE,
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': PRIMARY, 'line-width': 2.5, 'line-opacity': 0.9 },
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
  map.on('load', () => {
    mapLoaded = true
    initLayers()
    syncMarkers()
    syncPolyline()
    fitToStops(false)
  })
})

watch(
  () => [props.stops, props.shape],
  () => {
    syncMarkers()
    syncPolyline()
    fitToStops(initialFitDone)
  },
  { deep: true },
)

onUnmounted(() => {
  markers.forEach((m) => m.remove())
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="mapContainer" style="width: 100%; height: 100%; min-height: 480px" />
</template>
