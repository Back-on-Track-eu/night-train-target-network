<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-csp-worker.js?url'

// Vite 8 production builds corrupt the worker MapLibre assembles from its own
// bundled code (maplibre-gl-js#7339): GeoJSON sources then fail in the worker
// ("<name> is not defined") and route lines never render, while dev builds are
// unaffected. Point MapLibre at the self-contained CSP worker file instead so
// the worker never depends on how the main bundle was chunked or minified.
maplibregl.setWorkerUrl(maplibreWorkerUrl)
import { octilinearPath } from '@/utils/octilinear'

// Two sources/layers: the in-scope route (highlighted) and the out-of-scope
// route (dimmed grey). The dim layer is added first so the highlight draws on
// top of it at shared junctions.
const ROUTE_SOURCE = 'route'
const ROUTE_SOURCE_DIM = 'route-dim'
const ROUTE_LAYER = 'route-line'
const ROUTE_LAYER_DIM = 'route-line-dim'
// Invisible, much wider copies of the two line layers, used only as hover
// targets — a 3px line is near-impossible to hit with the cursor, and MapLibre
// still hit-tests layers painted at zero opacity.
const ROUTE_LAYER_HIT = 'route-line-hit'
const ROUTE_LAYER_DIM_HIT = 'route-line-dim-hit'
const HIT_LAYERS = [ROUTE_LAYER_HIT, ROUTE_LAYER_DIM_HIT]
// Persistent station-name labels, from their own point source.
const STOPS_SOURCE = 'stops'
const STOPS_LABEL_LAYER = 'stops-label'
const PRIMARY = '#2271b3'
const PRIMARY_LIGHT = '#eef4fb'
// A lighter tint of PRIMARY (not grey) for out-of-scope route parts and stops.
const DIMMED = '#9cc0e5'
// Label and tooltip text sits directly on the near-white basemap, which needs
// more contrast than the marker fills do — so text uses a darker shade of each
// tint than the corresponding line/marker.
const LABEL_PRIMARY = '#15517f'
const LABEL_DIMMED = '#7aa6d0'
// Font stacks the basemap's own glyph server already serves (see the Carto
// positron style): bold for the route endpoints, regular for intermediate stops.
const FONT_BOLD = ['Montserrat Medium', 'Open Sans Bold', 'Noto Sans Regular']
const FONT_REGULAR = ['Montserrat Regular', 'Open Sans Regular', 'Noto Sans Regular']
// Sentinel for "no travel time available" in feature properties, which cannot
// carry null through MapLibre's GeoJSON serialisation reliably.
const NO_TRAVEL_TIME = -1
// west, south, east, north — generous Europe + North Africa margin
const EUROPE_BOUNDS: [number, number, number, number] = [-30, 27, 50, 73]

interface MarkerStop {
  lat: number
  lon: number
  name: string
  highlighted: boolean
}

// One leg of the route: its geometry plus the endpoint names and travel time
// shown when the leg is hovered.
interface MapSegment {
  coordinates: [number, number][]
  highlighted: boolean
  fromName: string
  toName: string
  travelMinutes: number | null
}

const props = defineProps<{
  stops: MarkerStop[]
  shape?: { type: string; coordinates: [number, number][] } | null
  // When provided, the route is drawn per-leg so out-of-scope parts can be
  // dimmed (highlighted=false) and each leg can be hovered for its travel time.
  // Falls back to `shape` (all highlighted) when absent.
  segments?: MapSegment[] | null
}>()

const { t } = useI18n()

const mapContainer = ref<HTMLDivElement | null>(null)
let map: maplibregl.Map | null = null
let markers: maplibregl.Marker[] = []
let hoverPopup: maplibregl.Popup | null = null
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

// The station-name labels are a MapLibre symbol layer rather than DOM added to
// each marker, so we get collision handling (dense stop sequences drop the
// labels that would overlap) for free.
function syncStopLabels() {
  if (!map || !mapLoaded) return
  const src = map.getSource(STOPS_SOURCE) as maplibregl.GeoJSONSource | undefined
  if (!src) return
  const n = props.stops.length
  src.setData({
    type: 'FeatureCollection',
    features: props.stops.map((stop, i) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [stop.lon, stop.lat] },
      properties: {
        name: stop.name,
        endpoint: i === 0 || i === n - 1,
        highlighted: stop.highlighted,
      },
    })),
  })
}

type LegProps = { fromName: string; toName: string; travelMinutes: number }

function lineFeature(coordinates: [number, number][], properties: LegProps | null = null) {
  return {
    type: 'Feature' as const,
    geometry: { type: 'LineString' as const, coordinates },
    properties: properties ?? {},
  }
}

function legFeature(seg: MapSegment) {
  return lineFeature(seg.coordinates, {
    fromName: seg.fromName,
    toName: seg.toName,
    travelMinutes: seg.travelMinutes ?? NO_TRAVEL_TIME,
  })
}

function syncPolyline() {
  if (!map || !mapLoaded) return
  const src = map.getSource(ROUTE_SOURCE) as maplibregl.GeoJSONSource | undefined
  const srcDim = map.getSource(ROUTE_SOURCE_DIM) as maplibregl.GeoJSONSource | undefined
  if (!src || !srcDim) return
  // The route being redrawn invalidates whatever leg the tooltip was showing.
  hideLegTooltip()

  if (props.segments && props.segments.length > 0) {
    const hi = props.segments.filter((s) => s.highlighted).map(legFeature)
    const lo = props.segments.filter((s) => !s.highlighted).map(legFeature)
    src.setData({ type: 'FeatureCollection', features: hi })
    srcDim.setData({ type: 'FeatureCollection', features: lo })
    return
  }

  // Real backend rail geometry (`shape`) is authoritative and drawn as-is. It
  // arrives as one stitched polyline with no per-leg boundaries, so it carries
  // no hover properties.
  if (props.shape) {
    src.setData({ type: 'FeatureCollection', features: [lineFeature(props.shape.coordinates)] })
    srcDim.setData({ type: 'FeatureCollection', features: [] })
    return
  }

  // The raw-stops fallback (edit mode, before a shape is computed) is rendered
  // as a schematic octilinear "train itinerary" connector instead of a straight
  // line. octilinearPath treats each leg independently, so building it one leg
  // at a time draws the same shape while keeping every leg hoverable — with no
  // travel time, since there is no timetable yet.
  const legs = []
  for (let i = 0; i < props.stops.length - 1; i++) {
    const from = props.stops[i]
    const to = props.stops[i + 1]
    const coords = octilinearPath([
      [from.lon, from.lat],
      [to.lon, to.lat],
    ])
    legs.push(
      lineFeature(coords, {
        fromName: from.name,
        toName: to.name,
        travelMinutes: NO_TRAVEL_TIME,
      }),
    )
  }
  src.setData({ type: 'FeatureCollection', features: legs })
  srcDim.setData({ type: 'FeatureCollection', features: [] })
}

// Minutes -> "6h 12m" / "3h" / "45m". Deliberately distinct from the "HH:MM"
// clock format used for stop arrival/departure times.
function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return t('proposal.map.durationM', { m })
  if (m === 0) return t('proposal.map.durationH', { h })
  return t('proposal.map.durationHm', { h, m })
}

function tooltipLine(text: string, styles: Partial<CSSStyleDeclaration>): HTMLDivElement {
  const el = document.createElement('div')
  el.textContent = text
  Object.assign(el.style, styles)
  return el
}

// Built as DOM rather than HTML so station names are never interpolated into
// markup. Colours are inlined from the constants above, like makeMarkerEl.
function legTooltipContent(featureProps: Record<string, unknown>): HTMLElement {
  const root = document.createElement('div')
  const from = String(featureProps.fromName ?? '')
  const to = String(featureProps.toName ?? '')
  const minutes = Number(featureProps.travelMinutes)
  const duration =
    Number.isFinite(minutes) && minutes >= 0
      ? formatDuration(minutes)
      : t('proposal.map.unknownDuration')

  root.append(
    tooltipLine(`${from} → ${to}`, {
      color: LABEL_PRIMARY,
      fontWeight: '600',
      whiteSpace: 'nowrap',
    }),
    tooltipLine(`${t('proposal.map.travelTime')} ${duration}`, {
      color: LABEL_DIMMED,
      marginTop: '2px',
    }),
  )
  return root
}

function onLegHover(e: maplibregl.MapLayerMouseEvent) {
  const feature = e.features?.[0]
  if (!map || !hoverPopup || !feature || feature.properties?.fromName === undefined) return
  map.getCanvas().style.cursor = 'pointer'
  hoverPopup.setLngLat(e.lngLat).setDOMContent(legTooltipContent(feature.properties)).addTo(map)
}

function hideLegTooltip() {
  if (map) map.getCanvas().style.cursor = ''
  hoverPopup?.remove()
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
  for (const id of [ROUTE_SOURCE_DIM, ROUTE_SOURCE, STOPS_SOURCE]) {
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
  for (const [id, source] of [
    [ROUTE_LAYER_DIM_HIT, ROUTE_SOURCE_DIM],
    [ROUTE_LAYER_HIT, ROUTE_SOURCE],
  ]) {
    map.addLayer({
      id,
      type: 'line',
      source,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': PRIMARY, 'line-width': 16, 'line-opacity': 0 },
    })
  }
  map.addLayer({
    id: STOPS_LABEL_LAYER,
    type: 'symbol',
    source: STOPS_SOURCE,
    layout: {
      'text-field': ['get', 'name'],
      'text-font': ['case', ['get', 'endpoint'], ['literal', FONT_BOLD], ['literal', FONT_REGULAR]],
      'text-size': ['case', ['get', 'endpoint'], 13, 11],
      'text-max-width': 8,
      'text-padding': 3,
      // Radial placement lets MapLibre put each label on whichever side of its
      // marker is free, so dense stop sequences keep more of their names.
      'text-variable-anchor': ['left', 'right', 'top', 'bottom'],
      'text-radial-offset': 0.9,
      'text-justify': 'auto',
      // Lower sort key wins a collision, so endpoints outrank intermediate stops.
      'symbol-sort-key': ['case', ['get', 'endpoint'], 0, 1],
    },
    paint: {
      'text-color': ['case', ['get', 'highlighted'], LABEL_PRIMARY, LABEL_DIMMED],
      'text-halo-color': PRIMARY_LIGHT,
      'text-halo-width': 1.6,
      'text-halo-blur': 0.2,
    },
  })

  map.on('mousemove', HIT_LAYERS, onLegHover)
  map.on('mouseleave', HIT_LAYERS, hideLegTooltip)
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
  // Follows the cursor along the hovered leg; `leg-tooltip` also turns off its
  // pointer events so it can never steal the hover from the line underneath.
  hoverPopup = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    offset: 14,
    className: 'leg-tooltip',
    maxWidth: '280px',
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
  map.on('load', () => {
    mapLoaded = true
    initLayers()
    syncMarkers()
    syncStopLabels()
    syncPolyline()
    fitToStops(false)
  })
})

// Stops/shape change → remarker, relabel, redraw, refit. Segments (scope)
// change → redraw only, so toggling scope doesn't reset the user's manual zoom.
watch(
  () => [props.stops, props.shape],
  () => {
    syncMarkers()
    syncStopLabels()
    syncPolyline()
    fitToStops(initialFitDone)
  },
  { deep: true },
)
// Scope also decides which stops are lit, so the labels follow the segments.
watch(
  () => props.segments,
  () => {
    syncStopLabels()
    syncPolyline()
  },
  { deep: true },
)

onUnmounted(() => {
  markers.forEach((m) => m.remove())
  hoverPopup?.remove()
  hoverPopup = null
  map?.remove()
  map = null
})
</script>

<template>
  <div
    ref="mapContainer"
    class="overflow-hidden rounded-xl"
    style="width: 100%; height: 100%; min-height: 480px"
  />
</template>

<style scoped>
/* MapLibre mounts popups inside the map container (this component's root), so
   :deep() reaches them. Scoped to .leg-tooltip so the marker click popup keeps
   its default look. */
:deep(.leg-tooltip) {
  /* Without this the tooltip sits under the cursor and steals the hover from
     the line it describes, flickering it in and out. */
  pointer-events: none;
}
:deep(.leg-tooltip .maplibregl-popup-content) {
  padding: 6px 10px;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgb(0 0 0 / 18%);
  font-size: 12px;
  line-height: 1.35;
}
:deep(.leg-tooltip .maplibregl-popup-tip) {
  display: none;
}
</style>
