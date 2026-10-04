<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
// Sets MapLibre's worker URL (maplibre-gl-js#7339). This component previously
// lacked the call while MapView.vue had it — so opening /gallery first spawned
// the corrupt worker and no route line rendered anywhere in that session.
import '@/lib/maplibreWorker'
import {
  ANCHOR_CITY_RADIUS,
  ANCHOR_COLOR,
  ANCHOR_HALO,
  ANCHOR_RADIUS,
  CORRIDOR_COLORS,
  CORRIDOR_COUNT_PROPERTIES,
  CORRIDOR_ISOLATED_WIDTH,
  CORRIDOR_KINDS,
  CORRIDOR_OPACITY,
  CORRIDOR_RECEDED_COLOR,
  CORRIDOR_RECEDED_OPACITY,
  COUNTRY_COLOR,
  COUNTRY_FILL_OPACITY,
  ROUTE_CASING_COLOR,
  ROUTE_CASING_WIDTH,
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
import AppSpinner from '@/components/AppSpinner.vue'
import AppIcon from '@/components/AppIcon.vue'
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
//   corridors recede to a faint grey and that row's own route is drawn over
//   them on a white casing, flat and in its source colour, with a dot per
//   stop (endpoints larger and labelled bold). One route on screen means the
//   count ramp has nothing to compare against, so varying thickness along it
//   would imply a difference that isn't there. Grey rather than dimmed blue
//   because a thousand proposals overdraw any dimming back to full strength.
//
//   SEARCH HIGHLIGHTS — what the active search targets, persistent across
//   hover: the searched station(s) or city/cities as sapphire pins (a city
//   once, at its centroid, a step larger), the selected country or country
//   pair as a tinted land outline (lib/countryShapes.ts — LAND, not the
//   backend's EEZ attribution polygons, which would tint the North Sea), and
//   the search in words in the chip top-left, whatever the tab.
const EUROPE_BOUNDS: [number, number, number, number] = [-30, 27, 50, 73]
const CORRIDORS_SOURCE = 'gallery-corridors'
// Four corridor layers: solid and dashed per kind, added in CORRIDOR_KINDS
// order so the proposal pair ends up above the existing pair.
const corridorLayerId = (kind: CorridorKind, dashed: boolean): string =>
  `gallery-corridors-${kind}${dashed ? '-dashed' : ''}`
const ROUTE_SOURCE = 'gallery-route'
// Three layers over one source: a white casing under both variants, then the
// route split on whether the geometry is real routing. `line-dasharray` is not
// a data-driven property in MapLibre, so the dashed variant has to be its own
// layer behind a filter rather than an expression.
const ROUTE_CASING_LAYER = 'gallery-route-casing'
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
  /** The active search as the chip top-left shows it: the tab's icon and
   *  the search in words — "via Berlin Hbf", "Germany ↔ Spain" (both
   *  directions, because that is what the filter means). */
  searchSummary?: { icon: string; text: string } | null
}>()

const emit = defineEmits<{ 'retry-corridors': [] }>()

const { t } = useI18n()
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
// Whether the map is currently showing one row rather than the overview —
// mirrors applyHighlight's own bail-out: a hovered row with neither geometry
// nor stops on hand leaves the overview standing, and the legend with it.
const isolating = computed(
  () =>
    !!props.highlightedRow &&
    (!!routeForRow(props.routes, props.highlightedRow) ||
      (props.highlightedStops?.length ?? 0) > 0),
)
// Listed in stacking order, top layer first — the legend then reads the way
// the map draws. The context rows appear only while their mark is on the
// map, so the legend never promises a symbol the reader cannot find.
const legendItems = computed(() => [
  ...(anchors.value.length
    ? [
        {
          kind: 'anchor' as const,
          label: t(
            anchors.value.some((a) => a.city)
              ? 'gallery.map.legend.city'
              : 'gallery.map.legend.anchor',
          ),
        },
      ]
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
  // While a route is isolated the two colours above describe only that route;
  // everything else on the map has gone grey, and the legend says so.
  ...(isolating.value
    ? [
        {
          kind: 'line' as const,
          color: CORRIDOR_RECEDED_COLOR,
          label: t('gallery.map.legend.others'),
        },
      ]
    : []),
  ...(selectedCountries.value.features.length
    ? [{ kind: 'country' as const, label: t('gallery.map.legend.country') }]
    : []),
])

const geoJsonSource = (id: string): maplibregl.GeoJSONSource | undefined =>
  map?.getSource(id) as maplibregl.GeoJSONSource | undefined

// The overlays the fit must keep clear of: the top-left stack (loading chip,
// search chip) and the legend bottom-left. Measured, because the legend grows
// a row while a card is hovered and the chip's width is the search's.
const topLeftOverlay = ref<HTMLDivElement | null>(null)
const legendOverlay = ref<HTMLDivElement | null>(null)
// Room for a stop label beside its dot at the frame's edge — the labels are
// placed radially (left/right/top/bottom of the dot), so a point exactly on
// the padded edge still gets its name inside the map. Width of a long
// station name at 12 px, roughly.
const LABEL_ALLOWANCE_PX = 120
const LABEL_ALLOWANCE_Y_PX = 28
const OVERLAY_GUTTER_PX = 12
// MapLibre's zoom control top-right (29 px box + its 10 px margin).
const ZOOM_CONTROL_PX = 48

/**
 * Padding for fitBounds, in px per side: the overlays' footprint where they
 * sit, plus the label allowance everywhere. Capped so the two sides of an
 * axis never eat more than two thirds of the map — MapLibre throws when the
 * padding exceeds the canvas, and a phone-width map is not much wider than
 * the legend.
 */
function fitPadding(): { top: number; right: number; bottom: number; left: number } {
  const width = mapContainer.value?.clientWidth ?? 0
  const height = mapContainer.value?.clientHeight ?? 0
  const topLeft = topLeftOverlay.value
  const legend = legendOverlay.value
  const leftOverlay = Math.max(topLeft?.offsetWidth ?? 0, legend?.offsetWidth ?? 0)
  const want = {
    top: LABEL_ALLOWANCE_Y_PX + (topLeft?.offsetHeight ?? 0) + OVERLAY_GUTTER_PX,
    right: LABEL_ALLOWANCE_PX + ZOOM_CONTROL_PX,
    bottom: LABEL_ALLOWANCE_Y_PX + (legend?.offsetHeight ?? 0) + OVERLAY_GUTTER_PX,
    left: LABEL_ALLOWANCE_PX + leftOverlay + OVERLAY_GUTTER_PX,
  }
  const scaleX = Math.min(1, (width * 2) / 3 / Math.max(1, want.left + want.right))
  const scaleY = Math.min(1, (height * 2) / 3 / Math.max(1, want.top + want.bottom))
  return {
    top: Math.floor(want.top * scaleY),
    right: Math.floor(want.right * scaleX),
    bottom: Math.floor(want.bottom * scaleY),
    left: Math.floor(want.left * scaleX),
  }
}

/** Fit after the DOM has caught up with the legend/chip change that usually
 *  accompanies the call, so the padding measures what will be on screen. */
function fitTo(bounds: [number, number, number, number] | null, maxZoom: number) {
  if (!map || !bounds) return
  void nextTick(() => {
    if (!map) return
    map.fitBounds(bounds, { padding: fitPadding(), maxZoom, duration: 600 })
  })
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

/** Send the corridors to the background — faint grey — or bring them back in
 *  their own colours. Both properties are constants on these layers, so
 *  MapLibre fades them over the transitions set in initLayers. */
function setCorridorsReceded(receded: boolean) {
  if (!map) return
  for (const kind of CORRIDOR_KINDS) {
    const color = receded ? CORRIDOR_RECEDED_COLOR : CORRIDOR_COLORS[kind]
    const opacity = receded ? CORRIDOR_RECEDED_OPACITY : CORRIDOR_OPACITY[kind]
    for (const dashed of [false, true]) {
      map.setPaintProperty(corridorLayerId(kind, dashed), 'line-color', color)
      map.setPaintProperty(corridorLayerId(kind, dashed), 'line-opacity', opacity)
    }
  }
}

/**
 * Draw the hovered row's route and stops over receded corridors, or restore the
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
  setCorridorsReceded(!!row)

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
      'fill-color': COUNTRY_COLOR,
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
    // Thin and in the area's own colour: enough to close the shape against
    // the sea, never mistakable for a route.
    paint: { 'line-color': COUNTRY_COLOR, 'line-width': 1.2, 'line-opacity': 0.8 },
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
      // Fading to grey and back rather than snapping when a card is hovered.
      'line-color-transition': { duration: 200, delay: 0 },
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
  // The casing goes under both variants unfiltered and always solid: a dashed
  // placeholder route reads as dashes on a white band, which is still plainly
  // a placeholder, and a dashed casing would only double the gaps.
  map.addLayer({
    id: ROUTE_CASING_LAYER,
    type: 'line',
    source: ROUTE_SOURCE,
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': ROUTE_CASING_COLOR, 'line-width': ROUTE_CASING_WIDTH },
  } as maplibregl.LayerSpecification)
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
      'circle-radius': ['case', ['get', 'city'], ANCHOR_CITY_RADIUS + 6, ANCHOR_RADIUS + 5],
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
      'circle-radius': ['case', ['get', 'city'], ANCHOR_CITY_RADIUS, ANCHOR_RADIUS],
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
    <!-- Top-left stack: the corridor request's state, and the search in words
         (every tab — station, city or country). The corridor overview loads after the cards; say so on the
         map itself rather than in the card column, which is already usable. -->
    <div ref="topLeftOverlay" class="absolute top-3 left-3 flex flex-col items-start gap-2">
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
        v-if="searchSummary"
        class="bg-surface-0/90 flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold text-surface-900 shadow-md backdrop-blur-sm"
      >
        <AppIcon :path="searchSummary.icon" :size="14" class="shrink-0 text-surface-700" />
        <span>{{ searchSummary.text }}</span>
      </div>
    </div>
    <!-- Without this the "already served" signal reads as an arbitrary palette. -->
    <div
      ref="legendOverlay"
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
              borderColor: COUNTRY_COLOR,
              backgroundColor: `color-mix(in srgb, ${COUNTRY_COLOR} 25%, white)`,
            }"
          />
          <span class="text-surface-700">{{ item.label }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>
