<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { EvaluationResponse, MapScope, Stop } from '@/types/api'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Skeleton from 'primevue/skeleton'
import AppIcon from '@/components/AppIcon.vue'
import StopSelect from '@/components/StopSelect.vue'
import CompositionSelectCard from '@/components/CompositionSelectCard.vue'
import EvaluationPanel from '@/components/EvaluationPanel.vue'
import MapView from '@/components/MapView.vue'
import { mdiClose, mdiPencil, mdiPlus, mdiSwapVertical, mdiTrashCan } from '@mdi/js'

const props = defineProps<{ mode: 'edit' | 'loading' | 'display' }>()

const { t } = useI18n()
const store = useStore()

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:5000'

const currentMode = ref<'edit' | 'loading' | 'display'>(props.mode)
const selectedCompositionId = ref<string | null>(null)
const evaluateError = ref<string | null>(null)

// Raw route as returned by /api/route/plan (before adaptRoute()). The cost/
// revenue endpoint needs this un-adapted object, so we keep it around.
const rawRoute = ref<BackendRoute | null>(null)
// Result of POST /api/evaluation/calc — rendered by EvaluationPanel.
const calcResult = ref<EvaluationResponse | null>(null)
const calcError = ref<string | null>(null)
// Which part of the route the evaluation panel is currently scoped to — drives
// the map's highlight/dim. 'all' = whole route.
const evalScope = ref<MapScope>({ kind: 'all' })

interface StopTimeFmt {
  stop_id: string
  stop_name: string
  country_code: string
  lat: number
  lon: number
  arrival_time_fmt: string | null
  departure_time_fmt: string | null
}

interface TripResult {
  trip_id: string
  direction_id: number
  departure_time: string
  stop_times: StopTimeFmt[]
  shape: { type: string; coordinates: [number, number][] }
}

interface RouteResult {
  route_id: string
  trips: TripResult[]
}

// --- Shapes returned by POST /api/route/plan, before adapting into the
//     RouteResult/TripResult/StopTimeFmt shape the rest of this component
//     already renders against. Kept minimal — only the fields used below. ---
interface BackendStop {
  stop_id: string
  stop_name: string
  country_code: string
  lat: number
  lon: number
  arrival_time_min: number | null
  departure_time_min: number | null
}

interface BackendSegment {
  from_stop: BackendStop
  to_stop: BackendStop
  geometry_id: string
  country_distance_shares: Record<string, number>
}

interface BackendTripSide {
  trip_id: string
  direction: number
  segments: BackendSegment[]
}

interface BackendTripPair {
  outbound: BackendTripSide
  return_trip: BackendTripSide
}

interface BackendGeometry {
  id: string
  coords: number[][]
}

interface BackendRoute {
  route_id: string
  trip_pairs: BackendTripPair[]
  geometries: BackendGeometry[]
}

// Minutes-since-midnight (as returned by the API) -> "HH:MM" for display.
// Wraps values outside 0-1439 (the mirror-around-02:30 timetable can produce
// them) into a valid clock time rather than rendering "25:10".
function formatMinutes(min: number | null): string | null {
  if (min === null || min === undefined) return null
  const wrapped = ((min % 1440) + 1440) % 1440
  const h = Math.floor(wrapped / 60)
  const m = wrapped % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function toStopTimeFmt(stop: BackendStop): StopTimeFmt {
  return {
    stop_id: stop.stop_id,
    stop_name: stop.stop_name,
    country_code: stop.country_code,
    lat: stop.lat,
    lon: stop.lon,
    arrival_time_fmt: formatMinutes(stop.arrival_time_min),
    departure_time_fmt: formatMinutes(stop.departure_time_min),
  }
}

// segments[] holds one from_stop/to_stop pair per leg — walk them into the
// flat per-stop list the template expects (first leg's from_stop, then every
// leg's to_stop).
function buildStopTimes(segments: BackendSegment[]): StopTimeFmt[] {
  if (segments.length === 0) return []
  return [
    toStopTimeFmt(segments[0].from_stop),
    ...segments.map((seg) => toStopTimeFmt(seg.to_stop)),
  ]
}

// Geometry lives at route level now (route.geometries[]), referenced by
// segments[].geometry_id — stitch the referenced polylines back into one
// LineString per trip, in leg order.
function buildShape(
  segments: BackendSegment[],
  geometryById: Map<string, BackendGeometry>,
): { type: string; coordinates: [number, number][] } {
  const coordinates: [number, number][] = []
  for (const seg of segments) {
    const geom = geometryById.get(seg.geometry_id)
    if (!geom) continue
    for (const point of geom.coords) {
      coordinates.push([point[0], point[1]])
    }
  }
  return { type: 'LineString', coordinates }
}

function toTripResult(
  side: BackendTripSide,
  geometryById: Map<string, BackendGeometry>,
): TripResult {
  const stopTimes = buildStopTimes(side.segments)
  return {
    trip_id: side.trip_id,
    direction_id: side.direction,
    departure_time: stopTimes[0]?.departure_time_fmt ?? '',
    stop_times: stopTimes,
    shape: buildShape(side.segments, geometryById),
  }
}

// Adapts a POST /api/route/plan "route" object (trip_pairs[] of
// outbound/return_trip, each with segments[], plus a flat geometries[]) into
// the RouteResult shape this component was already built around.
function adaptRoute(backendRoute: BackendRoute): RouteResult {
  const geometryById = new Map(backendRoute.geometries.map((g) => [g.id, g]))
  const trips: TripResult[] = backendRoute.trip_pairs.flatMap((pair) => [
    toTripResult(pair.outbound, geometryById),
    toTripResult(pair.return_trip, geometryById),
  ])
  return { route_id: backendRoute.route_id, trips }
}

const routeResult = ref<RouteResult | null>(null)
const selectedTripId = ref<string | null>(null)

const selectedTrip = computed(
  () => routeResult.value?.trips.find((t) => t.trip_id === selectedTripId.value) ?? null,
)

// Direction toggle: reverse the stop order, and — when a routing is live
// (display, or a clean re-edit) — also swap to the other precomputed trip so
// the timetable and evaluation follow along. Because a pure reversal isn't
// "dirty", the computed view stays put; without a live routing (fresh build or
// an already-dirty edit) it's just a reorder of what's being assembled.
function swapDirection() {
  const live = showComputedView.value
  itinerary.value = [...itinerary.value].reverse()
  if (live) {
    const trips = routeResult.value?.trips ?? []
    const other = trips.find((t) => t.trip_id !== selectedTripId.value)
    if (other) selectedTripId.value = other.trip_id
  }
}

// Ordered stops (outbound direction) backing the route-section slider.
const sectionStops = computed(() => {
  const trips = routeResult.value?.trips ?? []
  const outbound = trips.find((t) => t.direction_id === 0) ?? trips[0]
  return outbound?.stop_times.map((s) => ({ stop_id: s.stop_id, name: s.stop_name })) ?? []
})

// In display mode, lock the composition card to the one used for the routing —
// a single-element list hides the card's navigation (arrows/dots).
const compositionCards = computed(() => {
  if (currentMode.value === 'display' && selectedCompositionId.value) {
    const sel = store.compositions.filter((c) => c.comp_id === selectedCompositionId.value)
    if (sel.length > 0) return sel
  }
  return store.compositions
})

async function evaluate() {
  const validStops = itinerary.value.filter((s) => s.selectedStop !== null)
  if (validStops.length < 2 || !selectedCompositionId.value) return
  currentMode.value = 'loading'
  evaluateError.value = null
  try {
    const response = await fetch(`${BASE_URL}/api/route/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        // proposal_id/proposal_version omitted — this is always a brand new
        // plan from this screen, and the API mints its own draft id/version
        // when they're absent. Per-stop stop_type is gone too: boarding/
        // alighting is now derived automatically from the timetable.
        stops: validStops.map((s) => s.selectedStop!.stop_id),
        composition_id: selectedCompositionId.value,
      }),
    })
    const json = await response.json()
    if (!response.ok) {
      evaluateError.value = json.message ?? `HTTP ${response.status}`
      currentMode.value = 'edit'
    } else {
      rawRoute.value = json.route
      const route = adaptRoute(json.route)
      routeResult.value = route
      selectedTripId.value =
        route.trips.find((t) => t.direction_id === 0)?.trip_id ?? route.trips[0]?.trip_id ?? null
      // Rebuild the itinerary from the planned route so the builder reflects
      // what's actually on the map — the router may have inserted intermediate
      // stops that are now part of the route. Commit that as the clean state so
      // the builder isn't "dirty" and Cancel Edit can restore exactly this.
      itinerary.value = itineraryFromRoute(route)
      committedItinerary.value = itinerary.value.map((s) => ({ ...s }))
      committedCompId.value = selectedCompositionId.value
      currentMode.value = 'display'
      // Fire-and-forget — let cost/revenue results fill in underneath without
      // blocking the route/map render.
      runCalc()
    }
  } catch (err) {
    evaluateError.value = err instanceof Error ? err.message : 'Unknown network error'
    currentMode.value = 'edit'
  }
}

// Cost/revenue evaluation for the completed routing. Posts the raw route to
// the backend calc endpoint (single source of truth — see plan). For now we
// just log the JSON and dump it into a panel under the viewport.
async function runCalc() {
  if (!rawRoute.value) return
  calcError.value = null
  calcResult.value = null
  try {
    const res = await fetch(`${BASE_URL}/api/evaluation/calc`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // scenario_id omitted — the route JSON carries its own.
      body: JSON.stringify({ route: rawRoute.value }),
    })
    const json = await res.json()
    if (!res.ok) {
      calcError.value = json.message ?? json.error ?? `HTTP ${res.status}`
    } else {
      calcResult.value = json as EvaluationResponse
      console.log('[calc] /api/evaluation/calc result:', json)
    }
  } catch (err) {
    calcError.value = err instanceof Error ? err.message : 'Unknown network error'
  }
}

interface ItineraryStop {
  id: number
  name: string
  selectedStop: Stop | null
}

const itinerary = ref<ItineraryStop[]>([])

let _nextId = 1

// Snapshot of the itinerary + composition as they were at the last successful
// evaluation. Used to (a) detect whether the builder has diverged from what the
// displayed routing was computed for ("dirty"), and (b) restore that state when
// the user cancels an edit. Null until the first evaluation.
const committedItinerary = ref<ItineraryStop[] | null>(null)
const committedCompId = ref<string | null>(null)

// Ordered stop ids of the current itinerary — the basis for the dirty check.
const currentStopIds = computed(() =>
  itinerary.value.filter((s) => s.selectedStop).map((s) => s.selectedStop!.stop_id),
)

// The builder is "dirty" once it diverges from the last evaluated state: a
// different composition, or a different set/order of stops. Fresh (never
// evaluated) is not dirty — there's nothing to diverge from yet. A pure
// reversal is NOT dirty: both directions of the route are already computed, so
// swapping direction is a free view change, not a re-sequencing.
const isDirty = computed(() => {
  if (!committedItinerary.value) return false
  if (selectedCompositionId.value !== committedCompId.value) return true
  const committedIds = committedItinerary.value
    .filter((s) => s.selectedStop)
    .map((s) => s.selectedStop!.stop_id)
  const cur = currentStopIds.value
  if (cur.length !== committedIds.length) return true
  const sameForward = cur.every((id, i) => id === committedIds[i])
  const sameReverse = cur.every((id, i) => id === committedIds[committedIds.length - 1 - i])
  return !sameForward && !sameReverse
})

// True when the rich computed view (times, exact map routing, evaluation) is in
// force: display mode, and re-edit mode up until the first change. Making a
// change (dirty) drops us back to the plain builder view even though we stay in
// edit mode.
const showComputedView = computed(
  () =>
    currentMode.value === 'display' ||
    (currentMode.value === 'edit' && routeResult.value !== null && !isDirty.value),
)

// Swap button is shown wherever there's a direction to flip: a multi-trip
// route in display, or two or more stops while editing.
const showSwap = computed(() => {
  if (currentMode.value === 'display') return (routeResult.value?.trips.length ?? 0) > 1
  if (currentMode.value === 'edit') return itinerary.value.length >= 2
  return false
})

// Cancel is only meaningful once there's a committed state to fall back to.
const showCancelEdit = computed(
  () => currentMode.value === 'edit' && committedItinerary.value !== null,
)

// Evaluate is shown while there's something worth (re)computing: a fresh build,
// or a dirty re-edit. It doubles as the loading spinner.
const showEvaluate = computed(
  () =>
    currentMode.value === 'loading' ||
    (currentMode.value === 'edit' && (committedItinerary.value === null || isDirty.value)),
)

// The evaluation results section is shown whenever a routing has been computed,
// i.e. in display and re-edit. It's greyed while dirty (stale results).
const showEvaluationSection = computed(
  () => currentMode.value !== 'loading' && routeResult.value !== null,
)

// Shared pill styling for the itinerary controls (Add Stop / Edit / Swap /
// Cancel), matching the direction-swap button.
const pillClass =
  'flex cursor-pointer items-center gap-1.5 rounded-full border border-primary-50/20 px-3 py-1.5 text-sm leading-none text-primary-50 transition hover:bg-primary-50/10'

// Build itinerary rows from a planned route's outbound stops, so re-editing
// starts from the actual route (router-inserted stops included), not the
// original input. Each stop is matched back to the loaded stop list to recover
// its full record, with a synthesised fallback if it isn't there.
function itineraryFromRoute(rr: RouteResult): ItineraryStop[] {
  const outbound = rr.trips.find((t) => t.direction_id === 0) ?? rr.trips[0]
  const byId = new Map(store.stops.map((s) => [s.stop_id, s]))
  return (outbound?.stop_times ?? []).map((st) => ({
    id: _nextId++,
    name: st.stop_name,
    selectedStop: byId.get(st.stop_id) ?? {
      stop_id: st.stop_id,
      name: st.stop_name,
      country_code: st.country_code,
      lat: st.lat,
      lon: st.lon,
      stop_charge_eur: { value: 0, is_default: true },
    },
  }))
}

// Computed times for an itinerary row, looked up from the selected trip by stop
// id — used to keep the timetable labels beside the (still editable) stops in a
// clean re-edit. Null when there's no computed routing to read from.
function rowTimes(
  stop: ItineraryStop,
): { arrival: string | null; departure: string | null } | null {
  const id = stop.selectedStop?.stop_id
  if (!id || !selectedTrip.value) return null
  const st = selectedTrip.value.stop_times.find((s) => s.stop_id === id)
  return st ? { arrival: st.arrival_time_fmt, departure: st.departure_time_fmt } : null
}

// Enter re-edit from display: stay on the computed view, just surface the
// editing affordances (Add Stop / drag / delete / composition / Cancel).
function startEdit() {
  currentMode.value = 'edit'
}

// Discard edits and return to the last evaluated state — including the outbound
// direction, so the restored itinerary order and the shown trip stay in sync.
function cancelEdit() {
  if (committedItinerary.value) {
    itinerary.value = committedItinerary.value.map((s) => ({ ...s }))
    selectedCompositionId.value = committedCompId.value
  }
  selectedTripId.value =
    routeResult.value?.trips.find((t) => t.direction_id === 0)?.trip_id ??
    routeResult.value?.trips[0]?.trip_id ??
    selectedTripId.value
  currentMode.value = 'display'
}

function onRowReorder(event: { value: ItineraryStop[] }) {
  itinerary.value = event.value
}

function onStopSelect(stop: ItineraryStop, selected: Stop) {
  if (isDuplicate(selected.stop_id, stop)) return
  stop.name = selected.name
  stop.selectedStop = selected
}

function removeStop(index: number) {
  itinerary.value.splice(index, 1)
}

function dist(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const dLat = a.lat - b.lat
  const dLon = a.lon - b.lon
  return Math.sqrt(dLat * dLat + dLon * dLon)
}

function optimalInsertIndex(stop: Stop): number {
  const items = itinerary.value
  const n = items.length
  if (n === 0) return 0

  const coords = (item: ItineraryStop) => item.selectedStop ?? { lat: 0, lon: 0 }

  let bestIndex = n
  let bestExtra = Infinity

  for (let i = 0; i <= n; i++) {
    let extra: number
    if (i === 0) {
      extra = dist(stop, coords(items[0]))
    } else if (i === n) {
      extra = dist(coords(items[n - 1]), stop)
    } else {
      const prev = coords(items[i - 1])
      const next = coords(items[i])
      extra = dist(prev, stop) + dist(stop, next) - dist(prev, next)
    }
    if (extra < bestExtra) {
      bestExtra = extra
      bestIndex = i
    }
  }

  return bestIndex
}

function isDuplicate(stopId: string, excludeRow?: ItineraryStop): boolean {
  return itinerary.value.some((s) => s !== excludeRow && s.selectedStop?.stop_id === stopId)
}

function addStop(stop: Stop) {
  if (isDuplicate(stop.stop_id)) return
  const index = optimalInsertIndex(stop)
  itinerary.value.splice(index, 0, {
    id: _nextId++,
    name: stop.name,
    selectedStop: stop,
  })
}

// PrimeVue's row-reorder only activates when the user mousedowns its own hidden
// handle element. We forward a synthetic event from the whole row so any drag
// gesture moves the row. The [data-row-actions] guard prevents the forward when
// the user is clicking the dropdown or remove button.
function onRowMouseDown(event: MouseEvent) {
  if ((event.target as HTMLElement).closest('[data-row-actions]')) return
  const row = (event.currentTarget as HTMLElement).closest('tr')
  const handle = row?.querySelector('[data-pc-section="reorderableRowHandle"]')
  if (handle) {
    handle.dispatchEvent(
      new MouseEvent('mousedown', {
        bubbles: true,
        cancelable: true,
        clientX: event.clientX,
        clientY: event.clientY,
      }),
    )
  }
}

const usedStopIds = computed(
  () => new Set(itinerary.value.map((s) => s.selectedStop?.stop_id).filter(Boolean) as string[]),
)

function usedStopIdsExcluding(row: ItineraryStop): Set<string> {
  const ids = new Set(usedStopIds.value)
  if (row.selectedStop) ids.delete(row.selectedStop.stop_id)
  return ids
}

interface ViewRow {
  id: number
  name: string
  arrival: string | null
  departure: string | null
}

const viewRows = computed((): ViewRow[] => {
  if (showComputedView.value && selectedTrip.value) {
    return selectedTrip.value.stop_times.map((st, i) => ({
      id: i,
      name: st.stop_name,
      arrival: st.arrival_time_fmt,
      departure: st.departure_time_fmt,
    }))
  }
  return itinerary.value.map((s) => ({
    id: s.id,
    name: s.name,
    arrival: null,
    departure: null,
  }))
})

const mapStops = computed(() => {
  if (showComputedView.value && selectedTrip.value) {
    const sts = selectedTrip.value.stop_times
    const scope = evalScope.value
    let odLo = -1
    let odHi = -1
    if (scope.kind === 'od') {
      const oi = sts.findIndex((s) => s.stop_id === scope.originStopId)
      const di = sts.findIndex((s) => s.stop_id === scope.destinationStopId)
      if (oi >= 0 && di >= 0) {
        odLo = Math.min(oi, di)
        odHi = Math.max(oi, di)
      }
    }
    return sts.map((st, i) => ({
      lat: st.lat,
      lon: st.lon,
      name: st.stop_name,
      highlighted:
        scope.kind === 'country'
          ? st.country_code === scope.country
          : scope.kind === 'stop'
            ? st.stop_id === scope.stopId
            : scope.kind === 'od'
              ? odLo >= 0 && i >= odLo && i <= odHi
              : true,
    }))
  }
  return itinerary.value
    .filter((s) => s.selectedStop !== null)
    .map((s) => ({
      lat: s.selectedStop!.lat,
      lon: s.selectedStop!.lon,
      name: s.name,
      highlighted: true,
    }))
})

const mapShape = computed(() => {
  if (showComputedView.value && selectedTrip.value) {
    return selectedTrip.value.shape
  }
  return null
})

function onScopeChange(scope: MapScope) {
  evalScope.value = scope
}

// Great-circle distance (km) between two [lon, lat] points.
function haversineKm(a: [number, number], b: [number, number]): number {
  const R = 6371
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(b[1] - a[1])
  const dLon = toRad(b[0] - a[0])
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

// Split a polyline into [before, after] at a fraction (0..1) of its length,
// interpolating the split point — used to cut a cross-border segment at the
// national border so each country's part can be highlighted independently.
function splitLineAtFraction(
  coords: [number, number][],
  fraction: number,
): [[number, number][], [number, number][]] {
  if (coords.length < 2 || fraction <= 0) return [[], coords]
  if (fraction >= 1) return [coords, []]
  const dists = coords.slice(1).map((c, i) => haversineKm(coords[i], c))
  const total = dists.reduce((s, d) => s + d, 0)
  const target = total * fraction
  let acc = 0
  for (let i = 1; i < coords.length; i++) {
    const d = dists[i - 1]
    if (acc + d >= target) {
      const t = d === 0 ? 0 : (target - acc) / d
      const p: [number, number] = [
        coords[i - 1][0] + (coords[i][0] - coords[i - 1][0]) * t,
        coords[i - 1][1] + (coords[i][1] - coords[i - 1][1]) * t,
      ]
      return [
        [...coords.slice(0, i), p],
        [p, ...coords.slice(i)],
      ]
    }
    acc += d
  }
  return [coords, []]
}

interface MapSegment {
  coordinates: [number, number][]
  highlighted: boolean
}

// Per-segment geometry for the displayed trip, each flagged highlighted/dimmed
// according to the evaluation panel's current scope. Null outside display mode
// (MapView then falls back to the plain shape).
const mapSegments = computed<MapSegment[] | null>(() => {
  const rr = rawRoute.value
  const tripId = selectedTripId.value
  if (!showComputedView.value || !rr || !tripId) return null

  let trip: BackendTripSide | null = null
  for (const pair of rr.trip_pairs) {
    if (pair.outbound.trip_id === tripId) trip = pair.outbound
    else if (pair.return_trip.trip_id === tripId) trip = pair.return_trip
    if (trip) break
  }
  if (!trip) return null

  const geoById = new Map<string, [number, number][]>(
    rr.geometries.map((g): [string, [number, number][]] => [g.id, g.coords as [number, number][]]),
  )
  const scope = evalScope.value

  // Ordered stop_ids along the trip: seg[i].from == stop[i], seg[i].to == stop[i+1].
  const stopIds = trip.segments.length
    ? [trip.segments[0].from_stop.stop_id, ...trip.segments.map((s) => s.to_stop.stop_id)]
    : []
  let odRange: [number, number] | null = null
  if (scope.kind === 'od') {
    const oi = stopIds.indexOf(scope.originStopId)
    const di = stopIds.indexOf(scope.destinationStopId)
    if (oi !== -1 && di !== -1) odRange = [Math.min(oi, di), Math.max(oi, di)]
  }

  const out: MapSegment[] = []
  trip.segments.forEach((seg, i) => {
    const coords = geoById.get(seg.geometry_id) ?? []
    if (scope.kind === 'country') {
      const fromC = seg.from_stop.country_code
      const toC = seg.to_stop.country_code
      const countries = Object.keys(seg.country_distance_shares)
      // Only a clean two-country border crossing is split precisely; single- or
      // multi-transit segments fall back to whole-segment membership.
      if (
        fromC !== toC &&
        countries.length === 2 &&
        countries.includes(fromC) &&
        countries.includes(toC)
      ) {
        const [before, after] = splitLineAtFraction(coords, seg.country_distance_shares[fromC] ?? 0)
        out.push({ coordinates: before, highlighted: fromC === scope.country })
        out.push({ coordinates: after, highlighted: toC === scope.country })
      } else {
        const inScope =
          fromC === scope.country || toC === scope.country || countries.includes(scope.country)
        out.push({ coordinates: coords, highlighted: inScope })
      }
      return
    }
    let highlighted: boolean
    if (scope.kind === 'stop')
      highlighted = false // whole line dims; only the marker stays lit
    else if (scope.kind === 'od') highlighted = odRange ? i >= odRange[0] && i < odRange[1] : true
    else highlighted = true
    out.push({ coordinates: coords, highlighted })
  })

  // Safety: a country/OD scope that matched nothing shouldn't grey the whole
  // route (by-stop dims deliberately, so it's exempt).
  if (scope.kind !== 'stop' && !out.some((s) => s.highlighted)) {
    return out.map((s) => ({ ...s, highlighted: true }))
  }
  return out
})

onMounted(async () => {
  await store.fetchStops()
  if (store.stops.length >= 2) {
    const shuffled = [...store.stops].sort(() => Math.random() - 0.5)
    itinerary.value = [
      { id: _nextId++, name: shuffled[0].name, selectedStop: shuffled[0] },
      { id: _nextId++, name: shuffled[1].name, selectedStop: shuffled[1] },
    ]
  }
  store.fetchCompositions()
})
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="flex gap-6">
      <!-- Left panel -->
      <div class="flex w-1/2 flex-col justify-center gap-12">
        <div class="itinerary-table px-32">
          <!-- Edit mode table -->
          <!-- border-collapse (set in pt.table) removes default cell spacing so
               the timeline line segments in consecutive rows connect seamlessly. -->
          <DataTable
            v-if="currentMode === 'edit'"
            :value="itinerary"
            :reorderable-rows="true"
            data-key="id"
            :pt="{
              table: { class: 'w-full border-collapse' },
              thead: { class: 'hidden' },
              row: { class: '!bg-transparent border-0' },
              bodyCell: { class: '!bg-transparent border-0 !p-0' },
            }"
            class="mb-8"
            @row-reorder="onRowReorder"
          >
            <!-- Times: only while the computed routing still applies (clean
                 re-edit); disappears the moment the builder goes dirty. -->
            <Column
              v-if="showComputedView"
              style="width: 5rem"
              :pt="{ bodyCell: { class: '!p-0' } }"
            >
              <template #body="{ data: stop }">
                <div class="flex flex-col items-end gap-1 py-2 pr-3">
                  <span
                    v-if="rowTimes(stop)?.arrival"
                    class="text-xs tabular-nums leading-none text-primary-50"
                    >{{ rowTimes(stop)?.arrival }}</span
                  >
                  <span
                    v-if="rowTimes(stop)?.departure"
                    class="text-xs tabular-nums leading-none text-primary-50"
                    >{{ rowTimes(stop)?.departure }}</span
                  >
                </div>
              </template>
            </Column>
            <Column
              row-reorder
              style="width: 2rem"
              :pt="{
                bodyCell: { class: 'reorder-col !p-0' },
                reorderableRowHandle: { style: { color: 'var(--p-primary-50)' } },
              }"
            />
            <Column style="width: 2.5rem" :pt="{ bodyCell: { class: 'timeline-col !p-0' } }">
              <template #body="{ index }">
                <div class="absolute inset-0 flex items-center justify-center">
                  <div
                    class="absolute left-1/2 w-0.5 -translate-x-1/2 bg-primary-50/30"
                    :class="[
                      index === 0 ? 'top-1/2' : 'top-0',
                      index === itinerary.length - 1 ? 'bottom-1/2' : 'bottom-0',
                    ]"
                  />
                  <div
                    class="relative z-10 rounded-full bg-primary-50"
                    :class="index === 0 || index === itinerary.length - 1 ? 'h-4 w-4' : 'h-3 w-3'"
                  />
                </div>
              </template>
            </Column>
            <Column field="name">
              <template #body="{ data: stop, index }">
                <div
                  class="group flex cursor-default select-none items-center gap-2 rounded-lg px-3 py-2"
                  @mousedown="onRowMouseDown"
                >
                  <span
                    :class="[
                      'text-primary-50 leading-tight',
                      index === 0 || index === itinerary.length - 1
                        ? 'text-2xl font-bold'
                        : 'text-lg font-semibold',
                    ]"
                  >
                    {{ stop.name }}
                  </span>

                  <div data-row-actions class="flex items-center gap-2">
                    <StopSelect
                      :stops="store.stops"
                      :disabled-ids="usedStopIdsExcluding(stop)"
                      @select="(s) => onStopSelect(stop, s)"
                    >
                      <AppIcon :path="mdiPencil" :size="20" color="var(--p-primary-50)" />
                    </StopSelect>

                    <span
                      class="inline-flex"
                      :title="itinerary.length <= 2 ? t('proposal.minStopsTooltip') : undefined"
                    >
                      <button
                        class="flex items-center justify-center text-primary-50 opacity-0 translate-x-[-8px] transition-all duration-200 ease-out group-hover:translate-x-0"
                        :class="
                          itinerary.length <= 2
                            ? 'cursor-not-allowed pointer-events-none group-hover:opacity-30'
                            : 'cursor-pointer group-hover:opacity-100'
                        "
                        :disabled="itinerary.length <= 2"
                        @click.stop="removeStop(index)"
                      >
                        <AppIcon :path="mdiTrashCan" :size="20" />
                      </button>
                    </span>
                  </div>
                </div>
              </template>
            </Column>
          </DataTable>

          <!-- Display / Loading mode table -->
          <DataTable
            v-else
            :value="viewRows"
            data-key="id"
            :pt="{
              table: { class: 'w-full border-collapse' },
              thead: { class: 'hidden' },
              row: { class: '!bg-transparent border-0' },
              bodyCell: { class: '!bg-transparent border-0 !p-0' },
            }"
            class="mb-4"
          >
            <!-- Times column (replaces drag handle) -->
            <Column style="width: 5rem" :pt="{ bodyCell: { class: '!p-0' } }">
              <template #body="{ data: row, index }">
                <div class="flex flex-col items-end gap-1 py-2 pr-3">
                  <template v-if="currentMode === 'loading'">
                    <Skeleton v-if="index > 0" width="3.5rem" height="10px" />
                    <Skeleton v-if="index < viewRows.length - 1" width="3.5rem" height="10px" />
                  </template>
                  <template v-else>
                    <span
                      v-if="row.arrival"
                      class="text-xs tabular-nums leading-none text-primary-50"
                      >{{ row.arrival }}</span
                    >
                    <span
                      v-if="row.departure"
                      class="text-xs tabular-nums leading-none text-primary-50"
                      >{{ row.departure }}</span
                    >
                  </template>
                </div>
              </template>
            </Column>

            <!-- Timeline dot -->
            <Column style="width: 2.5rem" :pt="{ bodyCell: { class: 'timeline-col !p-0' } }">
              <template #body="{ index }">
                <div class="absolute inset-0 flex items-center justify-center">
                  <div
                    class="absolute left-1/2 w-0.5 -translate-x-1/2 bg-primary-50/30"
                    :class="[
                      index === 0 ? 'top-1/2' : 'top-0',
                      index === viewRows.length - 1 ? 'bottom-1/2' : 'bottom-0',
                    ]"
                  />
                  <div
                    class="relative z-10 rounded-full bg-primary-50"
                    :class="index === 0 || index === viewRows.length - 1 ? 'h-4 w-4' : 'h-3 w-3'"
                  />
                </div>
              </template>
            </Column>

            <!-- Stop name -->
            <Column>
              <template #body="{ data: row, index }">
                <div class="flex items-center px-3 py-2">
                  <span
                    :class="[
                      'text-primary-50 leading-tight',
                      index === 0 || index === viewRows.length - 1
                        ? 'text-2xl font-bold'
                        : 'text-lg font-semibold',
                    ]"
                    >{{ row.name }}</span
                  >
                </div>
              </template>
            </Column>
          </DataTable>

          <!-- Itinerary controls: Add Stop / Edit + Swap on the left, Cancel
               Edit on the right. -->
          <div v-if="currentMode !== 'loading'" class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <!-- Add Stop (edit + re-edit) -->
              <StopSelect
                v-if="currentMode === 'edit'"
                :stops="store.stops"
                :disabled-ids="usedStopIds"
                @select="addStop"
              >
                <button :class="pillClass">
                  <AppIcon :path="mdiPlus" :size="16" />
                  {{ t('proposal.addStop') }}
                </button>
              </StopSelect>

              <!-- Edit (display) -->
              <button v-if="currentMode === 'display'" :class="pillClass" @click="startEdit">
                <AppIcon :path="mdiPencil" :size="16" />
                {{ t('proposal.edit') }}
              </button>

              <!-- Swap direction (both modes) -->
              <button v-if="showSwap" :class="pillClass" @click="swapDirection">
                <AppIcon :path="mdiSwapVertical" :size="16" />
              </button>
            </div>

            <!-- Cancel Edit (re-edit) -->
            <button v-if="showCancelEdit" :class="pillClass" @click="cancelEdit">
              <AppIcon :path="mdiClose" :size="16" />
              {{ t('proposal.cancelEdit') }}
            </button>
          </div>
        </div>

        <!-- Composition card — switchable in edit, locked to the used one in display -->
        <CompositionSelectCard
          v-if="store.compositionsStatus === 'success' && store.compositions.length > 0"
          :compositions="compositionCards"
          :selected-id="selectedCompositionId"
          @select="(id) => (selectedCompositionId = id)"
        />
        <div
          v-else
          class="flex h-32 items-center justify-center rounded-xl bg-primary-50/5 text-sm text-primary-50/40"
        >
          {{ t('proposal.trainCardPlaceholder') }}
        </div>

        <div
          v-if="store.stopsStatus === 'loading' || store.compositionsStatus === 'loading'"
          class="text-xs text-primary-50/40"
        >
          {{ t('proposal.loading') }}
        </div>
        <div v-if="store.stopsError || store.compositionsError" class="text-xs text-red-400">
          {{ store.stopsError ?? store.compositionsError }}
        </div>

        <!-- Evaluate button (fresh build, dirty re-edit, or loading) -->
        <div v-if="showEvaluate" class="flex flex-col items-center gap-2">
          <button
            :disabled="currentMode === 'loading'"
            class="flex items-center gap-2 rounded-full bg-primary-50/10 px-6 py-2 text-md text-primary-50 transition"
            :class="
              currentMode === 'loading'
                ? 'cursor-not-allowed opacity-40'
                : 'cursor-pointer hover:bg-primary-50/20'
            "
            @click="evaluate"
          >
            {{ t('proposal.evaluate') }}
            <span v-if="currentMode !== 'loading'">→</span>
            <span
              v-else
              class="h-4 w-4 animate-spin rounded-full border-2 border-primary-50/30 border-t-primary-50"
            />
          </button>
          <p v-if="evaluateError" class="text-xs text-red-400">{{ evaluateError }}</p>
        </div>
      </div>

      <!-- Right panel: map with loading overlay -->
      <div class="relative flex-1 overflow-hidden rounded-xl">
        <MapView
          :stops="mapStops"
          :shape="mapShape"
          :segments="mapSegments"
          class="w-full h-full"
        />
        <Transition name="fade">
          <div
            v-if="currentMode === 'loading'"
            class="absolute inset-0 flex items-center justify-center rounded-xl bg-black/20 backdrop-blur-sm"
          >
            <div
              class="h-10 w-10 animate-spin rounded-full border-4 border-primary-50/30 border-t-primary-50"
            />
          </div>
        </Transition>
      </div>
    </div>

    <!-- Cost/revenue results (display + re-edit). Greyed out while the builder
         is dirty, since the figures no longer match the current itinerary. -->
    <div
      v-if="showEvaluationSection"
      class="w-full transition-opacity duration-200"
      :class="isDirty ? 'pointer-events-none opacity-40' : ''"
    >
      <div v-if="calcError" class="rounded-xl bg-primary-50/5 p-4 text-sm text-red-400">
        {{ calcError }}
      </div>
      <EvaluationPanel
        v-else-if="calcResult"
        :result="calcResult"
        :stops="sectionStops"
        @scope-change="onScopeChange"
      />
      <div v-else class="rounded-xl bg-primary-50/5 p-4 text-sm text-primary-50/60">
        {{ t('proposal.evaluation.calculating') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
:deep(.p-datatable-table) {
  background: transparent;
}
:deep(.p-datatable-tbody > tr),
:deep(.p-datatable-tbody > tr > td) {
  background: transparent !important;
  border: none !important;
  font-size: inherit !important;
  user-select: none;
}
/* Timeline column: must be position:relative so absolute children span full cell height */
:deep(.timeline-col) {
  position: relative !important;
}
/* Drag handle: hover-only */
:deep(.reorder-col > *) {
  opacity: 0;
  transition: opacity 0.2s ease;
}
:deep(tr:hover .reorder-col > *) {
  opacity: 1;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
