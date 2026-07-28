<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Select from 'primevue/select'
import { mdiArrowLeftRight, mdiMapMarkerOutline, mdiEarth, mdiMagnify, mdiPlus } from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import StopSelect from '@/components/StopSelect.vue'
import ProposalCard from '@/components/ProposalCard.vue'
import GalleryMap from '@/components/GalleryMap.vue'
import { useStore } from '@/stores/store'
import { fetchProposals, fetchProposalRoute, ProposalsError } from '@/lib/proposalsApi'
import type {
  Stop,
  ProposalSummary,
  ProposalsRequest,
  ProposalsFilter,
  ProposalSort,
  ProposalSortKey,
  GalleryMapRoute,
} from '@/types/api'

const emit = defineEmits<{ create: [] }>()

const { t } = useI18n()
const store = useStore()

const LIMIT = 20

type SearchMode = 'aToB' | 'byStation' | 'byCountry'
const mode = ref<SearchMode>('aToB')

// Search inputs (kept per-mode; buildFilter() only reads the active mode's).
const fromStop = ref<Stop | null>(null)
const toStop = ref<Stop | null>(null)
const stationStop = ref<Stop | null>(null)
const countryCode = ref<string | null>(null)

// Encoded "<by>:<dir>" so the Select can use a primitive option-value.
const sortValue = ref('margin_eur:desc')

// Result list (accumulated across pages) + pagination bookkeeping.
const proposals = ref<ProposalSummary[]>([])
const total = ref(0)
const offset = ref(0)
const loading = ref(false)
const initialized = ref(false)
const errorMsg = ref<string | null>(null)
const sentinel = ref<HTMLElement | null>(null)

const tabs = computed(() => [
  { value: 'aToB' as const, label: t('gallery.tabs.aToB'), icon: mdiArrowLeftRight },
  { value: 'byStation' as const, label: t('gallery.tabs.byStation'), icon: mdiMapMarkerOutline },
  { value: 'byCountry' as const, label: t('gallery.tabs.byCountry'), icon: mdiEarth },
])

const sortOptions = computed(() => [
  { value: 'margin_eur:desc', label: t('gallery.sort.marginDesc') },
  { value: 'margin_eur:asc', label: t('gallery.sort.marginAsc') },
  { value: 'total_revenue_eur:desc', label: t('gallery.sort.revenueDesc') },
  { value: 'total_cost_eur:asc', label: t('gallery.sort.costAsc') },
  { value: 'created_at:desc', label: t('gallery.sort.newest') },
  { value: 'created_at:asc', label: t('gallery.sort.oldest') },
  { value: 'total_distance_km:desc', label: t('gallery.sort.longestDistance') },
  { value: 'total_distance_km:asc', label: t('gallery.sort.shortestDistance') },
])

// Distinct country codes present in the loaded stops (reactive — stops load
// asynchronously after mount).
const countryOptions = computed(() =>
  [...new Set(store.stops.map((s) => s.country_code))]
    .sort()
    .map((code) => ({ value: code, label: code })),
)

const currentSort = computed<ProposalSort>(() => {
  const [by, dir] = sortValue.value.split(':')
  return { by: by as ProposalSortKey, dir: dir === 'asc' ? 'asc' : 'desc' }
})

const reachedEnd = computed(() => initialized.value && proposals.value.length >= total.value)

// Map the active search mode + inputs to a backend filter. All backend filters
// are OR/any-match; "From A to B" therefore sends both stop_ids as an
// approximation (routes touching either stop), not a strict A→B connection.
function buildFilter(): ProposalsFilter | undefined {
  if (mode.value === 'aToB') {
    const ids = [fromStop.value?.stop_id, toStop.value?.stop_id].filter((id): id is string =>
      Boolean(id),
    )
    return ids.length ? { stop_ids: ids } : undefined
  }
  if (mode.value === 'byStation') {
    return stationStop.value ? { stop_ids: [stationStop.value.stop_id] } : undefined
  }
  return countryCode.value ? { countries: [countryCode.value] } : undefined
}

async function loadPage(): Promise<void> {
  if (loading.value) return
  loading.value = true
  errorMsg.value = null
  const requestOffset = offset.value
  try {
    const body: ProposalsRequest = {
      sort: [currentSort.value],
      limit: LIMIT,
      offset: requestOffset,
    }
    const filter = buildFilter()
    if (filter) body.filter = filter

    const res = await fetchProposals(body)
    proposals.value = requestOffset === 0 ? res.proposals : [...proposals.value, ...res.proposals]
    total.value = res.total
    offset.value = requestOffset + res.proposals.length
    initialized.value = true
  } catch (err) {
    errorMsg.value = err instanceof ProposalsError ? err.message : t('gallery.error')
  } finally {
    loading.value = false
  }
}

// A filter/sort change starts a fresh query from offset 0.
function resetAndLoad(): void {
  proposals.value = []
  total.value = 0
  offset.value = 0
  initialized.value = false
  loadPage()
}

function onSentinel(): void {
  if (loading.value || !initialized.value || reachedEnd.value) return
  loadPage()
}

// --- Map: draw every result's route --------------------------------------
// Summaries carry no geometry (stripped server-side), so each proposal's route
// is fetched once via GET /api/proposal/<id> and cached by id+version. The map
// shows the routes for whatever is currently loaded, growing with the list.
const proposalKey = (p: ProposalSummary) => `${p.proposal_id}-${p.proposal_version}`
// `routed` separates a real routed geometry (many points per leg) from a
// straight-line stand-in (e.g. the seed proposal) — only routed ones map.
type CachedRoute = GalleryMapRoute & { routed: boolean }
const routeCache = ref<Record<string, CachedRoute>>({})
const mapRoutes = computed(() =>
  proposals.value
    .map((p) => routeCache.value[proposalKey(p)])
    .filter((r): r is CachedRoute => Boolean(r) && r.routed),
)

async function ensureRoutes(list: ProposalSummary[]): Promise<void> {
  const missing = list.filter((p) => !routeCache.value[proposalKey(p)])
  if (!missing.length) return
  const loaded = await Promise.all(
    missing.map(async (p) => {
      try {
        const { route } = (await fetchProposalRoute(p.proposal_id)).route_body
        const stops: GalleryMapRoute['stops'] = []
        for (const pair of route.trip_pairs) {
          const segs = pair.outbound.segments
          if (!segs.length) continue
          const first = segs[0].from_stop
          const last = segs[segs.length - 1].to_stop
          stops.push(
            { lat: first.lat, lon: first.lon, name: first.stop_name },
            { lat: last.lat, lon: last.lon, name: last.stop_name },
          )
        }
        const lines = route.geometries.map((g) => g.coords)
        const entry: CachedRoute = {
          key: proposalKey(p),
          lines,
          stops,
          // A routed leg carries many intermediate points; a straight-line
          // stand-in is just its two endpoints.
          routed: lines.some((l) => l.length > 2),
        }
        return entry
      } catch {
        return null
      }
    }),
  )
  const add: Record<string, CachedRoute> = {}
  for (const entry of loaded) if (entry) add[entry.key] = entry
  if (Object.keys(add).length) routeCache.value = { ...routeCache.value, ...add }
}

// Hovering a route on the map scrolls its card into view and flashes its
// background briefly. Deduped so the continuous mousemove stream over one route
// only fires once (until the pointer leaves and re-enters).
const cardsContainer = ref<HTMLElement | null>(null)
const flashedKey = ref<string | null>(null)
let lastScrolledKey: string | null = null
let flashTimer: number | undefined
function onHoverRoute(key: string | null): void {
  if (!key) {
    lastScrolledKey = null
    return
  }
  if (key === lastScrolledKey) return
  lastScrolledKey = key
  cardsContainer.value
    ?.querySelector<HTMLElement>(`[data-proposal="${key}"]`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  flashedKey.value = key
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    flashedKey.value = null
  }, 900)
}

watch([mode, fromStop, toStop, stationStop, countryCode, sortValue], resetAndLoad)
watch(proposals, ensureRoutes)

let observer: IntersectionObserver | null = null
onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) onSentinel()
    },
    { rootMargin: '300px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
  resetAndLoad()
})
onBeforeUnmount(() => observer?.disconnect())

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
  <div class="flex w-full flex-col gap-6">
    <!-- Top-right CTA into the route planner -->
    <div class="flex justify-end">
      <button type="button" :class="ctaClass" @click="emit('create')">
        <AppIcon :path="mdiPlus" :size="18" />
        {{ t('gallery.cta.create') }}
      </button>
    </div>

    <!-- Search bar -->
    <div class="flex flex-col items-center gap-4">
      <!-- Category tabs -->
      <div class="flex overflow-hidden rounded-full border border-primary-50/20">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          type="button"
          class="flex cursor-pointer items-center gap-1.5 px-4 py-2 text-sm leading-none transition"
          :class="
            mode === tab.value
              ? 'bg-primary-50/20 text-primary-50'
              : 'text-primary-50/60 hover:bg-primary-50/10'
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
          <StopSelect :stops="store.stops" @select="fromStop = $event">
            <div class="flex flex-col rounded-full px-4 py-1.5 hover:bg-primary-50/10">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.from')
              }}</span>
              <span class="text-sm" :class="fromStop ? 'text-primary-50' : 'text-primary-50/40'">
                {{ fromStop?.name ?? t('gallery.search.fromPlaceholder') }}
              </span>
            </div>
          </StopSelect>
          <div class="h-8 w-px bg-primary-50/15"></div>
          <StopSelect :stops="store.stops" @select="toStop = $event">
            <div class="flex flex-col rounded-full px-4 py-1.5 hover:bg-primary-50/10">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.to')
              }}</span>
              <span class="text-sm" :class="toStop ? 'text-primary-50' : 'text-primary-50/40'">
                {{ toStop?.name ?? t('gallery.search.toPlaceholder') }}
              </span>
            </div>
          </StopSelect>
        </template>

        <!-- By Station: one stop input -->
        <template v-else-if="mode === 'byStation'">
          <StopSelect :stops="store.stops" @select="stationStop = $event">
            <div class="flex flex-col rounded-full px-4 py-1.5 hover:bg-primary-50/10">
              <span class="text-xs font-semibold text-primary-50">{{
                t('gallery.search.station')
              }}</span>
              <span class="text-sm" :class="stationStop ? 'text-primary-50' : 'text-primary-50/40'">
                {{ stationStop?.name ?? t('gallery.search.stationPlaceholder') }}
              </span>
            </div>
          </StopSelect>
        </template>

        <!-- By Country: a country select -->
        <template v-else>
          <div class="flex flex-col px-4 py-1.5">
            <span class="text-xs font-semibold text-primary-50">{{
              t('gallery.search.country')
            }}</span>
            <Select
              v-model="countryCode"
              :options="countryOptions"
              option-value="value"
              option-label="label"
              :placeholder="t('gallery.search.countryPlaceholder')"
              :unstyled="true"
              :pt="selectPt"
            />
          </div>
        </template>

        <!-- Search button -->
        <button
          type="button"
          class="flex cursor-pointer items-center justify-center rounded-full bg-primary-500 p-3 text-white transition hover:bg-primary-600"
          :aria-label="t('gallery.search.button')"
          @click="resetAndLoad"
        >
          <AppIcon :path="mdiMagnify" :size="20" />
        </button>
      </div>
    </div>

    <!-- Sort control -->
    <div class="flex items-center gap-2">
      <span class="text-sm text-primary-50/50">{{ t('gallery.sort.label') }}</span>
      <Select
        v-model="sortValue"
        :options="sortOptions"
        option-value="value"
        option-label="label"
        :unstyled="true"
        :pt="selectPt"
      />
    </div>

    <!-- Results: cards (left half, two per row) + map of every result route
         (right half, sticky while the card column scrolls) -->
    <div class="flex gap-6">
      <div class="flex w-1/2 flex-col gap-4">
        <p v-if="errorMsg" class="text-sm text-red-400">{{ errorMsg }}</p>

        <div v-if="proposals.length" ref="cardsContainer" class="columns-2 gap-4">
          <div
            v-for="p in proposals"
            :key="proposalKey(p)"
            :data-proposal="proposalKey(p)"
            class="mb-4 break-inside-avoid"
          >
            <ProposalCard :proposal="p" :flash="flashedKey === proposalKey(p)" />
          </div>
        </div>
        <p v-else-if="initialized && !loading" class="py-8 text-center text-sm text-primary-50/50">
          {{ t('gallery.empty') }}
        </p>

        <!-- Infinite-scroll sentinel + status -->
        <div ref="sentinel" class="flex h-8 items-center justify-center text-sm text-primary-50/40">
          <span v-if="loading">{{
            initialized ? t('gallery.loadingMore') : t('gallery.loading')
          }}</span>
          <span v-else-if="reachedEnd && proposals.length">{{
            t('gallery.end', { count: total })
          }}</span>
        </div>

        <!-- Trailing CTA -->
        <div class="flex justify-center pb-4">
          <button type="button" :class="ctaClass" @click="emit('create')">
            <AppIcon :path="mdiPlus" :size="18" />
            {{ t('gallery.cta.create') }}
          </button>
        </div>
      </div>

      <div class="w-1/2">
        <div class="sticky top-6 h-[70vh] overflow-hidden rounded-xl border border-primary-50/10">
          <GalleryMap :routes="mapRoutes" @hover-route="onHoverRoute" />
        </div>
      </div>
    </div>
  </div>
</template>
