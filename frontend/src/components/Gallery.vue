<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, onActivated, onDeactivated, watch } from 'vue'
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
import { octilinearPath } from '@/utils/octilinear'
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
  type ProposalSummaryExisting,
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
  { value: 'aToB' as const, label: t('gallery.tabs.aToB'), icon: mdiArrowLeftRight },
  { value: 'byStation' as const, label: t('gallery.tabs.byStation'), icon: mdiMapMarkerOutline },
  { value: 'byCountry' as const, label: t('gallery.tabs.byCountry'), icon: mdiEarth },
])

// Which source(s) the list shows. 'all' sends no `sources` key at all, which
// the backend reads as both.
type SourceChoice = 'all' | ProposalSourceKind
const sourceFilter = ref<SourceChoice>('all')
const SOURCE_CHOICES: readonly SourceChoice[] = ['all', 'proposal', 'existing']
const sourceOptions = computed(() =>
  SOURCE_CHOICES.map((value) => ({ value, label: t(`gallery.source.${value}`) })),
)

// Existing (ONTD) rows carry NULL in every proposal-only column, so offering
// CO₂ savings as a sort field while viewing ONTD only would sort a column no
// row has.
const SHARED_SORT_KEYS: readonly ProposalSortKey[] = ['total_distance_km', 'n_stops']

// Sort is presented as field-in-words × direction-as-icon ("Distance" + the mdi
// sort-descending glyph), so the option list is the cross product of these two.
// The icon is aria-hidden (AppIcon always is), hence the sr-only direction name
// rendered next to it in the template.
const SORT_FIELDS: readonly { field: ProposalSortKey; key: string }[] = [
  { field: 'total_distance_km', key: 'distance' },
  { field: 'co2_savings_t_per_year', key: 'co2' },
  { field: 'n_stops', key: 'stops' },
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
    shownTotal.value = res.total
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
// the routes for whatever is currently loaded, growing with the list.
//
// Existing (ONTD) rows have no per-row geometry endpoint, so they are drawn the
// way ProposalViewport draws an itinerary that has not been routed yet: one
// schematic octilinear connector per consecutive stop pair, built client-side
// from the loaded stop list (see schematicRoute).
const proposalKey = (p: ProposalSummary): string =>
  p.source === 'existing' ? `e-${p.route_id}` : `p-${p.proposal_id}-${p.proposal_version}`
// `drawable` gates what reaches the map: a proposal needs real routed geometry
// (a straight-line stand-in such as the seed proposal would read as a route it
// isn't), an existing row needs enough locatable stops to connect.
// `orderedCountries` lists the countries in itinerary order (the summary's own
// `countries` is alphabetical), used for the flag order on the card.
type MapRoute = GalleryMapRoute & { drawable: boolean }
type CachedRoute = MapRoute & { orderedCountries: string[] }
const routeCache = ref<Record<string, CachedRoute>>({})

// Coordinates for an existing row's itinerary. ONTD stop_ids are a mix of
// curated stop ids (which resolve here) and bare station names used as ids
// (which do not — those stops carry no coordinates anywhere in the API, the
// `map_stop_counts` section included), so an unlocatable stop is skipped and a
// row left with fewer than two of them is not drawn at all.
const stopById = computed(() => new Map(store.stops.map((s) => [s.stop_id, s])))

function schematicRoute(p: ProposalSummaryExisting): MapRoute | null {
  const pts = p.stop_ids.map((id) => stopById.value.get(id)).filter((s): s is Stop => Boolean(s))
  if (pts.length < 2) return null
  // Per leg rather than one path through all stops: octilinearPath treats each
  // leg independently, so this draws the identical shape (same as MapView.vue).
  const lines: [number, number][][] = []
  for (let i = 0; i < pts.length - 1; i++) {
    lines.push(
      octilinearPath([
        [pts[i].lon, pts[i].lat],
        [pts[i + 1].lon, pts[i + 1].lat],
      ]),
    )
  }
  return {
    key: proposalKey(p),
    lines,
    stops: pts.map((s) => ({ lat: s.lat, lon: s.lon, name: s.name })),
    drawable: true,
  }
}

const mapRoutes = computed<GalleryMapRoute[]>(() =>
  proposals.value
    .map((p) => (p.source === 'existing' ? schematicRoute(p) : routeCache.value[proposalKey(p)]))
    .filter((r): r is MapRoute => Boolean(r) && r.drawable),
)

// Keys whose geometry fetch failed. Without this the `watch(proposals)` below
// would retry every failed route on every page append — turning one bad
// proposal into a request on every scroll.
const failedRouteKeys = new Set<string>()
// Cancels the whole in-flight batch when the gallery unmounts, so navigating
// away mid-fan-out doesn't toast at a dead component.
const routeSlot = createAbortSlot()

async function ensureRoutes(list: ProposalSummary[]): Promise<void> {
  // Only proposal rows have a per-id route endpoint; existing (ONTD) rows need
  // no fetch at all — schematicRoute derives their lines from stops already
  // loaded (see the map note above).
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
      drawable: lines.some((l) => l.length > 2),
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
// This component is kept alive (App.vue), so leaving the gallery deactivates it
// instead of unmounting it. Cancelling in flight requests is right in BOTH
// cases — nobody is looking at the result any more — so the teardown is shared.
function teardown(): void {
  observer?.disconnect()
  // Drop everything in flight; their rejections are 'canceled' and stay silent.
  listSlot.cancel()
  routeSlot.cancel()
}
onBeforeUnmount(teardown)
onDeactivated(teardown)

// Coming back to a cached gallery. Deliberately does NOT re-run onMounted's
// hydrate-and-load: the whole point is that a there-and-back trip costs zero
// requests. Only a proposal published in the meantime forces a refresh.
onActivated(() => {
  if (sentinel.value && observer) observer.observe(sentinel.value)
  if (store.galleryStale) {
    store.galleryStale = false
    resetAndLoad()
  }
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

// One search-bar field (From / To / Station / Country). Fixed width, so picking
// a station no longer resizes the field and with it the whole pill; `group` so
// the hover target is the field's full box rather than just the glyphs of the
// station name sitting in it.
const searchFieldClass =
  'group flex w-48 flex-col rounded-full px-4 py-1.5 transition-colors hover:bg-primary-50/10'
// Long station names ellipsize rather than widening the now-fixed field.
const searchValueClass = 'truncate text-sm transition-colors group-hover:text-primary-50/80'
</script>

<template>
  <!-- -mb-6 trims App.vue's py-12 page padding to 24px below this page's last
       row, which is what stops the sticky map from being pushed up at the end of
       the scroll — see the results row's comment below. Keep the two in sync: if
       App.vue's bottom padding changes, this offset has to change with it. -->
  <div class="-mb-6 flex w-full max-w-6xl flex-col gap-6">
    <!-- Page intro. The gallery owns its own h1 (App.vue's centered one steps
         aside for this route): the question and the action it leads to on the
         left, the copy that answers it on the right. -->
    <div class="flex items-start gap-12 px-24">
      <div class="flex w-2/5 shrink-0 flex-col items-start gap-6">
        <h1 class="text-4xl font-light text-white">{{ t('gallery.heading') }}</h1>
        <button type="button" :class="ctaClass" @click="createProposal">
          <AppIcon :path="mdiPlus" :size="18" />
          {{ t('gallery.cta.create') }}
        </button>
      </div>
      <div class="flex-1 text-justify">
        <p class="text-base font-semibold text-primary-50">{{ t('gallery.welcome.lead') }}</p>
        <p class="mt-2 text-sm leading-relaxed text-primary-50/70">
          {{ t('gallery.welcome.body') }}
        </p>
        <p class="mt-3 text-sm leading-relaxed text-primary-50/70">
          {{ t('gallery.welcome.cta') }}
        </p>
      </div>
    </div>

    <!-- The gallery proper: search bar, result count, then the list + map. -->
    <div class="flex flex-col items-center gap-1 pt-4">
      <h2 class="text-4xl font-light text-primary-50 pt-8">{{ t('gallery.section.title') }}</h2>
      <p class="text-sm text-primary-50/60">{{ t('gallery.section.subtitle') }}</p>
    </div>

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
            <div :class="searchFieldClass">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.from')
              }}</span>
              <span
                :class="[searchValueClass, fromStop ? 'text-primary-50' : 'text-primary-50/40']"
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
            <div :class="searchFieldClass">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.to')
              }}</span>
              <span :class="[searchValueClass, toStop ? 'text-primary-50' : 'text-primary-50/40']">
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
            <div :class="searchFieldClass">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.station')
              }}</span>
              <span
                :class="[searchValueClass, stationStop ? 'text-primary-50' : 'text-primary-50/40']"
              >
                {{ stationStop?.name ?? t('gallery.search.stationPlaceholder') }}
              </span>
            </div>
          </StopSelect>
        </template>

        <!-- By Country: same picker style as the stop selection -->
        <template v-else>
          <CountrySelect :countries="countryOptions" @select="countryCode = $event">
            <div :class="searchFieldClass">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.country')
              }}</span>
              <span
                :class="[searchValueClass, countryCode ? 'text-primary-50' : 'text-primary-50/40']"
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

      <!-- How many rows the active search matched. Appears once the first query
           has come back and then stays put across later searches — see
           shownTotal. -->
      <p v-if="shownTotal !== null && !failure" class="text-sm text-primary-50/50">
        {{ t('gallery.matching', shownTotal) }}
      </p>
    </div>

    <!-- Results: one column of controls + cards (left) + a browser-height sticky
         map (right).
         The card column ends at the trailing CTA — no filler padding below it —
         so the page's last scroll position is the one where the row's bottom
         edge meets the stuck map's bottom edge, i.e. the CTA sits in the map's
         bottom corner (the CTA block's own pb-4 is the gap). Past that point a
         sticky element starts being pushed up out of view by the end of its
         containing block, which is exactly what the -mb-6 on the root above
         prevents: it leaves the document ending 24px below this row, matching
         the map's own top-6 inset, so the scroll runs out at the same moment
         the push would begin. -->
    <div class="flex gap-6">
      <div class="flex w-96 shrink-0 flex-col gap-4">
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
            :pt="selectPt"
          />
          <!-- Field and direction as ONE control: the field in words, the
               direction as an mdi sort glyph. -->
          <Select
            v-model="sortSelection"
            :options="sortOptions"
            option-value="value"
            option-label="label"
            :unstyled="true"
            :pt="selectPt"
          >
            <template #value>
              <span v-if="selectedSortOption" class="flex items-center gap-1.5">
                {{ selectedSortOption.label }}
                <AppIcon :path="selectedSortOption.icon" :size="16" />
                <span class="sr-only">{{ selectedSortOption.dirLabel }}</span>
              </span>
            </template>
            <template #option="{ option }">
              <span class="flex items-center gap-1.5">
                {{ option.label }}
                <AppIcon :path="option.icon" :size="16" />
                <span class="sr-only">{{ option.dirLabel }}</span>
              </span>
            </template>
          </Select>
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
