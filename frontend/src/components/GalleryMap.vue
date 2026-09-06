<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
// Sets MapLibre's worker URL (maplibre-gl-js#7339). This component previously
// lacked the call while MapView.vue had it — so opening /gallery first spawned
// the corrupt worker and no route line rendered anywhere in that session.
import '@/lib/maplibreWorker'
import {
  CORRIDOR_COLORS,
  CORRIDOR_ISOLATED_WIDTH,
  ROUTE_DASH_PATTERN,
  ROUTED_FILTER,
  UNROUTED_FILTER,
  corridorBounds,
  corridorColorExpression,
  corridorWidthExpression,
  featureBounds,
  routeColorExpression,
  routeForRow,
  type GalleryRowRef,
} from '@/lib/galleryMap'
import type { MapLinesSection, MapRouteFeature } from '@/types/api'

// Two layers, two grains, one map:
//
//   OVERVIEW — `map_lines`: one line per stop-pair corridor across the whole
//   filtered set, thickness by how often it was proposed, colour by whether a
//   real night train already runs it. Read-only; the map has no hover of its
//   own, because a corridor is shared by many rows and so names no single card.
//
//   ISOLATED — `map_routes`: while a card is hovered, the corridors are hidden
//   and that row's own route is drawn instead, flat and in its source colour.
//   One route on screen means the count ramp has nothing to compare against, so
//   varying thickness along it would imply a difference that isn't there.
const EUROPE_BOUNDS: [number, number, number, number] = [-30, 27, 50, 73]
const CORRIDORS_SOURCE = 'gallery-corridors'
const CORRIDORS_LAYER = 'gallery-corridors-line'
const CORRIDORS_LAYER_DASHED = 'gallery-corridors-line-dashed'
const ROUTE_SOURCE = 'gallery-route'
// Two layers over one source, split on whether the geometry is real routing.
// `line-dasharray` is not a data-driven property in MapLibre, so the dashed
// variant has to be its own layer behind a filter rather than an expression.
const ROUTE_LAYER = 'gallery-route-line'
const ROUTE_LAYER_DASHED = 'gallery-route-line-dashed'

const props = defineProps<{
  corridors: MapLinesSection | null
  /** Routes for the rows currently listed, accumulated page by page. */
  routes: MapRouteFeature[]
  /** The row whose card is hovered — its route gets isolated and framed. */
  highlightedRow?: GalleryRowRef | null
}>()

const { t } = useI18n()
const mapContainer = ref<HTMLDivElement | null>(null)
let map: maplibregl.Map | null = null
let mapLoaded = false
// The map lives in a flex/sticky column whose width settles after init;
// MapLibre doesn't watch its container, so resize it ourselves.
let resizeObserver: ResizeObserver | null = null

const EMPTY_CORRIDORS: MapLinesSection = { type: 'FeatureCollection', features: [] }
const EMPTY_ROUTE = { type: 'FeatureCollection' as const, features: [] as MapRouteFeature[] }

const legendItems = computed(() => [
  { color: CORRIDOR_COLORS.existing, label: t('gallery.map.legend.existing') },
  { color: CORRIDOR_COLORS.proposed, label: t('gallery.map.legend.proposed') },
])

function fitTo(bounds: [number, number, number, number] | null, maxZoom: number) {
  if (!map || !bounds) return
  map.fitBounds(bounds, { padding: 60, maxZoom, duration: 600 })
}

function fitAll() {
  if (!mapLoaded) return
  fitTo(corridorBounds(props.corridors), 9)
}

/**
 * Draw the hovered row's route and hide the corridors, or the reverse when
 * nothing is hovered. A row we have no geometry for — not on a loaded page, or
 * an ONTD route whose routing failed — leaves the current view alone rather
 * than blanking the map.
 */
function applyHighlight(row: GalleryRowRef | null) {
  if (!map || !mapLoaded) return
  const feature = routeForRow(props.routes, row)
  if (row && !feature) return

  const routeSource = map.getSource(ROUTE_SOURCE) as maplibregl.GeoJSONSource | undefined
  // Colour and dash both come off the feature's own properties, so there is no
  // window in which the new geometry is drawn with the previous styling.
  routeSource?.setData(feature ? { type: 'FeatureCollection', features: [feature] } : EMPTY_ROUTE)
  const corridorsVisible = feature ? 'none' : 'visible'
  map.setLayoutProperty(CORRIDORS_LAYER, 'visibility', corridorsVisible)
  map.setLayoutProperty(CORRIDORS_LAYER_DASHED, 'visibility', corridorsVisible)

  if (feature) fitTo(featureBounds([feature]), 10)
  else fitAll()
}

function sync() {
  if (!map || !mapLoaded) return
  const source = map.getSource(CORRIDORS_SOURCE) as maplibregl.GeoJSONSource | undefined
  source?.setData(props.corridors ?? EMPTY_CORRIDORS)
  // Features are being replaced — drop any isolation so a departed route
  // cannot leave the corridors permanently hidden.
  applyHighlight(null)
  fitAll()
}

function initLayers() {
  if (!map) return
  map.addSource(CORRIDORS_SOURCE, {
    type: 'geojson',
    data: props.corridors ?? EMPTY_CORRIDORS,
  })
  // Same split as the isolated route: a corridor whose only geometry is its two
  // stops joined up is a placeholder, and must not read as a surveyed line at
  // any point — not just while a card is hovered.
  const corridorLayout = {
    'line-join': 'round' as const,
    // Busier corridors draw last, so a heavily-proposed line is never buried
    // under a single-proposal one it crosses.
    'line-sort-key': ['get', 'total_count'],
  }
  const corridorPaint = {
    'line-color': corridorColorExpression(),
    'line-width': corridorWidthExpression(),
    // Below 1 so crossing corridors still read as two lines.
    'line-opacity': 0.75,
  }
  map.addLayer({
    id: CORRIDORS_LAYER,
    type: 'line',
    source: CORRIDORS_SOURCE,
    filter: ROUTED_FILTER,
    layout: { ...corridorLayout, 'line-cap': 'round' },
    paint: corridorPaint,
  } as maplibregl.LayerSpecification)
  map.addLayer({
    id: CORRIDORS_LAYER_DASHED,
    type: 'line',
    source: CORRIDORS_SOURCE,
    filter: UNROUTED_FILTER,
    // Butt caps: round ones smear the gaps shut at these widths.
    layout: { ...corridorLayout, 'line-cap': 'butt' },
    paint: { ...corridorPaint, 'line-dasharray': ROUTE_DASH_PATTERN },
  } as maplibregl.LayerSpecification)

  map.addSource(ROUTE_SOURCE, { type: 'geojson', data: EMPTY_ROUTE })
  map.addLayer({
    id: ROUTE_LAYER,
    type: 'line',
    source: ROUTE_SOURCE,
    filter: ROUTED_FILTER,
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: {
      'line-color': routeColorExpression(),
      'line-width': CORRIDOR_ISOLATED_WIDTH,
    },
  } as maplibregl.LayerSpecification)
  // Dashed: the ONTD catalogue could not route this one, so its "geometry" is
  // just its stops joined up. Drawn, because hiding it would make half the
  // existing cards do nothing on hover — but drawn as the placeholder it is.
  map.addLayer({
    id: ROUTE_LAYER_DASHED,
    type: 'line',
    source: ROUTE_SOURCE,
    filter: UNROUTED_FILTER,
    layout: { 'line-join': 'round', 'line-cap': 'butt' },
    paint: {
      'line-color': routeColorExpression(),
      'line-width': CORRIDOR_ISOLATED_WIDTH,
      'line-dasharray': ROUTE_DASH_PATTERN,
    },
  } as maplibregl.LayerSpecification)
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
    // The first payload usually arrives before the style finishes loading, so
    // the source is created WITH it here; sync() handles every later change.
    initLayers()
    fitAll()
    if (props.highlightedRow) applyHighlight(props.highlightedRow)
  })
  resizeObserver = new ResizeObserver(() => map?.resize())
  resizeObserver.observe(mapContainer.value)
})

watch(() => props.corridors, sync)
watch(
  () => props.highlightedRow,
  (row) => applyHighlight(row ?? null),
)

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  map?.remove()
  map = null
})
</script>

<template>
  <div class="relative" style="width: 100%; height: 100%; min-height: 480px">
    <div ref="mapContainer" class="h-full w-full overflow-hidden rounded-xl" />
    <!-- Without this the "already served" signal reads as an arbitrary palette. -->
    <div
      class="bg-surface-0/90 absolute bottom-3 left-3 rounded-lg px-3 py-2 text-xs shadow-md backdrop-blur-sm"
    >
      <ul class="space-y-1">
        <li v-for="item in legendItems" :key="item.label" class="flex items-center gap-2">
          <span
            class="inline-block h-1 w-5 shrink-0 rounded-full"
            :style="{ backgroundColor: item.color }"
          />
          <span class="text-surface-700">{{ item.label }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>
