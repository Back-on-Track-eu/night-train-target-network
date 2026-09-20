<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, onActivated, onDeactivated, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import {
  mdiAccountOutline,
  mdiArrowLeftRight,
  mdiMapMarkerOutline,
  mdiEarth,
  mdiFlagOutline,
  mdiMagnify,
  mdiPlus,
  mdiSortAscending,
  mdiSortDescending,
} from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import LandingIntro from '@/components/LandingIntro.vue'
import StopSelect from '@/components/StopSelect.vue'
import CountrySelect from '@/components/CountrySelect.vue'
import SearchField from '@/components/SearchField.vue'
import ProposalCard from '@/components/ProposalCard.vue'
import GalleryScenarioPanel from '@/components/GalleryScenarioPanel.vue'
import GalleryMap from '@/components/GalleryMap.vue'
import { useStore } from '@/stores/store'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { fetchProposals } from '@/lib/proposalsApi'
import { createAbortSlot } from '@/lib/apiClient'
import { ctaButtonClass } from '@/lib/ctaButtonClass'
import { selectPillPt } from '@/lib/selectPillPt'
import { asApiFailure, isRetryable, type ApiFailure } from '@/lib/apiError'
import { buildRelationToken, type GalleryRowRef } from '@/lib/galleryMap'
import { useApiFailure } from '@/composables/useApiFailure'
import {
  seedToQuery,
  seedFromQuery,
  queryString,
  type GallerySearchMode,
  type GallerySearchSeed,
} from '@/lib/proposalPrefill'
import {
  PROPOSAL_SORT_KEYS,
  SHARED_SORT_KEYS,
  type Stop,
  type ProposalSummary,
  type ProposalsRequest,
  type ProposalsFilter,
  type ProposalsSection,
  type ProposalSort,
  type ProposalSortKey,
  type ProposalSourceKind,
  type MapLinesSection,
  type MapRouteFeature,
} from '@/types/api'

const { t } = useI18n()
const store = useStore()
const { countryName } = useLocaleFormat()
const route = useRoute()
const router = useRouter()
const { describe, report } = useApiFailure()

const LIMIT = 20

// The list page and the whole map come from ONE request: the map sections are
// computed from the same filters but ignore limit/offset, so they cover the
// entire result set and only need to ride the first page of a query. Appends
// therefore ask for summaries alone.
// map_lines aggregates the WHOLE filtered set, so it rides the first page only.
// map_routes is the one section that follows limit/offset — it carries the route
// behind each listed card, so every append brings its own page's worth and the
// client accumulates them.
const FIRST_PAGE_SECTIONS: ProposalsSection[] = ['summaries', 'map_lines', 'map_routes']
const APPEND_SECTIONS: ProposalsSection[] = ['summaries', 'map_routes']

const mode = ref<GallerySearchMode>('aToB')

// Search inputs (kept per-mode; buildFilter() only reads the active mode's).
const fromStop = ref<Stop | null>(null)
const toStop = ref<Stop | null>(null)
const stationStop = ref<Stop | null>(null)
const countryCode = ref<string | null>(null)
// byRelation's two country selects, in pick order.
const relationFrom = ref<string | null>(null)
const relationTo = ref<string | null>(null)

// Current search-bar state, handed to "Suggest a new route" so the new
// proposal's itinerary can be prefilled from whatever the user was searching
// for instead of two arbitrary stops.
const searchSeed = computed<GallerySearchSeed>(() => ({
  mode: mode.value,
  fromStop: fromStop.value,
  toStop: toStop.value,
  stationStop: stationStop.value,
  countryCode: countryCode.value,
  relationFrom: relationFrom.value,
  relationTo: relationTo.value,
}))

// Stops the active search targeted — handed to each card so it can pin the
// matched stop(s) as itinerary anchors. Empty for by-country search.
const highlightStopIds = computed(() => {
  if (mode.value === 'aToB') {
    return [fromStop.value?.stop_id, toStop.value?.stop_id].filter((id): id is string => !!id)
  }
  if (mode.value === 'byStation') {
    return stationStop.value ? [stationStop.value.stop_id] : []
  }
  return []
})

// Sort as a field + direction. These stay the source of truth (the URL sync and
// the request body are both field+direction); the single Select below drives
// them through one combined "field:dir" value.
//
// Distance-desc is the default because it is the only sortable column BOTH
// gallery sources carry a real value for — CO₂ savings is NULL on every
// existing (ONTD) row, so defaulting to it would open the gallery on a page of
// the handful of evaluated proposals with the whole catalogue sorted behind
// them by NULLS LAST.
const sortField = ref<ProposalSortKey>('total_distance_km')
const sortDir = ref<'asc' | 'desc'>('desc')

// The map, which arrives with the list in the SAME response — no per-proposal
// geometry fetch anywhere.
//
// `corridors` is the overview: the whole filtered set aggregated into one
// feature per stop-pair corridor, carrying how many proposals and how many real
// ONTD trains use it. `routeFeatures` is the per-card layer, one already-
// simplified polyline per LISTED row, accumulated as pages load — which is what
// keeps it a fixed cost per page however many proposals exist.
const corridors = ref<MapLinesSection | null>(null)
const routeFeatures = ref<MapRouteFeature[]>([])

// Result list (accumulated across pages) + pagination bookkeeping.
const proposals = ref<ProposalSummary[]>([])
const total = ref(0)
// The count the result label shows. Separate from `total` (which pagination
// resets to 0 on every new query) so hitting search keeps the previous number
// on screen until the new one arrives, instead of blinking out and back.
const shownTotal = ref<number | null>(null)
const offset = ref(0)
const loading = ref(false)
const initialized = ref(false)
const failure = ref<ApiFailure | null>(null)
const failureMsg = ref<string | null>(null)
const sentinel = ref<HTMLElement | null>(null)

// One list query in flight at a time, newest wins: a filter change during a
// slow load supersedes it instead of being dropped on the floor (which is what
// the old `if (loading) return` guard did to it).
const listSlot = createAbortSlot()
// Belt and braces on top of the abort: only the newest request may write to
// proposals/offset/total, so a late loser can never reorder the list.
let requestSeq = 0

const tabs = computed(() => [
  {
    value: 'aToB' as const,
    label: t('gallery.tabs.aToB'),
    icon: mdiArrowLeftRight,
  },
  {
    value: 'byStation' as const,
    label: t('gallery.tabs.byStation'),
    icon: mdiMapMarkerOutline,
  },
  {
    value: 'byCountry' as const,
    label: t('gallery.tabs.byCountry'),
    icon: mdiEarth,
  },
  {
    value: 'byRelation' as const,
    label: t('gallery.tabs.byRelation'),
    icon: mdiFlagOutline,
  },
])

// "Only mine": the same list narrowed to the signed-in account's own rows,
// via the backend's `user_ids` filter. Existing (ONTD) rows carry no user_id,
// so this is a proposals-only view by construction — hence the source switch
// below drops the toggle whenever it is showing existing trains alone.
const mineOnly = ref(false)
// Guests get a user_id too, and their proposals are theirs until the session is
// merged into an account — so the switch works for any identity, not for
// registered users only. Signed out there is nothing to filter by, so the
// "mine" half asks for an identity instead of filtering.
const canFilterMine = computed(() => store.userId !== null)

// The two halves of the ownership switch, as one pair of class strings rather
// than a literal in each button.
const activeOwnerClass = 'bg-primary-50/15 text-primary-50 font-semibold'
const inactiveOwnerClass = 'text-primary-50/60 hover:text-primary-50'

function selectMine(): void {
  if (!canFilterMine.value) {
    // No identity yet: the filter is meaningless until there is one, so the
    // click opens the same modal the rest of the app gates on.
    store.openAuthModal({ context: 'standalone' })
    return
  }
  // Existing (ONTD) rows have no owner, so "mine" and "existing only" cannot
  // both hold — move the source switch rather than filtering to an empty list
  // behind a dropdown that still says "Existing".
  if (sourceFilter.value === 'existing') sourceFilter.value = 'proposal'
  mineOnly.value = true
}

// --- The scenario the gallery is read on -----------------------------------
// Every proposal is stored once per scenario variant (backend §5.4a), and
// the request reads one of those projections: figures, sort order, the
// per-card geometry and the corridor map all follow the chosen scenario.
// Existing (ONTD) trains are scenario-independent and unaffected.
//
// Null until the scenarios load; the store then holds the base. Kept here
// rather than in store.selectedScenarioId, which is the BUILDER's selection
// — a reader browsing the gallery on Infra 2032 must not move the scenario
// the builder would open with (openProposal below hands it over on purpose,
// which is a different thing from sharing one ref).
const galleryScenarioId = ref<number | null>(null)
watch(
  () => store.scenarios,
  (scenarios) => {
    if (galleryScenarioId.value !== null || scenarios.length === 0) return
    galleryScenarioId.value =
      scenarios.find((s) => s.is_current_base)?.scenario_id ?? scenarios[0].scenario_id
  },
  { immediate: true },
)

const galleryScenario = computed(
  () => store.scenarios.find((s) => s.scenario_id === galleryScenarioId.value) ?? null,
)

// The id the request carries — only when the reader has moved OFF the base,
// so the base view stays exactly the pre-§5.4a request. Either way the
// result set is the same: the backend joins the scenario's figures onto the
// base projection rather than reading a different table, so a filter
// returns the same proposals on every scenario.
const scenarioVariantId = computed<number | null>(() => {
  if (galleryScenario.value === null || galleryScenario.value.is_current_base) return null
  return store.variantFor(galleryScenario.value.scenario_id)?.scenario_variant_id ?? null
})

// Which source(s) the list shows. 'all' sends no `sources` key at all, which
// the backend reads as both.
type SourceChoice = 'all' | ProposalSourceKind
const sourceFilter = ref<SourceChoice>('all')
const SOURCE_CHOICES: readonly SourceChoice[] = ['all', 'proposal', 'existing']
const sourceOptions = computed(() =>
  SOURCE_CHOICES.map((value) => ({
    value,
    label: t(`gallery.source.${value}`),
  })),
)

// Sort is presented as field-in-words × direction-as-icon ("Distance" + the mdi
// sort-descending glyph), so the option list is the cross product of these two.
// The icon is aria-hidden (AppIcon always is), hence the sr-only direction name
// rendered next to it in the template.
//
// Everything outside SHARED_SORT_KEYS (imported from types/api) is NULL on every
// existing (ONTD) row, so those options are hidden while viewing ONTD only —
// see sortOptions and the sourceFilter watcher below.
const SORT_FIELDS: readonly { field: ProposalSortKey; key: string }[] = [
  { field: 'total_distance_km', key: 'distance' },
  { field: 'n_stops', key: 'stops' },
  { field: 'co2_savings_t_per_year', key: 'co2' },
  { field: 'likes_count', key: 'likes' },
  { field: 'comments_count', key: 'comments' },
  { field: 'created_at', key: 'created' },
  { field: 'updated_at', key: 'updated' },
]
const SORT_DIRS: readonly { dir: 'asc' | 'desc'; icon: string }[] = [
  { dir: 'desc', icon: mdiSortDescending },
  { dir: 'asc', icon: mdiSortAscending },
]

const sortOptions = computed(() =>
  SORT_FIELDS.filter(
    (f) => sourceFilter.value !== 'existing' || SHARED_SORT_KEYS.includes(f.field),
  ).flatMap((f) =>
    SORT_DIRS.map((d) => ({
      value: `${f.field}:${d.dir}`,
      label: t(`gallery.sort.${f.key}`),
      icon: d.icon,
      dirLabel: t(`gallery.sort.dir.${d.dir}`),
    })),
  ),
)

// The Select's single value, projected onto the field/direction pair the rest of
// the component (request body, URL sync) is built around. Both refs are written
// in one tick, so the watcher below still fires exactly once.
const sortSelection = computed<string>({
  get: () => `${sortField.value}:${sortDir.value}`,
  set: (value) => {
    const [by, dir] = value.split(':')
    sortField.value = by as ProposalSortKey
    sortDir.value = dir === 'asc' ? 'asc' : 'desc'
  },
})

// The closed Select renders through its #value slot, which only receives the
// model value — this resolves it back to the option (label + icon) to draw.
const selectedSortOption = computed(
  () => sortOptions.value.find((o) => o.value === sortSelection.value) ?? null,
)

// Switching to ONTD-only while sorted by a proposal-only column would leave the
// Select showing an option that is no longer offered — fall back to distance.
// The same switch drops "only mine", which is meaningless on rows nobody owns.
watch(sourceFilter, (choice) => {
  if (choice !== 'existing') return
  if (!SHARED_SORT_KEYS.includes(sortField.value)) sortField.value = 'total_distance_km'
  mineOnly.value = false
})

// Signing out mid-session leaves nothing to filter by, so the switch releases
// itself — otherwise the list stays narrowed to an account with no way back.
watch(canFilterMine, (can) => {
  if (!can) mineOnly.value = false
})

// Who is signed in is part of what the list SAYS, not just of what it filters:
// signing in merges the guest session into the account, so proposals published
// as a guest change hands and their "proposed by" line with them. The loaded
// page would otherwise keep showing the old proposer until something else
// forced a reload.
watch(
  () => [store.userId, store.username],
  () => {
    if (hydrating) return
    // Signing in usually happens somewhere else in the app while this page sits
    // in its keep-alive cache — firing a request at a page nobody is looking at
    // is the same waste the deactivate teardown exists to avoid, so hand it to
    // the staleness flag onActivated already honours.
    if (!isActive.value) {
      store.galleryStale = true
      return
    }
    resetAndLoad()
  },
)

// Country codes present in the loaded stops, resolved to full names in the
// active locale (unknown codes fall back to the raw code).
const countryOptions = computed(() =>
  [...new Set(store.stops.map((s) => s.country_code))]
    .map((code) => ({ code, name: countryName(code) }))
    .sort((a, b) => a.name.localeCompare(b.name)),
)
const selectedCountryName = computed(() =>
  countryCode.value ? countryName(countryCode.value) : null,
)
const selectedRelationFromName = computed(() =>
  relationFrom.value ? countryName(relationFrom.value) : null,
)
const selectedRelationToName = computed(() =>
  relationTo.value ? countryName(relationTo.value) : null,
)
// The stored "AT__DE" token, or null while the pair is incomplete or identical.
const relationToken = computed(() => buildRelationToken(relationFrom.value, relationTo.value))

const currentSort = computed<ProposalSort>(() => ({
  by: sortField.value,
  dir: sortDir.value,
}))

const reachedEnd = computed(() => initialized.value && proposals.value.length >= total.value)

// Map the active search mode + inputs to a backend filter.
//
// "From A to B" with both fields filled asks for containment (mode 'all'), so a
// result must touch BOTH stops rather than either — the array filters default to
// overlap ('any'), which used to make this an approximation. It is still not a
// strict A→B connection: the backend has no ordering predicate, so a route
// serving B before A matches too.
function buildFilter(): ProposalsFilter | undefined {
  const base: ProposalsFilter = {}
  // Omitting `sources` means BOTH on the backend, so only send it when the
  // user has narrowed the list. ['proposal'] compiles to a query that never
  // touches the ontd schema at all.
  if (sourceFilter.value !== 'all') base.sources = [sourceFilter.value]

  // Own proposals only. `sources` is pinned alongside it because an existing
  // row's NULL user_id would drop out of the result anyway — saying so up
  // front keeps the query off the ontd schema instead of joining it to filter
  // it away again.
  if (mineOnly.value && store.userId !== null) {
    base.user_ids = [store.userId]
    base.sources = ['proposal']
  }

  if (mode.value === 'aToB') {
    const ids = [fromStop.value?.stop_id, toStop.value?.stop_id].filter((id): id is string =>
      Boolean(id),
    )
    // One stop filled is a by-station search in disguise — 'all' over a single
    // value is the same query as 'any', so send the plain list.
    if (ids.length > 1) base.stop_ids = { values: ids, mode: 'all' }
    else if (ids.length) base.stop_ids = ids
  } else if (mode.value === 'byStation') {
    if (stationStop.value) base.stop_ids = [stationStop.value.stop_id]
  } else if (mode.value === 'byRelation') {
    if (relationToken.value) base.country_relations = [relationToken.value]
  } else if (countryCode.value) {
    base.countries = [countryCode.value]
  }

  return Object.keys(base).length ? base : undefined
}

async function loadPage(): Promise<void> {
  loading.value = true
  failure.value = null
  failureMsg.value = null
  const requestOffset = offset.value
  const isFirstPage = requestOffset === 0
  const seq = ++requestSeq
  const signal = listSlot.begin()
  try {
    const body: ProposalsRequest = {
      sort: [currentSort.value],
      limit: LIMIT,
      offset: requestOffset,
      include: isFirstPage ? FIRST_PAGE_SECTIONS : APPEND_SECTIONS,
    }
    const filter = buildFilter()
    if (filter) body.filter = filter
    if (scenarioVariantId.value !== null) body.scenario_variant_id = scenarioVariantId.value

    const res = await fetchProposals(body, signal)
    if (seq !== requestSeq) return
    const summaries = res.summaries ?? { total: 0, proposals: [] }
    proposals.value = isFirstPage
      ? summaries.proposals
      : [...proposals.value, ...summaries.proposals]
    total.value = summaries.total
    shownTotal.value = summaries.total
    offset.value = requestOffset + summaries.proposals.length
    // The corridor overview already covers the whole filtered set, so only the
    // first page carries it; the per-card routes arrive one page at a time.
    if (isFirstPage) corridors.value = res.map_lines ?? null
    const newRoutes = res.map_routes?.features ?? []
    routeFeatures.value = isFirstPage ? newRoutes : [...routeFeatures.value, ...newRoutes]
    initialized.value = true
  } catch (err) {
    // A superseded request is not a failure — say nothing and let the winner
    // own the loading state.
    const f = asApiFailure(err)
    if (f?.kind === 'canceled' || seq !== requestSeq) return
    failure.value = f
    failureMsg.value = describe(err, 'errors.proposalsLoadFailed')
    report(err, { fallbackKey: 'errors.proposalsLoadFailed', force: 'inline' })
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

// A filter/sort change starts a fresh query from offset 0. Deliberately NOT
// guarded on `loading`: the point is to replace whatever is in flight.
//
// Just as deliberately, this does NOT empty the list, the map or the count
// first. Doing so collapsed the page to a three-card skeleton, the document
// shrank, and the browser clamped the scroll position to the new maximum — so
// changing the sort order or the search mode threw the reader back to the top
// of the page. loadPage() swaps all of it at once when the response lands,
// which is the same reasoning `shownTotal` already applies to the result count.
function resetAndLoad(): void {
  offset.value = 0
  loadPage()
}

function retryLoad(): void {
  // Retrying a first page is a reset; retrying a later page resumes it.
  if (offset.value === 0) resetAndLoad()
  else loadPage()
}

// Appending the same page twice IS a bug, so pagination keeps its guard —
// unlike resetAndLoad, which means to supersede.
function onSentinel(): void {
  if (loading.value || !initialized.value || reachedEnd.value || failure.value) return
  loadPage()
}

// How many of the loaded rows the chosen scenario has no figures for — not
// evaluable on that network, or not yet backfilled. They stay in the list
// (a scenario changes what a card says, never which cards a filter returns —
// the backend guarantees the same result set on every scenario); the card
// itself says why it has no figures, and the panel header carries the count.
const withoutFigures = computed(
  () => proposals.value.filter((p) => p.source === 'proposal' && p.status !== 'ok').length,
)

// Row identity for :key. Existing (ONTD) rows have no proposal id; proposals are
// versioned, so the version is part of the key.
const proposalKey = (p: ProposalSummary): string =>
  p.source === 'existing' ? `e-${p.route_id}` : `p-${p.proposal_id}-${p.proposal_version}`

// The same row as map_routes identifies it. Version-free: a route feature
// carries proposal_id, and a row's geometry does not change within a page.
const rowRefOf = (p: ProposalSummary): GalleryRowRef =>
  p.source === 'existing'
    ? { kind: 'existing', id: p.route_id }
    : { kind: 'proposal', id: p.proposal_id }

// Whether this (kept-alive) page is the one on screen — see the identity
// watcher below and the deactivate teardown.
const isActive = ref(true)

// Set while a card is hovered; the map isolates and frames that row's route.
// One direction only — the map itself has no hover, because a corridor is
// shared by many rows and so names no single card.
const hoveredRow = ref<GalleryRowRef | null>(null)

// LandingIntro's secondary call to action. The target lives here rather than in
// the intro because the intro has no business knowing what follows it.
const gallerySection = ref<HTMLElement | null>(null)
// Breathing room above the heading; landing flush against the viewport edge
// reads as a cut-off page.
const GALLERY_SCROLL_MARGIN_PX = 24

function scrollToGallery(): void {
  const target = gallerySection.value
  if (!target) return
  const top = target.getBoundingClientRect().top + window.scrollY
  window.scrollTo({ top: top - GALLERY_SCROLL_MARGIN_PX, behavior: 'smooth' })
}

// --- Fitting the whole gallery into one screen ------------------------------
// The results row — card column AND map — is exactly one viewport tall minus
// the gallery's own chrome (heading, tabs, search pill, gutters). Two things
// follow from that, and both are the point:
//
//   * the search bar stays on screen beside the map at 100% zoom, so changing a
//     filter and seeing the result costs no scrolling;
//   * the two columns are the same height, so the card column ends at the map's
//     bottom edge instead of running past it. The cards scroll INSIDE their
//     column (cardScroller below) rather than scrolling the page.
//
// Measured, not hardcoded: the heading wraps at narrow widths and the search
// pill changes height with the active mode, so the chrome is not a constant.
const resultsRow = ref<HTMLElement | null>(null)
const cardScroller = ref<HTMLElement | null>(null)
// Floor for short windows. Sized so the column still holds about three cards;
// below this the row stops shrinking and the page scrolls a little instead.
const ROW_MIN_HEIGHT_PX = 560
const rowHeight = ref(`calc(100vh - ${2 * GALLERY_SCROLL_MARGIN_PX}px)`)

function measureRow(): void {
  const section = gallerySection.value
  const row = resultsRow.value
  if (!section || !row) return
  // Everything between the top of the gallery block and the top of the results
  // row, plus one gutter above the heading and one below the row.
  const chrome = row.getBoundingClientRect().top - section.getBoundingClientRect().top
  const reserved = Math.round(chrome) + 2 * GALLERY_SCROLL_MARGIN_PX
  rowHeight.value = `max(${ROW_MIN_HEIGHT_PX}px, calc(100vh - ${reserved}px))`
}

// --- URL <-> search-bar sync -------------------------------------------
// Reflects the whole search bar (filters + sort) in /gallery's query string
// so results are shareable, reload-safe, and back/forward-navigable.
// Suppressed during the initial hydration in onMounted below — otherwise
// each ref assignment there would fire its own resetAndLoad()/router.replace
// before the async stop-id resolution finishes, flashing unfiltered results.
let hydrating = true

function currentSearchQuery(): LocationQueryRaw {
  const query: LocationQueryRaw = {
    ...seedToQuery(searchSeed.value),
    sort: sortField.value,
    dir: sortDir.value,
  }
  // Only when on: an absent key is the default, and a shared link should not
  // carry a filter that resolves against whoever opens it.
  if (mineOnly.value) query.mine = '1'
  // The SCENARIO, not the variant: the variant ids are materialised and can
  // be rebuilt, the scenario is what a shared link should still mean.
  if (galleryScenario.value && !galleryScenario.value.is_current_base) {
    query.scenario = String(galleryScenario.value.scenario_id)
  }
  return query
}

watch(
  [
    mode,
    fromStop,
    toStop,
    stationStop,
    countryCode,
    relationFrom,
    relationTo,
    sortField,
    sortDir,
    sourceFilter,
    mineOnly,
    galleryScenarioId,
  ],
  () => {
    if (hydrating) return
    resetAndLoad()
    router.replace({ query: currentSearchQuery() })
  },
)

// Navigate to a saved proposal's detail route (ProposalCard's @select, only
// fired for source==='proposal' rows — see ProposalCard.vue).
function openProposal(proposalId: number): void {
  handOverScenario()
  router.push({ name: 'proposal', params: { id: proposalId } })
}

// A reader who browsed the gallery on another scenario opened THAT train's
// figures, so the proposal view should present the same member once its
// family is there. Off-URL via the store, like the builder's prefill seed:
// a stored proposal always loads on the base first (it is stored on the
// base), and the viewport switches when the family arrives.
function handOverScenario(): void {
  store.pendingScenarioId =
    galleryScenario.value && !galleryScenario.value.is_current_base
      ? galleryScenario.value.scenario_id
      : null
}

// The card's comment count opens the same proposal AT its discussion. The hash
// is the whole instruction: ProposalWorkspace reads it and ProposalViewport
// scrolls there once the thread is on the page (the discussion only mounts
// after the results do, so a plain browser anchor would fire too early).
function openDiscussion(proposalId: number): void {
  handOverScenario()
  router.push({ name: 'proposal', params: { id: proposalId }, hash: '#comments' })
}

// "Suggest a new route" — hand the current search bar to the builder route as
// its prefill seed, off-URL via the store (see pendingProposalSeed) so it
// doesn't show up in /proposal-builder's address bar.
function createProposal(): void {
  store.pendingProposalSeed = searchSeed.value
  router.push({ name: 'proposal-builder' })
}

let observer: IntersectionObserver | null = null
// Watches the whole document, like LandingIntro's own band: what changes the
// chrome above the results row is mostly elements ABOVE the gallery (the
// header image loading, the API status banner appearing), which an observer on
// the row itself would never see.
let chromeObserver: ResizeObserver | null = null

onMounted(async () => {
  // The list scrolls inside its own column now, so the sentinel is watched
  // against that box rather than the viewport — against the viewport it would
  // either never intersect or (worse) intersect permanently.
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) onSentinel()
    },
    { root: cardScroller.value, rootMargin: '300px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)

  // Hydrate the search bar from the URL before the first query fires, so a
  // shared or reloaded /gallery?... link reproduces the exact same results.
  const hasStopParams = ['from', 'to', 'station'].some((k) => queryString(route.query[k]))
  if (hasStopParams && store.stopsStatus !== 'success') await store.fetchStops()
  const seed = seedFromQuery(route.query, store.stops)
  mode.value = seed.mode
  fromStop.value = seed.fromStop
  toStop.value = seed.toStop
  stationStop.value = seed.stationStop
  countryCode.value = seed.countryCode
  relationFrom.value = seed.relationFrom
  relationTo.value = seed.relationTo
  const sortParam = queryString(route.query.sort)
  if (sortParam && (PROPOSAL_SORT_KEYS as readonly string[]).includes(sortParam)) {
    sortField.value = sortParam as ProposalSortKey
  }
  const dirParam = queryString(route.query.dir)
  if (dirParam === 'asc' || dirParam === 'desc') sortDir.value = dirParam
  // Resolves against whoever is signed in now — the account is deliberately
  // not part of the link.
  mineOnly.value = queryString(route.query.mine) === '1' && canFilterMine.value
  const scenarioParam = Number(queryString(route.query.scenario))
  if (
    Number.isInteger(scenarioParam) &&
    store.scenarios.some((s) => s.scenario_id === scenarioParam)
  ) {
    galleryScenarioId.value = scenarioParam
  }

  hydrating = false
  resetAndLoad()
  router.replace({ query: currentSearchQuery() })

  measureRow()
  chromeObserver = new ResizeObserver(measureRow)
  chromeObserver.observe(document.body)
  window.addEventListener('resize', measureRow)
})
// This component is kept alive (App.vue), so leaving the gallery deactivates it
// instead of unmounting it. Cancelling in flight requests is right in BOTH
// cases — nobody is looking at the result any more — so the teardown is shared.
function teardown(): void {
  isActive.value = false
  observer?.disconnect()
  chromeObserver?.disconnect()
  chromeObserver = null
  window.removeEventListener('resize', measureRow)
  // Drop everything in flight; their rejections are 'canceled' and stay silent.
  listSlot.cancel()
}
onBeforeUnmount(teardown)
onDeactivated(teardown)

// Coming back to a cached gallery. Deliberately does NOT re-run onMounted's
// hydrate-and-load: the whole point is that a there-and-back trip costs zero
// requests. Only a proposal published in the meantime forces a refresh.
onActivated(() => {
  isActive.value = true
  if (sentinel.value && observer) observer.observe(sentinel.value)
  // The layout above can have changed while the gallery was cached, and the
  // teardown dropped both listeners — re-measure and re-attach them.
  measureRow()
  chromeObserver = new ResizeObserver(measureRow)
  chromeObserver.observe(document.body)
  window.addEventListener('resize', measureRow)
  if (store.galleryStale) {
    store.galleryStale = false
    resetAndLoad()
  }
})
</script>

<template>
  <!-- -mb-6 trims App.vue's py-12 page padding to the 24px gutter the row's
       height budget assumes below it (measureRow), so the gallery ends exactly
       one screen after its heading. Keep the two in sync: if App.vue's bottom
       padding changes, this offset has to change with it. -->
  <div class="-mb-6 flex w-full max-w-6xl flex-col gap-4">
    <!-- Landing pitch: one viewport-filling opening band, the statement beside
         the argument and the four ways onward. Self-contained — it owns its own
         sizing and h1 (App.vue's centred heading steps aside for this route);
         the longer story lives at /docs/. -->
    <LandingIntro @create="createProposal" @browse="scrollToGallery" />

    <!-- The gallery proper: search bar, then the list + map. The rule and the
         padding are what separate it from the landing pitch above — without
         them the two read as one continuous column. Kept deliberately tight:
         every pixel here comes off the map's height budget (see measureRow),
         and the pitch above has already introduced the page. -->
    <div
      ref="gallerySection"
      class="mt-2 flex w-full flex-wrap items-baseline justify-center gap-x-3 border-t border-primary-50/10 pt-6"
    >
      <h2 class="text-2xl font-light text-primary-50">
        {{ t('gallery.section.title') }}
      </h2>
      <p class="text-sm text-primary-50/60">
        {{ t('gallery.section.subtitle') }}
      </p>
    </div>

    <!-- Search bar. `relative z-10` gives the mode tabs and the pill dropdowns a
         stacking context of their own, so neither the intro above nor the
         sticky map column beside them can paint over the controls. -->
    <div class="relative z-10 flex flex-col items-center gap-3">
      <!-- Category tabs -->
      <div class="flex divide-x divide-primary-50/20 overflow-hidden rounded-full">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          type="button"
          class="flex cursor-pointer items-center gap-1.5 px-4 py-2 text-sm leading-none transition"
          :class="
            mode === tab.value
              ? 'text-primary-50 font-bold'
              : 'text-primary-50/60 hover:text-primary-50/100'
          "
          @click="mode = tab.value"
        >
          <AppIcon :path="tab.icon" :size="16" />
          {{ tab.label }}
        </button>
      </div>

      <!-- Input pill — adapts to the active mode -->
      <div
        class="flex items-center gap-1 rounded-full border border-primary-50/20 bg-primary-50/5 py-1.5 pl-2 pr-1.5 shadow-lg"
      >
        <!-- From A to B: two stop inputs -->
        <template v-if="mode === 'aToB'">
          <StopSelect
            :stops="store.stops"
            :status="store.stopsStatus"
            @select="fromStop = $event"
            @retry="store.fetchStops()"
          >
            <SearchField
              :label="t('gallery.search.from')"
              :value="fromStop?.name ?? null"
              :placeholder="t('gallery.search.fromPlaceholder')"
              @clear="fromStop = null"
            />
          </StopSelect>
          <div class="h-8 w-px bg-primary-50/15"></div>
          <StopSelect
            :stops="store.stops"
            :status="store.stopsStatus"
            @select="toStop = $event"
            @retry="store.fetchStops()"
          >
            <SearchField
              :label="t('gallery.search.to')"
              :value="toStop?.name ?? null"
              :placeholder="t('gallery.search.toPlaceholder')"
              @clear="toStop = null"
            />
          </StopSelect>
        </template>

        <!-- By Station: one stop input -->
        <template v-else-if="mode === 'byStation'">
          <StopSelect
            :stops="store.stops"
            :status="store.stopsStatus"
            @select="stationStop = $event"
            @retry="store.fetchStops()"
          >
            <SearchField
              :label="t('gallery.search.station')"
              :value="stationStop?.name ?? null"
              :placeholder="t('gallery.search.stationPlaceholder')"
              @clear="stationStop = null"
            />
          </StopSelect>
        </template>

        <!-- By Country: same picker style as the stop selection -->
        <template v-else-if="mode === 'byCountry'">
          <CountrySelect :countries="countryOptions" @select="countryCode = $event">
            <SearchField
              :label="t('gallery.search.country')"
              :value="selectedCountryName"
              :placeholder="t('gallery.search.countryPlaceholder')"
              @clear="countryCode = null"
            />
          </CountrySelect>
        </template>

        <!-- By Relation: a country PAIR. The stored token is alphabetical and
             direction-agnostic, so these two are interchangeable — picking
             AT/DE and DE/AT runs the same query. -->
        <template v-else>
          <CountrySelect :countries="countryOptions" @select="relationFrom = $event">
            <SearchField
              :label="t('gallery.search.relationFrom')"
              :value="selectedRelationFromName"
              :placeholder="t('gallery.search.countryPlaceholder')"
              @clear="relationFrom = null"
            />
          </CountrySelect>
          <div class="h-8 w-px bg-primary-50/15"></div>
          <CountrySelect :countries="countryOptions" @select="relationTo = $event">
            <SearchField
              :label="t('gallery.search.relationTo')"
              :value="selectedRelationToName"
              :placeholder="t('gallery.search.countryPlaceholder')"
              @clear="relationTo = null"
            />
          </CountrySelect>
        </template>

        <!-- Search button -->
        <button
          type="button"
          class="flex cursor-pointer items-center justify-center rounded-full bg-primary-50/10 p-3 text-primary-50 transition hover:bg-primary-50/20"
          :aria-label="t('gallery.search.button')"
          @click="resetAndLoad"
        >
          <AppIcon :path="mdiMagnify" :size="20" />
        </button>
      </div>
    </div>

    <!-- The scenario the figures are read on. Collapsed to one line by
         default — see the component: an open panel costs the map its height
         (measureRow), and the summary line already answers "which figures am
         I looking at?". -->
    <GalleryScenarioPanel
      v-model="galleryScenarioId"
      :scenarios="store.scenarios"
      :without-figures="withoutFigures"
    />

    <!-- Results: controls + a scrolling card list (left) beside the map
         (right), the row exactly one screen tall (measureRow). Both columns are
         that height, which is what puts the bottom of the card list on the
         bottom edge of the map: the list scrolls inside its own box rather than
         running down the page past the map's corner. -->
    <div ref="resultsRow" class="flex gap-6" :style="{ height: rowHeight }">
      <div class="flex h-full w-96 shrink-0 flex-col gap-3">
        <!-- Source + sort, at the head of the column whose order they set —
             which also puts the map's top edge level with them. -->
        <div class="flex items-center justify-between gap-2">
          <!-- Source switch. Suggested routes and the existing ONTD network are
               two different kinds of thing sharing one list; this separates them,
               and narrows the sort fields to the ones ONTD rows actually carry. -->
          <Select
            v-model="sourceFilter"
            :options="sourceOptions"
            option-value="value"
            option-label="label"
            :unstyled="true"
            :pt="selectPillPt"
          />
          <!-- Field and direction as ONE control: the field in words, the
               direction as an mdi sort glyph. -->
          <Select
            v-model="sortSelection"
            :options="sortOptions"
            option-value="value"
            option-label="label"
            :unstyled="true"
            :pt="selectPillPt"
          >
            <!-- Direction glyph first, then the field: the icon is the part
                 that changes between adjacent options, so leading with it makes
                 the list scannable down its left edge. -->
            <template #value>
              <span v-if="selectedSortOption" class="flex items-center gap-1.5">
                <AppIcon :path="selectedSortOption.icon" :size="16" />
                <span class="sr-only">{{ selectedSortOption.dirLabel }}</span>
                {{ selectedSortOption.label }}
              </span>
            </template>
            <template #option="{ option }">
              <span class="flex items-center gap-1.5">
                <AppIcon :path="option.icon" :size="16" />
                <span class="sr-only">{{ option.dirLabel }}</span>
                {{ option.label }}
              </span>
            </template>
          </Select>
        </div>

        <!-- Whose routes (left) and how many the search matched (right). The
             ownership switch is always on screen, whatever the source switch or
             the sign-in state says: hiding it for signed-out readers made it a
             control nobody could find. Picking "mine" while the list is showing
             existing trains alone moves the source switch with it, since an
             ONTD row has no owner. The count appears once the first query has
             come back and then stays put across later searches — see
             shownTotal. -->
        <div class="flex min-h-8 items-center justify-between gap-2">
          <div
            class="flex items-center gap-0.5 rounded-full border border-primary-50/20 p-0.5 text-sm"
            role="group"
            :aria-label="t('gallery.filter.label')"
          >
            <button
              type="button"
              class="cursor-pointer rounded-full px-3 py-1 transition"
              :class="mineOnly ? inactiveOwnerClass : activeOwnerClass"
              :aria-pressed="!mineOnly"
              @click="mineOnly = false"
            >
              {{ t('gallery.filter.all') }}
            </button>
            <button
              type="button"
              class="flex cursor-pointer items-center gap-1.5 rounded-full px-3 py-1 transition"
              :class="mineOnly ? activeOwnerClass : inactiveOwnerClass"
              :aria-pressed="mineOnly"
              @click="selectMine"
            >
              <AppIcon :path="mdiAccountOutline" :size="16" />
              {{ t('gallery.filter.mine') }}
            </button>
          </div>
          <p v-if="shownTotal !== null && !failure" class="text-sm text-primary-50/50">
            {{ t('gallery.matching', shownTotal) }}
          </p>
        </div>

        <!-- Failures land here, in the column the user is reading, rather than
             as a one-line note above the fold. -->
        <div
          v-if="failureMsg"
          class="rounded-xl border border-red-400/30 bg-red-950/30 px-4 py-3"
          role="alert"
        >
          <p class="text-sm text-red-200">{{ failureMsg }}</p>
          <button
            v-if="!failure || isRetryable(failure)"
            type="button"
            class="mt-2 cursor-pointer text-sm font-semibold text-red-100 underline decoration-red-400/50 underline-offset-2 transition hover:decoration-red-100"
            @click="retryLoad"
          >
            {{ t('errors.retry') }}
          </button>
        </div>

        <!-- The scrolling part of the column. min-h-0 is what lets a flex child
             shrink below its content and scroll; pr-1 keeps the thin scrollbar
             off the cards. -->
        <div ref="cardScroller" class="thin-scroll min-h-0 flex-1 overflow-y-auto pr-1">
          <!-- First load: cards the size of real cards, so the column doesn't
               collapse to a single line of text and then jump. -->
          <div v-if="loading && !initialized" class="flex flex-col gap-3" aria-hidden="true">
            <Skeleton v-for="n in 3" :key="n" height="11rem" border-radius="0.75rem" />
          </div>

          <div v-if="proposals.length" class="flex flex-col gap-3">
            <ProposalCard
              v-for="p in proposals"
              :key="proposalKey(p)"
              :proposal="p"
              :highlight-stop-ids="highlightStopIds"
              @select="openProposal"
              @discuss="openDiscussion"
              @mouseenter="hoveredRow = rowRefOf(p)"
              @mouseleave="hoveredRow = null"
            />
          </div>
          <!-- "No proposals found" is only true if the query actually succeeded —
               without the !failure guard it renders on top of a failed load and
               reads as an answer. -->
          <p
            v-else-if="initialized && !loading && !failure"
            class="py-8 text-center text-sm text-primary-50/50"
          >
            {{ t('gallery.empty') }}
          </p>

          <!-- Infinite-scroll sentinel + status -->
          <div
            ref="sentinel"
            class="flex h-8 items-center justify-center text-sm text-primary-50/40"
          >
            <span v-if="loading && initialized">{{ t('gallery.loadingMore') }}</span>
          </div>

          <!-- Trailing CTA, at the end of the list it belongs to -->
          <div class="flex justify-center pb-2">
            <button type="button" :class="ctaButtonClass" @click="createProposal">
              <AppIcon :path="mdiPlus" :size="18" />
              {{ t('gallery.cta.create') }}
            </button>
          </div>
        </div>
      </div>

      <div class="h-full flex-1 overflow-hidden rounded-xl border border-primary-50/10">
        <GalleryMap :corridors="corridors" :routes="routeFeatures" :highlighted-row="hoveredRow" />
      </div>
    </div>
  </div>
</template>
