<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import { useToastStore } from '@/stores/toastStore'
import type {
  EvaluationResponse,
  EvaluationViews,
  FamilyDocument,
  FamilyRequest,
  MapScope,
  ProposalCalcSummary,
  PublishRequest,
  Stop,
  SuggestedStop,
} from '@/types/api'
import { publishProposal, fetchProposalRoute } from '@/lib/proposalsApi'
import { createAbortSlot } from '@/lib/apiClient'
import { ApiError, asApiFailure, isRetryable, type ApiFailure } from '@/lib/apiError'
import { useApiFailure } from '@/composables/useApiFailure'
import { resolvePrefillStops, type GallerySearchSeed } from '@/lib/proposalPrefill'
import { readDraft, writeDraft, clearDraft } from '@/lib/proposalDraftStorage'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { buildSuggestRows, settledRows, type SuggestRow } from '@/lib/suggestPlacement'
import { formatClock, dayOffset } from '@/lib/tripClock'
import { useProposalFamily } from '@/composables/useProposalFamily'
import { buildScenarioAxes } from '@/lib/scenarioAxes'
import { inflateRoute, memberFailure, routeFor } from '@/lib/proposalFamily'
import {
  addonFor,
  addonsForDirection,
  droppedAddons,
  emptyExpert,
  fromRequest,
  fromRouteSegments,
  isEmptyExpert,
  mirrorDirection,
  pruneExpertToStops,
  setAddon,
  swapDirections,
  toRequest as expertToRequest,
  type DepartureOverride,
  type ExpertState,
  type ExpertTimetableRequest,
  type SegmentAddon,
} from '@/lib/expertTimetable'
import { routeFacts } from '@/lib/shareLinks'
import { provideProposalEngagement } from '@/composables/useProposalEngagement'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Skeleton from 'primevue/skeleton'
import AppIcon from '@/components/AppIcon.vue'
import AppSpinner from '@/components/AppSpinner.vue'
import StopSelect from '@/components/StopSelect.vue'
import ProposalResults from '@/components/ProposalResults.vue'
import OwnershipLine from '@/components/OwnershipLine.vue'
import CountryFlags from '@/components/CountryFlags.vue'
import StopTime from '@/components/StopTime.vue'
import ExpertTimetableControls from '@/components/ExpertTimetableControls.vue'
import LoadingFunFact from '@/components/LoadingFunFact.vue'
import MapView from '@/components/MapView.vue'
import MapShareBar from '@/components/MapShareBar.vue'
import CommentSection from '@/components/CommentSection.vue'
import InlineAlert from '@/components/InlineAlert.vue'
import {
  mdiArrowLeft,
  mdiArrowLeftRight,
  mdiCheckCircle,
  mdiMapMarkerMultipleOutline,
  mdiClose,
  mdiPencil,
  mdiPlus,
  mdiSpeedometerMedium,
  mdiSwapVertical,
  mdiTimerCogOutline,
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

const { t } = useI18n()
const { formatInt, countryName } = useLocaleFormat()
const store = useStore()
const toastStore = useToastStore()
const { describe, report } = useApiFailure()

const currentMode = ref<'edit' | 'loading' | 'display' | 'suggest'>(props.mode)
const selectedCompositionId = ref<string | null>(null)

// --- Compute state --------------------------------------------------------
// The family build is the one genuinely long call in the app (routing engine,
// one leg at a time, once per corridor), so it reports progress rather than
// just spinning: 'slow' at 8s, 'verySlow' at 30s, cancellable throughout.
const calcPhase = ref<'idle' | 'working' | 'slow' | 'verySlow'>('idle')
const calcFailure = ref<ApiFailure | null>(null)
const calcFailureMsg = ref<string | null>(null)
const calcSlot = createAbortSlot()
// Arguments of the last calc, so Retry replays it rather than guessing.
const lastCalcArgs = ref<{ stopIds: string[]; autoStopAddition: 'off' | 'suggest' } | null>(null)

// --- Expert timetable state -------------------------------------------------
// Manual overrides on top of the computed timetable: a pinned or shifted first
// departure, and extra minutes on individual legs. The arithmetic (mirroring,
// pruning, request shape) lives in lib/expertTimetable.ts; what stays here is
// the state, the reconciliation after a calc, and the recompute trigger.
//
// Deliberately only reachable once a route exists (display mode): both
// controls are relative to a computed timetable — there is no automatic
// departure to pin, and no leg to pad, before the first evaluation.
const expertMode = ref(false)
const expert = ref<ExpertState>(emptyExpert())
// What the displayed results were computed with — the comparison behind
// paramsStale below, exactly like committedCompId/committedScenarioId.
const committedExpert = ref<ExpertState | null>(null)

// Failure of loading a STORED proposal (/proposal/:id) — kept apart from the
// calc's, because it must not fall through to the builder (see loadStored).
const loadFailure = ref<ApiFailure | null>(null)
const loadFailureMsg = ref<string | null>(null)
const loadSlot = createAbortSlot()

// Raw route in the full shape (a loaded proposal's, or the family's compact
// route inflated by lib/proposalFamily.ts) before adaptRoute() —
// the map segment/highlight logic below reads it directly.
const rawRoute = ref<BackendRoute | null>(null)
// Evaluation bundle rendered by ProposalResults — assembled in applyPlan()
// from the same merged calc response the route came from.
const calcResult = ref<EvaluationResponse | null>(null)
// Gallery KPI summary block of the same calc response — route-level demand /
// modal-shift / emissions figures the results' KPI grid renders alongside the
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
const basePlan = ref<MemberPlan | null>(null)
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
// Whether the proposal on screen is the user's OWN — published from this
// session, or opened from the gallery and authored by them. It is what
// decides whether a recompute saves: the builder saves automatically, and a
// change the user made by hand should not quietly evaporate on the way back
// to the gallery — but recomputing SOMEONE ELSE'S proposal against another
// scenario is a private what-if and must never overwrite their work (the
// backend refuses it anyway, and a 403 is not an answer to a question the
// user did not ask).
//
// THREE states, not a boolean: opening a proposal from the gallery gives us
// its id immediately and its author only once the load returns, so a boolean
// defaulting to false made the header assert "someone else's proposal" for
// the length of every load — a claim we had not checked yet, and the wrong
// one most of the time. 'unknown' is what the header renders nothing for.
const proposalOwnership = ref<'unknown' | 'own' | 'other'>('unknown')
const ownsProposal = computed(() => proposalOwnership.value === 'own')
// Set when a calc finished but the user still has to pick an identity in the
// gate — the authChoice watcher publishes once they do.
const pendingPublish = ref(false)
const saved = ref(false)
const publishError = ref<string | null>(null)
// Publish recomputes server-side, so it is as slow as a calc and escalates the
// same way.
const publishPhase = ref<'idle' | 'working' | 'slow' | 'verySlow'>('idle')

// --- The family (composables/useProposalFamily.ts) --------------------------
// Every evaluation is one POST /api/proposal/family: the stops and HOW fields
// under every offered scenario × every composition, as one document. The
// presented member is what applyPlan() puts on screen; the rest is what
// makes a scenario or composition switch a lookup rather than a request
// (the watchers below), and what feeds the comparison bars, the combination
// grid and the supply table. A member's six evaluation views are not in the
// document — they are fetched for the member on screen (loadViews) and
// cached per family. Reset as soon as the itinerary is edited: its members
// would describe a route that no longer exists.
const family = useProposalFamily()
// The author's display name of a loaded proposal, for the ownership line.
const authorName = ref<string | null>(null)

// The proposal_id a discussion can hang off: the one we opened, or the one the
// first publish adopted. Null in a fresh builder session, which is why neither
// the comment section nor the map's like/share pill can exist there — there is
// nothing to comment on, like, or link to yet.
const storedProposalId = computed(() => props.proposalId ?? publishedProposalId.value)

// Likes + comment thread for that proposal, fetched ONCE here and injected by
// both the map pill and the discussion below (see the composable's header for
// why it isn't a per-component fetch or a global store).
provideProposalEngagement(storedProposalId)

interface StopTimeFmt {
  stop_id: string
  stop_name: string
  country_code: string
  lat: number
  lon: number
  arrival_time_fmt: string | null
  departure_time_fmt: string | null
  // Calendar days after the trip's first departure — drives the "+1" marker, so
  // a 20:00 → 08:00 night train doesn't read as travelling backwards in time.
  arrival_day: number
  departure_day: number
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

// --- The full route shape (route_serialize.route_to_dict(): GET /api/
//     proposal/<id>'s route, and what inflateRoute() rebuilds from the
//     family document), before adapting into the RouteResult/TripResult/
//     StopTimeFmt shape the rest of this component already renders against.
//     Kept minimal — only the fields used below. ---
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
  // Manual expert-mode minutes on this leg (ROUTE_BUILDER 0.9.32) — the
  // authoritative record of which add-ons actually landed. Optional so a
  // proposal stored before 0.9.32 still type-checks.
  addon_time_min?: number
}

// Headline physics figures the backend attaches per trip (route_serialize.py
// _trip_general_parameters) — read at a glance rather than derived from
// segments.
interface BackendGeneralParameters {
  trip_km: number
  route_duration_min: number
  average_speed_kmh: number
  // Track gauge the trip was routed on (ROUTE_BUILDER 0.9.27+) — 1435 for
  // nearly everything; 1520 on the ex-Soviet/Finnish family, 1600 Ireland,
  // 1668 Iberia. Optional so older stored proposals still type-check.
  track_gauge_mm?: number
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
}

// What applyPlan() puts on screen: one member of the family, in the shape
// the rest of this component was built around — a FULL route (the document's
// compact one inflated by lib/proposalFamily.ts), the resolved request with
// this member's composition and scenario filled in, its summary, and its
// views if they are already known (a stored proposal carries them inline; a
// family member's are fetched after — null until then).
interface MemberPlan {
  route_builder_version: string
  calc_version: string
  request: Record<string, unknown>
  suggested_stops?: SuggestedStop[]
  summary: ProposalCalcSummary | undefined
  route: BackendRoute
  views: EvaluationViews | null
}

// Clock formatting and the overnight day offset live in lib/tripClock.ts.

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

// baseMin is the trip's own first departure — the reference the "+1" markers are
// counted from (see lib/tripClock.ts).
function toStopTimeFmt(stop: BackendStop, baseMin: number | null): StopTimeFmt {
  return {
    stop_id: stop.stop_id,
    stop_name: stop.stop_name,
    country_code: stop.country_code,
    lat: stop.lat,
    lon: stop.lon,
    arrival_time_fmt: formatClock(stop.arrival_time_min),
    departure_time_fmt: formatClock(stop.departure_time_min),
    arrival_day: dayOffset(stop.arrival_time_min, baseMin),
    departure_day: dayOffset(stop.departure_time_min, baseMin),
  }
}

// segments[] holds one from_stop/to_stop pair per leg — walk them into the
// flat per-stop list the template expects (first leg's from_stop, then every
// leg's to_stop).
function buildStopTimes(segments: BackendSegment[]): StopTimeFmt[] {
  if (segments.length === 0) return []
  const baseMin = segments[0].from_stop.departure_time_min
  return [
    toStopTimeFmt(segments[0].from_stop, baseMin),
    ...segments.map((seg) => toStopTimeFmt(seg.to_stop, baseMin)),
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
  // The expert overrides are keyed to the posted stop order, which this
  // reversal changes — so the two directions' overrides change places with
  // it (see swapDirections()). Without this every add-on would be measured
  // against the opposite direction's legs and dropped on the next recompute.
  // committedExpert is deliberately NOT swapped: it stays paired with
  // committedItinerary, in the orientation the results were computed in, and
  // expertChanged below compares against either orientation.
  expert.value = swapDirections(expert.value)
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

// --- Expert timetable: request, reconciliation, editing ---------------------

// The expert_timetable block for a calc over `stopIds`, or null when nothing
// is overridden. Pruning here rather than at edit time is what guarantees the
// posted block is always legal for the stops it accompanies: a stop removed
// from the itinerary takes the add-ons on the two legs it joined with it.
function expertRequest(stopIds: string[]): Record<string, unknown> | null {
  if (!expertMode.value || isEmptyExpert(expert.value)) return null
  const pruned = pruneExpertToStops(expert.value, stopIds)
  expert.value = pruned
  return expertToRequest(pruned) as Record<string, unknown> | null
}

// The route's own view of which minutes survived, read off its segments —
// see lib/expertTimetable.ts. The backend drops an add-on whose stop pair
// auto_stop_addition split, so what came back is the truth and local state
// follows it rather than the other way round.
function reconcileExpert(
  route: BackendRoute,
  sentOutbound: SegmentAddon[],
  sentReturn: SegmentAddon[],
): SegmentAddon[] {
  const pair = route.trip_pairs[0]
  if (!pair) return []
  const appliedOutbound = fromRouteSegments(pair.outbound.segments)
  const appliedReturn = fromRouteSegments(pair.return_trip.segments)

  expert.value = {
    outbound: { ...expert.value.outbound, addons: appliedOutbound },
    // The link is kept as the user left it: a mirroring return goes on
    // mirroring (its minutes are outbound's), an unlinked one takes its own
    // applied list.
    returnTrip: expert.value.returnTrip
      ? { ...expert.value.returnTrip, addons: appliedReturn }
      : null,
  }
  return [
    ...droppedAddons(sentOutbound, appliedOutbound),
    ...(expert.value.returnTrip ? droppedAddons(sentReturn, appliedReturn) : []),
  ]
}

// The controls always edit expert.outbound, and expert.outbound always
// describes the direction ON SCREEN. That holds because flipping direction
// reverses the itinerary as well as the shown trip (swapDirection above), so
// the trip being looked at is always the one whose stop order gets posted —
// and swapDirection exchanges the two override slots to keep it that way.
// The alternative (keying the slots to the route's direction ids) silently
// checks each set of add-ons against the other direction's legs after a flip,
// which drops all of them on the next recompute.
const otherDirectionMirrors = computed(() => expert.value.returnTrip === null)

// Stop mirroring: the opposite direction gets its own copy of what is on
// screen, so breaking the link changes no times by itself.
function unlinkReturn() {
  expert.value = { ...expert.value, returnTrip: mirrorDirection(expert.value.outbound) }
}

// Back to mirroring — the opposite direction's own times are discarded, which
// is what "mirror this direction again" means.
function relinkReturn() {
  expert.value = { ...expert.value, returnTrip: null }
}

// The automatic departure per direction — what a shift is measured from, what
// "reset" returns to, and what the hint quotes. The response reports where the
// trip actually departed, so the automatic value is recovered by backing the
// override out of it: none means it IS the automatic value, a shift means
// minus the shift. A PINNED departure hides it (the response only says where
// the user put the train), so the last known value is kept instead — which is
// exactly the case where the automatic value stopped mattering, and the next
// calc without a pin refreshes it.
const lastAutoDeparture = ref<[number, number]>([0, 0])

function rememberAutoDeparture(route: BackendRoute, sent: ExpertState | null) {
  const pair = route.trip_pairs[0]
  if (!pair) return
  const next: [number, number] = [...lastAutoDeparture.value]
  for (const [direction, trip] of [
    [0, pair.outbound],
    [1, pair.return_trip],
  ] as const) {
    const departed = trip.segments[0]?.from_stop.departure_time_min
    if (departed == null) continue
    const applied = sent ? slotFor(sent, direction).departure : null
    if (applied === null) next[direction] = departed
    else if (applied.mode === 'shift') next[direction] = departed - applied.minutes
  }
  lastAutoDeparture.value = next
}

// Indexed by the ROUTE's direction id, not by which slot is on screen: the
// route's directions do not move when the itinerary is flipped, so this
// survives a flip without having to be swapped alongside the overrides.
const autoDepartureMin = computed(
  () => lastAutoDeparture.value[selectedTrip.value?.direction_id === 1 ? 1 : 0],
)

function slotFor(state: ExpertState, direction: 0 | 1) {
  if (direction === 0) return state.outbound
  return state.returnTrip ?? { departure: null, addons: addonsForDirection(state, 1) }
}

const currentDeparture = computed(() => expert.value.outbound.departure)

function setDepartureOverride(value: DepartureOverride | null) {
  expert.value = { ...expert.value, outbound: { ...expert.value.outbound, departure: value } }
}

// Minutes currently on the leg arriving at `stopId` from `fromStopId`, for the
// direction on screen.
function legAddon(fromStopId: string | null, stopId: string): number {
  if (!fromStopId) return 0
  return addonFor(expert.value.outbound.addons, fromStopId, stopId)
}

function setLegAddon(fromStopId: string | null, stopId: string, minutes: number) {
  if (!fromStopId) return
  expert.value = {
    ...expert.value,
    outbound: {
      ...expert.value.outbound,
      addons: setAddon(expert.value.outbound.addons, fromStopId, stopId, minutes),
    },
  }
}

function onLegAddonInput(fromStopId: string | null, stopId: string, event: Event) {
  setLegAddon(fromStopId, stopId, Number((event.target as HTMLInputElement).value))
}

function cloneExpert(state: ExpertState): ExpertState {
  return JSON.parse(JSON.stringify(state)) as ExpertState
}

// Add-ons the backend could not place, named by leg so the message says
// which minutes went and why they could not simply be moved.
function reportDroppedAddons(dropped: SegmentAddon[]) {
  const byId = new Map(store.stops.map((s) => [s.stop_id, s.name]))
  const legs = dropped
    .map((a) => `${byId.get(a.fromStopId) ?? a.fromStopId} → ${byId.get(a.toStopId) ?? a.toStopId}`)
    .join(', ')
  toastStore.addToast('warn', t('proposal.expert.droppedAddons', { legs }))
}

// Turning expert mode off drops the overrides rather than hiding them: a
// hidden override that still reaches the next calc is the worst of both.
function toggleExpertMode() {
  expertMode.value = !expertMode.value
  if (!expertMode.value) expert.value = emptyExpert()
}

// The offered scenarios' variants, in the picker's order — the family's
// scenario axis. A network still held back as "coming soon"
// (lib/scenarioAxes.ts) costs neither a switch the user cannot flip nor a
// member nobody can see. Empty (scenarios not loaded yet) means "omit the
// axis" and let the backend use its default.
const familyVariantIds = computed(() =>
  buildScenarioAxes(store.scenarios)
    .ordered.map((sc) => store.variantFor(sc.scenario_id)?.scenario_variant_id)
    .filter((id): id is number => id !== undefined),
)

// The family request for the given stop ids: the HOW fields as the builder
// has them, the offered scenarios, every composition, and the member the
// user is looking at as `presented` — the only member whose "suggest"
// search runs. composition_id is omitted until the user picks one, so the
// first evaluation presents the backend's standard composition
// (DEFAULT_COMPOSITION_ID) and applyPlan() adopts whichever it reports back.
function familyRequest(
  stopIds: string[],
  autoStopAddition: 'off' | 'suggest',
  expertBlock: ExpertTimetableRequest | null,
): FamilyRequest {
  const variantIds = familyVariantIds.value
  const selectedVariant = store.variantFor(store.selectedScenarioId)?.scenario_variant_id
  // A presented member has to be on the axes, or the backend answers 400:
  // a scenario the picker offers but the family does not cover (a preview
  // network) falls back to the backend's default, the base scenario.
  const presentedVariant =
    selectedVariant !== undefined &&
    (variantIds.length === 0 || variantIds.includes(selectedVariant))
      ? selectedVariant
      : undefined
  return {
    stops: stopIds,
    // Omitted entirely while nothing is overridden: an absent block and an
    // empty one are the same request server-side. Pruned first — the
    // backend rejects an add-on whose stop pair is not a leg of the stops
    // being posted.
    ...(expertBlock ? { expert_timetable: expertBlock } : {}),
    auto_stop_addition: autoStopAddition,
    ...(variantIds.length > 0 ? { scenario_variant_ids: variantIds } : {}),
    presented: {
      ...(presentedVariant !== undefined ? { scenario_variant_id: presentedVariant } : {}),
      ...(selectedCompositionId.value ? { composition_id: selectedCompositionId.value } : {}),
    },
  }
}

// Stops + HOW + axes — what identifies a family. `presented` is deliberately
// not in it: choosing another member never rebuilds.
function familyKey(body: FamilyRequest): string {
  const { presented: _presented, ...identity } = body
  void _presented
  return JSON.stringify(identity)
}

// POST /api/proposal/family for the given stop ids and auto_stop_addition
// mode. Returns the document, or null on error (having set calcFailure and
// dropped back to edit mode). proposal_id/proposal_version don't exist on
// this request — persistence is publish's concern, not compute's.
async function requestFamily(
  stopIds: string[],
  autoStopAddition: 'off' | 'suggest',
): Promise<FamilyDocument | null> {
  // Remember the arguments so Retry can replay exactly this call.
  lastCalcArgs.value = { stopIds, autoStopAddition }
  const expertBlock = expertRequest(stopIds)
  const body = familyRequest(stopIds, autoStopAddition, expertBlock)
  calcPhase.value = 'working'
  calcSlot.begin()
  // No deadline: the routing engine's own timeout is per leg and gunicorn
  // allows 120s, so any client deadline we picked would sometimes kill a
  // request that was about to succeed — and aborting wouldn't free the
  // worker anyway. The user gets escalating copy and a Cancel button.
  const document = await family.start(familyKey(body), body, store.authHeaders(), (phase) => {
    calcPhase.value = phase
  })
  calcPhase.value = 'idle'
  if (document) return document
  const failure = family.failure.value
  // The user cancelled, or a newer build superseded this one: no error, and
  // the caller of cancelCalc() owns the mode.
  if (!failure || failure.kind === 'canceled') return null
  calcFailure.value = failure
  // Two surfaces, never the same sentence twice. Actionable detail (the
  // backend's own validation text) belongs inline, next to the control. A
  // systemic failure gets a SHORT inline note plus the full explanation in a
  // sticky toast — printing the long "something went wrong on our side…"
  // copy inline as well is what put it on screen twice.
  const verbatim = new ApiError(failure).verbatim
  calcFailureMsg.value = verbatim ?? t('errors.calcFailed')
  if (!verbatim) report(new ApiError(failure))
  currentMode.value = 'edit'
  return null
}

// The member of `document` for a scenario and composition, as the plan
// applyPlan() consumes — or null, with calcFailure set, when that member is
// an error member (a gauge clash, an unroutable pair, a graph this
// deployment does not run). A failed member is a 200 on the wire; this is
// where it becomes the failure the builder's copy paths already know.
// null/undefined selections fall back to the document's own presented
// member, which is what the backend resolved the defaults to.
function memberPlanFor(
  document: FamilyDocument,
  scenarioId: number | null,
  compositionId: string | null,
): MemberPlan | null {
  const variant =
    (scenarioId !== null ? family.variantOf.value.get(scenarioId) : undefined) ??
    document.axes.scenario_variants.find(
      (v) => v.scenario_variant_id === document.presented.scenario_variant_id,
    )
  if (!variant) return null
  const comp = compositionId ?? document.presented.composition_id
  const member = family.member(variant.scenario_id, comp)
  if (!member) return null
  if (member.status === 'error') {
    calcFailure.value = memberFailure(member)
    calcFailureMsg.value = member.message
    currentMode.value = 'edit'
    return null
  }
  const isPresented =
    variant.scenario_variant_id === document.presented.scenario_variant_id &&
    comp === document.presented.composition_id
  return {
    route_builder_version: document.route_builder_version,
    calc_version: document.calc_version,
    request: { ...document.request, composition_id: comp, scenario_id: variant.scenario_id },
    // Suggestions were searched for the presented member only.
    ...(isPresented && document.suggested_stops
      ? { suggested_stops: document.suggested_stops }
      : {}),
    summary: member.summary,
    route: inflateRoute(document, routeFor(document, member)) as unknown as BackendRoute,
    views: null,
  }
}

// One evaluation, start to plan: the family, then the presented member of
// it. What evaluate(), the suggest flow and Recalculate all call.
async function requestPlan(
  stopIds: string[],
  autoStopAddition: 'off' | 'suggest',
): Promise<MemberPlan | null> {
  const document = await requestFamily(stopIds, autoStopAddition)
  if (!document) return null
  return memberPlanFor(document, store.selectedScenarioId, selectedCompositionId.value)
}

// What the map overlay says while we wait. Both the calc and publish escalate
// through the same phases; whichever is running drives the copy.
const progressCaption = computed(() => {
  const phase = calcPhase.value !== 'idle' ? calcPhase.value : publishPhase.value
  if (phase === 'verySlow') return t('errors.highDemand')
  if (phase === 'slow') return t('errors.stillWorking')
  return t('proposal.evaluating')
})

/** Stop waiting. Honest about what it does: the server keeps working. */
function cancelCalc(): void {
  calcSlot.cancel()
  family.abort()
  calcPhase.value = 'idle'
  currentMode.value = 'edit'
}

/** Replay the last calc. Manual only — an automatic retry would re-queue work
 *  on an already-saturated worker pool, which is what made the overload worse. */
function retryCalc(): void {
  const args = lastCalcArgs.value
  if (!args) return
  calcFailure.value = null
  calcFailureMsg.value = null
  currentMode.value = 'loading'
  requestPlan(args.stopIds, args.autoStopAddition).then((plan) => {
    if (plan) applyPlan(plan, true)
  })
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
  const countries = [
    ...new Set(trip.segments.flatMap((seg) => Object.keys(seg.country_distance_shares))),
  ]
  return {
    distanceKm: gp.trip_km,
    avgSpeedKmh: gp.average_speed_kmh,
    nStops: trip.segments.length + 1,
    countries,
  }
})

// Headline route figures shown under the itinerary once a route exists:
// distance, speed, stops. The countries sit next to them as flags
// (CountryFlags.vue, the same discs the gallery cards use) rather than as
// another icon-and-text row — codes read as an abbreviation, flags as a
// route. Frequency moved to the results' "evaluated with" line: it is an
// evaluation input, not a route fact.
const routeStatRows = computed(() => {
  const stats = routeStats.value
  if (!stats) return []
  return [
    { icon: mdiArrowLeftRight, value: `${formatInt(stats.distanceKm)} km`, title: undefined },
    { icon: mdiSpeedometerMedium, value: `${formatInt(stats.avgSpeedKmh)} km/h`, title: undefined },
    { icon: mdiMapMarkerMultipleOutline, value: `${stats.nStops}`, title: t('proposal.stops') },
  ]
})

// Retry after a family-level failure (network, 503): re-runs the last
// request — the route on screen — from the start.
function retryFamily() {
  family.retry()
}

// The views of the member on screen, fetched after the document (they are
// not in it) and cached per family. Guarded by a token: a switch that
// arrives while a fetch is out must not have the older member's figures
// land on top of it.
let viewsToken = 0
async function loadViews(scenarioId: number | null, compositionId: string | null) {
  const token = ++viewsToken
  if (scenarioId === null || compositionId === null) return
  try {
    const views = await family.views(scenarioId, compositionId)
    if (token !== viewsToken || !views || !calcResult.value) return
    calcResult.value = { ...calcResult.value, views }
  } catch (err) {
    if (token !== viewsToken) return
    // Zone E stays on its skeleton; the rest of the page — route, KPIs,
    // comparisons — is unaffected, so this is a toast, not a mode change.
    report(err, { fallbackKey: 'errors.viewsFailed' })
  }
}

// Wire a member onto the display: adapt the route, publish the evaluation
// bundle, select the outbound trip, rebuild the itinerary from
// the planned route (so the builder reflects what's actually on the map —
// including any stops the user chose to add) and commit it as the clean state
// so the builder isn't "dirty" and Cancel Edit can restore exactly this.
// `publish` is true only for user-initiated evaluations (Evaluate button, stop
// selection) — a passive scenario-switch recompute passes false so it never
// creates or overwrites a proposal.
function applyPlan(json: MemberPlan, publish = false) {
  rawRoute.value = json.route
  // Expert overrides. Three steps, each answering a different question:
  //   1. what did we ASK for — the state as it stands, kept for the dropped
  //      check below;
  //   2. what was it computed WITH — the resolved echo, which is also how a
  //      stored proposal's own expert timetable arrives (it lives in the
  //      compute request the proposal replays, so hydrating from it is what
  //      stops opening one and recomputing it from silently reverting it to
  //      the automatic timetable);
  //   3. what actually LANDED — the route's own segments, authoritative for
  //      add-ons, since the backend drops any whose stop pair no longer
  //      exists once auto_stop_addition has had its say.
  // Reconciling before the committed snapshot matters: a dropped add-on left
  // in the state would make the results read as permanently stale.
  const sentOutbound = expertMode.value ? expert.value.outbound.addons : []
  const sentReturn = expertMode.value ? addonsForDirection(expert.value, 1) : []
  const echoed = json.request?.expert_timetable as ExpertTimetableRequest | null | undefined
  if (echoed) {
    expertMode.value = true
    expert.value = fromRequest(echoed)
  }
  rememberAutoDeparture(json.route, echoed ? expert.value : null)
  if (expertMode.value) {
    const dropped = reconcileExpert(json.route, sentOutbound, sentReturn)
    if (dropped.length > 0) reportDroppedAddons(dropped)
  }
  committedExpert.value = cloneExpert(expert.value)
  // The panel-facing EvaluationResponse: views are inline for a loaded
  // proposal and fetched below for a family member (null meanwhile — the
  // cost/revenue zone shows its skeleton, everything else is already here).
  calcResult.value = {
    calc_version: json.calc_version,
    route_id: json.route.route_id,
    views: json.views,
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
  if (json.views === null) loadViews(committedScenarioId.value, committedCompId.value)
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
  // Someone else's proposal, evaluated by this user: a COPY into their own
  // proposals, with the provenance recorded — never an overwrite of the
  // original, which ownsProposal already guarantees. Their own work, and
  // anything already published from this session, overwrites.
  const copying = proposalOwnership.value === 'other' && props.proposalId != null
  const body: PublishRequest = {
    mode: publishedProposalId.value && !copying ? 'overwrite' : copying ? 'copy' : 'new',
    name: derivedName(),
    compute_request: { ...req, scenario_id: null },
  }
  const isFirstPublish = publishedProposalId.value === null || copying
  if (copying) body.based_on_proposal_id = props.proposalId!
  else if (publishedProposalId.value) body.proposal_id = publishedProposalId.value
  publishPhase.value = 'working'
  try {
    const resp = await publishProposal(body, store.authHeaders(), {
      onSlow: (phase) => {
        publishPhase.value = phase
      },
    })
    publishedProposalId.value = resp.proposal_id
    proposalOwnership.value = 'own'
    saved.value = true
    // The gallery is kept alive, so its cached list would otherwise not contain
    // the proposal the user just published. Flag it to refetch once on return.
    store.galleryStale = true
    clearDraft()
    toastStore.addToast('success', t('proposal.saved'))
    if (isFirstPublish) emit('published', resp.proposal_id)
  } catch (err) {
    if (asApiFailure(err)?.kind === 'canceled') return
    publishError.value = describe(err, 'errors.publishFailed')
    report(err, { fallbackKey: 'errors.publishFailed' })
  } finally {
    publishPhase.value = 'idle'
  }
}

async function evaluate() {
  const validStops = itinerary.value.filter((s) => s.selectedStop !== null)
  if (validStops.length < 2) return
  currentMode.value = 'loading'
  calcFailure.value = null
  calcFailureMsg.value = null
  saved.value = false
  publishError.value = null
  // First pass: "suggest" routes exactly the caller's stops and reports the
  // candidate stops along the way, without adding any automatically. The calc
  // itself runs tokenless (compute-only); the register/guest prompt only
  // appears once a result is ready, in applyPlan().
  const json = await requestPlan(
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
  calcFailure.value = null
  calcFailureMsg.value = null
  const json = await requestPlan(stopIds, 'suggest')
  if (!json) return // requestPlan already reset currentMode to 'edit' and set calcFailure
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

// Close the register/guest gate THIS component opened — and only that. These
// paths used to call closeAuthModal() unconditionally, which also slammed shut a
// "Log in / Register" the user had opened themselves from the header: they
// opened it while a proposal was still computing, the compute settled, and their
// modal vanished under them. A standalone login is the user's, not ours.
function dismissEvaluationGate(): void {
  if (store.authModal.context === 'evaluation') store.closeAuthModal()
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
// it directly. Otherwise the itinerary becomes exactly what the timeline showed
// — the caller's stops with the opted-in candidates on the leg they were listed
// on — and we recompute with auto_stop_addition="off": the caller has made the
// selection, so no further suggestions are wanted.
async function confirmStopSelection(selectedIds: string[]) {
  const base = basePlan.value
  const suggestions = suggestedStops.value
  const chosen = suggestions.filter((s) => selectedIds.includes(s.stop_id))
  // Read the placement off the same rows the timeline rendered, before the
  // suggest state (which baseOutbound derives from) is torn down below. Not
  // suggestRows: that one is reversed when the user flipped the view, and the
  // flip is a pure view change that leaves the itinerary's direction alone.
  const confirmedStops = baseOutbound.value?.stop_times ?? []
  const settled = settledRows(confirmedStops, suggestions, new Set(selectedIds))
  suggestedStops.value = []
  basePlan.value = null
  suggestSelected.value = new Set()
  suggestReversed.value = false
  if (!base) {
    currentMode.value = 'edit'
    dismissEvaluationGate()
    return
  }
  if (chosen.length === 0) {
    applyPlan(base, true) // opens the choose-phase gate for a no-choice visitor
    return
  }
  itinerary.value = itineraryFromSettledRows(settled, confirmedStops, chosen)
  currentMode.value = 'loading'
  const stopIds = itinerary.value.filter((s) => s.selectedStop).map((s) => s.selectedStop!.stop_id)
  const json = await requestPlan(stopIds, 'off')
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
  dismissEvaluationGate()
}

// Rebuild the itinerary from the settled suggest rows, keeping their order.
// That order is the backend's own along-route order (see lib/suggestPlacement.ts)
// and is authoritative here: re-deriving each stop's position from lat/lon —
// which is what addStop() does for a manual pick — reorders whole clusters once
// several stops arrive at once.
//
// Rows the caller already had keep their existing itinerary row, so the full
// Stop record survives; the rest resolve against the loaded stop list, falling
// back to the fields the response itself carries.
function itineraryFromSettledRows(
  rows: SuggestRow[],
  confirmed: StopTimeFmt[],
  chosen: SuggestedStop[],
): ItineraryStop[] {
  const existing = new Map(
    itinerary.value.filter((s) => s.selectedStop).map((s) => [s.selectedStop!.stop_id, s]),
  )
  const byId = new Map(store.stops.map((s) => [s.stop_id, s]))
  const fromCalc = new Map([...confirmed, ...chosen].map((s) => [s.stop_id, s]))
  const out: ItineraryStop[] = []
  const seen = new Set<string>()
  for (const row of rows) {
    if (seen.has(row.stopId)) continue
    seen.add(row.stopId)
    const kept = existing.get(row.stopId)
    if (kept) {
      out.push(kept)
      continue
    }
    const known = byId.get(row.stopId)
    const src = fromCalc.get(row.stopId)
    if (!known && !src) continue
    const stop: Stop = known ?? {
      stop_id: src!.stop_id,
      name: src!.stop_name,
      country_code: src!.country_code,
      lat: src!.lat,
      lon: src!.lon,
      stop_charge_eur: { value: 0, is_default: true },
    }
    out.push({ id: _nextId++, name: stop.name, selectedStop: stop })
  }
  return out
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
      store.selectedScenarioId !== committedScenarioId.value ||
      expertChanged.value),
)

// An expert edit is not "dirty" — the stops are untouched — it is stale
// results, the same state a composition switch produces, and it takes the
// same Recalculate control. Compared structurally: the state is small, and
// two states that differ only in add-on order mean the same timetable, which
// toRequest() already canonicalises.
const expertChanged = computed(() => {
  const committed = committedExpert.value
  if (committed === null) return false
  const current = JSON.stringify(expertToRequest(expert.value))
  // Either orientation counts as unchanged, for the same reason isDirty
  // accepts a reversed stop list: flipping direction re-keys the overrides
  // (swapDirection above) without moving a single minute of the timetable,
  // and must not put the results behind a Recalculate button.
  return (
    current !== JSON.stringify(expertToRequest(committed)) &&
    current !== JSON.stringify(expertToRequest(swapDirections(committed)))
  )
})

// The stale results' recompute: same "stops are settled" call the scenario
// switch used to make on its own, now behind the user's click.
async function recomputeWithSelection() {
  const stopIds = currentStopIds.value
  if (stopIds.length < 2 || currentMode.value === 'loading') return
  currentMode.value = 'loading'
  calcFailure.value = null
  calcFailureMsg.value = null
  const json = await requestPlan(stopIds, 'off')
  // Persist when the proposal is the user's own (see ownsProposal): this
  // recompute is the only way an expert timetable — or a composition or
  // scenario switch — reaches a stored proposal, and a change the user made
  // by hand that survives only until they navigate away is worse than no
  // change at all. Someone else's proposal is still never overwritten:
  // recomputing it to look at another scenario stays a private what-if.
  if (json) applyPlan(json, ownsProposal.value)
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

// Gate for the discussion. Keyed on routeResult ALONE, deliberately not on
// currentMode like the evaluation section above: opening a stored proposal runs
// 'display' -> 'loading' -> 'display' (loadStoredProposal, then applyPlan), so
// a mode-based condition unmounts and remounts the section mid-load and it
// fetches the thread twice, aborting the first request. routeResult is only
// ever assigned, never cleared, so this flips false->true exactly once per
// proposal and survives a re-evaluate. The storedProposalId !== null half of
// the condition stays in the template, where it also narrows the prop.
const showCommentSection = computed(() => routeResult.value !== null)

// Share-message inputs. The figures are the real computed ones — never the
// summary block's co2/demand fields, which are placeholders (see routeFacts()).
// The names mirror derivedName(), which is what the proposal was published as,
// so the message and the preview card's title agree.
const shareFacts = computed(() => routeFacts(rawRoute.value))
const shareOrigin = computed(() => sectionStops.value[0]?.name ?? '')
const shareDestination = computed(
  () => sectionStops.value[sectionStops.value.length - 1]?.name ?? '',
)

// Quiet pill — used by the "Gallery" back link above the workspace.
const pillClass =
  'flex cursor-pointer items-center gap-1.5 rounded-full border border-primary-50/20 px-3 py-1.5 text-sm leading-none text-primary-50 transition hover:bg-primary-50/10'

// The itinerary's own tools (Edit / Add Stop / Swap / Cancel Edit). Same shape
// as pillClass but filled and semibold: as bare outlines tucked under the table
// they read as decoration and were being missed. Deliberately a SEPARATE
// constant — pillClass is shared with the back link, which should stay quiet.
// Still not solid CTAs: four secondary tools must not compete with Evaluate.
const toolPillClass =
  'flex cursor-pointer items-center gap-1.5 rounded-full border border-primary-50/30 bg-primary-50/10 px-3.5 py-2 text-sm font-semibold leading-none text-primary-50 transition hover:bg-primary-50/20'

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
// proposalDraftStorage.ts). Unlike itineraryFromRoute()/itineraryFromSettledRows(),
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
function rowTimes(stop: ItineraryStop): {
  arrival: string | null
  departure: string | null
  arrivalDay: number
  departureDay: number
} | null {
  const id = stop.selectedStop?.stop_id
  if (!id || !selectedTrip.value) return null
  const st = selectedTrip.value.stop_times.find((s) => s.stop_id === id)
  return st
    ? {
        arrival: st.arrival_time_fmt,
        departure: st.departure_time_fmt,
        arrivalDay: st.arrival_day,
        departureDay: st.departure_day,
      }
    : null
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
    // Restored together, and they have to be: committedExpert is keyed to
    // committedItinerary's stop order, so putting one back without the other
    // leaves the overrides describing the opposite direction.
    if (committedExpert.value) expert.value = cloneExpert(committedExpert.value)
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
  arrivalDay: number
  departureDay: number
  // Identity of the row's stop and of the stop before it — the ordered pair
  // an expert add-on is keyed by. null on the first row, which no leg
  // arrives at.
  stopId: string
  prevStopId: string | null
}

const viewRows = computed((): ViewRow[] => {
  if (showComputedView.value && selectedTrip.value) {
    const stops = selectedTrip.value.stop_times
    return stops.map((st, i) => ({
      id: i,
      name: st.stop_name,
      arrival: st.arrival_time_fmt,
      departure: st.departure_time_fmt,
      arrivalDay: st.arrival_day,
      departureDay: st.departure_day,
      stopId: st.stop_id,
      prevStopId: i === 0 ? null : stops[i - 1].stop_id,
    }))
  }
  return itinerary.value.map((s) => ({
    id: s.id,
    name: s.name,
    arrival: null,
    departure: null,
    arrivalDay: 0,
    departureDay: 0,
    stopId: s.selectedStop?.stop_id ?? '',
    prevStopId: null,
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

// Confirmed stops interleaved with the proposed stops along the way — see
// lib/suggestPlacement.ts for the ordering rule. Reversed for display when the
// user flips direction, after placement, so the flip stays a pure view change.
const suggestRows = computed<SuggestRow[]>(() => {
  const rows = buildSuggestRows(
    baseOutbound.value?.stop_times ?? [],
    suggestedStops.value,
    suggestSelected.value,
  )
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

// Every catalogue stop the user could still add, shown as dots on the map while
// editing. Motivation from the field: a traveller does not know which stations
// are even available, so the Add Stop dropdown is a search you can only use if
// you already know the answer. Stops already on the itinerary are excluded —
// they are drawn as route markers, and re-adding one is a no-op anyway.
const mapAvailable = computed(() => {
  if (currentMode.value !== 'edit') return null
  const used = usedStopIds.value
  return store.stops
    .filter((s) => !used.has(s.stop_id))
    .map((s) => ({ stopId: s.stop_id, lat: s.lat, lon: s.lon, name: s.name }))
})

// Adding from the map reuses addStop(), so a map pick lands at the same
// geographically sensible position as one made through the dropdown.
function onMapAddStop(stopId: string): void {
  const stop = store.stops.find((s) => s.stop_id === stopId)
  if (stop) addStop(stop)
}

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

// Load a stored proposal by id and populate display mode. GET /api/proposal/
// <id> carries the FULL route and the views inline (types/api.ts's
// ProposalDetailResponse), so applyPlan() hydrates rawRoute/calcResult/
// itinerary from it directly — no inflation, no views fetch. The family for
// its request is then built in the background, so that switching scenario
// or composition on a loaded proposal is the same lookup it is on a fresh
// one. selectedCompositionId is set first so the supply table locks onto
// the composition the stored route actually used.
async function loadStoredProposal(proposalId: number) {
  currentMode.value = 'loading'
  loadFailure.value = null
  loadFailureMsg.value = null
  // Whose it is is a property of the proposal being loaded, so a retry — or
  // opening a different one without leaving the workspace — starts from
  // "not known yet" rather than keeping the previous answer on screen.
  proposalOwnership.value = 'unknown'
  authorName.value = null
  try {
    const detail = await fetchProposalRoute<BackendRoute>(proposalId, loadSlot.begin())
    publishedProposalId.value = detail.proposal_id
    // Own work is saved on every recompute; a stranger's is never touched.
    // user_id is null on a proposal whose author deleted their account —
    // nobody owns it then, and null === null must not read as "mine".
    proposalOwnership.value =
      detail.user_id !== null && detail.user_id === store.userId ? 'own' : 'other'
    authorName.value = detail.user_name
    selectedCompositionId.value = detail.route.trip_pairs[0]?.composition_id ?? null
    applyPlan(
      {
        route_builder_version: detail.route_builder_version,
        calc_version: detail.calc_version,
        request: detail.request,
        summary: detail.summary,
        route: detail.route,
        views: detail.evaluation.views,
      },
      false,
    )
    startFamilyInBackground(detail.request)
  } catch (err) {
    if (asApiFailure(err)?.kind === 'canceled') return
    // Deliberately NOT falling through to 'edit'. That is what the old code did,
    // and it silently turned "we couldn't load proposal 42" into a route BUILDER
    // seeded with two arbitrary prefill stops, under a message about saving —
    // so a shared link opened during a blip looked like a working (wrong) app.
    loadFailure.value = asApiFailure(err)
    loadFailureMsg.value = describe(err, 'errors.proposalLoadFailed')
  }
}

// The family for a loaded proposal's request — its stops and HOW fields, the
// same axes a fresh evaluation posts — without touching the mode or the
// progress overlay: the proposal is already on screen, this only makes the
// switches instant. Failures are the family's own (the compare zone shows
// them); the proposal stays loaded.
function startFamilyInBackground(request: Record<string, unknown>) {
  const stops = request.stops as string[] | undefined
  if (!stops || stops.length < 2) return
  const expertBlock =
    (request.expert_timetable as ExpertTimetableRequest | null | undefined) ?? null
  const body: FamilyRequest = {
    ...familyRequest(stops, 'off', expertBlock),
    timetable_mode: request.timetable_mode as string | undefined,
    fixed_night_interval: (request.fixed_night_interval as string[] | null | undefined) ?? null,
    schedule_mode: request.schedule_mode as string | undefined,
    routing_mode: request.routing_mode as string | undefined,
  }
  family.start(familyKey(body), body, store.authHeaders())
}

function retryLoadStored(): void {
  if (props.proposalId != null) loadStoredProposal(props.proposalId)
}

// Leaving mid-request: both rejections classify as 'canceled', so nothing is
// reported and neither counts against backend health.
onBeforeUnmount(() => {
  calcSlot.cancel()
  loadSlot.cancel()
  family.reset()
})

// An edited itinerary invalidates every member (they describe the previous
// route); the next evaluation builds a fresh family.
watch(isDirty, (dirty) => {
  if (dirty) family.reset()
})

// A scenario or composition switch is served from the family when that
// member is there: applyPlan() with the member, which commits the new
// selection and therefore never raises the stale flag. Without a member —
// family still loading, that member errored, the switch happened before the
// document returned — nothing happens here and the ordinary Recalculate path
// takes over (recomputeWithSelection presents the new selection).
function applyMemberFromFamily(scenarioId: number | null, compositionId: string | null) {
  if (scenarioId === null || compositionId === null) return
  if (isDirty.value || currentMode.value === 'loading') return
  const document = family.document.value
  if (!document) return
  const member = family.okMember(scenarioId, compositionId)
  if (!member) return
  const plan = memberPlanFor(document, scenarioId, compositionId)
  // Not persisted: switching is a look, not an edit. The user's own
  // proposal is saved by the paths that do change it.
  if (plan) applyPlan(plan)
}

watch(
  () => store.selectedScenarioId,
  (scenarioId) => {
    if (scenarioId === committedScenarioId.value) return
    applyMemberFromFamily(scenarioId, selectedCompositionId.value)
  },
)

watch(selectedCompositionId, (compositionId) => {
  if (compositionId === committedCompId.value) return
  applyMemberFromFamily(store.selectedScenarioId, compositionId)
})

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
    <div class="flex flex-wrap items-center justify-between gap-3">
      <button type="button" :class="pillClass" @click="emit('back')">
        <AppIcon :path="mdiArrowLeft" :size="16" />
        {{ t('gallery.back') }}
      </button>
      <!-- Whose proposal this is, and what a change does to it (copy-on-edit
           in words). Only once there IS a stored proposal and we know whose it
           is — saying nothing during the load beats saying the wrong thing. -->
      <OwnershipLine
        v-if="storedProposalId !== null && proposalOwnership !== 'unknown'"
        :owned="ownsProposal"
        :author-name="authorName"
      />
    </div>

    <!-- A stored proposal that wouldn't load. This REPLACES the workspace
         rather than letting it fall through to edit mode: the old behaviour
         quietly handed the user a route builder seeded with arbitrary stops,
         which looks like a working app showing the wrong thing. -->
    <div
      v-if="loadFailureMsg"
      class="flex flex-col items-center gap-4 rounded-xl border border-red-400/30 bg-red-950/20 px-8 py-16 text-center"
      role="alert"
    >
      <p class="max-w-md text-primary-50">{{ loadFailureMsg }}</p>
      <div class="flex items-center gap-3">
        <button
          v-if="!loadFailure || isRetryable(loadFailure)"
          type="button"
          class="cursor-pointer rounded-full bg-primary-50/10 px-6 py-2 text-sm text-primary-50 transition hover:bg-primary-50/20"
          @click="retryLoadStored"
        >
          {{ t('errors.retry') }}
        </button>
        <button
          type="button"
          class="cursor-pointer text-sm text-primary-50/60 underline underline-offset-2 transition hover:text-primary-50"
          @click="emit('back')"
        >
          {{ t('gallery.back') }}
        </button>
      </div>
    </div>

    <div
      v-else
      class="flex gap-6 transition-opacity duration-200"
      :class="paramsStale ? 'opacity-40' : ''"
    >
      <!-- Left panel: shrink-wrapped to its content's natural width (the
           itinerary text) rather than a fixed share of the row, so MapView
           gets whatever width is left over. -->
      <div class="flex w-fit shrink-0 flex-col justify-center gap-12">
        <!-- The itinerary column is capped so it stays a column beside the
             map. Expert mode adds a stepper per leg, which does not fit that
             cap: rather than letting the table scroll sideways (a scrollbar
             under a timetable reads as broken, and the control it hides is
             the one being used), the cap is raised while the steppers are
             shown. The map is flex-1 and simply gets the remaining width. -->
        <div
          class="itinerary-table"
          :class="expertMode && currentMode === 'display' ? 'max-w-lg' : 'max-w-sm'"
        >
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
              style="width: 6rem"
              :pt="{ bodyCell: { class: '!p-0' } }"
            >
              <template #body="{ data: stop }">
                <div class="flex flex-col items-end gap-1 py-2 pr-3">
                  <StopTime
                    :time="rowTimes(stop)?.arrival ?? null"
                    :day="rowTimes(stop)?.arrivalDay"
                  />
                  <StopTime
                    :time="rowTimes(stop)?.departure ?? null"
                    :day="rowTimes(stop)?.departureDay"
                  />
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
                      :status="store.stopsStatus"
                      :disabled-ids="usedStopIdsExcluding(stop)"
                      @select="(s) => onStopSelect(stop, s)"
                      @retry="store.fetchStops()"
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

          <!-- Expert timetable: the departure control, plus the mirror notice
               when the return is still following outbound. The per-leg
               minutes live in the table below, on the row the leg arrives
               at — a leg strip cannot be lifted out of the rows it sits
               between without duplicating the whole table. -->
          <div v-if="expertMode && currentMode === 'display'" class="mb-4 flex flex-col gap-2">
            <ExpertTimetableControls
              :departure="currentDeparture"
              :auto-min="autoDepartureMin"
              @update="setDepartureOverride"
            />
            <!-- You always edit the direction on screen; this says what that
                 does to the other one, and offers the way out of it. Use the
                 swap button to look at the other direction — the overrides
                 follow it. -->
            <p class="flex flex-wrap items-center gap-2 px-1 text-xs text-primary-50/50">
              <template v-if="otherDirectionMirrors">
                {{ t('proposal.expert.mirrored') }}
                <button
                  type="button"
                  class="cursor-pointer font-semibold text-primary-50/80 underline underline-offset-2 transition hover:text-primary-50"
                  @click="unlinkReturn"
                >
                  {{ t('proposal.expert.editSeparately') }}
                </button>
              </template>
              <template v-else>
                {{ t('proposal.expert.ownTimes') }}
                <button
                  type="button"
                  class="cursor-pointer font-semibold text-primary-50/80 underline underline-offset-2 transition hover:text-primary-50"
                  @click="relinkReturn"
                >
                  {{ t('proposal.expert.relink') }}
                </button>
              </template>
            </p>
          </div>

          <!-- Display / Loading mode table. A standalone v-if, not the tail
               of the suggest block's chain: the expert controls above sit
               between the two, and a v-else-if would silently bind to them
               instead. Same condition either way — suggest mode renders the
               table above, edit mode the one at the top. -->
          <DataTable
            v-if="currentMode !== 'edit' && currentMode !== 'suggest'"
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
            <Column style="width: 6rem" :pt="{ bodyCell: { class: '!p-0' } }">
              <template #body="{ data: row, index }">
                <div class="flex flex-col items-end gap-1 py-2 pr-3">
                  <template v-if="currentMode === 'loading'">
                    <Skeleton v-if="index > 0" width="3.5rem" height="10px" />
                    <Skeleton v-if="index < viewRows.length - 1" width="3.5rem" height="10px" />
                  </template>
                  <template v-else>
                    <StopTime :time="row.arrival" :day="row.arrivalDay" />
                    <StopTime :time="row.departure" :day="row.departureDay" />
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

            <!-- Stop name. min-w-0 + break-words so a long single word
                 ("Hauptbahnhof") wraps inside the column instead of forcing
                 the table wider than its container. -->
            <Column>
              <template #body="{ data: row, index }">
                <div class="flex min-w-0 items-center px-3 py-2">
                  <span
                    :class="[
                      'text-primary-50 leading-tight break-words',
                      index === 0 || index === viewRows.length - 1
                        ? 'text-2xl font-bold'
                        : 'text-lg font-semibold',
                    ]"
                    >{{ row.name }}</span
                  >
                </div>
              </template>
            </Column>

            <!-- Expert: minutes added to the leg ARRIVING at this stop. The
                 control is a number input with min="0" plus ±1 buttons, so
                 "never shorter than the physics" is visible in the control
                 rather than only enforced on submit.
                 It belongs to the leg BETWEEN two stops, not to either of
                 them, so it is lifted half a row up onto the boundary — level
                 with the timeline between the two names it spans. -->
            <Column
              v-if="expertMode && currentMode === 'display'"
              style="width: 6.25rem"
              :pt="{ bodyCell: { class: '!p-0 align-top' } }"
            >
              <template #body="{ data: row }">
                <div
                  v-if="row.prevStopId"
                  class="flex -translate-y-1/2 items-center justify-end gap-1 py-2"
                >
                  <button
                    type="button"
                    class="h-5 w-5 shrink-0 cursor-pointer rounded border border-primary-50/20 text-xs leading-none text-primary-50 transition hover:bg-primary-50/15 disabled:cursor-not-allowed disabled:opacity-40"
                    :aria-label="t('proposal.expert.lessAria', { stop: row.name })"
                    @click="
                      setLegAddon(
                        row.prevStopId,
                        row.stopId,
                        legAddon(row.prevStopId, row.stopId) - 1,
                      )
                    "
                  >
                    −
                  </button>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    class="expert-addon-input h-5 w-10 rounded border bg-sapphire px-1 text-right text-xs tabular-nums text-primary-50"
                    :class="
                      legAddon(row.prevStopId, row.stopId) > 0
                        ? 'border-amber-300/50 text-amber-200'
                        : 'border-primary-50/20'
                    "
                    :value="legAddon(row.prevStopId, row.stopId)"
                    :aria-label="t('proposal.expert.legAria', { stop: row.name })"
                    @change="onLegAddonInput(row.prevStopId, row.stopId, $event)"
                  />
                  <button
                    type="button"
                    class="h-5 w-5 shrink-0 cursor-pointer rounded border border-primary-50/20 text-xs leading-none text-primary-50 transition hover:bg-primary-50/15 disabled:cursor-not-allowed disabled:opacity-40"
                    :aria-label="t('proposal.expert.moreAria', { stop: row.name })"
                    @click="
                      setLegAddon(
                        row.prevStopId,
                        row.stopId,
                        legAddon(row.prevStopId, row.stopId) + 1,
                      )
                    "
                  >
                    +
                  </button>
                </div>
              </template>
            </Column>
          </DataTable>

          <!-- Itinerary controls, always centered as a group under the itinerary:
               Back to edit (suggest) / Edit (display) / Add Stop (edit) + Swap in
               the middle; Cancel Edit (re-edit) on the right. The two flex-1
               spacers keep the middle group centered regardless of which side
               buttons are present. -->
          <div
            v-if="currentMode !== 'loading'"
            class="mt-5 flex items-center gap-2 border-t border-primary-50/10 pt-5"
          >
            <div class="flex flex-1 items-center gap-2" />

            <div class="flex items-center gap-2">
              <!-- Back to edit (suggest) — abandon the suggestion step, itinerary
                   untouched. -->
              <button
                v-if="currentMode === 'suggest'"
                :class="toolPillClass"
                @click="cancelSuggestMode"
              >
                <AppIcon :path="mdiArrowLeft" :size="16" />
                {{ t('proposal.suggestions.backToEdit') }}
              </button>

              <!-- Edit (display) -->
              <button v-if="currentMode === 'display'" :class="toolPillClass" @click="startEdit">
                <AppIcon :path="mdiPencil" :size="16" />
                {{ t('proposal.edit') }}
              </button>

              <!-- Add Stop (edit + re-edit) -->
              <StopSelect
                v-if="currentMode === 'edit'"
                :stops="store.stops"
                :status="store.stopsStatus"
                :disabled-ids="usedStopIds"
                @select="addStop"
                @retry="store.fetchStops()"
              >
                <button :class="toolPillClass">
                  <AppIcon :path="mdiPlus" :size="16" />
                  {{ t('proposal.addStop') }}
                </button>
              </StopSelect>

              <!-- Swap direction (all modes where applicable) -->
              <button
                v-if="showSwap"
                :class="toolPillClass"
                :aria-label="t('proposal.swapDirection')"
                @click="swapDirection"
              >
                <AppIcon :path="mdiSwapVertical" :size="16" />
              </button>

              <!-- Expert timetable. Sits with the itinerary's own tools, not
                   in the evaluation panel: it changes what is BUILT, not how
                   finished results are sliced. Only in display mode — both
                   its controls are relative to a computed timetable, so
                   there is nothing to pin or pad before the first
                   evaluation. -->
              <button
                v-if="currentMode === 'display'"
                :class="[toolPillClass, expertMode ? 'expert-pill-on' : '']"
                :aria-pressed="expertMode"
                @click="toggleExpertMode"
              >
                <AppIcon :path="mdiTimerCogOutline" :size="16" />
                {{ t('proposal.expert.toggle') }}
              </button>
            </div>

            <div class="flex flex-1 items-center justify-end gap-2">
              <!-- Cancel Edit (re-edit) -->
              <button v-if="showCancelEdit" :class="toolPillClass" @click="cancelEdit">
                <AppIcon :path="mdiClose" :size="16" />
                {{ t('proposal.cancelEdit') }}
              </button>
            </div>
          </div>

          <!-- Headline route figures — distance, average speed, frequency.
               Its own panel under the itinerary controls, matching the boxes
               in the results section, and labelled the same way so the strip
               reads as a titled panel rather than three loose pills. -->
          <div
            v-if="currentMode === 'display' && routeStatRows.length > 0"
            class="mt-8 flex flex-col items-center gap-2 rounded-xl bg-primary-50/5 px-4 py-3 text-primary-50/70"
          >
            <span class="text-xs tracking-wide text-primary-50/50 uppercase">
              {{ t('proposal.routeStats') }}
            </span>
            <div class="flex flex-wrap justify-center gap-x-8 gap-y-3">
              <div
                v-for="stat in routeStatRows"
                :key="stat.icon"
                class="flex items-center gap-2"
                :title="stat.title"
              >
                <AppIcon :path="stat.icon" :size="20" />
                <span class="text-base font-semibold">{{ stat.value }}</span>
              </div>
              <CountryFlags
                v-if="routeStats"
                :countries="routeStats.countries"
                :title="routeStats.countries.map((c) => countryName(c)).join(', ')"
              />
            </div>
          </div>
        </div>

        <div v-if="store.stopsStatus === 'loading'" class="text-xs text-primary-50/40">
          {{ t('proposal.loading') }}
        </div>
        <div v-if="store.stopsFailure" class="max-w-sm text-xs break-words" role="alert">
          <span class="text-red-400">{{ t('errors.stopsUnavailable') }}</span>
          <button
            type="button"
            class="ml-2 cursor-pointer font-semibold text-primary-50 underline underline-offset-2"
            @click="store.fetchStops()"
          >
            {{ t('errors.retry') }}
          </button>
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
            <AppSpinner v-else :size="16" />
          </button>

          <!-- max-w-sm (inside InlineAlert) matches the itinerary table's own
               cap. The parent panel is `w-fit`, so an uncapped sentence sets
               the panel's width and collapses the flex-1 map beside it into a
               sliver. -->
          <InlineAlert v-if="calcFailureMsg" :message="calcFailureMsg">
            <button
              v-if="calcFailure && isRetryable(calcFailure)"
              type="button"
              class="w-fit cursor-pointer text-xs font-semibold text-primary-50 underline underline-offset-2"
              @click="retryCalc"
            >
              {{ t('errors.retry') }}
            </button>
          </InlineAlert>
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
          <InlineAlert v-if="publishError" :message="publishError" />
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
            :available="mapAvailable"
            class="w-full h-full"
            @toggle-suggested="toggleSuggested"
            @add-stop="onMapAddStop"
          />
          <!-- Like + share, bottom-left: MapLibre's zoom control is top-right
               and its attribution bottom-right, so this corner is free. Placed
               BEFORE the loading scrim below, which is `absolute inset-0` and
               should legitimately cover it while a calc runs. Unlike the
               evaluation panel it is NOT greyed out while the builder is dirty:
               likes and links are about the proposal as published, not about
               the unsaved itinerary. -->
          <MapShareBar
            v-if="storedProposalId !== null"
            :proposal-id="storedProposalId"
            :origin="shareOrigin"
            :destination="shareDestination"
            :facts="shareFacts"
          />
          <!-- Deliberately NOT wrapped in <Transition>. The fade wedged its own
               state machine here: the element kept `fade-enter-from` (opacity 0)
               into `fade-leave-active`, so the leave animated 0 -> 0, fired no
               transitionend, and Vue never removed the node — not even with an
               explicit :duration. What was left behind was invisible but still
               an `absolute inset-0` scrim over the map, swallowing every click,
               and (once Cancel moved in here) holding a focusable phantom
               button. A 200ms fade on a loading scrim is not worth that. -->
          <div
            v-if="currentMode === 'loading'"
            class="absolute inset-0 flex items-center justify-center rounded-xl bg-black/20 px-8 backdrop-blur-sm"
          >
            <!-- The caption sits on its own dark panel rather than straight on
                   the scrim: the map underneath can be near-white (light tiles,
                   or tiles that haven't loaded), and bg-black/20 is not enough
                   contrast for light text — the message has to be readable to be
                   worth showing. -->
            <div
              class="flex flex-col items-center gap-4 rounded-xl bg-sapphire-100/95 px-6 py-5 shadow-xl"
            >
              <div
                class="h-10 w-10 animate-spin rounded-full border-4 border-primary-50/30 border-t-primary-50"
              />
              <!-- An unchanging spinner is what felt bad during the overload,
                     so the caption escalates: what we're doing, then that the
                     server is busy, then that we're under load. -->
              <p class="max-w-xs text-center text-sm text-primary-50" aria-live="polite">
                {{ progressCaption }}
              </p>
              <!-- Sits BELOW the caption, never replacing it: the escalating
                   caption is how the user learns the server is slow, and a fun
                   fact must not push that off screen. -->
              <LoadingFunFact />
              <!-- Lives here, beside the spinner, rather than under the Evaluate
                   button: a calc started from suggest mode hides that button, so
                   anchoring Cancel to it left the longest waits uncancellable.
                   The server keeps working either way — aborting the fetch
                   cannot free its worker — so this only ever means "I've stopped
                   watching", and the copy avoids claiming otherwise. -->
              <button
                type="button"
                class="cursor-pointer text-xs text-primary-50/60 underline underline-offset-2 transition hover:text-primary-50"
                @click="cancelCalc"
              >
                {{ t('errors.cancel') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Results (display + re-edit): scenario switches + main KPIs, the
         scenario/composition comparison, the discussion, and the collapsible
         detail settings and cost breakdown — ProposalResults.vue. Greyed out
         while the builder is dirty, since the figures no longer match the
         current itinerary. The discussion is slotted in so it is NEVER greyed:
         a thread is about the proposal and has no business going dead
         mid-edit, and it hangs off storedProposalId, which only this
         component knows. -->
    <div
      v-if="showEvaluationSection && !loadFailureMsg && calcResult && calcSummary"
      class="w-full"
    >
      <ProposalResults
        :result="calcResult"
        :summary="calcSummary"
        :stops="sectionStops"
        :compositions="store.compositions"
        :selected-composition-id="selectedCompositionId"
        :family="family"
        :params-stale="paramsStale"
        :dimmed="isDirty"
        :schedule-mode="(publishRequest?.schedule_mode as string | undefined) ?? null"
        @select-composition="(id) => (selectedCompositionId = id)"
        @recalculate="recomputeWithSelection"
        @scope-change="onScopeChange"
        @retry-family="retryFamily"
      >
        <template #discussion>
          <div v-if="storedProposalId !== null && showCommentSection" class="w-full">
            <CommentSection :proposal-id="storedProposalId" />
          </div>
        </template>
      </ProposalResults>
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
/* The per-leg minute field is a number input for its keyboard and its
   min=0 clamp, not for its spinners: at 20px tall they are unusable and
   they cost a third of the field's width. The ± buttons are the
   affordance. */
.expert-addon-input {
  -moz-appearance: textfield;
  appearance: textfield;
}
.expert-addon-input::-webkit-outer-spin-button,
.expert-addon-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
/* Expert mode on: the same gold this app already uses for "a value you
   chose" (ProposalResults' scenario card, ExpertTimetableControls). */
.expert-pill-on {
  border-color: color-mix(in srgb, #fbbf24 45%, transparent);
  background: color-mix(in srgb, #fbbf24 14%, transparent);
  color: #fde68a;
}
/* Drag handle: hover-only */
:deep(.reorder-col > *) {
  opacity: 0;
  transition: opacity 0.2s ease;
}
:deep(tr:hover .reorder-col > *) {
  opacity: 1;
}
</style>
