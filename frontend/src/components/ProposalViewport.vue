<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import {
  daysPerWeekFromRequest,
  demandFromRequest,
  demandRequest,
  sameDemand,
  scheduleRequest,
  sameTariff,
  tariffFromRequest,
  tariffRequest,
  type Tariff,
} from '@/lib/detailsScope'
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
import { SELECTION_SAVE_DELAY_MS, selectionSaveNeeded } from '@/lib/selectionSave'
import { useApiFailure } from '@/composables/useApiFailure'
import { resolvePrefillStops, type GallerySearchSeed } from '@/lib/proposalPrefill'
import { readDraft, writeDraft, clearDraft } from '@/lib/proposalDraftStorage'
import {
  inNightInterval,
  legIsNight,
  pruneNightInterval,
  reverseNightInterval,
  sameNightInterval,
  toggleNightStop,
  type NightInterval,
  type NightSelection,
} from '@/lib/nightInterval'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { buildSuggestRows, settledRows, type SuggestRow } from '@/lib/suggestPlacement'
import { formatClock, dayOffset } from '@/lib/tripClock'
import { useProposalFamily } from '@/composables/useProposalFamily'
import { useDeferredFlag } from '@/composables/useDeferredFlag'
import { buildScenarioAxes, conditionLabelKey } from '@/lib/scenarioAxes'
import { alternativeRoutes, inflateRoute, memberFailure, routeFor } from '@/lib/proposalFamily'
import {
  addonFor,
  addonsForDirection,
  clockToServiceMinute,
  droppedAddons,
  emptyExpert,
  fromRequest,
  fromRouteSegments,
  isEmptyExpert,
  materialiseSlack,
  mirrorDirection,
  pruneExpertToStops,
  resolveDeparture,
  resolveTimetable,
  setDeparture,
  setAddon,
  swapDirections,
  toggleDepartureMode,
  type ResolvedDirection,
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
import InfoPopover from '@/components/InfoPopover.vue'
import AppSpinner from '@/components/AppSpinner.vue'
import StopSelect from '@/components/StopSelect.vue'
import ProposalResults from '@/components/ProposalResults.vue'
import OwnershipLine from '@/components/OwnershipLine.vue'
import CountryFlags from '@/components/CountryFlags.vue'
import StopTime from '@/components/StopTime.vue'
import LoadingFunFact from '@/components/LoadingFunFact.vue'
import MapView from '@/components/MapView.vue'
import TripPairComingSoon from '@/components/TripPairComingSoon.vue'
import MapShareBar from '@/components/MapShareBar.vue'
import CommentSection from '@/components/CommentSection.vue'
import InlineAlert from '@/components/InlineAlert.vue'
import {
  mdiArrowLeft,
  mdiArrowLeftRight,
  mdiCheckCircle,
  mdiLock,
  mdiLockOpenVariant,
  mdiMirror,
  mdiRestore,
  mdiSleep,
  mdiSwapHorizontal,
  mdiWalk,
  mdiExitRun,
  mdiWeatherNight,
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
  // Which part of the page the reader came for — 'comments' when they clicked a
  // gallery card's comment count. Routing stays in ProposalWorkspace, which
  // translates /proposal/<id>#comments into this prop.
  focusSection?: 'comments' | null
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
// The family build is the one genuinely long call in the app, so it reports
// progress rather than just spinning, cancellable throughout. When it
// escalates to 'slow' and 'verySlow' depends on the route: the family
// composable sizes the thresholds from members × legs and whether the route
// needs live routing (lib/calcExpectation.ts), so "longer than usual" is
// only said when it is.
const calcPhase = ref<'idle' | 'working' | 'slow' | 'verySlow'>('idle')
const calcFailure = ref<ApiFailure | null>(null)
const calcFailureMsg = ref<string | null>(null)
const calcSlot = createAbortSlot()
// Arguments of the last calc, so Retry replays it rather than guessing.
const lastCalcArgs = ref<{ stopIds: string[]; autoStopAddition: 'off' | 'suggest' } | null>(null)

// --- Fixed night -------------------------------------------------------------
// Where the night goes: null = the automatic timetable (the whole trip
// centred on 02:30), an interval = timetable_mode "simpleAutomaticWithFixed-
// Night" with 00:00–05:00 centred on that section instead. A display-mode
// tool like expert mode: switched on with the moon pill, picked stop by stop
// on the timetable (lib/nightInterval.ts) in the itinerary's current travel
// order — flipping direction reverses it (swapDirection). Moving it is stale
// results like an expert edit, and takes the same Recalculate over the
// timetable; switching the tool off is back to the automatic night.
const nightMode = ref(false)
const nightSelection = ref<NightSelection>({ interval: null, pending: null })
// The interval the displayed results were computed with, in the orientation
// they were computed in (the same convention as committedItinerary).
const committedNightInterval = ref<NightInterval | null>(null)

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
// The night tool is one of expert mode's tools: the pill and the markers
// need expert mode on and a computed timetable to act on.
const nightToolOn = computed(
  () => expertMode.value && nightMode.value && currentMode.value === 'display',
)
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
// The composition the STORED proposal currently carries — what a
// family-served switch is compared against to decide whether anything needs
// saving (lib/selectionSave.ts). Set wherever the stored state is learned:
// on load, and after every successful publish.
const savedCompositionId = ref<string | null>(null)
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
  // How the backend classified the stop on the clock (boarding / night /
  // alighting / both) — null on a stored proposal older than the field.
  stop_type: string | null
  // Whether the leg arriving here / leaving here runs through the night
  // window (lib/nightInterval.ts legIsNight) — what colours the timeline.
  night_in: boolean
  night_out: boolean
  // Night-stretch minutes on the leg arriving here (Segment.slack_time_min).
  slack_in: number
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
  stop_type?: string
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
  // Minutes the fixed-night stretch put on this leg (0 outside that mode) —
  // shown in the same field as the manual minutes, since both are extra
  // time on the leg beyond its physics.
  slack_time_min?: number
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
  // How far an expert departure moved the trip off its automatic value
  // (ROUTE_BUILDER 0.9.37) — 0 on an automatic timetable. Optional for the
  // same reason.
  departure_shift_min?: number
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
function toStopTimeFmt(
  stop: BackendStop,
  baseMin: number | null,
  night: { in: boolean; out: boolean; slackIn: number },
): StopTimeFmt {
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
    stop_type: stop.stop_type ?? null,
    night_in: night.in,
    night_out: night.out,
    slack_in: night.slackIn,
  }
}

// segments[] holds one from_stop/to_stop pair per leg — walk them into the
// flat per-stop list the template expects (first leg's from_stop, then every
// leg's to_stop). Each leg's night flag lands on both of its stops: as
// `night_out` on the one it leaves, `night_in` on the one it reaches.
function buildStopTimes(segments: BackendSegment[]): StopTimeFmt[] {
  if (segments.length === 0) return []
  const baseMin = segments[0].from_stop.departure_time_min
  const nightLeg = segments.map((seg) =>
    legIsNight(seg.from_stop.departure_time_min, seg.to_stop.arrival_time_min),
  )
  return [
    toStopTimeFmt(segments[0].from_stop, baseMin, { in: false, out: nightLeg[0], slackIn: 0 }),
    ...segments.map((seg, i) =>
      toStopTimeFmt(seg.to_stop, baseMin, {
        in: nightLeg[i],
        out: nightLeg[i + 1] ?? false,
        slackIn: seg.slack_time_min ?? 0,
      }),
    ),
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
  expert.value = swapDirections(expert.value, autosOnScreen())
  if (nightSelection.value.interval) {
    nightSelection.value = {
      ...nightSelection.value,
      interval: reverseNightInterval(nightSelection.value.interval),
    }
  }
  if (live) {
    const trips = routeResult.value?.trips ?? []
    const other = trips.find((t) => t.trip_id !== selectedTripId.value)
    if (other) selectedTripId.value = other.trip_id
  }
}

// Ordered stops (outbound direction) backing the route-section slider.
// The route's two example journeys, priced by the Supply tab's fare table:
// the longest OD pair the route sells (its terminals) and the shortest (the
// closest two consecutive stops). Computed here because only the raw route
// carries per-segment distances; a fare in €/km means little without them.
const exampleOdPairs = computed(() => {
  const pair = rawRoute.value?.trip_pairs?.[0]
  const segments = pair?.outbound?.segments ?? []
  if (segments.length === 0) return { longest: null, shortest: null }
  const first = segments[0].from_stop
  const last = segments[segments.length - 1].to_stop
  const totalKm = segments.reduce((sum, seg) => sum + seg.distance_m / 1000, 0)
  let shortest = segments[0]
  for (const seg of segments) if (seg.distance_m < shortest.distance_m) shortest = seg
  return {
    longest: { name: `${first.stop_name} – ${last.stop_name}`, km: totalKm },
    shortest: {
      name: `${shortest.from_stop.stop_name} – ${shortest.to_stop.stop_name}`,
      km: shortest.distance_m / 1000,
    },
  }
})

// Both directions, which is what the summary's total_distance_km counts and
// therefore what one operating day covers.
const cycleDistanceKm = computed(() => calcSummary.value?.total_distance_km ?? 0)

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

// Mirrored ↔ own times. Leaving mirroring gives the opposite direction its
// own copy of what the mirror was showing it, so the switch changes no times
// by itself; going back discards those own times and mirrors the direction
// on screen — always the one on screen, which is what "mirror this
// direction" means.
function setMirrored(mirrored: boolean) {
  expert.value = {
    ...expert.value,
    returnTrip: mirrored ? null : mirrorDirection(expert.value.outbound, autosOnScreen()),
  }
}

// The automatic departure per direction — what a shift is measured from, what
// "reset" returns to, what the hint quotes, and what mirroring a pinned
// departure is measured against. The response says how far each trip was
// moved off it (general_parameters.departure_shift_min, 0 on an automatic
// timetable), so it is recovered exactly, pinned or not.
const lastAutoDeparture = ref<[number, number]>([0, 0])

function rememberAutoDeparture(route: BackendRoute) {
  const pair = route.trip_pairs[0]
  if (!pair) return
  const next: [number, number] = [...lastAutoDeparture.value]
  for (const [direction, trip] of [
    [0, pair.outbound],
    [1, pair.return_trip],
  ] as const) {
    const departed = trip.segments[0]?.from_stop.departure_time_min
    if (departed == null) continue
    next[direction] = departed - (trip.general_parameters.departure_shift_min ?? 0)
  }
  lastAutoDeparture.value = next
}

// Indexed by the ROUTE's direction id, not by which slot is on screen: the
// route's directions do not move when the itinerary is flipped, so this
// survives a flip without having to be swapped alongside the overrides.
const onScreenDirection = computed<0 | 1>(() => (selectedTrip.value?.direction_id === 1 ? 1 : 0))
const autoDepartureMin = computed(() => lastAutoDeparture.value[onScreenDirection.value])

// The pair of automatic values as lib/expertTimetable's mirroring wants
// them: `own` for the direction on screen, `other` for the opposite one.
function autosOnScreen() {
  const [outbound, returnTrip] = lastAutoDeparture.value
  return onScreenDirection.value === 0
    ? { own: outbound, other: returnTrip }
    : { own: returnTrip, other: outbound }
}

const currentDeparture = computed(() => expert.value.outbound.departure)
const pinnedDeparture = computed(() => currentDeparture.value?.mode !== 'shift')
const pinHintText = computed(() =>
  t(pinnedDeparture.value ? 'proposal.expert.pinnedAria' : 'proposal.expert.followsAria'),
)
const mirrorHintText = computed(() =>
  t(otherDirectionMirrors.value ? 'proposal.expert.mirroredAria' : 'proposal.expert.ownTimesAria'),
)

function setDepartureOverride(value: DepartureOverride | null) {
  expert.value = { ...expert.value, outbound: { ...expert.value.outbound, departure: value } }
}

// The first departure as the strip's input shows it: the override in force
// (or the automatic value), NOT the computed row — a typed time has to stay
// on screen until the recalculation that applies it. Wall clock in, service
// minute out; the +1 markers on the later rows say what day it means.
const currentDepartureMin = computed(() =>
  resolveDeparture(currentDeparture.value, autoDepartureMin.value),
)
const currentDepartureClock = computed(() => formatClock(currentDepartureMin.value) ?? '')

function onDepartureInput(event: Event) {
  const minute = clockToServiceMinute(
    (event.target as HTMLInputElement).value,
    currentDepartureMin.value,
  )
  if (minute === null) return
  setDepartureOverride(setDeparture(currentDeparture.value, autoDepartureMin.value, minute))
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

// The stepper shows every extra minute on the leg beyond its physics: the
// manual add-on plus what the fixed-night stretch put there (the backend
// shares that stretch over the section's legs in proportion to each leg's
// running time — driving, acceleration/deceleration and buffer).
//
// The night band is just another way of adding time: the model chose the
// minutes and where the trip sits, the user can take them over at any
// point. So the first manual touch of a stretched leg — a step either way,
// or a typed value — MATERIALISES the night (lib/expertTimetable.ts
// materialiseSlack): every leg's stretch becomes its manual minutes, the
// departure is pinned where the trip currently leaves, the fixed night is
// dropped (tool off). Not a minute moves, and from there the field is an
// ordinary add-on field: 160 steps to 159 or 161, exactly as it reads.
// (Left to the backend instead, a manual minute inside a fixed-night
// section only shrinks the stretch, and the field would spring back to 160
// on the recompute.) Nothing here recalculates — that stays the button's.
//
// The stretch on screen is the last calc's and only describes the leg while
// the night is where that calc put it; once moved, the field shows the
// manual part alone until the next calc.
function legSlack(row: ViewRow): number {
  return nightSelection.value.interval !== null &&
    sameNightInterval(nightSelection.value.interval, committedNightInterval.value)
    ? row.slackIn
    : 0
}

function legExtra(row: ViewRow): number {
  return legAddon(row.prevStopId, row.stopId) + legSlack(row)
}

// The legs of a trip as materialiseSlack() wants them, from its rows.
function slackLegs(stopTimes: StopTimeFmt[]) {
  return stopTimes.slice(1).map((st, i) => ({
    fromStopId: stopTimes[i].stop_id,
    toStopId: st.stop_id,
    slackMin: st.slack_in,
  }))
}

function materialiseNight() {
  const trips = routeResult.value?.trips ?? []
  const onScreen = selectedTrip.value
  if (!onScreen) return
  const other = trips.find((t) => t.trip_id !== onScreen.trip_id)
  const autos = autosOnScreen()
  const outbound = materialiseSlack(
    expert.value.outbound,
    slackLegs(onScreen.stop_times),
    currentDepartureMin.value,
  )
  // A return with its own times takes over its own stretch too; a
  // mirroring one is derived from outbound and needs nothing.
  const returnTrip =
    expert.value.returnTrip && other
      ? materialiseSlack(
          expert.value.returnTrip,
          slackLegs(other.stop_times),
          resolveDeparture(expert.value.returnTrip.departure, autos.other),
        )
      : expert.value.returnTrip
  expert.value = { outbound, returnTrip }
  nightMode.value = false
  nightSelection.value = { interval: null, pending: null }
}

function stepLegExtra(row: ViewRow, delta: number) {
  if (legSlack(row) > 0) materialiseNight()
  setLegAddon(row.prevStopId, row.stopId, legAddon(row.prevStopId, row.stopId) + delta)
}

function onLegExtraInput(row: ViewRow, event: Event) {
  const minutes = Number((event.target as HTMLInputElement).value)
  if (legSlack(row) > 0) materialiseNight()
  setLegAddon(row.prevStopId, row.stopId, minutes)
}

function legExtraHint(row: ViewRow): string {
  const slack = legSlack(row)
  return slack > 0
    ? t('proposal.night.slackHint', { minutes: slack })
    : t('proposal.expert.legAria', { stop: row.name })
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

// Hover text for the icon-only tools (direction switch, pinned, mirrored,
// reset): one shared InfoPopover under the tool row, driven the way
// FactorInfoPopover is driven from many icons — the key skips a redundant
// re-open on the icon already showing. The sentence is the same one the
// icon's aria-label carries, so sighted and screen-reader users read alike.
const toolHint = ref<InstanceType<typeof InfoPopover> | null>(null)
const toolHintText = ref('')

function showToolHint(event: Event, text: string) {
  toolHintText.value = text
  toolHint.value?.open(event, text)
}

// Turning expert mode off drops the overrides rather than hiding them: a
// hidden override that still reaches the next calc is the worst of both.
function toggleExpertMode() {
  expertMode.value = !expertMode.value
  if (!expertMode.value) {
    expert.value = emptyExpert()
    // The night goes back to what the results were computed with — not to
    // automatic: a placed night is part of the saved proposal, and leaving
    // expert mode is not a request to move it.
    nightSelection.value = { interval: committedNightInterval.value, pending: null }
  }
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
  // Pruned against the stops actually posted, for the same reason the expert
  // add-ons are: a night placed on a stop that is gone is a 400.
  const night = pruneNightInterval(nightSelection.value.interval, stopIds)
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
  // The Details card's inputs (zone D): the schedule, the prices and the
  // demand. They are HOW fields: part of the family key, echoed in the
  // resolved request, and saved with the proposal. The frequency is always
  // posted — the backend expands it onto its month grid and hashes the map,
  // so one figure and the spelled-out map are the same family.
  const schedule = scheduleRequest(store.scheduleDaysPerWeek)
  return {
    stops: stopIds,
    // Omitted entirely while nothing is overridden: an absent block and an
    // empty one are the same request server-side. Pruned first — the
    // backend rejects an add-on whose stop pair is not a leg of the stops
    // being posted.
    ...(expertBlock ? { expert_timetable: expertBlock } : {}),
    ...(night
      ? { timetable_mode: 'simpleAutomaticWithFixedNight', fixed_night_interval: night }
      : {}),
    ...schedule,
    // The four tariff maps, posted only once the model registry has seeded
    // them: an empty object would price every class at nothing, which is not
    // what an unanswered request means.
    ...(Object.keys(store.faresEurPerKm).length > 0 ? tariffRequest(currentTariff.value) : {}),
    // The demand block, once the registry has seeded it; omitted before that
    // means the backend's own defaults, which is what it would post anyway.
    ...(store.demand ? demandRequest(store.demand) : {}),
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
//
// The overlay itself appears only after LOADING_SCRIM_DELAY_MS and then stays
// at least LOADING_SCRIM_MIN_MS: a document-cache hit answers in 0.2–0.4 s,
// and a scrim flashing on and off for that reads as a glitch. The builder is
// in loading mode (inputs disabled) from the first millisecond either way.
const LOADING_SCRIM_DELAY_MS = 500
const LOADING_SCRIM_MIN_MS = 700
const loadingScrimVisible = useDeferredFlag(() => currentMode.value === 'loading', {
  delayMs: LOADING_SCRIM_DELAY_MS,
  minVisibleMs: LOADING_SCRIM_MIN_MS,
})
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
    const bundle = await family.views(scenarioId, compositionId)
    if (token !== viewsToken || !bundle || !calcResult.value) return
    calcResult.value = { ...calcResult.value, views: bundle.views, operations: bundle.operations }
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
/** The Details inputs as the resolved request echo has them. */
function restoreDetailInputs(request: Record<string, unknown>) {
  store.scheduleDaysPerWeek = daysPerWeekFromRequest(
    request.schedule as Record<string, number> | null | undefined,
  )
  // An echo written before DEMAND 0.1.0 has no block: keep the registry's
  // defaults, and the Details card will report the demand as changed until
  // the first recalculation commits it.
  const demand = demandFromRequest(request)
  if (demand) store.demand = demand
  const tariff = tariffFromRequest(request)
  // Only what the echo actually carries: a request written before CALC
  // 0.9.30 has no fixed-fare or services map, and overwriting the seeded
  // defaults with {} would price those parts at nothing.
  if (Object.keys(tariff.faresPerKm).length) store.faresEurPerKm = { ...tariff.faresPerKm }
  if (Object.keys(tariff.faresPerPax).length) store.faresEurPerPax = { ...tariff.faresPerPax }
  if (Object.keys(tariff.servicesPerPax).length) {
    store.servicesEurPerPax = { ...tariff.servicesPerPax }
  }
  if (Object.keys(tariff.cateringPerPax).length) {
    store.cateringEurPerPax = { ...tariff.cateringPerPax }
  }
}

// `look`: the plan is another member of the SAME family (a scenario or
// composition switch), not the result of what the builder currently asks
// for — so add-ons the member does not carry were not "dropped", they are
// the user's pending edits, and applyMemberFromFamily() puts them back.
function applyPlan(json: MemberPlan, publish = false, look = false) {
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
  rememberAutoDeparture(json.route)
  if (expertMode.value) {
    const dropped = reconcileExpert(json.route, sentOutbound, sentReturn)
    if (dropped.length > 0 && !look) reportDroppedAddons(dropped)
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
  // Put the Details inputs back where the echo says they were. This is what
  // makes a STORED proposal open with its own schedule and prices rather than
  // the defaults — without it a reload would recompute against defaults and
  // report itself stale the moment it finished loading.
  restoreDetailInputs(json.request)
  const route = adaptRoute(json.route)
  routeResult.value = route
  selectedTripId.value =
    route.trips.find((t) => t.direction_id === 0)?.trip_id ?? route.trips[0]?.trip_id ?? null
  itinerary.value = itineraryFromRoute(route)
  committedItinerary.value = itinerary.value.map((s) => ({ ...s }))
  // The night as computed — the echo is in the posted order, which is the
  // itinerary order just set. A stored proposal opens with its own night
  // this way rather than reverting to automatic on its first recompute.
  const echoedNight = json.request?.fixed_night_interval as string[] | null | undefined
  const night: NightInterval | null =
    echoedNight && echoedNight.length === 2 ? [echoedNight[0], echoedNight[1]] : null
  nightSelection.value = { interval: night, pending: null }
  committedNightInterval.value = night
  if (night) nightMode.value = true
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
async function doPublish(silent = false) {
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
    savedCompositionId.value = (req.composition_id as string | null) ?? null
    // The gallery is kept alive, so its cached list would otherwise not contain
    // the proposal the user just published. Flag it to refetch once on return.
    store.galleryStale = true
    clearDraft()
    // A selection save is the user's own click, one debounce ago — the
    // inline "saved" line under the results says so. A toast per arrow
    // through the composition catalogue would be noise.
    if (!silent) toastStore.addToast('success', t('proposal.saved'))
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
  [itinerary, selectedCompositionId, currentMode, suggestSelected, nightSelection],
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
      nightIntervalIds: pruneNightInterval(nightSelection.value.interval, stopIds),
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

// The night section moved: stale results, like an expert edit (see
// expertChanged). Either orientation is the same night (sameNightInterval),
// so a flip stays clean here too; an interval a stop edit made illegal
// counts as removed, which is what the next request will post.
const nightChanged = computed(
  () =>
    committedItinerary.value !== null &&
    !sameNightInterval(
      pruneNightInterval(nightSelection.value.interval, currentStopIds.value),
      committedNightInterval.value,
    ),
)

// While the night on screen is no longer the one requested, its band and
// stop icons fade: what is drawn is the last calculation's, and a dropped
// night has to be visibly gone before the recompute confirms it.
const nightOnScreenStale = computed(() => nightChanged.value)

// The two timetable tools together: what puts the Recalculate control over
// the timetable rather than over the results.
const timetableChanged = computed(() => expertChanged.value || nightChanged.value)

// True when the rich computed view (times, exact map routing, evaluation) is in
// force: display mode, and re-edit mode up until the first change. Making a
// change (dirty) drops us back to the plain builder view even though we stay in
// edit mode.
const showComputedView = computed(
  () =>
    currentMode.value === 'display' ||
    (currentMode.value === 'edit' && routeResult.value !== null && !isDirty.value),
)

// --- Saving the creator's last selection ------------------------------------
// A composition switch served from the family is applied without a compute
// (applyMemberFromFamily below), so nothing used to reach the store: the
// proposal kept the composition of the last RECALCULATE, and every figure
// the gallery showed described a train the creator had moved on from. The
// switch now schedules a publish-overwrite, debounced so that arrowing
// through the catalogue costs one publish rather than one per step.
//
// The publish is the ordinary one: the server recomputes, but by then the
// member is in its member cache and the family document the builder wrote
// carries the per-scenario rows, so the round trip is the cheap path (see
// the backend's api/helpers/scenario_summaries.py). Only the composition is
// treated this way — prices, demand, schedule and expert edits already
// reach the store through the Recalculate that computes them, and the
// scenario is deliberately not stored (a proposal always represents the
// current base; the gallery's scenario panel shows the others).
let selectionSaveTimer: ReturnType<typeof setTimeout> | null = null

function cancelSelectionSave(): void {
  if (selectionSaveTimer !== null) {
    clearTimeout(selectionSaveTimer)
    selectionSaveTimer = null
  }
}

function selectionSaveState() {
  return {
    ownsProposal: ownsProposal.value,
    proposalId: publishedProposalId.value,
    selectedCompositionId: selectedCompositionId.value,
    savedCompositionId: savedCompositionId.value,
    dirty: isDirty.value,
    busy: currentMode.value === 'loading' || publishPhase.value !== 'idle',
  }
}

function scheduleSelectionSave(): void {
  cancelSelectionSave()
  if (!selectionSaveNeeded(selectionSaveState())) return
  selectionSaveTimer = setTimeout(() => {
    selectionSaveTimer = null
    // Re-checked at fire time, not only when scheduled: the user may have
    // switched back, started an edit, or hit Recalculate in the meantime —
    // and that last one saves on its own path.
    if (selectionSaveNeeded(selectionSaveState())) doPublish(true)
  }, SELECTION_SAVE_DELAY_MS)
}

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
      expertChanged.value ||
      nightChanged.value ||
      detailsChanged.value),
)

// The Details card's own inputs (zone D) are stale results in exactly the
// same sense as a composition switch: the figures above no longer describe
// what the fields say. The card is deliberately NOT greyed with the rest —
// it is where the inputs live — so it carries its own Recalculate and its
// own per-panel waiting state; this flag is what greys zones A, B and E.
const detailsChanged = computed(() => {
  const request = publishRequest.value
  if (!request) return false
  const committedDays = daysPerWeekFromRequest(
    request.schedule as Record<string, number> | null | undefined,
  )
  if (committedDays !== store.scheduleDaysPerWeek) return true
  if (!sameDemand(store.demand, demandFromRequest(request))) return true
  return !sameTariff(currentTariff.value, tariffFromRequest(request))
})

/** The tariff as the fields currently have it. */
const currentTariff = computed<Tariff>(() => ({
  faresPerKm: store.faresEurPerKm,
  faresPerPax: store.faresEurPerPax,
  servicesPerPax: store.servicesEurPerPax,
  cateringPerPax: store.cateringEurPerPax,
}))

// An expert edit is not "dirty" — the stops are untouched — it is stale
// results, the same state a composition switch produces, and it takes the
// same Recalculate control. Compared on the CLOCK, not on the request: a pin
// at the automatic value, a pin↔follows toggle, or breaking the mirror link
// changes the request without moving a minute, and must not ask for a
// recalculation — only a departure or a leg that actually moved does. (The
// mode itself reaches the stored proposal with the next recalculation that
// is needed anyway; until then it only matters for what that recalculation
// posts.)
// Compared by the route's direction, so a flipped view counts as unchanged
// for the same reason isDirty accepts a reversed stop list: the committed
// state is in the computed orientation (slot 0 = direction 0), the current
// one has the direction on screen in slot 0.
const expertChanged = computed(() => {
  const committed = committedExpert.value
  if (committed === null) return false
  const [outbound, returnTrip] = lastAutoDeparture.value
  const committedByDirection = resolveTimetable(committed, { own: outbound, other: returnTrip })
  const current = resolveTimetable(expert.value, autosOnScreen())
  const currentByDirection: [ResolvedDirection, ResolvedDirection] =
    onScreenDirection.value === 0 ? current : [current[1], current[0]]
  return JSON.stringify(currentByDirection) !== JSON.stringify(committedByDirection)
})

// The stale results' recompute: same "stops are settled" call the scenario
// switch used to make on its own, now behind the user's click.
//
// The results section unmounts while the compute is out (currentMode is
// 'loading'), so the page collapses to the builder and the browser puts the
// reader back at the top. Remembering the scroll offset and restoring it once
// the new figures are mounted keeps a Recalculate pressed inside the Details
// card where it was pressed — the card's own open state and tab survive in
// the store for the same reason.
async function recomputeWithSelection() {
  const stopIds = currentStopIds.value
  if (stopIds.length < 2 || currentMode.value === 'loading') return
  // This path publishes on its own for an owned proposal — a pending
  // selection save would be a second write of the same state.
  cancelSelectionSave()
  const scrollY = window.scrollY
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
  // After the results are back on the page, not before — the offset means
  // nothing while the section is unmounted.
  await nextTick()
  window.scrollTo({ top: scrollY })
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

// Scroll the reader to the discussion when that is what they clicked. The
// section mounts only once the results are on the page, so a browser anchor
// would resolve against nothing — this waits for the gate above to open and
// fires once, leaving later navigation inside the page alone.
const discussionAnchor = ref<HTMLElement | null>(null)
let discussionFocused = false
watch(
  [() => props.focusSection, showCommentSection],
  async ([focus, ready]) => {
    if (focus !== 'comments' || !ready || discussionFocused) return
    discussionFocused = true
    await nextTick()
    discussionAnchor.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  },
  { immediate: true },
)

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
    nightSelection.value = { interval: committedNightInterval.value, pending: null }
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

// The moon pill: on shows the markers, off is the automatic night again.
function toggleNightMode() {
  nightMode.value = !nightMode.value
  if (!nightMode.value) nightSelection.value = { interval: null, pending: null }
}

// The night marker on a timetable row: two clicks place the night section,
// a click on either end of it takes it away (lib/nightInterval.ts).
function toggleNight(stopId: string) {
  nightSelection.value = toggleNightStop(nightSelection.value, stopId, currentStopIds.value)
}

type NightMark = 'pending' | 'end' | 'inside' | 'none'

function nightMark(stopId: string): NightMark {
  const { interval, pending } = nightSelection.value
  if (pending === stopId) return 'pending'
  if (interval && (interval[0] === stopId || interval[1] === stopId)) return 'end'
  return inNightInterval(interval, stopId, currentStopIds.value) ? 'inside' : 'none'
}

const nightEndNames = computed(() => {
  const interval = nightSelection.value.interval
  if (!interval) return null
  const byId = new Map(store.stops.map((st) => [st.stop_id, st.name]))
  return { a: byId.get(interval[0]) ?? interval[0], b: byId.get(interval[1]) ?? interval[1] }
})

// What each stop type means, for the icon beside the name and its hover
// text. "both" is a boarding-and-alighting stop the backend marks on a
// timetable that has no night on it at all.
const STOP_TYPE_ICON: Record<string, string> = {
  boarding: mdiWalk,
  night: mdiSleep,
  alighting: mdiExitRun,
  both: mdiSwapHorizontal,
}

function stopTypeHint(stopType: string | null): string {
  return stopType && stopType in STOP_TYPE_ICON ? t(`proposal.night.stopType.${stopType}`) : ''
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
  stopType: string | null
  nightIn: boolean
  nightOut: boolean
  slackIn: number
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
      stopType: st.stop_type,
      nightIn: st.night_in,
      nightOut: st.night_out,
      slackIn: st.slack_in,
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
    stopType: null,
    nightIn: false,
    nightOut: false,
    slackIn: 0,
  }))
})

// Whether the timetable on screen has a night on it at all — the legend
// below the table is only worth its line then.
const hasNightLeg = computed(() => viewRows.value.some((r) => r.nightOut))

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
  // Edit mode: the markers carry their stop id and may be removed from the map,
  // under the same floor as the table's delete control — two stops are a route,
  // one is not.
  const removable = currentMode.value === 'edit' && itinerary.value.length > 2
  return itinerary.value
    .filter((s) => s.selectedStop !== null)
    .map((s) => ({
      lat: s.selectedStop!.lat,
      lon: s.selectedStop!.lon,
      name: s.name,
      highlighted: true,
      stopId: s.selectedStop!.stop_id,
      removable,
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

// ...and removing from the map reuses removeStop(), so both routes into the
// itinerary go through one edit. The row is found by stop id rather than by
// marker order: mapStops drops rows that have no stop chosen yet, so an index
// into the markers is not an index into the itinerary.
function onMapRemoveStop(stopId: string): void {
  if (itinerary.value.length <= 2) return
  const index = itinerary.value.findIndex((s) => s.selectedStop?.stop_id === stopId)
  if (index >= 0) removeStop(index)
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

// --- The family's other corridors on the map -------------------------------
// Every other member's route, faded, under the one on screen — so a switch is
// something you can see before you make it. The document already carries all
// of them (one compact route per scenario × composition over a shared geometry
// pool), so this costs a lookup, not a request.
//
// Which corridor is "the one on screen" comes from the family member, not from
// rawRoute: a route loaded through GET /api/proposal/<id> carries per-trip
// geometry ids (`<trip>_L3`), while the document's pool is content-addressed
// (`g:<hash>`), and only the member's route_ref names the same thing in both
// worlds. No member, no alternatives — showing all of them would paint one
// straight over the route.
interface MapAlternative {
  key: string
  scenarioId: number
  compositionId: string
  label: string
  lines: [number, number][][]
}

const mapAlternatives = computed<MapAlternative[] | null>(() => {
  const doc = family.document.value
  const scenarioId = committedScenarioId.value
  const compositionId = committedCompId.value
  if (!doc || scenarioId === null || compositionId === null) return null
  if (currentMode.value !== 'display' || !showComputedView.value) return null
  const current = family.okMember(scenarioId, compositionId)
  if (!current) return null

  const axes = buildScenarioAxes(store.scenarios)
  return alternativeRoutes(doc, current.route_ref, compositionId)
    .map((alt) => {
      const state = axes.stateOf(alt.scenarioId)
      const scenario = [
        t('proposal.compare.axes.infra', { network: state?.network ?? '' }),
        state ? t(`proposal.compare.conditionsShort.${conditionLabelKey(state)}`) : null,
      ]
        .filter(Boolean)
        .join(' · ')
      return {
        key: alt.key,
        scenarioId: alt.scenarioId,
        compositionId: alt.compositionId,
        // The composition is only worth naming when it is not the one already
        // on screen — otherwise every label would end in the same id.
        label:
          alt.compositionId === compositionId ? scenario : `${scenario} · ${alt.compositionId}`,
        lines: alt.geometryIds
          .map((id) => (doc.geometries[id] ?? []) as [number, number][])
          .filter((coords) => coords.length > 1),
      }
    })
    .filter((alt) => alt.lines.length > 0)
})

// Clicking a faded corridor is the same switch the scenario switches and the
// comparison grid make: set the selection and let the watchers below serve the
// member from the family. applyPlan commits both, so whichever watcher runs
// second finds nothing left to do.
function onSelectAlternative(scenarioId: number, compositionId: string) {
  store.selectedScenarioId = scenarioId
  selectedCompositionId.value = compositionId
}

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
    // What the stored proposal carries, as opposed to what is on screen —
    // the two only diverge once the reader switches (lib/selectionSave.ts).
    savedCompositionId.value = selectedCompositionId.value
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
  // Leaving before the debounce elapsed drops the save rather than firing
  // it at an unmounted component: the selection is still in the draft, and
  // the next deliberate action saves it.
  cancelSelectionSave()
})

// An edited itinerary invalidates every member (they describe the previous
// route); the next evaluation builds a fresh family.
watch(isDirty, (dirty) => {
  if (!dirty) return
  family.reset()
  // An edited itinerary invalidates the pending save too: it would store
  // the previous route's member under stops the user has since changed.
  cancelSelectionSave()
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
  if (!plan) return
  // The timetable tools' state survives the switch: what the user has set
  // but not yet recomputed (a moved departure, add-ons, a night being
  // placed, a materialised night) is theirs, not the member's. applyPlan()
  // rebuilds the state from the family's request — the committed one — and
  // puts the itinerary back in outbound order, so both are captured first
  // and restored after, in the orientation the user was looking at. The
  // mirroring itself needs nothing: it is a rule in the request, and the
  // backend applies it to every member around the same 02:30.
  const pending = {
    expert: cloneExpert(expert.value),
    night: { ...nightSelection.value },
    nightMode: nightMode.value,
    direction: onScreenDirection.value,
  }
  // applyPlan does not publish here: the switch is applied from the family,
  // and what (if anything) needs storing is decided by the debounced save
  // below — a scenario switch stores nothing, a composition switch stores
  // the new selection once the user stops moving.
  applyPlan(plan, false, true)
  if (pending.direction === 1) swapDirection()
  expert.value = pending.expert
  nightSelection.value = pending.night
  nightMode.value = pending.nightMode
  scheduleSelectionSave()
}

watch(
  () => store.selectedScenarioId,
  (scenarioId) => {
    if (scenarioId === committedScenarioId.value) return
    applyMemberFromFamily(scenarioId, selectedCompositionId.value)
  },
)

// A proposal opened from a gallery that was being browsed on another
// scenario: the reader clicked THOSE figures, so present that member. It
// cannot happen before the family is there — a stored proposal loads on the
// base, which is what it is stored on — so this waits for the document and
// then moves the selection, which the watcher above turns into the switch.
// Read once: a later scenario switch is the reader's own.
watch(
  () => family.document.value,
  (document) => {
    const scenarioId = store.pendingScenarioId
    if (!document || scenarioId === null) return
    store.pendingScenarioId = null
    if (scenarioId !== store.selectedScenarioId) store.selectedScenarioId = scenarioId
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
      nightSelection.value = {
        interval: pruneNightInterval(draft!.nightIntervalIds, draft!.stopIds),
        pending: null,
      }
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

    <!-- Itinerary beside the map, stacked below `lg`. The two only coexist
         above about 900px — a max-w-sm itinerary column plus MapView's 480px
         minimum plus the gap — and below that the row used to overflow the
         page rather than wrap. -->
    <!-- Dimmed while stale like the results. When the timetable itself is
         what changed (expert edit, night moved), the Recalculate control sits over the itinerary column
         instead of over the results (it is where the edit was made, and
         must not need a scroll), so the column dims its own content under
         that scrim below and only the map dims here. -->
    <div
      v-else
      class="flex flex-col gap-6 transition-opacity duration-200 lg:flex-row"
      :class="paramsStale && !timetableChanged ? 'opacity-40' : ''"
    >
      <!-- Left panel: shrink-wrapped to its content's natural width (the
           itinerary text) rather than a fixed share of the row, so MapView
           gets whatever width is left over. Full width once stacked. -->
      <div class="flex w-full flex-col justify-center gap-12 lg:w-fit lg:shrink-0">
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
          <!-- What this band becomes: more than one trip pair, i.e. Y- and
               X-shaped routes. Above the itinerary because that is where the
               control will go. -->
          <TripPairComingSoon />

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

          <!-- Display / Loading mode table. A standalone v-if rather than
               the tail of the suggest block's chain, so it does not depend
               on what sits between the two. Same condition either way —
               suggest mode renders the table above, edit mode the one at
               the top. In expert mode the first departure is an input in
               the times column and the per-leg minutes a column of their
               own; the switches for both live with the direction switch
               below. -->
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
                    <!-- Expert mode: the first departure is typed here, in
                         the strip, rather than in a control of its own. The
                         toggles that say how it behaves (pinned/follows,
                         mirrored/own times) sit with the direction switch
                         below. -->
                    <input
                      v-if="expertMode && currentMode === 'display' && index === 0"
                      type="time"
                      step="60"
                      class="expert-time-input h-6 rounded-md border border-amber-300/40 bg-sapphire px-1 text-xs tabular-nums text-primary-50"
                      :value="currentDepartureClock"
                      :aria-label="t('proposal.expert.firstDeparture')"
                      @change="onDepartureInput"
                    />
                    <StopTime v-else :time="row.departure" :day="row.departureDay" />
                  </template>
                </div>
              </template>
            </Column>

            <!-- What the stop is on the clock — boarding, sleeping, alighting
                 — between its times and the band. With the fixed-night tool
                 on, the same icon is the click target that places the night:
                 blue ring = chosen end, faint blue = inside the section,
                 pulsing = one end picked, the other still to come. Blue is
                 the night's colour throughout: this icon, the band, the pill. -->
            <Column style="width: 2rem" :pt="{ bodyCell: { class: '!p-0' } }">
              <template #body="{ data: row }">
                <button
                  v-if="nightToolOn"
                  type="button"
                  class="flex h-7 w-7 cursor-pointer items-center justify-center rounded-full transition"
                  :class="{
                    'bg-sky-400/20 text-sky-300 ring-1 ring-sky-300/60':
                      nightMark(row.stopId) === 'end',
                    'text-sky-300/80': nightMark(row.stopId) === 'inside',
                    'animate-pulse bg-sky-400/20 text-sky-300': nightMark(row.stopId) === 'pending',
                    'text-primary-50/50 hover:text-primary-50': nightMark(row.stopId) === 'none',
                  }"
                  :aria-pressed="nightMark(row.stopId) !== 'none'"
                  :aria-label="t('proposal.night.markAria', { stop: row.name })"
                  @mouseenter="
                    showToolHint($event, t('proposal.night.markAria', { stop: row.name }))
                  "
                  @mouseleave="toolHint?.scheduleClose()"
                  @click="toggleNight(row.stopId)"
                >
                  <AppIcon :path="STOP_TYPE_ICON[row.stopType ?? 'both']" :size="16" />
                </button>
                <span
                  v-else-if="row.stopType && currentMode !== 'loading'"
                  class="flex items-center justify-center"
                  :class="
                    row.stopType === 'night' && !nightOnScreenStale
                      ? 'text-sky-300'
                      : 'text-primary-50/50'
                  "
                  :aria-label="stopTypeHint(row.stopType)"
                  role="img"
                  @mouseenter="showToolHint($event, stopTypeHint(row.stopType))"
                  @mouseleave="toolHint?.scheduleClose()"
                >
                  <AppIcon :path="STOP_TYPE_ICON[row.stopType]" :size="16" />
                </span>
              </template>
            </Column>

            <!-- Timeline. Two halves per row (leg arriving, leg leaving) so
                 the legs that run through 00:00–05:00 read as the night. -->
            <Column style="width: 2.5rem" :pt="{ bodyCell: { class: 'timeline-col !p-0' } }">
              <template #body="{ data: row, index }">
                <div class="absolute inset-0 flex items-center justify-center">
                  <div
                    v-if="index > 0"
                    class="absolute top-0 bottom-1/2 left-1/2 w-0.5 -translate-x-1/2"
                    :class="
                      row.nightIn && !nightOnScreenStale ? 'bg-sky-400/80' : 'bg-primary-50/30'
                    "
                  />
                  <div
                    v-if="index < viewRows.length - 1"
                    class="absolute top-1/2 bottom-0 left-1/2 w-0.5 -translate-x-1/2"
                    :class="
                      row.nightOut && !nightOnScreenStale ? 'bg-sky-400/80' : 'bg-primary-50/30'
                    "
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
                <div class="flex min-w-0 items-center gap-2 px-3 py-2">
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
                 rather than only enforced on submit. It shows the night
                 stretch too (blue), so where the fixed night put its minutes
                 is read in the same place as where the user put theirs.
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
                    :disabled="legExtra(row) === 0"
                    @click="stepLegExtra(row, -1)"
                  >
                    −
                  </button>
                  <input
                    type="number"
                    step="1"
                    class="expert-addon-input h-5 w-10 rounded border bg-sapphire px-1 text-right text-xs tabular-nums text-primary-50"
                    :class="
                      legAddon(row.prevStopId, row.stopId) > 0
                        ? 'border-amber-300/50 text-amber-200'
                        : legSlack(row) > 0
                          ? 'border-sky-400/50 text-sky-200'
                          : 'border-primary-50/20'
                    "
                    min="0"
                    :value="legExtra(row)"
                    :aria-label="legExtraHint(row)"
                    @mouseenter="showToolHint($event, legExtraHint(row))"
                    @mouseleave="toolHint?.scheduleClose()"
                    @change="onLegExtraInput(row, $event)"
                  />
                  <button
                    type="button"
                    class="h-5 w-5 shrink-0 cursor-pointer rounded border border-primary-50/20 text-xs leading-none text-primary-50 transition hover:bg-primary-50/15 disabled:cursor-not-allowed disabled:opacity-40"
                    :aria-label="t('proposal.expert.moreAria', { stop: row.name })"
                    @click="stepLegExtra(row, 1)"
                  >
                    +
                  </button>
                </div>
              </template>
            </Column>
          </DataTable>

          <!-- The night on this timetable, spelled out once: the blue legs
               are the 00:00–05:00 window and what the stop icons mean. With
               the fixed-night tool on, also where the night is being put. -->
          <div
            v-if="
              currentMode === 'display' && ((hasNightLeg && !nightOnScreenStale) || nightToolOn)
            "
            class="-mt-2 mb-4 flex flex-col gap-1 px-1 text-xs text-primary-50/50"
          >
            <p
              v-if="hasNightLeg && !nightOnScreenStale"
              class="flex flex-wrap items-center gap-x-3 gap-y-1"
            >
              <span class="flex items-center gap-1">
                <span class="inline-block h-0.5 w-4 bg-sky-400/80" />
                {{ t('proposal.night.legendNight') }}
              </span>
              <span class="flex items-center gap-1">
                <AppIcon :path="mdiWalk" :size="14" />
                {{ t('proposal.night.legendBoarding') }}
              </span>
              <span class="flex items-center gap-1 text-sky-300">
                <AppIcon :path="mdiSleep" :size="14" />
                {{ t('proposal.night.legendNightStop') }}
              </span>
              <span class="flex items-center gap-1">
                <AppIcon :path="mdiExitRun" :size="14" />
                {{ t('proposal.night.legendAlighting') }}
              </span>
            </p>
            <p
              v-if="nightToolOn"
              class="flex flex-wrap items-center gap-x-2 gap-y-1 text-primary-50/60"
            >
              <template v-if="nightSelection.pending">
                {{ t('proposal.night.pendingHint') }}
              </template>
              <template v-else-if="nightEndNames">
                {{ t('proposal.night.fixedHint', nightEndNames) }}
              </template>
              <template v-else>{{ t('proposal.night.autoHint') }}</template>
            </p>
          </div>

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
                @mouseenter="showToolHint($event, t('proposal.swapDirection'))"
                @mouseleave="toolHint?.scheduleClose()"
                @focus="showToolHint($event, t('proposal.swapDirection'))"
                @blur="toolHint?.scheduleClose()"
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

              <!-- Fixed night, one of expert mode's tools: on, each row's
                   stop icon picks the section the 00:00–05:00 window is
                   centred on; off is the automatic night. -->
              <button
                v-if="expertMode && currentMode === 'display'"
                :class="[toolPillClass, nightMode ? 'night-pill-on' : '']"
                :aria-pressed="nightMode"
                :aria-label="t('proposal.night.toggleAria')"
                @mouseenter="showToolHint($event, t('proposal.night.toggleAria'))"
                @mouseleave="toolHint?.scheduleClose()"
                @focus="showToolHint($event, t('proposal.night.toggleAria'))"
                @blur="toolHint?.scheduleClose()"
                @click="toggleNightMode"
              >
                <AppIcon :path="mdiWeatherNight" :size="16" />
              </button>

              <!-- Expert mode's two switches, icon-only, in the same pill as
                   the direction switch: pinned/follows for the first
                   departure typed into the strip above, mirrored/own times
                   for the opposite direction. Gold = on. A reset appears
                   once a departure is overridden. -->
              <template v-if="expertMode && currentMode === 'display'">
                <button
                  :class="[toolPillClass, pinnedDeparture ? 'expert-pill-on' : '']"
                  :aria-pressed="pinnedDeparture"
                  :aria-label="pinHintText"
                  @mouseenter="showToolHint($event, pinHintText)"
                  @mouseleave="toolHint?.scheduleClose()"
                  @focus="showToolHint($event, pinHintText)"
                  @blur="toolHint?.scheduleClose()"
                  @click="
                    setDepartureOverride(toggleDepartureMode(currentDeparture, autoDepartureMin))
                  "
                >
                  <AppIcon :path="pinnedDeparture ? mdiLock : mdiLockOpenVariant" :size="16" />
                </button>
                <button
                  :class="[toolPillClass, otherDirectionMirrors ? 'expert-pill-on' : '']"
                  :aria-pressed="otherDirectionMirrors"
                  :aria-label="mirrorHintText"
                  @mouseenter="showToolHint($event, mirrorHintText)"
                  @mouseleave="toolHint?.scheduleClose()"
                  @focus="showToolHint($event, mirrorHintText)"
                  @blur="toolHint?.scheduleClose()"
                  @click="setMirrored(!otherDirectionMirrors)"
                >
                  <AppIcon
                    :path="otherDirectionMirrors ? mdiMirror : mdiArrowLeftRight"
                    :size="16"
                  />
                </button>
                <button
                  v-if="currentDeparture !== null"
                  :class="toolPillClass"
                  :aria-label="t('proposal.expert.reset')"
                  @mouseenter="showToolHint($event, t('proposal.expert.reset'))"
                  @mouseleave="toolHint?.scheduleClose()"
                  @focus="showToolHint($event, t('proposal.expert.reset'))"
                  @blur="toolHint?.scheduleClose()"
                  @click="setDepartureOverride(null)"
                >
                  <AppIcon :path="mdiRestore" :size="16" />
                </button>
              </template>
            </div>

            <InfoPopover ref="toolHint">
              <p class="w-72 text-sm text-primary-50/75">{{ toolHintText }}</p>
            </InfoPopover>

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
               reads as a titled panel rather than three loose pills.
               While the timetable's own inputs (expert edits, the night)
               have changed, this panel is what greys out and carries the
               Recalculate control — the timetable above stays fully live so
               several things can be adjusted before one recompute. -->
          <div v-if="currentMode === 'display' && routeStatRows.length > 0" class="relative mt-8">
            <div
              class="flex flex-col items-center gap-2 rounded-xl bg-primary-50/5 px-4 py-3 text-primary-50/70 transition-opacity duration-200"
              :class="paramsStale && timetableChanged ? 'opacity-30' : ''"
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

            <!-- Stale timetable (expert edit or night moved): the recompute
                 control, over the route stats — the one place it is needed,
                 with nothing to scroll to and nothing blocked. The results
                 below only grey out (their own control is suppressed, see
                 ProposalResults props). -->
            <button
              v-if="paramsStale && timetableChanged"
              type="button"
              class="absolute inset-0 flex cursor-pointer items-center justify-center rounded-xl"
              @click="recomputeWithSelection"
            >
              <span
                class="flex items-center gap-2 rounded-full bg-primary-500 px-6 py-2 text-md font-semibold text-white shadow-lg transition hover:bg-primary-600"
              >
                {{ t('proposal.recalculate') }}
                <span aria-hidden="true">→</span>
              </span>
            </button>
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
        <!-- Sticky only in the two-column layout: stacked, the map is a block
             the page scrolls past like any other, and pinning it would park it
             over the results below. -->
        <div
          class="relative isolate h-full overflow-hidden rounded-xl border border-primary-50/10 transition-opacity duration-200 lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)]"
          :class="paramsStale && timetableChanged ? 'opacity-60' : ''"
          style="clip-path: inset(0 round 0.75rem)"
        >
          <MapView
            :stops="mapStops"
            :shape="mapShape"
            :segments="mapSegments"
            :suggested="mapSuggested"
            :available="mapAvailable"
            :alternatives="mapAlternatives"
            class="w-full h-full"
            @toggle-suggested="toggleSuggested"
            @add-stop="onMapAddStop"
            @remove-stop="onMapRemoveStop"
            @select-alternative="onSelectAlternative"
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
            v-if="loadingScrimVisible"
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
                   watching", and the copy avoids claiming otherwise. Shown
                   only while there is something to cancel: the scrim may
                   outlive the calc by up to LOADING_SCRIM_MIN_MS, and
                   cancelCalc() would drop fresh results back to edit mode. -->
              <button
                v-if="currentMode === 'loading'"
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
        :params-stale="paramsStale && !timetableChanged"
        :dimmed="isDirty || (paramsStale && timetableChanged)"
        :schedule-mode="(publishRequest?.schedule_mode as string | undefined) ?? null"
        :committed-request="publishRequest"
        :cycle-distance-km="cycleDistanceKm"
        :longest-od="exampleOdPairs.longest"
        :shortest-od="exampleOdPairs.shortest"
        @select-composition="(id) => (selectedCompositionId = id)"
        @recalculate="recomputeWithSelection"
        @scope-change="onScopeChange"
        @retry-family="retryFamily"
      >
        <template #discussion>
          <div
            v-if="storedProposalId !== null && showCommentSection"
            id="comments"
            ref="discussionAnchor"
            class="w-full scroll-mt-6"
          >
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
   chose" (ProposalResults' scenario card). */
.expert-pill-on {
  border-color: color-mix(in srgb, #fbbf24 45%, transparent);
  background: color-mix(in srgb, #fbbf24 14%, transparent);
  color: #fde68a;
}
/* Fixed-night tool on: the night's blue, as on the band and the stop icons. */
.night-pill-on {
  border-color: color-mix(in srgb, #38bdf8 45%, transparent);
  background: color-mix(in srgb, #38bdf8 14%, transparent);
  color: #bae6fd;
}
/* The strip's departure input: no picker icon, it does not fit a 6-rem
   column and the value is typed anyway. */
.expert-time-input::-webkit-calendar-picker-indicator {
  display: none;
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
