<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import {
  mdiArrowLeftRight,
  mdiMapMarkerOutline,
  mdiEarth,
  mdiMagnify,
  mdiPlus,
  mdiSortAscending,
  mdiSortDescending,
} from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import StopSelect from '@/components/StopSelect.vue'
import CountrySelect from '@/components/CountrySelect.vue'
import ProposalCard from '@/components/ProposalCard.vue'
import GalleryMap from '@/components/GalleryMap.vue'
import { useStore } from '@/stores/store'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { fetchProposals, fetchProposalRoute } from '@/lib/proposalsApi'
import { createAbortSlot } from '@/lib/apiClient'
import { asApiFailure, isRetryable, type ApiFailure } from '@/lib/apiError'
import { mapLimit } from '@/lib/promisePool'
import { useApiFailure } from '@/composables/useApiFailure'
import {
  seedToQuery,
  seedFromQuery,
  queryString,
  type GallerySearchSeed,
} from '@/lib/proposalPrefill'
import {
  PROPOSAL_SORT_KEYS,
  type Stop,
  type ProposalSummary,
  type ProposalSummaryProposal,
  type ProposalsRequest,
  type ProposalsFilter,
  type ProposalSort,
  type ProposalSortKey,
  type ProposalSourceKind,
  type GalleryMapRoute,
} from '@/types/api'

const { t } = useI18n()
const store = useStore()
const { countryName } = useLocaleFormat()
const route = useRoute()
const router = useRouter()
const { describe, report } = useApiFailure()

const LIMIT = 20
// The gallery fans out one GET /api/proposal/<id> per card to draw its route.
// Unbounded, a 20-card page meant 20 simultaneous requests against a backend
// running 4 gunicorn workers — the gallery could manufacture the overload it
// then reports.
const ROUTE_FETCH_CONCURRENCY = 4

type SearchMode = 'aToB' | 'byStation' | 'byCountry'
const mode = ref<SearchMode>('aToB')

// Search inputs (kept per-mode; buildFilter() only reads the active mode's).
const fromStop = ref<Stop | null>(null)
const toStop = ref<Stop | null>(null)
const stationStop = ref<Stop | null>(null)
const countryCode = ref<string | null>(null)

// Current search-bar state, handed to "Suggest a new route" so the new
// proposal's itinerary can be prefilled from whatever the user was searching
// for instead of two arbitrary stops.
const searchSeed = computed<GallerySearchSeed>(() => ({
  mode: mode.value,
  fromStop: fromStop.value,
  toStop: toStop.value,
  stationStop: stationStop.value,
  countryCode: countryCode.value,
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

// Sort as a field + direction. The field Select shows only field names; the
// direction is an icon toggle (ascending/descending).
const sortField = ref<ProposalSortKey>('margin_eur_per_train_km')
const sortDir = ref<'asc' | 'desc'>('desc')

// Result list (accumulated across pages) + pagination bookkeeping.
const proposals = ref<ProposalSummary[]>([])
const total = ref(0)
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
  { value: 'aToB' as const, label: t('gallery.tabs.aToB'), icon: mdiArrowLeftRight },
  { value: 'byStation' as const, label: t('gallery.tabs.byStation'), icon: mdiMapMarkerOutline },
  { value: 'byCountry' as const, label: t('gallery.tabs.byCountry'), icon: mdiEarth },
])

// Which source(s) the list shows. 'all' sends no `sources` key at all, which
// the backend reads as both.
type SourceChoice = 'all' | ProposalSourceKind
const sourceFilter = ref<SourceChoice>('all')
const sourceChoices: { value: SourceChoice; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'proposal', label: 'Suggested' },
  { value: 'existing', label: 'ONTD' },
]

// Existing (ONTD) rows carry NULL in every financial column and have no
// created_at, so offering those as sort fields while viewing ONTD only would
// sort a column no row has — which is exactly why the default "Margin, desc"
// looked arbitrary on a list that is 205 existing rows and 2 proposals.
const SHARED_SORT_KEYS: readonly ProposalSortKey[] = ['total_distance_km', 'total_time_h']

const sortFieldOptions = computed<{ value: ProposalSortKey; label: string }[]>(() => {
  const all = [
    { value: 'margin_eur_per_train_km' as ProposalSortKey, label: t('gallery.sort.margin') },
    { value: 'revenue_eur_per_train_km' as ProposalSortKey, label: t('gallery.sort.revenue') },
    { value: 'cost_eur_per_train_km' as ProposalSortKey, label: t('gallery.sort.cost') },
    { value: 'created_at' as ProposalSortKey, label: t('gallery.sort.date') },
    { value: 'total_distance_km' as ProposalSortKey, label: t('gallery.sort.distance') },
    { value: 'total_time_h' as ProposalSortKey, label: t('gallery.sort.duration') },
  ]
  return sourceFilter.value === 'existing'
    ? all.filter((o) => SHARED_SORT_KEYS.includes(o.value))
    : all
})

// Switching to ONTD-only while sorted by a proposal-only column would leave the
// Select showing a field that is no longer offered — fall back to distance.
watch(sourceFilter, (choice) => {
  if (choice === 'existing' && !SHARED_SORT_KEYS.includes(sortField.value)) {
    sortField.value = 'total_distance_km'
  }
})

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

const currentSort = computed<ProposalSort>(() => ({ by: sortField.value, dir: sortDir.value }))
function toggleSortDir(): void {
  sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
}

const reachedEnd = computed(() => initialized.value && proposals.value.length >= total.value)

// Map the active search mode + inputs to a backend filter. All backend filters
// are OR/any-match; "From A to B" therefore sends both stop_ids as an
// approximation (routes touching either stop), not a strict A→B connection.
function buildFilter(): ProposalsFilter | undefined {
  const base: ProposalsFilter = {}
  // Omitting `sources` means BOTH on the backend, so only send it when the
  // user has narrowed the list. ['proposal'] compiles to a query that never
  // touches the ontd schema at all.
  if (sourceFilter.value !== 'all') base.sources = [sourceFilter.value]

  if (mode.value === 'aToB') {
    const ids = [fromStop.value?.stop_id, toStop.value?.stop_id].filter((id): id is string =>
      Boolean(id),
    )
    if (ids.length) base.stop_ids = ids
  } else if (mode.value === 'byStation') {
    if (stationStop.value) base.stop_ids = [stationStop.value.stop_id]
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
  const seq = ++requestSeq
  const signal = listSlot.begin()
  try {
    const body: ProposalsRequest = {
      sort: [currentSort.value],
      limit: LIMIT,
      offset: requestOffset,
    }
    const filter = buildFilter()
    if (filter) body.filter = filter

    const res = await fetchProposals(body, signal)
    if (seq !== requestSeq) return
    proposals.value = requestOffset === 0 ? res.proposals : [...proposals.value, ...res.proposals]
    total.value = res.total
    offset.value = requestOffset + res.proposals.length
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
function resetAndLoad(): void {
  proposals.value = []
  total.value = 0
  offset.value = 0
  initialized.value = false
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

// --- Map: draw every result's route --------------------------------------
// Summaries carry no geometry (stripped server-side), so each proposal's route
// is fetched once via GET /api/proposal/<id> and cached by key. The map shows
// the routes for whatever is currently loaded, growing with the list. Existing
// (ONTD) rows have no per-row geometry endpoint and are not drawn on the map
// yet — they still appear as cards (map geometry for them would come from the
// list response's `map_lines` section, a separate change).
const proposalKey = (p: ProposalSummary): string =>
  p.source === 'existing' ? `e-${p.route_id}` : `p-${p.proposal_id}-${p.proposal_version}`
// `routed` separates a real routed geometry (many points per leg) from a
// straight-line stand-in (e.g. the seed proposal) — only routed ones map.
// `orderedCountries` lists the countries in itinerary order (the summary's own
// `countries` is alphabetical), used for the flag order on the card.
type CachedRoute = GalleryMapRoute & { routed: boolean; orderedCountries: string[] }
const routeCache = ref<Record<string, CachedRoute>>({})
const mapRoutes = computed(() =>
  proposals.value
    .map((p) => routeCache.value[proposalKey(p)])
    .filter((r): r is CachedRoute => Boolean(r) && r.routed),
)

// Keys whose geometry fetch failed. Without this the `watch(proposals)` below
// would retry every failed route on every page append — turning one bad
// proposal into a request on every scroll.
const failedRouteKeys = new Set<string>()
// Cancels the whole in-flight batch when the gallery unmounts, so navigating
// away mid-fan-out doesn't toast at a dead component.
const routeSlot = createAbortSlot()

async function ensureRoutes(list: ProposalSummary[]): Promise<void> {
  // Only proposal rows have a per-id route endpoint; existing (ONTD) rows are
  // skipped (see the map note above).
  const missing = list.filter(
    (p): p is ProposalSummaryProposal =>
      p.source === 'proposal' &&
      !routeCache.value[proposalKey(p)] &&
      !failedRouteKeys.has(proposalKey(p)),
  )
  if (!missing.length) return
  const signal = routeSlot.begin()
  const settled = await mapLimit(missing, ROUTE_FETCH_CONCURRENCY, async (p) => {
    const { route } = await fetchProposalRoute(p.proposal_id, signal)
    // Every stop along the route, in order — each segment's origin, then the
    // final segment's destination. The gallery map dedupes the boundary
    // repeats when it draws the bubbles.
    const stops: GalleryMapRoute['stops'] = []
    for (const pair of route.trip_pairs) {
      const segs = pair.outbound.segments
      if (!segs.length) continue
      for (const seg of segs) {
        stops.push({
          lat: seg.from_stop.lat,
          lon: seg.from_stop.lon,
          name: seg.from_stop.stop_name,
        })
      }
      const last = segs[segs.length - 1].to_stop
      stops.push({ lat: last.lat, lon: last.lon, name: last.stop_name })
    }
    const lines = route.geometries.map((g) => g.coords)
    const orderedCountries: string[] = []
    for (const pair of route.trip_pairs) {
      for (const seg of pair.outbound.segments) {
        for (const cc of Object.keys(seg.country_distance_shares)) {
          if (!orderedCountries.includes(cc)) orderedCountries.push(cc)
        }
      }
    }
    const entry: CachedRoute = {
      key: proposalKey(p),
      lines,
      stops,
      // A routed leg carries many intermediate points; a straight-line
      // stand-in is just its two endpoints.
      routed: lines.some((l) => l.length > 2),
      orderedCountries,
    }
    return entry
  })

  const add: Record<string, CachedRoute> = {}
  let firstFailure: unknown = null
  settled.forEach((result, index) => {
    if (result.ok) {
      add[result.value.key] = result.value
      return
    }
    // A cancelled batch (unmount, or a newer batch superseding this one) is not
    // a failure and must not be remembered as one.
    if (asApiFailure(result.error)?.kind === 'canceled') return
    failedRouteKeys.add(proposalKey(missing[index]))
    firstFailure ??= result.error
  })
  if (Object.keys(add).length) routeCache.value = { ...routeCache.value, ...add }
  // ONE toast for the whole batch. Per-proposal toasts would mean twenty
  // identical alerts during an outage; the dedupe key would collapse them
  // anyway, but not fetching twenty times over is the real point.
  if (firstFailure) report(firstFailure, { fallbackKey: 'errors.mapPartial', force: 'toast' })
}

// Hovering a route on the map scrolls its card into view and flashes its
// background briefly. Scrolled manually (not via scrollIntoView) so the
// target lands relative to the sticky map's own bounds rather than the raw
// window edge: the first card's top aligns with the map's top, the last
// card's bottom aligns with the map's bottom, and everything in between is
// just centered in the viewport — mirroring where the hovered route sits
// within the map itself (near the top edge, near the bottom edge, or
// somewhere in the middle). Deduped so the continuous mousemove stream over
// one route only fires once (until the pointer leaves and re-enters).
const cardsContainer = ref<HTMLElement | null>(null)
const flashedKey = ref<string | null>(null)
// Set while a card is hovered; drives the map's route highlight (card → map).
const cardHoverKey = ref<string | null>(null)
// Keep in sync with the sticky map wrapper's `top-6` class below — its top and
// bottom gaps from the viewport are equal (top-6 + h-[calc(100vh-3rem)]).
const MAP_EDGE_OFFSET_PX = 24
let lastScrolledKey: string | null = null
let flashTimer: number | undefined
function onHoverRoute(key: string | null): void {
  if (!key) {
    lastScrolledKey = null
    return
  }
  if (key === lastScrolledKey) return
  lastScrolledKey = key
  const card = cardsContainer.value?.querySelector<HTMLElement>(`[data-proposal="${key}"]`)
  if (card) {
    const index = proposals.value.findIndex((p) => proposalKey(p) === key)
    const rect = card.getBoundingClientRect()
    let desiredViewportTop: number
    if (index === 0) {
      desiredViewportTop = MAP_EDGE_OFFSET_PX
    } else if (index === proposals.value.length - 1) {
      desiredViewportTop = window.innerHeight - MAP_EDGE_OFFSET_PX - rect.height
    } else {
      desiredViewportTop = (window.innerHeight - rect.height) / 2
    }
    window.scrollTo({ top: window.scrollY + rect.top - desiredViewportTop, behavior: 'smooth' })
  }
  flashedKey.value = key
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    flashedKey.value = null
  }, 900)
}

// --- URL <-> search-bar sync -------------------------------------------
// Reflects the whole search bar (filters + sort) in /gallery's query string
// so results are shareable, reload-safe, and back/forward-navigable.
// Suppressed during the initial hydration in onMounted below — otherwise
// each ref assignment there would fire its own resetAndLoad()/router.replace
// before the async stop-id resolution finishes, flashing unfiltered results.
let hydrating = true

function currentSearchQuery(): LocationQueryRaw {
  return {
    ...seedToQuery({
      mode: mode.value,
      fromStop: fromStop.value,
      toStop: toStop.value,
      stationStop: stationStop.value,
      countryCode: countryCode.value,
    }),
    sort: sortField.value,
    dir: sortDir.value,
  }
}

watch([mode, fromStop, toStop, stationStop, countryCode, sortField, sortDir, sourceFilter], () => {
  if (hydrating) return
  resetAndLoad()
  router.replace({ query: currentSearchQuery() })
})
watch(proposals, ensureRoutes)

// Navigate to a saved proposal's detail route (ProposalCard's @select, only
// fired for source==='proposal' rows — see ProposalCard.vue).
function openProposal(proposalId: number): void {
  router.push({ name: 'proposal', params: { id: proposalId } })
}

// "Suggest a new route" — hand the current search bar to the builder route as
// its prefill seed, off-URL via the store (see pendingProposalSeed) so it
// doesn't show up in /proposal-builder's address bar.
function createProposal(): void {
  store.pendingProposalSeed = searchSeed.value
  router.push({ name: 'proposal-builder' })
}

let observer: IntersectionObserver | null = null
onMounted(async () => {
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) onSentinel()
    },
    { rootMargin: '300px' },
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
  const sortParam = queryString(route.query.sort)
  if (sortParam && (PROPOSAL_SORT_KEYS as readonly string[]).includes(sortParam)) {
    sortField.value = sortParam as ProposalSortKey
  }
  const dirParam = queryString(route.query.dir)
  if (dirParam === 'asc' || dirParam === 'desc') sortDir.value = dirParam

  hydrating = false
  resetAndLoad()
  router.replace({ query: currentSearchQuery() })
})
onBeforeUnmount(() => {
  observer?.disconnect()
  // Drop everything in flight; their rejections are 'canceled' and stay silent.
  listSlot.cancel()
  routeSlot.cancel()
})

// Same pill passthrough as the Selects in EvaluationPanel.vue.
const selectPt = {
  root: {
    class:
      'flex cursor-pointer items-center rounded-full border border-primary-50/20 bg-transparent transition hover:bg-primary-50/10',
  },
  label: { class: 'px-3 py-1.5 text-sm text-primary-50 leading-none' },
  dropdown: { class: 'flex items-center pr-3 text-primary-50/60' },
  overlay: {
    class:
      'z-50 mt-1 overflow-hidden rounded-xl border border-primary-50/20 bg-sapphire-100 shadow-xl',
  },
  listContainer: { class: 'overflow-auto' },
  option: {
    class: 'cursor-pointer px-4 py-2 text-sm text-primary-50 transition hover:bg-primary-50/10',
  },
}

const ctaClass =
  'flex cursor-pointer items-center gap-1.5 rounded-full bg-primary-50/10 px-5 py-2 text-sm text-primary-50 transition hover:bg-primary-50/20'
// A circle whose 28px (h-7/w-7) diameter equals the sort Select's height, so
// the two sit as an equal-height pair.
const iconBtnClass =
  'flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-full border border-primary-50/20 text-primary-50/70 transition hover:bg-primary-50/10'
</script>

<template>
  <div class="flex w-full max-w-6xl flex-col gap-6">
    <!-- Search bar -->
    <div class="flex flex-col items-center gap-4">
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
            <div class="flex flex-col rounded-full px-4 py-1.5">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.from')
              }}</span>
              <span
                class="text-sm hover:text-primary-50/80"
                :class="fromStop ? 'text-primary-50' : 'text-primary-50/40'"
              >
                {{ fromStop?.name ?? t('gallery.search.fromPlaceholder') }}
              </span>
            </div>
          </StopSelect>
          <div class="h-8 w-px bg-primary-50/15"></div>
          <StopSelect
            :stops="store.stops"
            :status="store.stopsStatus"
            @select="toStop = $event"
            @retry="store.fetchStops()"
          >
            <div class="flex flex-col rounded-full px-4 py-1.5">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.to')
              }}</span>
              <span
                class="text-sm hover:text-primary-50/80"
                :class="toStop ? 'text-primary-50' : 'text-primary-50/40'"
              >
                {{ toStop?.name ?? t('gallery.search.toPlaceholder') }}
              </span>
            </div>
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
            <div class="flex flex-col rounded-full px-4 py-1.5">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.station')
              }}</span>
              <span
                class="text-sm hover:text-primary-50/80"
                :class="stationStop ? 'text-primary-50' : 'text-primary-50/40'"
              >
                {{ stationStop?.name ?? t('gallery.search.stationPlaceholder') }}
              </span>
            </div>
          </StopSelect>
        </template>

        <!-- By Country: same picker style as the stop selection -->
        <template v-else>
          <CountrySelect :countries="countryOptions" @select="countryCode = $event">
            <div class="flex flex-col rounded-full px-4 py-1.5">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.country')
              }}</span>
              <span
                class="text-sm hover:text-primary-50/80"
                :class="countryCode ? 'text-primary-50' : 'text-primary-50/40'"
              >
                {{ selectedCountryName ?? t('gallery.search.countryPlaceholder') }}
              </span>
            </div>
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

    <!-- Controls: source + sort (above the card list) + plan a new route -->
    <div class="flex items-center gap-2">
      <!-- Source switch. Suggested routes and the existing ONTD network are two
           different kinds of thing sharing one list; this separates them, and
           narrows the sort fields to the ones ONTD rows actually carry. -->
      <div
        class="flex shrink-0 items-center gap-0.5 rounded-full border border-primary-50/20 bg-primary-50/5 p-0.5"
      >
        <button
          v-for="choice in sourceChoices"
          :key="choice.value"
          type="button"
          class="cursor-pointer rounded-full px-3 py-1 text-xs leading-none transition"
          :class="
            sourceFilter === choice.value
              ? 'bg-primary-50/20 font-bold text-primary-50'
              : 'text-primary-50/60 hover:text-primary-50'
          "
          @click="sourceFilter = choice.value"
        >
          {{ choice.label }}
        </button>
      </div>
      <div class="flex items-stretch gap-2">
        <Select
          v-model="sortField"
          :options="sortFieldOptions"
          option-value="value"
          option-label="label"
          :unstyled="true"
          :pt="selectPt"
        />
        <button
          type="button"
          :class="iconBtnClass"
          :aria-label="t('gallery.sort.direction')"
          @click="toggleSortDir"
        >
          <AppIcon :path="sortDir === 'asc' ? mdiSortAscending : mdiSortDescending" :size="18" />
        </button>
      </div>
      <button type="button" :class="[ctaClass, 'ml-auto']" @click="createProposal">
        <AppIcon :path="mdiPlus" :size="18" />
        {{ t('gallery.cta.create') }}
      </button>
    </div>

    <!-- Results: one column of cards (left) + a browser-height sticky map (right).
         The left column's trailing pb-[calc(100vh-3rem)] matches the map's own
         height so a sticky element's unavoidable "catch up and rise" as it nears
         its containing block's bottom happens entirely within that empty
         padding, after the last real card/CTA — not while real content is still
         on screen. Without it, the map visibly detaches and creeps upward while
         the trailing CTA is still visible, well before the column truly ends. -->
    <div class="flex gap-6">
      <div class="flex w-96 shrink-0 flex-col gap-4 pb-[calc(100vh-3rem)]">
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

        <!-- First load: cards the size of real cards, so the column doesn't
             collapse to a single line of text and then jump. -->
        <div v-if="loading && !initialized" class="flex flex-col gap-4" aria-hidden="true">
          <Skeleton v-for="n in 3" :key="n" height="9rem" border-radius="0.75rem" />
        </div>

        <div v-if="proposals.length" ref="cardsContainer" class="flex flex-col gap-4">
          <div
            v-for="p in proposals"
            :key="proposalKey(p)"
            :data-proposal="proposalKey(p)"
            @mouseenter="cardHoverKey = proposalKey(p)"
            @mouseleave="cardHoverKey = null"
          >
            <ProposalCard
              :proposal="p"
              :flash="flashedKey === proposalKey(p)"
              :ordered-countries="routeCache[proposalKey(p)]?.orderedCountries"
              :highlight-stop-ids="highlightStopIds"
              @select="openProposal"
            />
          </div>
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
        <div ref="sentinel" class="flex h-8 items-center justify-center text-sm text-primary-50/40">
          <span v-if="loading && initialized">{{ t('gallery.loadingMore') }}</span>
        </div>

        <!-- Trailing CTA -->
        <div class="flex justify-center pb-4">
          <button type="button" :class="ctaClass" @click="createProposal">
            <AppIcon :path="mdiPlus" :size="18" />
            {{ t('gallery.cta.create') }}
          </button>
        </div>
      </div>

      <div class="flex-1">
        <div
          class="sticky top-6 h-[calc(100vh-3rem)] overflow-hidden rounded-xl border border-primary-50/10"
        >
          <GalleryMap
            :routes="mapRoutes"
            :highlighted-key="cardHoverKey"
            @hover-route="onHoverRoute"
          />
        </div>
      </div>
    </div>
  </div>
</template>
