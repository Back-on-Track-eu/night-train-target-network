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
  ANCHOR_COLOR,
  ANCHOR_HALO,
  ANCHOR_RADIUS,
  CORRIDOR_COLORS,
  CORRIDOR_COUNT_PROPERTIES,
  CORRIDOR_DIM_FACTOR,
  CORRIDOR_ISOLATED_WIDTH,
  CORRIDOR_KINDS,
  CORRIDOR_OPACITY,
  COUNTRY_FILL_OPACITY,
  ROUTE_DASH_PATTERN,
  ROUTED_FILTER,
  STOP_END_RADIUS,
  STOP_RADIUS,
  UNROUTED_FILTER,
  anchorCollection,
  corridorPresenceFilter,
  corridorWidthExpression,
  featureBounds,
  routeColorExpression,
  routeForRow,
  routeStopsCollection,
  selectedCountriesCollection,
  type CorridorKind,
  type CountryShapesCollection,
  type GalleryRowRef,
  type GalleryStopMarker,
} from '@/lib/galleryMap'
import { loadCountryShapes } from '@/lib/countryShapes'
import { MAP_FONT_BOLD, MAP_FONT_REGULAR } from '@/lib/mapFonts'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import AppSpinner from '@/components/AppSpinner.vue'
import type { MapLinesSection, MapRouteFeature, ProposalSourceKind } from '@/types/api'

// Two grains and two kinds of highlight, one map:
//
//   OVERVIEW — `map_lines`: one line per stop-pair corridor across the whole
//   filtered set, thickness by how often it was proposed or served. Drawn in
//   two passes over the same features — existing trains first, proposals over
//   the top — so a corridor carrying both shows its suggestion in front rather
//   than resolving to a single colour. Read-only; the map has no hover of its
//   own, because a corridor is shared by many rows and so names no single card.
//
//   ISOLATED — `map_routes` + the row's stops: while a card is hovered, the
//   corridors dim and that row's own route is drawn instead, flat and in its
//   source colour, with a dot per stop (endpoints larger and labelled bold).
//   One route on screen means the count ramp has nothing to compare against,
//   so varying thickness along it would imply a difference that isn't there.
//
//   SEARCH HIGHLIGHTS — what the active search targets, persistent across
//   hover: the searched station(s) as sapphire pins, and the selected country
//   or country pair as a tinted land outline (lib/countryShapes.ts — LAND, not
//   the backend's EEZ attribution polygons, which would tint the North Sea).
const EUROPE_BOUNDS: [number, number, number, number] = [-30, 27, 50, 73]
const CORRIDORS_SOURCE = 'gallery-corridors'
// Four corridor layers: solid and dashed per kind, added in CORRIDOR_KINDS
// order so the proposal pair ends up above the existing pair.
const corridorLayerId = (kind: CorridorKind, dashed: boolean): string =>
  `gallery-corridors-${kind}${dashed ? '-dashed' : ''}`
const ROUTE_SOURCE = 'gallery-route'
// Two layers over one source, split on whether the geometry is real routing.
// `line-dasharray` is not a data-driven property in MapLibre, so the dashed
// variant has to be its own layer behind a filter rather than an expression.
const ROUTE_LAYER = 'gallery-route-line'
const ROUTE_LAYER_DASHED = 'gallery-route-line-dashed'
const STOPS_SOURCE = 'gallery-route-stops'
const STOPS_LAYER = 'gallery-route-stops'
const STOPS_LABEL_LAYER = 'gallery-route-stops-label'
const ANCHORS_SOURCE = 'gallery-anchors'
const ANCHOR_HALO_LAYER = 'gallery-anchors-halo'
const ANCHOR_LAYER = 'gallery-anchors'
const ANCHOR_LABEL_LAYER = 'gallery-anchors-label'
const COUNTRIES_SOURCE = 'gallery-countries'
const COUNTRIES_FILL_LAYER = 'gallery-countries-fill'
const COUNTRIES_LINE_LAYER = 'gallery-countries-line'

const props = defineProps<{
  corridors: MapLinesSection | null
  /** The overview's own request, loaded apart from the cards (Gallery.vue's
   *  loadCorridors): 'loading' and 'failed' get a chip on the map. */
  corridorsStatus?: 'idle' | 'loading' | 'failed'
  /** Routes for the rows currently listed, accumulated page by page. */
  routes: MapRouteFeature[]
  /** The row whose card is hovered — its route gets isolated and framed. */
  highlightedRow?: GalleryRowRef | null
  /** The hovered row's stops in travel order, resolved by the parent against
   *  the stops store (empty until the store has loaded). */
  highlightedStops?: GalleryStopMarker[]
  /** The station(s) the active search targets — pinned, and kept pinned while
   *  a card is hovered. */
  anchorStops?: GalleryStopMarker[]
  /** ISO codes of the selected country, or the pair of a relation search, in
   *  pick order. */
  highlightedCountries?: string[]
}>()

const emit = defineEmits<{ 'retry-corridors': [] }>()

const { t } = useI18n()
const { countryName } = useLocaleFormat()
const mapContainer = ref<HTMLDivElement | null>(null)
let map: maplibregl.Map | null = null
let mapLoaded = false
// The map lives in a flex/sticky column whose width settles after init;
// MapLibre doesn't watch its container, so resize it ourselves.
let resizeObserver: ResizeObserver | null = null
// The land outlines arrive once, on the first country filter; null until then,
// and a filter applied before they land is drawn by the watcher that follows.
const countryShapes = ref<CountryShapesCollection | null>(null)

const EMPTY_CORRIDORS: MapLinesSection = { type: 'FeatureCollection', features: [] }
const EMPTY_ROUTE = { type: 'FeatureCollection' as const, features: [] as MapRouteFeature[] }
const EMPTY_POINTS = { type: 'FeatureCollection' as const, features: [] }

const anchors = computed(() => props.anchorStops ?? [])
const anchorIds = computed(() => new Set(anchors.value.map((s) => s.stop_id)))
const countries = computed(() => props.highlightedCountries ?? [])
const selectedCountries = computed(() =>
  selectedCountriesCollection(countryShapes.value, countries.value),
)
// What the chip above the map says: the country, or the pair joined by an
// arrow — the vocabulary is the search bar's, so the reader can tie them.
const countryLabel = computed(() => {
  const [a, b] = countries.value
  if (a && b)
    return t('gallery.map.highlight.relation', { from: countryName(a), to: countryName(b) })
  return a ? countryName(a) : null
})

// Listed in stacking order, top layer first — the legend then reads the way
// the map draws. The three context rows appear only while their mark is on
// the map, so the legend never promises a symbol the reader cannot find.
const legendItems = computed(() => [
  ...(anchors.value.length
    ? [{ kind: 'anchor' as const, label: t('gallery.map.legend.anchor') }]
    : []),
  ...(props.highlightedRow && (props.highlightedStops?.length ?? 0) > 0
    ? [{ kind: 'stop' as const, label: t('gallery.map.legend.stops') }]
    : []),
  {
    kind: 'line' as const,
    color: CORRIDOR_COLORS.proposed,
    label: t('gallery.map.legend.proposed'),
  },
  {
    kind: 'line' as const,
    color: CORRIDOR_COLORS.existing,
    label: t('gallery.map.legend.existing'),
  },
  ...(selectedCountries.value.features.length
    ? [{ kind: 'country' as const, label: t('gallery.map.legend.country') }]
    : []),
])

const geoJsonSource = (id: string): maplibregl.GeoJSONSource | undefined =>
  map?.getSource(id) as maplibregl.GeoJSONSource | undefined

function fitTo(bounds: [number, number, number, number] | null, maxZoom: number) {
  if (!map || !bounds) return
  map.fitBounds(bounds, { padding: 60, maxZoom, duration: 600 })
}

/** Frame the overview: the corridors, plus the searched station(s) and the
 *  selected countries, so what the reader asked for is always in the frame. */
function fitAll() {
  if (!mapLoaded) return
  const framed = [
    ...(props.corridors?.features ?? []),
    ...anchorCollection(anchors.value).features,
    ...selectedCountries.value.features,
  ]
  fitTo(featureBounds(framed), 9)
}

function setCorridorsDimmed(dimmed: boolean) {
  if (!map) return
  for (const kind of CORRIDOR_KINDS) {
    const opacity = CORRIDOR_OPACITY[kind] * (dimmed ? CORRIDOR_DIM_FACTOR : 1)
    map.setPaintProperty(corridorLayerId(kind, false), 'line-opacity', opacity)
    map.setPaintProperty(corridorLayerId(kind, true), 'line-opacity', opacity)
  }
}

/**
 * Draw the hovered row's route and stops over dimmed corridors, or restore the
 * overview when nothing is hovered. A row we have neither geometry nor stops
 * for — not on a loaded page, with the stops store still loading — leaves the
 * current view alone rather than blanking the map. An ONTD route whose routing
 * failed still shows its stops: the line is missing, the itinerary is not.
 */
function applyHighlight(row: GalleryRowRef | null) {
  if (!map || !mapLoaded) return
  const feature = routeForRow(props.routes, row)
  const stops = row ? (props.highlightedStops ?? []) : []
  if (row && !feature && !stops.length) return

  const source: ProposalSourceKind = row?.kind === 'existing' ? 'existing' : 'proposal'
  // Colour and dash both come off the feature's own properties, so there is no
  // window in which the new geometry is drawn with the previous styling.
  geoJsonSource(ROUTE_SOURCE)?.setData(
    feature ? { type: 'FeatureCollection', features: [feature] } : EMPTY_ROUTE,
  )
  geoJsonSource(STOPS_SOURCE)?.setData(
    row ? routeStopsCollection(stops, source, anchorIds.value) : EMPTY_POINTS,
  )
  setCorridorsDimmed(!!row)

  if (!row) {
    fitAll()
    return
  }
  // The searched station stays in the frame even when the hovered route only
  // passes it at one end.
  const framed = [
    ...(feature ? [feature] : []),
    ...anchorCollection([...stops, ...anchors.value]).features,
  ]
  fitTo(featureBounds(framed), 10)
}

function syncAnchors() {
  if (!mapLoaded) return
  geoJsonSource(ANCHORS_SOURCE)?.setData(anchorCollection(anchors.value))
}

function syncCountries() {
  if (!mapLoaded) return
  geoJsonSource(COUNTRIES_SOURCE)?.setData(selectedCountries.value)
}

function sync() {
  if (!map || !mapLoaded) return
  geoJsonSource(CORRIDORS_SOURCE)?.setData(props.corridors ?? EMPTY_CORRIDORS)
  // The corridors load apart from the cards, so they can land while a card is
  // hovered: keep that route isolated and framed — the new corridors appear
  // dimmed behind it. Otherwise drop any isolation (applyHighlight(null)
  // refits), so a departed route cannot leave the corridors permanently dimmed.
  if (routeForRow(props.routes, props.highlightedRow ?? null)) return
  applyHighlight(null)
}

function initLayers() {
  if (!map) return
  // Countries go in first and so draw below everything else: a tint under the
  // corridors, never a veil over them.
  map.addSource(COUNTRIES_SOURCE, { type: 'geojson', data: selectedCountries.value })
  map.addLayer({
    id: COUNTRIES_FILL_LAYER,
    type: 'fill',
    source: COUNTRIES_SOURCE,
    paint: {
      'fill-color': CORRIDOR_COLORS.proposed,
      'fill-opacity': [
        'case',
        ['==', ['get', 'rank'], 0],
        COUNTRY_FILL_OPACITY[0],
        COUNTRY_FILL_OPACITY[1],
      ],
    },
  } as maplibregl.LayerSpecification)
  map.addLayer({
    id: COUNTRIES_LINE_LAYER,
    type: 'line',
    source: COUNTRIES_SOURCE,
    layout: { 'line-join': 'round' },
    paint: { 'line-color': CORRIDOR_COLORS.proposed, 'line-width': 1.5, 'line-opacity': 0.9 },
  } as maplibregl.LayerSpecification)

  map.addSource(CORRIDORS_SOURCE, {
    type: 'geojson',
    data: props.corridors ?? EMPTY_CORRIDORS,
  })
  // Two passes over the one source, existing before proposed, each split again
  // on whether the geometry is real routing: a corridor whose only geometry is
  // its two stops joined up is a placeholder, and must not read as a surveyed
  // line at any point — not just while a card is hovered.
  for (const kind of CORRIDOR_KINDS) {
    const layout = {
      'line-join': 'round' as const,
      // Busier corridors draw last within a layer, so a heavily-proposed line
      // is never buried under a single-proposal one it crosses.
      'line-sort-key': ['get', CORRIDOR_COUNT_PROPERTIES[kind]],
    }
    const paint = {
      'line-color': CORRIDOR_COLORS[kind],
      'line-width': corridorWidthExpression(kind),
      'line-opacity': CORRIDOR_OPACITY[kind],
      // Fading in and out rather than snapping when a card is hovered.
      'line-opacity-transition': { duration: 200, delay: 0 },
    }
    const presence = corridorPresenceFilter(kind)
    map.addLayer({
      id: corridorLayerId(kind, false),
      type: 'line',
      source: CORRIDORS_SOURCE,
      filter: ['all', presence, ROUTED_FILTER],
      layout: { ...layout, 'line-cap': 'round' },
      paint,
    } as maplibregl.LayerSpecification)
    map.addLayer({
      id: corridorLayerId(kind, true),
      type: 'line',
      source: CORRIDORS_SOURCE,
      // Butt caps: round ones smear the gaps shut at these widths.
      filter: ['all', presence, UNROUTED_FILTER],
      layout: { ...layout, 'line-cap': 'butt' },
      paint: { ...paint, 'line-dasharray': ROUTE_DASH_PATTERN },
    } as maplibregl.LayerSpecification)
  }

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

  // The hovered route's stops: hollow dots in the route's colour, the two
  // endpoints filled and a step larger. Labels are a symbol layer so MapLibre
  // resolves their collisions; endpoints outrank intermediate stops.
  map.addSource(STOPS_SOURCE, { type: 'geojson', data: EMPTY_POINTS })
  const stopColor = [
    'case',
    ['==', ['get', 'source'], 'existing'],
    CORRIDOR_COLORS.existing,
    CORRIDOR_COLORS.proposed,
  ]
  map.addLayer({
    id: STOPS_LAYER,
    type: 'circle',
    source: STOPS_SOURCE,
    paint: {
      'circle-radius': ['case', ['get', 'endpoint'], STOP_END_RADIUS, STOP_RADIUS],
      'circle-color': ['case', ['get', 'endpoint'], stopColor, ANCHOR_HALO],
      'circle-stroke-color': stopColor,
      'circle-stroke-width': 2,
    },
  } as maplibregl.LayerSpecification)
  map.addLayer({
    id: STOPS_LABEL_LAYER,
    type: 'symbol',
    source: STOPS_SOURCE,
    layout: {
      'text-field': ['get', 'name'],
      'text-font': [
        'case',
        ['get', 'endpoint'],
        ['literal', MAP_FONT_BOLD],
        ['literal', MAP_FONT_REGULAR],
      ],
      'text-size': ['case', ['get', 'endpoint'], 12, 11],
      'text-max-width': 8,
      'text-padding': 3,
      'text-variable-anchor': ['left', 'right', 'top', 'bottom'],
      'text-radial-offset': 0.9,
      'text-justify': 'auto',
      'symbol-sort-key': ['case', ['get', 'endpoint'], 0, 1],
    },
    paint: {
      'text-color': ANCHOR_COLOR,
      'text-halo-color': ANCHOR_HALO,
      'text-halo-width': 1.6,
      'text-halo-blur': 0.2,
    },
  } as maplibregl.LayerSpecification)

  // The searched station(s): a sapphire pin with a white ring and a faint
  // outer halo, above the route stops so it never disappears under them.
  map.addSource(ANCHORS_SOURCE, { type: 'geojson', data: anchorCollection(anchors.value) })
  map.addLayer({
    id: ANCHOR_HALO_LAYER,
    type: 'circle',
    source: ANCHORS_SOURCE,
    paint: {
      'circle-radius': ANCHOR_RADIUS + 5,
      'circle-color': 'transparent',
      'circle-stroke-color': ANCHOR_COLOR,
      'circle-stroke-width': 1.5,
      'circle-stroke-opacity': 0.45,
    },
  } as maplibregl.LayerSpecification)
  map.addLayer({
    id: ANCHOR_LAYER,
    type: 'circle',
    source: ANCHORS_SOURCE,
    paint: {
      'circle-radius': ANCHOR_RADIUS,
      'circle-color': ANCHOR_COLOR,
      'circle-stroke-color': ANCHOR_HALO,
      'circle-stroke-width': 2.5,
    },
  } as maplibregl.LayerSpecification)
  map.addLayer({
    id: ANCHOR_LABEL_LAYER,
    type: 'symbol',
    source: ANCHORS_SOURCE,
    layout: {
      'text-field': ['get', 'name'],
      'text-font': MAP_FONT_BOLD,
      'text-size': 12,
      'text-max-width': 8,
      'text-padding': 3,
      'text-variable-anchor': ['left', 'right', 'top', 'bottom'],
      'text-radial-offset': 1.1,
      'text-justify': 'auto',
      // The pin's name beats every route-stop label in a collision.
      'symbol-sort-key': -1,
    },
    paint: {
      'text-color': ANCHOR_COLOR,
      'text-halo-color': ANCHOR_HALO,
      'text-halo-width': 1.8,
      'text-halo-blur': 0.2,
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
// The stops store can finish loading while a card is already hovered: redraw
// the same row so its dots appear without a second mouseenter.
watch(
  () => props.highlightedStops,
  () => {
    if (props.highlightedRow) applyHighlight(props.highlightedRow)
  },
)
watch(anchors, () => {
  syncAnchors()
  if (!props.highlightedRow) fitAll()
})
// First country filter fetches the outlines; every later one reuses them.
watch(
  countries,
  (codes) => {
    if (codes.length && !countryShapes.value) {
      loadCountryShapes().then((shapes) => {
        countryShapes.value = shapes
      })
    }
  },
  { immediate: true },
)
watch(selectedCountries, () => {
  syncCountries()
  if (!props.highlightedRow) fitAll()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  map?.remove()
  map = null
})
</script>

<template>
  <!-- Fills whatever box the gallery gives it: the sticky column is sized to
       leave the search bar on screen beside the map (Gallery.vue's measureMap),
       so a min-height here would fight that budget on short viewports. -->
  <div class="relative h-full w-full">
    <div ref="mapContainer" class="h-full w-full overflow-hidden rounded-xl" />
    <!-- Top-left stack: the corridor request's state, and what the search
         highlights. The corridor overview loads after the cards; say so on the
         map itself rather than in the card column, which is already usable. -->
    <div class="absolute top-3 left-3 flex flex-col items-start gap-2">
      <div
        v-if="corridorsStatus === 'loading' || corridorsStatus === 'failed'"
        class="bg-surface-0/90 flex items-center gap-2 rounded-lg px-3 py-2 text-xs shadow-md backdrop-blur-sm"
        role="status"
      >
        <template v-if="corridorsStatus === 'loading'">
          <AppSpinner :size="12" />
          <span class="text-surface-700">{{ t('gallery.map.loading') }}</span>
        </template>
        <template v-else>
          <span class="text-surface-700">{{ t('gallery.map.failed') }}</span>
          <button
            type="button"
            class="cursor-pointer font-semibold text-surface-900 underline underline-offset-2"
            @click="emit('retry-corridors')"
          >
            {{ t('errors.retry') }}
          </button>
        </template>
      </div>
      <div
        v-if="countryLabel"
        class="bg-surface-0/90 rounded-lg px-3 py-2 text-xs font-semibold text-surface-900 shadow-md backdrop-blur-sm"
      >
        {{ countryLabel }}
      </div>
    </div>
    <!-- Without this the "already served" signal reads as an arbitrary palette. -->
    <div
      class="bg-surface-0/90 absolute bottom-3 left-3 rounded-lg px-3 py-2 text-xs shadow-md backdrop-blur-sm"
    >
      <ul class="space-y-1">
        <li v-for="item in legendItems" :key="item.label" class="flex items-center gap-2">
          <span
            v-if="item.kind === 'line'"
            class="inline-block h-1 w-5 shrink-0 rounded-full"
            :style="{ backgroundColor: item.color }"
          />
          <span
            v-else-if="item.kind === 'stop'"
            class="mx-1.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full border-2 bg-white"
            :style="{ borderColor: CORRIDOR_COLORS.proposed }"
          />
          <span
            v-else-if="item.kind === 'anchor'"
            class="mx-1 inline-block h-3 w-3 shrink-0 rounded-full border-2 border-white"
            :style="{ backgroundColor: ANCHOR_COLOR, boxShadow: `0 0 0 1px ${ANCHOR_COLOR}` }"
          />
          <span
            v-else
            class="inline-block h-3 w-5 shrink-0 rounded-sm border"
            :style="{
              borderColor: CORRIDOR_COLORS.proposed,
              backgroundColor: `color-mix(in srgb, ${CORRIDOR_COLORS.proposed} 20%, white)`,
            }"
          />
          <span class="text-surface-700">{{ item.label }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>
