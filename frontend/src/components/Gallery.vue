<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, onActivated, onDeactivated, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import {
  mdiArrowLeftRight,
  mdiChevronDown,
  mdiMapMarkerOutline,
  mdiEarth,
  mdiFlagOutline,
  mdiMagnify,
  mdiPlus,
  mdiSortAscending,
  mdiSortDescending,
} from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import StopSelect from '@/components/StopSelect.vue'
import CountrySelect from '@/components/CountrySelect.vue'
import SearchField from '@/components/SearchField.vue'
import ProposalCard from '@/components/ProposalCard.vue'
import GalleryMap from '@/components/GalleryMap.vue'
import { useStore } from '@/stores/store'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { fetchProposals } from '@/lib/proposalsApi'
import { createAbortSlot } from '@/lib/apiClient'
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
  { value: 'aToB' as const, label: t('gallery.tabs.aToB'), icon: mdiArrowLeftRight },
  { value: 'byStation' as const, label: t('gallery.tabs.byStation'), icon: mdiMapMarkerOutline },
  { value: 'byCountry' as const, label: t('gallery.tabs.byCountry'), icon: mdiEarth },
  { value: 'byRelation' as const, label: t('gallery.tabs.byRelation'), icon: mdiFlagOutline },
])

// Which source(s) the list shows. 'all' sends no `sources` key at all, which
// the backend reads as both.
type SourceChoice = 'all' | ProposalSourceKind
const sourceFilter = ref<SourceChoice>('all')
const SOURCE_CHOICES: readonly SourceChoice[] = ['all', 'proposal', 'existing']
const sourceOptions = computed(() =>
  SOURCE_CHOICES.map((value) => ({ value, label: t(`gallery.source.${value}`) })),
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
const selectedRelationFromName = computed(() =>
  relationFrom.value ? countryName(relationFrom.value) : null,
)
const selectedRelationToName = computed(() =>
  relationTo.value ? countryName(relationTo.value) : null,
)
// The stored "AT__DE" token, or null while the pair is incomplete or identical.
const relationToken = computed(() => buildRelationToken(relationFrom.value, relationTo.value))

const currentSort = computed<ProposalSort>(() => ({ by: sortField.value, dir: sortDir.value }))

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

// Set while a card is hovered; the map isolates and frames that row's route.
// One direction only — the map itself has no hover, because a corridor is
// shared by many rows and so names no single card.
const hoveredRow = ref<GalleryRowRef | null>(null)

// --- Hero sizing + scroll affordance ----------------------------------------
// The intro fills the viewport below whatever sits above it (App.vue's header,
// the API status banner, the page padding), so scrolled to the top a visitor
// sees the pitch and nothing else. Measured rather than hardcoded: the header
// carries a background image, and the status banner appears and disappears, so
// the offset is not a constant — a ResizeObserver keeps it honest.
const hero = ref<HTMLElement | null>(null)
const gallerySection = ref<HTMLElement | null>(null)
const heroMinHeight = ref('100vh')
let heroObserver: ResizeObserver | null = null

// The scroll cue has done its job the moment the reader starts scrolling, and
// left on screen it just follows them down the page. Faded rather than removed
// so it comes back the same way it left when they scroll home.
const scrolled = ref(false)
function onScroll(): void {
  scrolled.value = window.scrollY > 24
}

// The cue sits this far above the foot of the viewport — far enough from the
// copy to read as "there is more below" rather than as another line of it.
// Once the cue fades, that band is dead space between the hero and the gallery,
// so the gallery reclaims exactly it (see the negative margin in the template).
const HERO_CUE_SPACE_VH = 16
// Breathing room left above the gallery heading when the cue is clicked;
// landing flush against the viewport edge reads as a cut-off page.
const GALLERY_SCROLL_MARGIN_PX = 32

// Both ends of the reclaim, so the band is described in exactly one place.
const heroCueSpace = { paddingBottom: `${HERO_CUE_SPACE_VH}vh` }
const galleryShift = computed(() => ({
  marginTop: scrolled.value ? `-${HERO_CUE_SPACE_VH}vh` : '0px',
}))

function measureHero(): void {
  if (!hero.value) return
  const top = hero.value.getBoundingClientRect().top + window.scrollY
  heroMinHeight.value = `calc(100vh - ${Math.max(0, Math.round(top))}px)`
}

function scrollToGallery(): void {
  const target = gallerySection.value
  if (!target) return
  // The click itself flips `scrolled`, which pulls the gallery up by the band
  // the cue was occupying. Aim at where the heading will END UP, not where it
  // is now — the reclaim animates, so measuring again mid-scroll wouldn't see
  // the final position either.
  const reclaimed = scrolled.value ? 0 : (window.innerHeight * HERO_CUE_SPACE_VH) / 100
  const top = target.getBoundingClientRect().top + window.scrollY
  window.scrollTo({ top: top - reclaimed - GALLERY_SCROLL_MARGIN_PX, behavior: 'smooth' })
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
    ...seedToQuery(searchSeed.value),
    sort: sortField.value,
    dir: sortDir.value,
  }
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

  measureHero()
  // Watches the whole document rather than the hero itself: what moves the hero
  // is everything ABOVE it changing height (header image loading, status banner
  // appearing), which an observer on the hero would never see.
  heroObserver = new ResizeObserver(measureHero)
  heroObserver.observe(document.body)
  window.addEventListener('resize', measureHero)
  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()

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
}
onBeforeUnmount(() => {
  teardown()
  heroObserver?.disconnect()
  heroObserver = null
  window.removeEventListener('resize', measureHero)
  window.removeEventListener('scroll', onScroll)
})
onDeactivated(teardown)

// Coming back to a cached gallery. Deliberately does NOT re-run onMounted's
// hydrate-and-load: the whole point is that a there-and-back trip costs zero
// requests. Only a proposal published in the meantime forces a refresh.
onActivated(() => {
  if (sentinel.value && observer) observer.observe(sentinel.value)
  // The layout above the hero can have changed while this was cached.
  measureHero()
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
</script>

<template>
  <!-- -mb-6 trims App.vue's py-12 page padding to 24px below this page's last
       row, which is what stops the sticky map from being pushed up at the end of
       the scroll — see the results row's comment below. Keep the two in sync: if
       App.vue's bottom padding changes, this offset has to change with it. -->
  <div class="-mb-6 flex w-full max-w-6xl flex-col gap-6">
    <!-- Page intro, sized to fill whatever is left of the viewport below the
         site header (measured, not guessed — see heroMinHeight) so a fresh
         visitor sees the pitch and nothing else. The gallery owns its own h1
         (App.vue's centered one steps aside for this route): the question and
         the action it leads to on the left, the copy that answers it on the
         right. -->
    <!-- Two bands, not one centred stack: the copy takes all the room left over
         and the cue keeps a fixed distance from the foot of the viewport
         (heroCueSpace). Centring both together is what previously glued the cue
         to the copy and left the leftover height dumped below it. -->
    <!-- Deliberately NOT `relative`: it had no absolutely-positioned child to
         anchor, and a positioned element paints in a later phase than static
         in-flow content — so it covered the search bar that galleryShift pulls
         up into its padding band below, swallowing every click on the mode
         tabs once the page was scrolled. -->
    <section
      ref="hero"
      class="flex w-full flex-col"
      :style="{ minHeight: heroMinHeight, ...heroCueSpace }"
    >
      <!-- my-auto rather than flex-1: it centres the row in the space the cue
           leaves without turning items-start into a cross-axis centre, which
           would drag the two columns out of alignment with each other. -->
      <div class="my-auto flex items-start gap-12 px-24">
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

      <!-- Scroll affordance: without it the page looks like it ends here. -->
      <button
        type="button"
        class="flex cursor-pointer flex-col items-center gap-0.5 self-center text-sm text-primary-50/60 transition-opacity duration-300 hover:text-primary-50"
        :class="scrolled ? 'pointer-events-none opacity-0' : 'opacity-100'"
        :aria-hidden="scrolled"
        :tabindex="scrolled ? -1 : 0"
        @click="scrollToGallery"
      >
        {{ t('gallery.browse') }}
        <AppIcon :path="mdiChevronDown" :size="22" class="animate-bounce" />
      </button>
    </section>

    <!-- The gallery proper: search bar, result count, then the list + map.
         Rises into the band the scroll cue vacates (galleryShift) so the fade
         doesn't just leave a hole where the cue used to be. -->
    <div
      ref="gallerySection"
      class="flex flex-col items-center gap-1 transition-[margin-top] duration-500 ease-out"
      :style="galleryShift"
    >
      <h2 class="text-4xl font-light text-primary-50">{{ t('gallery.section.title') }}</h2>
      <p class="text-sm text-primary-50/60">{{ t('gallery.section.subtitle') }}</p>
    </div>

    <!-- Search bar. `relative z-10` because this block is pulled up into the
         hero's reserved cue band by galleryShift and therefore genuinely
         overlaps it — the stacking context is what keeps the mode tabs
         clickable there, whatever the hero above is positioned as. Removing
         it re-breaks tab switching for anyone who has scrolled. -->
    <div class="relative z-10 flex flex-col items-center gap-4">
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

        <div v-if="proposals.length" class="flex flex-col gap-4">
          <ProposalCard
            v-for="p in proposals"
            :key="proposalKey(p)"
            :proposal="p"
            :highlight-stop-ids="highlightStopIds"
            @select="openProposal"
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
            :corridors="corridors"
            :routes="routeFeatures"
            :highlighted-row="hoveredRow"
          />
        </div>
      </div>
    </div>
  </div>
</template>
