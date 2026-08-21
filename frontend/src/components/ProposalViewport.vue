<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import { useToastStore } from '@/stores/toastStore'
import type {
  EvaluationResponse,
  MapScope,
  ProposalCalcResponse,
  ProposalCalcSummary,
  PublishRequest,
  Stop,
  SuggestedStop,
} from '@/types/api'
import { publishProposal, fetchProposalRoute, ProposalsError } from '@/lib/proposalsApi'
import { resolvePrefillStops, type GallerySearchSeed } from '@/lib/proposalPrefill'
import { readDraft, writeDraft, clearDraft } from '@/lib/proposalDraftStorage'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Skeleton from 'primevue/skeleton'
import AppIcon from '@/components/AppIcon.vue'
import StopSelect from '@/components/StopSelect.vue'
import ComputeInputsPanel from '@/components/ComputeInputsPanel.vue'
import EvaluationPanel from '@/components/EvaluationPanel.vue'
import MapView from '@/components/MapView.vue'
import {
  mdiArrowLeft,
  mdiArrowLeftRight,
  mdiCalendarSync,
  mdiCheckCircle,
  mdiClose,
  mdiPencil,
  mdiPlus,
  mdiSpeedometerMedium,
  mdiSwapVertical,
  mdiTrashCan,
} from '@mdi/js'

const props = defineProps<{
  mode: 'edit' | 'loading' | 'display'
  // Set when opened from a gallery card, to load and view a stored proposal.
  proposalId?: number | null
  // The gallery search bar's state when "Suggest a new route" was clicked —
  // seeds the itinerary in fresh 'edit' mode (mode='edit', proposalId=null).
  searchSeed?: GallerySearchSeed | null
}>()
const emit = defineEmits<{ back: []; published: [proposalId: number] }>()

const { t, te } = useI18n()
const { formatInt } = useLocaleFormat()
const store = useStore()
const toastStore = useToastStore()

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:5050'

const currentMode = ref<'edit' | 'loading' | 'display' | 'suggest'>(props.mode)
const selectedCompositionId = ref<string | null>(null)
const evaluateError = ref<string | null>(null)

// Raw route as returned by POST /api/proposal/calc (before adaptRoute()) —
// the map segment/highlight logic below reads it directly.
const rawRoute = ref<BackendRoute | null>(null)
// Evaluation bundle rendered by EvaluationPanel — assembled in applyPlan()
// from the same merged calc response the route came from.
const calcResult = ref<EvaluationResponse | null>(null)
// Gallery KPI summary block of the same calc response — route-level demand /
// modal-shift / emissions figures the EvaluationPanel renders alongside the
// financial KPIs (currently placeholder values; see summary.py).
const calcSummary = ref<ProposalCalcSummary | null>(null)
// Which part of the route the evaluation panel is currently scoped to — drives
// the map's highlight/dim. 'all' = whole route.
const evalScope = ref<MapScope>({ kind: 'all' })

// Stop-suggestion state. evaluate() first computes with
// auto_stop_addition="suggest": the backend routes exactly the caller's stops
// but returns the candidate stops along the way. If any come back, we enter the
// inline 'suggest' mode (currentMode) — the timeline and map show those
// candidates so the user can pick which to include (default: none) instead of
// adding them automatically. basePlan holds that first "suggest" response so it
// can be reused directly when the user adds nothing.
const suggestedStops = ref<SuggestedStop[]>([])
const basePlan = ref<CalcResponse | null>(null)
// Suggested stop ids the user has opted in (default none). Single source of
// truth driving both the timeline bubbles and the map markers.
const suggestSelected = ref<Set<string>>(new Set())
// Pure display reversal for the suggest-mode timeline/markers — no reroute.
const suggestReversed = ref(false)

// --- Publish (persist) state ----------------------------------------------
// The resolved compute request from the last applied calc — sent verbatim to
// publish (the server recomputes from it). Null until the first successful calc.
const publishRequest = ref<Record<string, unknown> | null>(null)
// proposal_id adopted after the first publish; later saves "overwrite" it, so a
// building session yields one proposal rather than a duplicate per re-evaluation.
const publishedProposalId = ref<number | null>(null)
// Set when a calc finished but the user still has to pick an identity in the
// gate — the authChoice watcher publishes once they do.
const pendingPublish = ref(false)
const saved = ref(false)
const publishError = ref<string | null>(null)

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

// --- Shapes of POST /api/proposal/calc's "route" key, before adapting into
//     the RouteResult/TripResult/StopTimeFmt shape the rest of this component
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

// Headline physics figures the backend attaches per trip (route_serialize.py
// _trip_general_parameters) — read at a glance rather than derived from
// segments.
interface BackendGeneralParameters {
  trip_km: number
  route_duration_min: number
  average_speed_kmh: number
}

interface BackendTripSide {
  trip_id: string
  direction: number
  general_parameters: BackendGeneralParameters
  segments: BackendSegment[]
}

interface BackendTripPair {
  composition_id: string
  outbound: BackendTripSide
  return_trip: BackendTripSide
}

interface BackendGeometry {
  id: string
  coords: number[][]
}

interface BackendSeasonalSchedule {
  season: string
  frequency: string
}

interface BackendRoute {
  route_id: string
  scenario_id: number
  trip_pairs: BackendTripPair[]
  geometries: BackendGeometry[]
  schedule: { seasonal_schedules: BackendSeasonalSchedule[] }
  // Countries the route runs through — feeds evaluation rate scoping
  // (costFactorRates reads it via calcResult.input.route).
  track_infrastructure: { country_code: string }[]
}

// The merged calc response with its route key concretely typed.
type CalcResponse = ProposalCalcResponse<BackendRoute>

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

// Travel time of a leg, in minutes, from the timetable the API already returns.
// A negative difference means the leg runs over midnight, so wrap by a full day
// (the mirror-around-02:30 timetable can also put either value outside 0-1439,
// which the same modulo handles). Null when either end has no time.
function legTravelMinutes(seg: BackendSegment): number | null {
  const departure = seg.from_stop.departure_time_min
  const arrival = seg.to_stop.arrival_time_min
  if (departure == null || arrival == null) return null
  return (((arrival - departure) % 1440) + 1440) % 1440
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

// Adapts a calc response "route" object (trip_pairs[] of
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
  // In suggest mode reversing is a pure view flip of the temporary route — no
  // reroute, no redraw of the route line.
  if (currentMode.value === 'suggest') {
    suggestReversed.value = !suggestReversed.value
    return
  }
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

// POST /api/proposal/calc for the given stop ids and auto_stop_addition mode
// — the merged, stateless compute endpoint: one call returns route AND
// evaluation (no more separate plan + evaluation round trips). Returns the
// parsed response, or null on error (having set evaluateError and dropped back
// to edit mode). proposal_id/proposal_version don't exist on this request —
// persistence is publish's concern, not compute's.
async function requestCalc(
  stopIds: string[],
  autoStopAddition: 'off' | 'suggest',
): Promise<CalcResponse | null> {
  try {
    const response = await fetch(`${BASE_URL}/api/proposal/calc`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...store.authHeaders() },
      // composition_id is omitted until the user picks one: the first
      // evaluation runs on the backend's standard composition
      // (DEFAULT_COMPOSITION_ID), and applyPlan() adopts whichever one the
      // response reports back.
      body: JSON.stringify({
        stops: stopIds,
        ...(selectedCompositionId.value ? { composition_id: selectedCompositionId.value } : {}),
        auto_stop_addition: autoStopAddition,
        // Plan under the selected scenario (null = live base, resolved server-side).
        scenario_id: store.selectedScenarioId,
      }),
    })
    const json = await response.json()
    if (!response.ok) {
      evaluateError.value = json.message ?? `HTTP ${response.status}`
      currentMode.value = 'edit'
      return null
    }
    return json
  } catch (err) {
    evaluateError.value = err instanceof Error ? err.message : 'Unknown network error'
    currentMode.value = 'edit'
    return null
  }
}

// The raw backend trip currently shown (matches selectedTripId) — the source
// of the headline figures in RouteStatsCard.
const selectedBackendTrip = computed<BackendTripSide | null>(() => {
  const rr = rawRoute.value
  const id = selectedTripId.value
  if (!rr || !id) return null
  for (const pair of rr.trip_pairs) {
    if (pair.outbound.trip_id === id) return pair.outbound
    if (pair.return_trip.trip_id === id) return pair.return_trip
  }
  return null
})

// Distance / duration / average speed for the displayed trip plus the route's
// operating frequency — all straight from the calc response's route. Null
// until a route has been planned.
const routeStats = computed(() => {
  const trip = selectedBackendTrip.value
  const rr = rawRoute.value
  if (!trip || !rr) return null
  const gp = trip.general_parameters
  const frequencies = [...new Set(rr.schedule.seasonal_schedules.map((s) => s.frequency))]
  return {
    distanceKm: gp.trip_km,
    avgSpeedKmh: gp.average_speed_kmh,
    frequencies,
  }
})

// Headline route figures shown under the itinerary once a route exists.
const routeStatRows = computed(() => {
  const stats = routeStats.value
  if (!stats) return []
  const frequencies = stats.frequencies
    .map((f) => (te(`proposal.frequency.${f}`) ? t(`proposal.frequency.${f}`) : f))
    .join(', ')
  return [
    { icon: mdiArrowLeftRight, value: `${formatInt(stats.distanceKm)} km` },
    { icon: mdiSpeedometerMedium, value: `${formatInt(stats.avgSpeedKmh)} km/h` },
    { icon: mdiCalendarSync, value: frequencies },
  ]
})

// Wire a successful calc response into the display: adapt the route, publish
// the evaluation bundle, select the outbound trip, rebuild the itinerary from
// the planned route (so the builder reflects what's actually on the map —
// including any stops the user chose to add) and commit it as the clean state
// so the builder isn't "dirty" and Cancel Edit can restore exactly this.
// `publish` is true only for user-initiated evaluations (Evaluate button, stop
// selection) — a passive scenario-switch recompute passes false so it never
// creates or overwrites a proposal.
function applyPlan(json: CalcResponse, publish = false) {
  rawRoute.value = json.route
  // Assemble the panel-facing EvaluationResponse from the merged response:
  // calc_version/route_id lifted from their new positions, input.route
  // re-attached from the top-level route key (the wire carries the route
  // exactly once — costFactorRates scopes rates through input.route).
  calcResult.value = {
    calc_version: json.calc_version,
    route_id: json.route.route_id,
    models: json.evaluation.models,
    input: { route: json.route, parameters: json.evaluation.input.parameters },
    views: json.evaluation.views,
  }
  calcSummary.value = json.summary ?? null
  // Keep the resolved request so publish can send it verbatim (server recomputes).
  publishRequest.value = json.request
  const route = adaptRoute(json.route)
  routeResult.value = route
  selectedTripId.value =
    route.trips.find((t) => t.direction_id === 0)?.trip_id ?? route.trips[0]?.trip_id ?? null
  itinerary.value = itineraryFromRoute(route)
  committedItinerary.value = itinerary.value.map((s) => ({ ...s }))
  // The first calc posts no composition, so the response is where we learn
  // which one was used. Committing it in the same tick also keeps the
  // recalc watcher below quiet — it only fires on a divergence from the
  // committed value.
  selectedCompositionId.value =
    json.route.trip_pairs[0]?.composition_id ?? selectedCompositionId.value
  committedCompId.value = selectedCompositionId.value
  // Same for the scenario, which also settles the selector when a STORED
  // proposal was computed under a different one than the app currently has
  // selected — otherwise the results would show as stale the moment they load.
  const computedScenarioId = json.request.scenario_id
  if (typeof computedScenarioId === 'number') store.selectedScenarioId = computedScenarioId
  committedScenarioId.value = store.selectedScenarioId
  currentMode.value = 'display'
  if (!publish) return
  // Persist. An authenticated visitor (guest or registered) publishes right
  // away; a not-yet-decided one gets the register/guest gate first and the
  // authChoice watcher publishes once they choose.
  if (store.authChoice === 'none') {
    pendingPublish.value = true
    store.openAuthModal({
      context: 'evaluation',
      co2SavingsT: json.summary?.co2_savings_t_per_year ?? null,
    })
  } else {
    doPublish()
  }
}

// "Origin – Destination" from the outbound route — publish requires a non-empty
// name and there is no name field in the builder.
function derivedName(): string {
  const s = sectionStops.value
  if (s.length >= 2) return `${s[0].name} – ${s[s.length - 1].name}`
  if (s.length === 1) return s[0].name
  return 'Untitled route'
}

// Persist the just-computed proposal. First publish is "new" and its id is
// adopted; later saves in the same session "overwrite" it. scenario_id is nulled
// so the server stores the current base (proposals represent the base; a
// non-base scenario would 422).
async function doPublish() {
  const req = publishRequest.value
  if (!req) return
  publishError.value = null
  const body: PublishRequest = {
    mode: publishedProposalId.value ? 'overwrite' : 'new',
    name: derivedName(),
    compute_request: { ...req, scenario_id: null },
  }
  const isFirstPublish = publishedProposalId.value === null
  if (publishedProposalId.value) body.proposal_id = publishedProposalId.value
  try {
    const resp = await publishProposal(body, store.authHeaders())
    publishedProposalId.value = resp.proposal_id
    saved.value = true
    clearDraft()
    toastStore.addToast('success', t('proposal.saved'))
    if (isFirstPublish) emit('published', resp.proposal_id)
  } catch (err) {
    publishError.value = err instanceof ProposalsError ? err.message : t('proposal.publishError')
  }
}

async function evaluate() {
  const validStops = itinerary.value.filter((s) => s.selectedStop !== null)
  if (validStops.length < 2) return
  currentMode.value = 'loading'
  evaluateError.value = null
  saved.value = false
  publishError.value = null
  // First pass: "suggest" routes exactly the caller's stops and reports the
  // candidate stops along the way, without adding any automatically. The calc
  // itself runs tokenless (compute-only); the register/guest prompt only
  // appears once a result is ready, in applyPlan().
  const json = await requestCalc(
    validStops.map((s) => s.selectedStop!.stop_id),
    'suggest',
  )
  if (!json) return
  const suggestions = json.suggested_stops ?? []
  if (suggestions.length > 0) {
    // Hand the choice to the user inline (suggest mode) rather than a modal.
    basePlan.value = json
    suggestedStops.value = suggestions
    suggestSelected.value = new Set()
    suggestReversed.value = false
    currentMode.value = 'suggest'
  } else {
    applyPlan(json, true)
  }
}

// Mount-time counterpart to evaluate()'s "suggest" pass, used to restore a
// persisted draft that was mid suggest-flow. Deliberately NOT a call to
// evaluate() itself: its zero-suggestions branch calls applyPlan(json, true),
// which auto-publishes (or opens the auth gate) — reusing it here would risk
// a silent auto-publish if the backend happens to return no suggestions this
// time. On zero suggestions this just degrades to plain 'edit' instead.
async function restoreSuggestState(selectedIds: string[]) {
  const stopIds = currentStopIds.value
  if (stopIds.length < 2) return
  currentMode.value = 'loading'
  evaluateError.value = null
  const json = await requestCalc(stopIds, 'suggest')
  if (!json) return // requestCalc already reset currentMode to 'edit' and set evaluateError
  const suggestions = json.suggested_stops ?? []
  if (suggestions.length > 0) {
    basePlan.value = json
    suggestedStops.value = suggestions
    suggestSelected.value = new Set(
      selectedIds.filter((id) => suggestions.some((s) => s.stop_id === id)),
    )
    currentMode.value = 'suggest'
  } else {
    currentMode.value = 'edit'
  }
}

// User toggled a proposed stop's bubble/marker — the single selection source
// for both the timeline and the map (replace the Set so it stays reactive).
function toggleSuggested(stopId: string) {
  const next = new Set(suggestSelected.value)
  if (next.has(stopId)) next.delete(stopId)
  else next.add(stopId)
  suggestSelected.value = next
}

// User clicked "Continue with X additional stops". With no stops chosen, the
// first "suggest" response already routed exactly the caller's stops, so reuse
// it directly. Otherwise insert the chosen stops into the itinerary (by
// proximity) and recompute with auto_stop_addition="off" — the caller has made
// the selection, so no further suggestions are wanted.
async function confirmStopSelection(selectedIds: string[]) {
  const base = basePlan.value
  const chosen = suggestedStops.value.filter((s) => selectedIds.includes(s.stop_id))
  suggestedStops.value = []
  basePlan.value = null
  suggestSelected.value = new Set()
  suggestReversed.value = false
  if (!base) {
    currentMode.value = 'edit'
    store.closeAuthModal()
    return
  }
  if (chosen.length === 0) {
    applyPlan(base, true) // opens the choose-phase gate for a no-choice visitor
    return
  }
  for (const s of chosen) insertSuggestedStop(s)
  currentMode.value = 'loading'
  const stopIds = itinerary.value.filter((s) => s.selectedStop).map((s) => s.selectedStop!.stop_id)
  const json = await requestCalc(stopIds, 'off')
  if (!json) return
  applyPlan(json, true)
}

// "Adopt all suggested stops and continue" — same path as confirming a manual
// selection, just pre-filled with every candidate's id.
function adoptAllSuggested() {
  confirmStopSelection(suggestedStops.value.map((s) => s.stop_id))
}

// User backed out of suggest mode without continuing — abandon this evaluation
// and return to editing, leaving the itinerary untouched.
function cancelSuggestMode() {
  suggestedStops.value = []
  basePlan.value = null
  suggestSelected.value = new Set()
  suggestReversed.value = false
  currentMode.value = 'edit'
  store.closeAuthModal()
}

// Turn a suggested stop into a full Stop record (preferring the loaded stop
// list, falling back to the fields the suggestion already carries) and insert
// it into the itinerary at the best-fitting position via addStop().
function insertSuggestedStop(s: SuggestedStop) {
  const stop: Stop = store.stops.find((st) => st.stop_id === s.stop_id) ?? {
    stop_id: s.stop_id,
    name: s.stop_name,
    country_code: s.country_code,
    lat: s.lat,
    lon: s.lon,
    stop_charge_eur: { value: 0, is_default: true },
  }
  addStop(stop)
}

// Publish-after-auth: a no-choice visitor whose calc finished picks an identity
// in the gate; the moment they do (authChoice leaves 'none'), persist. The gate
// has no completion callback, so the store's auth state is the signal.
watch(
  () => store.authChoice,
  (choice) => {
    if (pendingPublish.value && choice !== 'none') {
      pendingPublish.value = false
      doPublish()
    }
  },
)

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
const committedScenarioId = ref<number | null>(null)

// Ordered stop ids of the current itinerary — the basis for the dirty check.
const currentStopIds = computed(() =>
  itinerary.value.filter((s) => s.selectedStop).map((s) => s.selectedStop!.stop_id),
)

// Guards the persistence watcher below against a mount-time race: while
// onMounted is still awaiting fetchStops() to restore a draft, the itinerary
// is still empty, and any watched ref settling in the meantime would be read
// as "the user cleared everything" — clearing the very draft being restored.
// Flipped true once onMounted's initial restore/prefill decision is
// finalized, whichever branch it takes.
const draftHydrated = ref(false)

// Persist the in-progress draft (itinerary, composition, and — mid
// suggest-flow — the opted-in candidate stops) so a reload can resume it.
// Only ever active for a fresh, unpublished /proposal-builder session
// (mode==='edit'); a /proposal/:id instance, or this same instance once
// router.replace flips props.mode to 'display' post-publish, never writes.
// deep: true is required, not just defensive — removeStop()/onStopSelect()
// mutate `itinerary` in place rather than reassigning it.
watch(
  [itinerary, selectedCompositionId, currentMode, suggestSelected],
  () => {
    if (!draftHydrated.value || props.mode !== 'edit' || currentMode.value === 'loading') return
    const stopIds = currentStopIds.value
    if (stopIds.length === 0) {
      clearDraft()
      return
    }
    writeDraft({
      stopIds,
      compositionId: selectedCompositionId.value,
      suggestSelectedIds: currentMode.value === 'suggest' ? [...suggestSelected.value] : null,
    })
  },
  { deep: true },
)

// The builder is "dirty" once it diverges from the last evaluated state: a
// different composition, or a different set/order of stops. Fresh (never
// evaluated) is not dirty — there's nothing to diverge from yet. A pure
// reversal is NOT dirty: both directions of the route are already computed, so
// swapping direction is a free view change, not a re-sequencing.
const isDirty = computed(() => {
  if (!committedItinerary.value) return false
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

// Changing scenario or composition marks the displayed results stale instead
// of recomputing on the spot: each arrow click through the composition
// catalogue would otherwise be a full recompute, and the new selection should
// be readable before it costs anything. Reverting to what the results were
// computed with clears the flag by itself — this is a comparison, not a latch.
// An itinerary that has itself diverged takes precedence: that path is the
// Evaluate button's, which also re-prompts for stop suggestions.
const paramsStale = computed(
  () =>
    routeResult.value !== null &&
    currentMode.value !== 'loading' &&
    currentMode.value !== 'suggest' &&
    !isDirty.value &&
    (selectedCompositionId.value !== committedCompId.value ||
      store.selectedScenarioId !== committedScenarioId.value),
)

// The stale results' recompute: same "stops are settled" call the scenario
// switch used to make on its own, now behind the user's click.
async function recomputeWithSelection() {
  const stopIds = currentStopIds.value
  if (stopIds.length < 2 || currentMode.value === 'loading') return
  currentMode.value = 'loading'
  evaluateError.value = null
  const json = await requestCalc(stopIds, 'off')
  if (json) applyPlan(json)
}

// Swap button is shown wherever there's a direction to flip: a multi-trip
// route in display, or two or more stops while editing.
const showSwap = computed(() => {
  if (currentMode.value === 'display') return (routeResult.value?.trips.length ?? 0) > 1
  if (currentMode.value === 'suggest') return (baseOutbound.value?.stop_times.length ?? 0) >= 2
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
  () =>
    currentMode.value !== 'loading' &&
    currentMode.value !== 'suggest' &&
    routeResult.value !== null,
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

// Restores an itinerary from a persisted draft's bare stop ids (see
// proposalDraftStorage.ts). Unlike itineraryFromRoute()/insertSuggestedStop(),
// there's no synthesized-fallback data to fall back on for an id no longer in
// the catalogue — such ids are simply dropped.
function itineraryFromStopIds(stopIds: string[]): ItineraryStop[] {
  const byId = new Map(store.stops.map((s) => [s.stop_id, s]))
  const rows: ItineraryStop[] = []
  for (const id of stopIds) {
    const stop = byId.get(id)
    if (stop) rows.push({ id: _nextId++, name: stop.name, selectedStop: stop })
  }
  return rows
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

// --- Suggest mode -----------------------------------------------------------
// The base "suggest" response, adapted, gives the confirmed stops (in order) and
// the temporary route shape shown on the map.
const baseOutbound = computed<TripResult | null>(() => {
  if (!basePlan.value) return null
  const rr = adaptRoute(basePlan.value.route)
  return rr.trips.find((t) => t.direction_id === 0) ?? rr.trips[0] ?? null
})

const suggestSelectedCount = computed(() => suggestSelected.value.size)

// Best insertion index for a point among an ordered coord list, minimising the
// added detour — the same nearest-neighbour rule as optimalInsertIndex, but over
// a plain coord array so it can place proposed stops without touching itinerary.
function bestInsertIndex(items: { lat: number; lon: number }[], p: { lat: number; lon: number }) {
  const n = items.length
  if (n === 0) return 0
  let bestIndex = n
  let bestExtra = Infinity
  for (let i = 0; i <= n; i++) {
    let extra: number
    if (i === 0) extra = dist(p, items[0])
    else if (i === n) extra = dist(items[n - 1], p)
    else extra = dist(items[i - 1], p) + dist(p, items[i]) - dist(items[i - 1], items[i])
    if (extra < bestExtra) {
      bestExtra = extra
      bestIndex = i
    }
  }
  return bestIndex
}

interface SuggestRow {
  kind: 'confirmed' | 'suggested'
  stopId: string
  name: string
  lat: number
  lon: number
  selected: boolean
  addedMin: number | null
}

// Confirmed stops (in order) interleaved with the proposed stops placed by
// proximity — the serialized SuggestedStop carries no leg index, so proximity is
// the robust placement. Reversed for display when the user flips direction.
const suggestRows = computed<SuggestRow[]>(() => {
  const confirmed = baseOutbound.value?.stop_times ?? []
  const rows: SuggestRow[] = confirmed.map(
    (st): SuggestRow => ({
      kind: 'confirmed',
      stopId: st.stop_id,
      name: st.stop_name,
      lat: st.lat,
      lon: st.lon,
      selected: true,
      addedMin: null,
    }),
  )
  for (const s of suggestedStops.value) {
    const idx = bestInsertIndex(rows, { lat: s.lat, lon: s.lon })
    rows.splice(idx, 0, {
      kind: 'suggested',
      stopId: s.stop_id,
      name: s.stop_name,
      lat: s.lat,
      lon: s.lon,
      selected: suggestSelected.value.has(s.stop_id),
      addedMin: s.added_time_min,
    })
  }
  return suggestReversed.value ? [...rows].reverse() : rows
})

// Indices of the first and last confirmed stop in suggestRows — only these get
// the pronounced endpoint styling (proposed stops are never endpoints).
const suggestEndpointIdx = computed(() => {
  const rows = suggestRows.value
  let first = -1
  let last = -1
  rows.forEach((r, i) => {
    if (r.kind === 'confirmed') {
      if (first < 0) first = i
      last = i
    }
  })
  return { first, last }
})

// Proposed-stop markers for MapView (suggest mode only). Independent of
// mapStops/mapShape so toggling selection re-syncs only these markers.
const mapSuggested = computed(() => {
  if (currentMode.value !== 'suggest') return null
  return suggestedStops.value.map((s) => ({
    stopId: s.stop_id,
    lat: s.lat,
    lon: s.lon,
    name: s.stop_name,
    selected: suggestSelected.value.has(s.stop_id),
  }))
})

const mapStops = computed(() => {
  // Suggest mode: only the confirmed stops are pronounced route markers; the
  // proposed stops ride on the separate `suggested` prop. Order follows the
  // reverse toggle so first/last markers match the timeline endpoints.
  if (currentMode.value === 'suggest') {
    const confirmed = (baseOutbound.value?.stop_times ?? []).map((st) => ({
      lat: st.lat,
      lon: st.lon,
      name: st.stop_name,
      highlighted: true,
    }))
    return suggestReversed.value ? [...confirmed].reverse() : confirmed
  }
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
  // Suggest mode draws the temporary route from the base "suggest" response, as
  // a single stitched polyline; it never changes when selection toggles.
  if (currentMode.value === 'suggest') return baseOutbound.value?.shape ?? null
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
  fromName: string
  toName: string
  travelMinutes: number | null
}

// Per-segment geometry for the displayed trip, each flagged highlighted/dimmed
// according to the evaluation panel's current scope and carrying the endpoint
// names + travel time MapView shows on hover. Null outside display mode (MapView
// then falls back to the plain shape).
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
    // Identity of the leg for the hover tooltip. A leg split at a border keeps
    // the same names/time on both halves — either half describes the whole leg.
    const leg = {
      fromName: seg.from_stop.stop_name,
      toName: seg.to_stop.stop_name,
      travelMinutes: legTravelMinutes(seg),
    }
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
        out.push({ ...leg, coordinates: before, highlighted: fromC === scope.country })
        out.push({ ...leg, coordinates: after, highlighted: toC === scope.country })
      } else {
        const inScope =
          fromC === scope.country || toC === scope.country || countries.includes(scope.country)
        out.push({ ...leg, coordinates: coords, highlighted: inScope })
      }
      return
    }
    let highlighted: boolean
    if (scope.kind === 'stop')
      highlighted = false // whole line dims; only the marker stays lit
    else if (scope.kind === 'od') highlighted = odRange ? i >= odRange[0] && i < odRange[1] : true
    else highlighted = true
    out.push({ ...leg, coordinates: coords, highlighted })
  })

  // Safety: a country/OD scope that matched nothing shouldn't grey the whole
  // route (by-stop dims deliberately, so it's exempt).
  if (scope.kind !== 'stop' && !out.some((s) => s.highlighted)) {
    return out.map((s) => ({ ...s, highlighted: true }))
  }
  return out
})

// Load a stored proposal by id and populate display mode — same wire shape
// as POST /api/proposal/calc (see types/api.ts's ProposalDetailResponse), so
// applyPlan() can hydrate rawRoute/calcResult/itinerary from it exactly like
// a fresh calc. selectedCompositionId is set first so CompositionPanel
// locks onto the composition the stored route actually used, rather than
// defaulting to the first one in the full catalogue.
async function loadStoredProposal(proposalId: number) {
  currentMode.value = 'loading'
  try {
    const detail = await fetchProposalRoute<BackendRoute>(proposalId)
    publishedProposalId.value = detail.proposal_id
    selectedCompositionId.value = detail.route.trip_pairs[0]?.composition_id ?? null
    applyPlan(
      {
        route_builder_version: detail.route_builder_version,
        calc_version: detail.calc_version,
        route_fingerprint: detail.route_fingerprint,
        request: detail.request,
        summary: detail.summary,
        route: detail.route,
        evaluation: detail.evaluation,
      },
      false,
    )
  } catch (err) {
    evaluateError.value = err instanceof ProposalsError ? err.message : t('proposal.publishError')
    currentMode.value = 'edit'
  }
}

onMounted(async () => {
  // App.vue loads this reference data at startup; only fetch if we arrived here
  // before it finished (or a fetch errored). The stop catalogue is needed both
  // to load a stored proposal's composition/stop names and to seed a fresh one.
  if (store.stopsStatus !== 'success') await store.fetchStops()
  if (store.compositionsStatus !== 'success') store.fetchCompositions()
  if (store.scenariosStatus !== 'success') store.fetchScenarios()

  if (props.mode === 'display' && props.proposalId != null) {
    await loadStoredProposal(props.proposalId)
    draftHydrated.value = true
    return
  }

  // An explicit Gallery seed always wins over a stale persisted draft — it's
  // a clear "start fresh" signal. Otherwise, resume a persisted draft if one
  // resolves to a usable itinerary; only then fall back to the random pair.
  if (!props.searchSeed) {
    const draft = readDraft()
    const restored = draft ? itineraryFromStopIds(draft.stopIds) : []
    if (restored.length >= 2) {
      itinerary.value = restored
      selectedCompositionId.value = draft!.compositionId
      if (draft!.suggestSelectedIds !== null) await restoreSuggestState(draft!.suggestSelectedIds)
      draftHydrated.value = true
      return
    }
  }

  const pair = resolvePrefillStops(props.searchSeed ?? null, store.stops)
  if (pair) {
    const [a, b] = pair
    itinerary.value = [
      { id: _nextId++, name: a.name, selectedStop: a },
      { id: _nextId++, name: b.name, selectedStop: b },
    ]
  }
  draftHydrated.value = true
})
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="flex">
      <button type="button" :class="pillClass" @click="emit('back')">
        <AppIcon :path="mdiArrowLeft" :size="16" />
        {{ t('gallery.back') }}
      </button>
    </div>
    <div
      class="flex gap-6 transition-opacity duration-200"
      :class="paramsStale ? 'opacity-40' : ''"
    >
      <!-- Left panel: shrink-wrapped to its content's natural width (the
           itinerary text) rather than a fixed share of the row, so MapView
           gets whatever width is left over. -->
      <div class="flex w-fit shrink-0 flex-col justify-center gap-12">
        <div class="itinerary-table max-w-sm">
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

          <!-- Suggest mode: confirmed stops (pronounced) interleaved with the
               proposed stops (dimmed until picked). The bubble toggles a proposal
               in/out; nothing else about the itinerary is editable here. -->
          <div v-if="currentMode === 'suggest'" class="mb-4 flex flex-col gap-1">
            <h3 class="text-lg font-bold leading-tight text-primary-50">
              {{ t('proposal.suggestions.title') }}
            </h3>
            <p class="text-sm text-primary-50/60">{{ t('proposal.suggestions.subtitle') }}</p>
          </div>
          <!-- Capped to ~7 visible rows so a long candidate list doesn't push the
               Continue button off-screen; the bottom fade signals there's more
               to scroll to, so picks below the fold aren't missed. -->
          <div v-if="currentMode === 'suggest'" class="relative mb-4">
            <DataTable
              :value="suggestRows"
              data-key="stopId"
              :pt="{
                table: { class: 'w-full border-collapse' },
                thead: { class: 'hidden' },
                row: { class: '!bg-transparent border-0' },
                bodyCell: { class: '!bg-transparent border-0 !p-0' },
              }"
              class="max-h-[16rem] overflow-y-auto"
            >
              <!-- Timeline bubble: plain dot for confirmed stops, a clickable
                   plus/close bubble for proposed ones. -->
              <Column style="width: 2.5rem" :pt="{ bodyCell: { class: 'timeline-col !p-0' } }">
                <template #body="{ data: row, index }">
                  <div class="absolute inset-0 flex items-center justify-center">
                    <div
                      class="absolute left-1/2 w-0.5 -translate-x-1/2 bg-primary-50/30"
                      :class="[
                        index === 0 ? 'top-1/2' : 'top-0',
                        index === suggestRows.length - 1 ? 'bottom-1/2' : 'bottom-0',
                      ]"
                    />
                    <div
                      v-if="row.kind === 'confirmed'"
                      class="relative z-10 rounded-full bg-primary-50"
                      :class="
                        index === suggestEndpointIdx.first || index === suggestEndpointIdx.last
                          ? 'h-4 w-4'
                          : 'h-3 w-3'
                      "
                    />
                    <button
                      v-else
                      type="button"
                      class="relative z-10 flex h-5 w-5 cursor-pointer items-center justify-center rounded-full transition-colors"
                      :class="
                        row.selected ? 'bg-primary-50' : 'bg-primary-50/30 hover:bg-primary-50/50'
                      "
                      :aria-label="
                        row.selected
                          ? t('proposal.suggestions.removeAria', { name: row.name })
                          : t('proposal.suggestions.addAria', { name: row.name })
                      "
                      @click="toggleSuggested(row.stopId)"
                    >
                      <AppIcon
                        :path="row.selected ? mdiClose : mdiPlus"
                        :size="14"
                        :color="row.selected ? '#23263d' : 'var(--p-primary-50)'"
                      />
                    </button>
                  </div>
                </template>
              </Column>

              <!-- Stop name (+ added time for proposals) -->
              <Column>
                <template #body="{ data: row, index }">
                  <div class="flex items-center gap-2 px-3 py-2">
                    <span
                      class="leading-tight"
                      :class="
                        row.kind === 'confirmed'
                          ? index === suggestEndpointIdx.first || index === suggestEndpointIdx.last
                            ? 'text-2xl font-bold text-primary-50'
                            : 'text-lg font-semibold text-primary-50'
                          : row.selected
                            ? 'text-lg font-semibold text-primary-50'
                            : 'text-lg text-primary-50/40'
                      "
                      >{{ row.name }}</span
                    >
                    <span
                      v-if="row.kind === 'suggested' && row.addedMin != null"
                      class="text-xs tabular-nums"
                      :class="row.selected ? 'text-primary-50/70' : 'text-primary-50/30'"
                    >
                      {{
                        t('proposal.suggestions.addedTime', { minutes: Math.round(row.addedMin) })
                      }}
                    </span>
                  </div>
                </template>
              </Column>
            </DataTable>
            <div
              v-if="suggestRows.length > 7"
              class="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-sapphire to-transparent"
            />
          </div>

          <!-- Display / Loading mode table -->
          <DataTable
            v-else-if="currentMode !== 'edit'"
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

          <!-- Itinerary controls, always centered as a group under the itinerary:
               Back to edit (suggest) / Edit (display) / Add Stop (edit) + Swap in
               the middle; Cancel Edit (re-edit) on the right. The two flex-1
               spacers keep the middle group centered regardless of which side
               buttons are present. -->
          <div v-if="currentMode !== 'loading'" class="flex items-center gap-2">
            <div class="flex flex-1 items-center gap-2" />

            <div class="flex items-center gap-2">
              <!-- Back to edit (suggest) — abandon the suggestion step, itinerary
                   untouched. -->
              <button
                v-if="currentMode === 'suggest'"
                :class="pillClass"
                @click="cancelSuggestMode"
              >
                <AppIcon :path="mdiArrowLeft" :size="16" />
                {{ t('proposal.suggestions.backToEdit') }}
              </button>

              <!-- Edit (display) -->
              <button v-if="currentMode === 'display'" :class="pillClass" @click="startEdit">
                <AppIcon :path="mdiPencil" :size="16" />
                {{ t('proposal.edit') }}
              </button>

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

              <!-- Swap direction (all modes where applicable) -->
              <button v-if="showSwap" :class="pillClass" @click="swapDirection">
                <AppIcon :path="mdiSwapVertical" :size="16" />
              </button>
            </div>

            <div class="flex flex-1 items-center justify-end gap-2">
              <!-- Cancel Edit (re-edit) -->
              <button v-if="showCancelEdit" :class="pillClass" @click="cancelEdit">
                <AppIcon :path="mdiClose" :size="16" />
                {{ t('proposal.cancelEdit') }}
              </button>
            </div>
          </div>

          <!-- Headline route figures — distance, average speed, frequency.
               Its own panel under the itinerary controls, matching the boxes
               in the results section. -->
          <div
            v-if="currentMode === 'display' && routeStatRows.length > 0"
            class="mt-8 flex flex-wrap justify-center gap-x-8 gap-y-3 rounded-xl bg-primary-50/5 px-4 py-3 text-primary-50/70"
          >
            <div v-for="stat in routeStatRows" :key="stat.icon" class="flex items-center gap-2">
              <AppIcon :path="stat.icon" :size="20" />
              <span class="text-base font-semibold">{{ stat.value }}</span>
            </div>
          </div>
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

        <!-- Continue button (suggest mode) — replaces Evaluate; carries the count
             of proposed stops the user opted in. Adopt-all is a tertiary shortcut
             beside it for taking every candidate without picking one by one. -->
        <div v-if="currentMode === 'suggest'" class="flex flex-col items-center gap-2">
          <button
            class="flex cursor-pointer items-center gap-2 rounded-full bg-primary-50/10 px-6 py-2 text-md text-primary-50 transition hover:bg-primary-50/20"
            @click="confirmStopSelection([...suggestSelected])"
          >
            {{
              suggestSelectedCount === 0
                ? t('proposal.suggestions.continueNone')
                : t('proposal.suggestions.continue', suggestSelectedCount)
            }}
            <span>→</span>
          </button>
          <button
            type="button"
            class="cursor-pointer text-sm text-primary-50/50 underline-offset-2 transition hover:text-primary-50/80 hover:underline"
            @click="adoptAllSuggested"
          >
            {{ t('proposal.suggestions.adoptAll') }}
          </button>
        </div>

        <!-- Publish status: saved confirmation (display) / publish error -->
        <div v-if="(saved && !isDirty) || publishError" class="flex flex-col items-center gap-1">
          <p v-if="saved && !isDirty" class="flex items-center gap-1.5 text-sm text-primary-50/70">
            <AppIcon :path="mdiCheckCircle" :size="16" />
            {{ t('proposal.saved') }}
          </p>
          <p v-if="publishError" class="text-xs text-red-400">{{ publishError }}</p>
        </div>
      </div>

      <!-- Right panel: map with loading overlay. The outer flex-1 div is
           stretched (default align-items:stretch) to the row's height, i.e.
           the left panel's natural content height; the inner div then reads
           that back via h-full and clamps it with max-h, so the map is
           exactly as tall as the itinerary when that's short, and capped to
           the viewport (sticky, scrolling in place until the left panel's
           extra height runs out) when it's long — a maximum, not a fixed
           height, unlike GalleryMap's browser-height map. `isolate` makes the
           inner wrapper a stacking context (as GalleryMap's sticky wrapper
           is), and the border gives the rounded edge the same visible
           definition as GalleryMap's sticky wrapper. `clip-path` (not just
           overflow-hidden + rounded-xl) is needed because the loading
           overlay's `backdrop-blur` is GPU composited like MapLibre's canvas
           (see MapView.vue) and would otherwise escape the rounded corners
           while loading. -->
      <div class="flex-1">
        <div
          class="sticky top-6 relative isolate h-full max-h-[calc(100vh-3rem)] overflow-hidden rounded-xl border border-primary-50/10"
          style="clip-path: inset(0 round 0.75rem)"
        >
          <MapView
            :stops="mapStops"
            :shape="mapShape"
            :segments="mapSegments"
            :suggested="mapSuggested"
            class="w-full h-full"
            @toggle-suggested="toggleSuggested"
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
    </div>

    <!-- Cost/revenue results (display + re-edit). Greyed out while the builder
         is dirty, since the figures no longer match the current itinerary. -->
    <div
      v-if="showEvaluationSection"
      class="w-full transition-opacity duration-200"
      :class="isDirty ? 'pointer-events-none opacity-40' : ''"
    >
      <!-- What the results were computed with. Only reachable once a route
           exists — the first evaluation runs on the standard composition.
           Stays interactive while the results below are stale: that is how
           you get back to the committed selection without recomputing. -->
      <ComputeInputsPanel
        v-if="store.compositions.length > 0 || store.scenarios.length > 0"
        class="mb-4"
        :compositions="store.compositions"
        :selected-composition-id="selectedCompositionId"
        @select-composition="(id) => (selectedCompositionId = id)"
      />

      <div class="relative">
        <!-- Route and evaluation arrive in the same calc response, so calcResult
             is always set by the time this section shows. -->
        <EvaluationPanel
          v-if="calcResult"
          :result="calcResult"
          :summary="calcSummary"
          :stops="sectionStops"
          @scope-change="onScopeChange"
        />

        <!-- Stale results: the whole area is the recompute control. -->
        <Transition name="fade">
          <button
            v-if="paramsStale"
            type="button"
            class="absolute inset-0 flex cursor-pointer items-start justify-center rounded-xl bg-sapphire/60 pt-12 backdrop-blur-[2px]"
            @click="recomputeWithSelection"
          >
            <span
              class="flex items-center gap-2 rounded-full bg-primary-500 px-6 py-2 text-md font-semibold text-white shadow-lg transition hover:bg-primary-600"
            >
              {{ t('proposal.recalculate') }}
              <span>→</span>
            </span>
          </button>
        </Transition>
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
