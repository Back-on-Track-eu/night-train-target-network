<script setup lang="ts">
import {
  ref,
  computed,
  nextTick,
  onMounted,
  onBeforeUnmount,
  onActivated,
  onDeactivated,
  watch,
} from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import {
  mdiAccountOutline,
  mdiArrowRight,
  mdiChevronLeft,
  mdiChevronRight,
  mdiCityVariantOutline,
  mdiClose,
  mdiMapMarkerOutline,
  mdiEarth,
  mdiPlus,
  mdiSortAscending,
  mdiSortDescending,
  mdiSwapHorizontal,
  mdiTuneVariant,
} from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import AppSpinner from '@/components/AppSpinner.vue'
import LandingIntro from '@/components/LandingIntro.vue'
import OptionSelect, { type SelectOption } from '@/components/OptionSelect.vue'
import SearchField from '@/components/SearchField.vue'
import ProposalCard from '@/components/ProposalCard.vue'
import GalleryScenarioPanel from '@/components/GalleryScenarioPanel.vue'
import ScenarioSwitches from '@/components/ScenarioSwitches.vue'
import GalleryMap from '@/components/GalleryMap.vue'
import GalleryDistribution from '@/components/GalleryDistribution.vue'
import GalleryRangesChip from '@/components/GalleryRangesChip.vue'
import { useStore } from '@/stores/store'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { LG_MEDIA_QUERY, useMediaQuery } from '@/composables/useMediaQuery'
import { fetchDistributions, fetchMapCorridors, fetchProposals } from '@/lib/proposalsApi'
import { createAbortSlot } from '@/lib/apiClient'
import { ctaButtonClass } from '@/lib/ctaButtonClass'
import { docsFeedbackUrl, FEEDBACK_TOPIC_MISSING_STOP } from '@/lib/feedbackLink'
import { selectPillPt } from '@/lib/selectPillPt'
import { asApiFailure, isRetryable, type ApiFailure } from '@/lib/apiError'
import { stopMarkers, type GalleryRowRef, type GalleryStopMarker } from '@/lib/galleryMap'
import {
  SEARCH_KINDS,
  activePicks,
  anchorStopIds,
  cityOptions,
  searchFilter,
  type CityOption,
  type GallerySearchKind,
  type GallerySearchTab,
} from '@/lib/gallerySearch'
import {
  isTypicalNightTrain,
  rangesFromQuery,
  rangesToFilter,
  rangesToQuery,
  typicalNightTrainRanges,
  type GalleryRanges,
} from '@/lib/galleryRanges'
import { entersAtGallery, GALLERY_HASH } from '@/lib/galleryEntry'
import { TYPICAL_NIGHT_TRAIN } from '@/lib/typicalNightTrain'
import { useApiFailure } from '@/composables/useApiFailure'
import {
  seedToQuery,
  seedFromQuery,
  queryString,
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
  type DistributionsSection,
} from '@/types/api'

const { t, locale } = useI18n()
const store = useStore()
const { countryName, formatInt } = useLocaleFormat()
const route = useRoute()
const router = useRouter()
const { describe, report } = useApiFailure()

const LIMIT = 20

// Every page asks for its cards and the route behind each one (map_routes
// follows limit/offset, so the client accumulates it page by page). The
// corridor overview (map_lines) is NOT part of it: it aggregates the WHOLE
// filtered set, so its cost grows with the catalogue, and riding along with
// the first page let an unfiltered gallery time out before a single card
// showed. It is its own request per query instead — see loadCorridors().
const PAGE_SECTIONS: ProposalsSection[] = ['summaries', 'map_routes']

// The search bar: one TAB (station / city / country), one KIND (via = one
// place, from → to = two), and the picks per tab. There are no tabs on
// screen any more: one field lists every kind of place, and picking one sets
// the tab (see pickPlace). The model keeps its tabs because the backend's
// filter and the link format are per kind — and a pair is two places of the
// same kind, which is all the backend offers.
// lib/gallerySearch.ts maps the active tab's picks to the request filter.
const tab = ref<GallerySearchTab>('station')
const kind = ref<GallerySearchKind>('via')
const stopA = ref<Stop | null>(null)
const stopB = ref<Stop | null>(null)
const cityA = ref<CityOption | null>(null)
const cityB = ref<CityOption | null>(null)
const countryA = ref<string | null>(null)
const countryB = ref<string | null>(null)

// Current search-bar state, handed to "Suggest a new route" so the new
// proposal's itinerary can be prefilled from whatever the user was searching
// for instead of two arbitrary stops.
const searchSeed = computed<GallerySearchSeed>(() => ({
  tab: tab.value,
  kind: kind.value,
  stops: [stopA.value, stopB.value],
  cities: [cityA.value, cityB.value],
  countries: [countryA.value, countryB.value],
}))

// Stops the active search targets — handed to each card so it can pin the
// matched stop(s) as itinerary anchors, and to the map. A city anchors all
// its stops. Empty for a country search.
const highlightStopIds = computed(() => anchorStopIds(searchSeed.value))

// The countries the active search names, in pick order — the map tints their
// land outline. Empty for the stop-based tabs.
const highlightCountries = computed(() =>
  tab.value === 'country' ? activePicks(searchSeed.value, (p) => p.countries) : [],
)

// Sort as a field + direction. These stay the source of truth (the URL sync and
// the request body are both field+direction); the single Select below drives
// them through one combined "field:dir" value.
//
// Newest first is the default (decided 2026-10-04): the gallery opens on
// proposals, and what a returning reader wants to see is what came in since.
// Existing (ONTD) rows carry no timestamps, so the sourceFilter watcher below
// falls back to distance — the one column both sources carry — the moment
// the list shows existing trains alone.
const DEFAULT_SORT: { field: ProposalSortKey; dir: 'asc' | 'desc' } = {
  field: 'created_at',
  dir: 'desc',
}
const sortField = ref<ProposalSortKey>(DEFAULT_SORT.field)
const sortDir = ref<'asc' | 'desc'>(DEFAULT_SORT.dir)

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
// The overview's own request state, shown on the map rather than in the card
// column: the list is usable whether or not the corridors have arrived.
const corridorsStatus = ref<'idle' | 'loading' | 'failed'>('idle')

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
// The corridor overview runs beside the list under the same rules.
const corridorSlot = createAbortSlot()
let corridorSeq = 0
// And so do the histograms of the distribution panel.
const distributionSlot = createAbortSlot()
let distributionSeq = 0

const TAB_ICONS: Record<GallerySearchTab, string> = {
  station: mdiMapMarkerOutline,
  city: mdiCityVariantOutline,
  country: mdiEarth,
}
const kinds = computed(() =>
  SEARCH_KINDS.map((value) => ({ value, label: t(`gallery.kind.${value}`) })),
)
const fromTo = computed(() => kind.value === 'fromTo')
// The field labels: "Place" for "via", From / To for a pair.
const fieldLabelA = computed(() =>
  fromTo.value ? t('gallery.search.from') : t('gallery.search.place'),
)

// Existing trains alone on screen: neither the scenario (they run as they run
// today) nor ownership (nobody owns them) applies, so both controls grey out
// rather than pretend.
const existingOnly = computed(() => sourceFilter.value === 'existing')

// "Only mine": the same list narrowed to the signed-in account's own rows,
// via the backend's `user_ids` filter. Existing (ONTD) rows carry no user_id,
// so this is a proposals-only view by construction — hence the source switch
// below drops the toggle whenever it is showing existing trains alone.
const mineOnly = ref(false)
// Registered accounts only. A guest session carries a user_id too, so on
// identity alone the switch would silently filter to an anonymous user's
// proposals and never ask for anything — which reads as "Mine does nothing"
// to someone who has not logged in. Registering merges the guest's proposals
// into the account, so nothing is lost by asking.
const canFilterMine = computed(() => store.authChoice === 'user')

// Whose routes, as one pill-select in the chip row ("Everyone's" / "Mine").
// Picking "mine" goes through selectMine, which may ask for an account first.
const whoseOptions = computed(() => [
  { value: 'all', label: t('gallery.filter.all') },
  { value: 'mine', label: t('gallery.filter.mine') },
])
const whose = computed<string>({
  get: () => (mineOnly.value ? 'mine' : 'all'),
  set: (value) => {
    if (value === 'mine') selectMine()
    else mineOnly.value = false
  },
})

// The four range filters the distribution panel edits (lib/galleryRanges.ts:
// distance, duration, average speed, stops), asked of PROPOSALS only —
// existing trains always stay listed, they are the comparison. They open on
// the position paper's "typical night train" preset (500–2 000 km, 7–21 h,
// ≥ 50 km/h): the gallery shows the set the launch report counted, and the
// 9 000 km four-nighters and the 2 km city hops are one drag away, not in the
// way. The preset is the default a shared link need not spell out; anything
// else goes into the URL explicitly (rangesToQuery).
const ranges = ref<GalleryRanges>(typicalNightTrainRanges())
// The histograms the panel draws, one request per query beside the corridors.
const distributions = ref<DistributionsSection | null>(null)
const distributionsStatus = ref<'idle' | 'loading' | 'failed'>('idle')

// Set when "Mine" was clicked without an identity: the auth modal opens, and
// the filter is applied the moment an identity exists — the click meant "show
// mine", not "show me a login form". Cleared if the modal is dismissed.
const mineAfterAuth = ref(false)

function selectMine(): void {
  if (!canFilterMine.value) {
    // Signed out or a guest: the click opens the login / registration modal
    // (standalone context — no "continue as guest" fork, that one belongs to
    // the evaluation gate) and the filter applies once the account exists.
    mineAfterAuth.value = true
    store.openAuthModal({ context: 'standalone' })
    return
  }
  applyMine()
}

function applyMine(): void {
  // Unreachable while the list shows existing trains alone — the switch is
  // disabled then — but an intent remembered across a login could land here
  // after the source moved, and "mine" on ONTD rows is an empty list.
  if (existingOnly.value) return
  mineOnly.value = true
}

watch(canFilterMine, (can) => {
  if (can && mineAfterAuth.value) {
    mineAfterAuth.value = false
    applyMine()
  }
})
watch(
  () => store.authModal.open,
  (open) => {
    // Closed without signing in: the intent dies with the modal.
    if (!open && !canFilterMine.value) mineAfterAuth.value = false
  },
)

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
// the backend reads as both. Proposals are the default (decided 2026-10-04):
// they are what the gallery exists to collect; the existing network is the
// comparison, one click away.
type SourceChoice = 'all' | ProposalSourceKind
const DEFAULT_SOURCE: SourceChoice = 'proposal'
const SOURCE_CHOICES: readonly SourceChoice[] = ['all', 'proposal', 'existing']
const sourceFilter = ref<SourceChoice>(DEFAULT_SOURCE)
// On screen in this order: the default first, "both" last.
const sourceOptions = computed(() =>
  (['proposal', 'existing', 'all'] as const).map((value) => ({
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
  () => store.userId,
  (next, previous) => {
    // Only a change from one identity to ANOTHER can relabel a listed row
    // (the guest merge). Restoring a session on boot (null → id) and
    // signing out (id → null) leave every proposer line as it was — and the
    // boot case ran after this page's own first load, so it used to fire a
    // second full request on every cold start.
    if (hydrating || previous === null || next === null) return
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
const countryOptions = computed<SelectOption[]>(() =>
  [...new Set(store.stops.map((s) => s.country_code))]
    .map((code) => ({ key: code, label: countryName(code) }))
    .sort((a, b) => a.label.localeCompare(b.label)),
)
// Cities, grouped from the same store (lib/gallerySearch.ts). The search text
// carries every catalogue-language name, like StopSelect does, so "Monaco"
// finds München on the English UI too.
const cities = computed(() => cityOptions(store.stops, locale.value))
const cityPickerOptions = computed<SelectOption[]>(() =>
  cities.value.map((c) => ({
    key: String(c.osm_id),
    label: c.name,
    subtitle: countryName(c.country_code),
    haystack: [c.name, ...Object.values(c.names), countryName(c.country_code)]
      .join('\u0000')
      .toLowerCase(),
  })),
)
const cityById = (key: string): CityOption | null =>
  cities.value.find((c) => String(c.osm_id) === key) ?? null

// Every station, the same search text StopSelect.vue builds (names in every
// catalogue language, so "Monaco" finds München Hbf on the English UI too)
// and its "city · country" second line.
const stationPickerOptions = computed<SelectOption[]>(() =>
  store.stops.map((s) => {
    const city = s.city ? s.city.names[locale.value] || s.city.names.en || s.city.name : ''
    const country = s.country_names?.[locale.value] || s.country_names?.en || s.country_code
    const parts = [s.name, s.name_latin, s.name_ascii, country]
    if (s.city) parts.push(s.city.name, ...Object.values(s.city.names))
    if (s.country_names) parts.push(...Object.values(s.country_names))
    return {
      key: s.stop_id,
      label: s.name,
      subtitle: city ? `${city} \u00b7 ${country}` : country,
      haystack: parts.filter(Boolean).join('\u0000').toLowerCase(),
    }
  }),
)

// The one place field's options: countries, cities, stations, each under its
// heading, keyed "tab:id". A pair is two places of one kind, so while the
// OTHER field of a pair holds a pick, this one offers only that kind.
const PLACE_TABS: readonly GallerySearchTab[] = ['country', 'city', 'station']
function placeOptions(slot: 0 | 1): SelectOption[] {
  const other = fromTo.value && pickLabel(slot === 0 ? 1 : 0) !== null
  const byTab: Record<GallerySearchTab, SelectOption[]> = {
    country: countryOptions.value,
    city: cityPickerOptions.value,
    station: stationPickerOptions.value,
  }
  return PLACE_TABS.filter((kindOfPlace) => !other || kindOfPlace === tab.value).flatMap(
    (kindOfPlace) =>
      byTab[kindOfPlace].map((o) => ({
        ...o,
        key: `${kindOfPlace}:${o.key}`,
        group: t(`gallery.search.groups.${kindOfPlace}`),
      })),
  )
}
// Placeholder of a field: any kind of place, or the kind the pair is in.
function placePlaceholder(slot: 0 | 1): string {
  const other = fromTo.value && pickLabel(slot === 0 ? 1 : 0) !== null
  return other ? t(`gallery.search.${tab.value}Placeholder`) : t('gallery.search.placePlaceholder')
}
// A pick of another kind than the current tab starts the search over in that
// kind — the picks of the old one would otherwise come back with it.
function pickPlace(slot: 0 | 1, key: string): void {
  const sep = key.indexOf(':')
  const kindOfPlace = key.slice(0, sep) as GallerySearchTab
  const id = key.slice(sep + 1)
  if (kindOfPlace !== tab.value) {
    stopA.value = stopB.value = null
    cityA.value = cityB.value = null
    countryA.value = countryB.value = null
    tab.value = kindOfPlace
  }
  if (kindOfPlace === 'station') {
    ;[stopA, stopB][slot].value = store.stops.find((s) => s.stop_id === id) ?? null
  } else if (kindOfPlace === 'city') {
    ;[cityA, cityB][slot].value = cityById(id)
  } else {
    ;[countryA, countryB][slot].value = id
  }
}

// What each field shows, and what the chip on the map repeats.
const pickLabel = (slot: 0 | 1): string | null => {
  if (tab.value === 'station') return [stopA, stopB][slot].value?.name ?? null
  if (tab.value === 'city') return [cityA, cityB][slot].value?.name ?? null
  const code = [countryA, countryB][slot].value
  return code ? countryName(code) : null
}
const labelA = computed(() => pickLabel(0))
const labelB = computed(() => pickLabel(1))
// The map's top-left chip: the tab's icon and the search in words, for every
// tab. A pair is joined with ↔, not the switch's →: the filter is both places
// touched in either direction, and the chip states the filter, not the UI.
const searchSummary = computed(() => {
  const a = labelA.value
  const b = fromTo.value ? labelB.value : null
  const place = a ?? b
  if (!place) return null
  const text =
    a && b
      ? t('gallery.map.highlight.pair', { from: a, to: b })
      : t('gallery.map.highlight.via', { place })
  return { icon: TAB_ICONS[tab.value], text }
})
// From and to change places. The filter is the same either way (both places
// touched, in either direction); the swap is for the reader's own sense of
// the trip, and for the builder, which the pair prefills in this order.
function swapPicks(): void {
  ;[stopA.value, stopB.value] = [stopB.value, stopA.value]
  ;[cityA.value, cityB.value] = [cityB.value, cityA.value]
  ;[countryA.value, countryB.value] = [countryB.value, countryA.value]
}
// Whose routes as the bar's last suffix, on a desktop: the pill-select's
// options, without its border — the rule before it separates it.
const whoseBarPt = {
  ...selectPillPt,
  root: {
    class:
      'flex h-11 cursor-pointer items-center rounded-full bg-transparent transition hover:bg-primary-50/10',
  },
}
// The kind switch as a "Via ▾" menu at the start of the field, on a phone.
const kindMenuPt = {
  ...selectPillPt,
  root: {
    class:
      'flex h-11 shrink-0 cursor-pointer items-center border-r border-primary-50/15 pl-3 bg-transparent',
  },
  label: { class: 'text-sm font-semibold text-primary-50 leading-none' },
  dropdown: { class: 'flex items-center px-2 text-primary-50/60' },
}
function clearPick(slot: 0 | 1): void {
  if (tab.value === 'station') [stopA, stopB][slot].value = null
  else if (tab.value === 'city') [cityA, cityB][slot].value = null
  else [countryA, countryB][slot].value = null
}

const currentSort = computed<ProposalSort>(() => ({
  by: sortField.value,
  dir: sortDir.value,
}))

const reachedEnd = computed(() => initialized.value && proposals.value.length >= total.value)

// "Reset" shows only once a filter differs from what the gallery opens on:
// no place, proposals, everyone's, the typical night trains. Sort and
// scenario are not filters — they change the order and the figures, never
// which routes are listed.
const filtersAtDefault = computed(
  () =>
    pickLabel(0) === null &&
    pickLabel(1) === null &&
    sourceFilter.value === DEFAULT_SOURCE &&
    !mineOnly.value &&
    isTypicalNightTrain(ranges.value),
)
function resetFilters(): void {
  stopA.value = stopB.value = null
  cityA.value = cityB.value = null
  countryA.value = countryB.value = null
  tab.value = 'station'
  kind.value = 'via'
  sourceFilter.value = DEFAULT_SOURCE
  mineOnly.value = false
  ranges.value = typicalNightTrainRanges()
}

// The range panel: opened under the search bar on a desktop — it costs the map
// its height (measureRow) only while the reader is actually editing — and in
// the Filters sheet on a phone (below lg the chip row gives way to one
// Filters button).
const rangesOpen = ref(false)
const filtersOpen = ref(false)
// Which screen of the Filters sheet is up: the overview, or one of the two
// that need room of their own. Every opening starts on the overview.
const sheetView = ref<'main' | 'ranges' | 'scenario'>('main')
function openFilters(): void {
  sheetView.value = 'main'
  filtersOpen.value = true
}
const sheetHeadingClass = 'text-xs font-semibold tracking-wider text-primary-50/60 uppercase'

// The sheet's preset switch — the same preset GalleryDistribution's pill
// toggles: on is "the ranges equal it", off clears every range.
const typicalOn = computed(() => isTypicalNightTrain(ranges.value))
function toggleTypical(): void {
  ranges.value = typicalOn.value ? {} : typicalNightTrainRanges()
}
const typicalValues = computed(() => {
  const n = TYPICAL_NIGHT_TRAIN
  return [
    `${formatInt(n.distanceKm.min)}–${formatInt(n.distanceKm.max)} km`,
    `${n.timeH.min}–${n.timeH.max} h`,
    `≥ ${n.avgSpeedKmh.min} km/h`,
  ].join(' · ')
})

// Map the search bar + switches to a backend filter. The search bar's part
// lives in lib/gallerySearch.ts (searchFilter), where it is tested.
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

  Object.assign(base, rangesToFilter(ranges.value))
  Object.assign(base, searchFilter(searchSeed.value))

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
      include: PAGE_SECTIONS,
      ...queryScope(),
    }

    const res = await fetchProposals(body, signal)
    if (seq !== requestSeq) return
    const summaries = res.summaries ?? { total: 0, proposals: [] }
    proposals.value = isFirstPage
      ? summaries.proposals
      : [...proposals.value, ...summaries.proposals]
    total.value = summaries.total
    shownTotal.value = summaries.total
    offset.value = requestOffset + summaries.proposals.length
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

// What a query asks for, independent of the page: the filter and the scenario
// variant. Shared by the list and the corridor overview, so the two always
// describe the same result set.
function queryScope(): Pick<ProposalsRequest, 'filter' | 'scenario_variant_id'> {
  const scope: Pick<ProposalsRequest, 'filter' | 'scenario_variant_id'> = {}
  const filter = buildFilter()
  if (filter) scope.filter = filter
  if (scenarioVariantId.value !== null) scope.scenario_variant_id = scenarioVariantId.value
  return scope
}

// The corridor overview for the current query. The previous query's corridors
// stay drawn until the new ones land (same reasoning as resetAndLoad below);
// a failure is reported on the map only — the cards are unaffected.
async function loadCorridors(): Promise<void> {
  corridorsStatus.value = 'loading'
  const seq = ++corridorSeq
  try {
    const res = await fetchMapCorridors(queryScope(), corridorSlot.begin())
    if (seq !== corridorSeq) return
    corridors.value = res.map_lines ?? null
    corridorsStatus.value = 'idle'
  } catch (err) {
    if (asApiFailure(err)?.kind === 'canceled' || seq !== corridorSeq) return
    corridorsStatus.value = 'failed'
  }
}

// The histograms for the current query, under the same rules as the
// corridors: the previous ones stay drawn until the new ones land, and a
// failure is reported in the panel only.
async function loadDistributions(): Promise<void> {
  distributionsStatus.value = 'loading'
  const seq = ++distributionSeq
  try {
    const res = await fetchDistributions(queryScope(), distributionSlot.begin())
    if (seq !== distributionSeq) return
    distributions.value = res.distributions ?? null
    distributionsStatus.value = 'idle'
  } catch (err) {
    if (asApiFailure(err)?.kind === 'canceled' || seq !== distributionSeq) return
    distributionsStatus.value = 'failed'
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
//
// The corridor overview and the histograms reload with it, except on a sort
// change: sorting reorders the cards but cannot change which corridors the
// result set covers or how it spreads.
function resetAndLoad({ corridors: withCorridors = true } = {}): void {
  offset.value = 0
  loadPage()
  if (withCorridors) {
    loadCorridors()
    loadDistributions()
  }
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

// Stop coordinates for the map's markers come from the stops store, which the
// search bar loads anyway; a gallery opened without a stop filter fetches it
// here so hovering a card can place its stops from the first card on.
const stopsById = computed(() => new Map(store.stops.map((s) => [s.stop_id, s])))
const hoveredSummary = computed(() => {
  const row = hoveredRow.value
  if (!row) return null
  return (
    proposals.value.find((p) =>
      row.kind === 'proposal'
        ? p.source === 'proposal' && p.proposal_id === row.id
        : p.source === 'existing' && p.route_id === row.id,
    ) ?? null
  )
})
const hoveredStops = computed(() =>
  stopMarkers(hoveredSummary.value?.stop_ids ?? [], stopsById.value),
)
// What the map pins: the searched station(s), or one pin per searched city at
// its centroid (its stops keep their own dots on hover, which is why the city
// marker carries no stop id a dot could be suppressed by).
const anchorStops = computed<GalleryStopMarker[]>(() => {
  if (tab.value === 'city') {
    return activePicks(searchSeed.value, (p) => p.cities).map((c) => ({
      stop_id: `city:${c.osm_id}`,
      name: c.name,
      lon: c.lon,
      lat: c.lat,
      city: true,
    }))
  }
  return stopMarkers(highlightStopIds.value, stopsById.value)
})

// LandingIntro's secondary call to action. The target lives here rather than in
// the intro because the intro has no business knowing what follows it.
const gallerySection = ref<HTMLElement | null>(null)
// Breathing room above the heading; landing flush against the viewport edge
// reads as a cut-off page.
const GALLERY_SCROLL_MARGIN_PX = 24

function scrollToGallery(behavior: 'smooth' | 'auto' = 'smooth'): void {
  const target = gallerySection.value
  if (!target) return
  const top = target.getBoundingClientRect().top + window.scrollY
  window.scrollTo({ top: top - GALLERY_SCROLL_MARGIN_PX, behavior })
}

// A reader who arrived FOR the gallery (lib/galleryEntry.ts) is put in front
// of it at once — no animation from the pitch, which they did not come to
// read. After the layout above has settled: the hero sizes itself on mount.
function openAtGalleryIfLinked(): void {
  if (!entersAtGallery(route.hash, route.query)) return
  requestAnimationFrame(() => scrollToGallery('auto'))
}

// --- Fitting the whole gallery into one screen ------------------------------
// From lg up, the results row — card column AND map — is exactly one viewport
// tall minus the gallery's own chrome (heading, tabs, search pill, gutters).
// Two things follow from that, and both are the point:
//
//   * the search bar stays on screen beside the map at 100% zoom, so changing a
//     filter and seeing the result costs no scrolling;
//   * the two columns are the same height, so the card column ends at the map's
//     bottom edge instead of running past it. The cards scroll INSIDE their
//     column (cardScroller below) rather than scrolling the page.
//
// Below lg there is no "beside": the map sits above the list at a fixed
// height and the cards run down the page, so the row takes no height budget
// and the list scrolls with the document — which is why the infinite-scroll
// observer below watches the viewport there, not the column.
//
// Measured, not hardcoded: the heading wraps at narrow widths and the search
// pill changes height with the active mode, so the chrome is not a constant.
const resultsRow = ref<HTMLElement | null>(null)
const cardScroller = ref<HTMLElement | null>(null)
// The one layout fact the template cannot settle on its own: the same
// breakpoint as the row's lg: classes, so the observer's root and the
// column's overflow never disagree about who scrolls.
const twoColumn = useMediaQuery(LG_MEDIA_QUERY)
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
  // Only off the default, so links stay short and an old link keeps meaning
  // "proposals".
  if (sourceFilter.value !== DEFAULT_SOURCE) query.src = sourceFilter.value
  Object.assign(query, rangesToQuery(ranges.value))
  // The SCENARIO, not the variant: the variant ids are materialised and can
  // be rebuilt, the scenario is what a shared link should still mean.
  if (galleryScenario.value && !galleryScenario.value.is_current_base) {
    query.scenario = String(galleryScenario.value.scenario_id)
  }
  return query
}

watch(
  [
    tab,
    kind,
    stopA,
    stopB,
    cityA,
    cityB,
    countryA,
    countryB,
    sourceFilter,
    mineOnly,
    ranges,
    // The variant, not the scenario id: the id resolves from null to the
    // base once the scenarios load, and that is not a change of what the
    // request asks for (both send nothing) — watching it reloaded the
    // whole gallery a second time on every cold start.
    scenarioVariantId,
    // Sort LAST: the callback tells a sort-only change (same result set, so
    // the corridors already drawn still apply) from one that moved the query.
    sortField,
    sortDir,
  ],
  (next, previous) => {
    if (hydrating) return
    const scopeChanged = next.slice(0, -2).some((value, i) => value !== previous[i])
    resetAndLoad({ corridors: scopeChanged })
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
// What the last teardown cancelled before it landed; onActivated resumes it.
const interrupted = { page: false, corridors: false }
// Watches the whole document, like LandingIntro's own band: what changes the
// chrome above the results row is mostly elements ABOVE the gallery (the
// header image loading, the API status banner appearing), which an observer on
// the row itself would never see.
let chromeObserver: ResizeObserver | null = null

// The infinite-scroll sentinel is watched against whatever scrolls the list:
// the card column from lg up, where it scrolls inside its own box (against the
// viewport the sentinel would either never intersect or intersect
// permanently), and the viewport below lg, where the column is just part of
// the page. A root is fixed at construction, so a layout change means a new
// observer — see the twoColumn watcher.
function observeSentinel(): void {
  observer?.disconnect()
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) onSentinel()
    },
    { root: twoColumn.value ? cardScroller.value : null, rootMargin: '300px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
}

// Only while on screen: a cached gallery re-attaches in onActivated anyway,
// and an observer built while the page is hidden would fire into nothing.
watch(twoColumn, () => {
  if (isActive.value) observeSentinel()
})

onMounted(async () => {
  observeSentinel()

  // The stops are needed either way — by the search bar, and by the map to
  // place a hovered row's stops — so they start loading at once. Only a link
  // that names a stop has to WAIT for them: hydrating the search bar from the
  // URL before the first query fires is what makes a shared or reloaded
  // /gallery?... link reproduce the exact same results.
  const stopsLoading = store.stopsStatus === 'success' ? null : store.fetchStops()
  const linkTab = queryString(route.query.tab) ?? queryString(route.query.mode)
  const namesStop =
    ['a', 'b', 'from', 'to', 'station'].some((k) => queryString(route.query[k])) &&
    linkTab !== 'country' &&
    linkTab !== 'byCountry' &&
    linkTab !== 'byRelation'
  if (namesStop && stopsLoading) await stopsLoading
  // Same for a scenario in the link: it can only be resolved against the
  // loaded scenarios, and resolving it after the first load would mean a
  // second one.
  if (queryString(route.query.scenario) && store.scenariosStatus !== 'success') {
    await store.fetchScenarios()
  }
  const seed = seedFromQuery(route.query, store.stops, cities.value)
  tab.value = seed.tab
  kind.value = seed.kind
  ;[stopA.value, stopB.value] = seed.stops
  ;[cityA.value, cityB.value] = seed.cities
  ;[countryA.value, countryB.value] = seed.countries
  const sortParam = queryString(route.query.sort)
  if (sortParam && (PROPOSAL_SORT_KEYS as readonly string[]).includes(sortParam)) {
    sortField.value = sortParam as ProposalSortKey
  }
  const dirParam = queryString(route.query.dir)
  if (dirParam === 'asc' || dirParam === 'desc') sortDir.value = dirParam
  const srcParam = queryString(route.query.src)
  if (srcParam && (SOURCE_CHOICES as readonly string[]).includes(srcParam)) {
    sourceFilter.value = srcParam as SourceChoice
  }
  // Resolves against whoever is signed in now — the account is deliberately
  // not part of the link.
  mineOnly.value = queryString(route.query.mine) === '1' && canFilterMine.value
  ranges.value = rangesFromQuery(route.query)
  const scenarioParam = Number(queryString(route.query.scenario))
  if (
    Number.isInteger(scenarioParam) &&
    store.scenarios.some((s) => s.scenario_id === scenarioParam)
  ) {
    galleryScenarioId.value = scenarioParam
  }

  // The assignments above reach the watcher on the next flush, so lift the
  // guard only after it: a link that sets any field (a range, a mode) would
  // otherwise load the gallery twice.
  await nextTick()
  hydrating = false
  resetAndLoad()
  // Read before the replace below drops the hash from the address bar.
  openAtGalleryIfLinked()
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
  // A load cut short here never lands, and a cancellation is silent by design
  // — so without remembering it, leaving before a query's first page arrived
  // came back to an empty (or stale) column with no skeleton, no count and no
  // retry. An interrupted APPEND needs nothing: the sentinel asks again.
  interrupted.page = loading.value && offset.value === 0
  interrupted.corridors =
    corridorsStatus.value === 'loading' || distributionsStatus.value === 'loading'
  // Drop everything in flight; their rejections are 'canceled' and stay silent.
  listSlot.cancel()
  corridorSlot.cancel()
  distributionSlot.cancel()
  if (interrupted.corridors) {
    corridorsStatus.value = 'idle'
    distributionsStatus.value = 'idle'
  }
}
onBeforeUnmount(teardown)
onDeactivated(teardown)

// Coming back to a cached gallery. Deliberately does NOT re-run onMounted's
// hydrate-and-load: the whole point is that a there-and-back trip costs zero
// requests. Only a proposal published in the meantime, or a load the teardown
// interrupted, forces a refresh.
onActivated(() => {
  isActive.value = true
  // Rebuilt rather than re-observed: the viewport may have crossed the
  // breakpoint while the gallery was cached, and the old root with it.
  observeSentinel()
  // The layout above can have changed while the gallery was cached, and the
  // teardown dropped both listeners — re-measure and re-attach them.
  measureRow()
  chromeObserver = new ResizeObserver(measureRow)
  chromeObserver.observe(document.body)
  window.addEventListener('resize', measureRow)
  if (store.galleryStale) {
    store.galleryStale = false
    resetAndLoad()
  } else if (interrupted.page) {
    resetAndLoad({ corridors: interrupted.corridors })
  } else if (interrupted.corridors) {
    loadCorridors()
    loadDistributions()
  }
  interrupted.page = interrupted.corridors = false
  // Back from a proposal (ProposalWorkspace pushes the hash): the gallery is
  // cached, so this is the moment it comes back into view. The hash has done
  // its job once read; the query stays as it was.
  if (route.hash === GALLERY_HASH) {
    requestAnimationFrame(() => scrollToGallery('auto'))
    router.replace({ query: route.query })
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
      class="mt-2 flex w-full flex-col gap-4 border-t border-primary-50/10 pt-6 lg:flex-row lg:items-center lg:justify-between"
    >
      <div class="flex flex-wrap items-baseline justify-center gap-x-3 lg:justify-start">
        <h2 class="text-2xl font-light text-primary-50">
          {{ t('gallery.section.title') }}
        </h2>
        <p class="text-sm text-primary-50/60">
          {{ t('gallery.section.subtitle') }}
        </p>
      </div>

      <!-- What to browse: suggested routes, the existing ONTD network, or
           both — always in view, never behind a menu: on a phone a row of its
           own under the heading, on a desktop at the heading's right end. -->
      <div
        class="mx-auto grid w-full max-w-md grid-cols-3 gap-1 rounded-full bg-primary-50/[0.06] p-1 lg:mx-0 lg:w-auto"
        role="group"
        :aria-label="t('gallery.source.label')"
      >
        <button
          v-for="option in sourceOptions"
          :key="option.value"
          type="button"
          class="min-h-10 cursor-pointer rounded-full px-3 text-sm whitespace-nowrap transition lg:px-5"
          :class="
            sourceFilter === option.value
              ? 'bg-primary-50/15 font-semibold text-primary-50'
              : 'text-primary-50/65 hover:text-primary-50'
          "
          :aria-pressed="sourceFilter === option.value"
          @click="sourceFilter = option.value"
        >
          {{ option.label }}
        </button>
      </div>
    </div>

    <!-- Search bar. `relative z-10` gives the pill dropdowns a stacking
         context of their own, so neither the intro above nor the sticky map
         column beside them can paint over the controls. -->
    <div class="relative z-10 flex flex-col items-center gap-2 lg:items-stretch">
      <!-- One bar: the kind switch inside it on the left, then one field or
           two. From sm up a row — the Via | From → to switch, the place (a
           search glyph, or "From" / "To" with a swap between a pair) — wider
           for a pair. From lg up it spans the page and ends on the other
           filters, the route length and whose routes, after a rule each. On a
           phone the switch is a "Via ▾" menu at the start of the field, a
           pair's "To" takes a second row under a rule, and the other filters
           live in the Filters sheet. No search button: every pick reloads the
           list by itself. -->
      <div
        class="flex w-full flex-col rounded-[1.75rem] border border-primary-50/20 bg-primary-50/[0.04] p-1 sm:flex-row sm:items-center sm:gap-1 sm:rounded-full sm:p-1.5 lg:max-w-none"
        :class="fromTo ? 'sm:max-w-[58.75rem]' : 'sm:max-w-[47.5rem]'"
      >
        <!-- The switch and the first field share a row on a phone; from sm up
             they are items of the bar itself (contents), so a pair's two
             fields split what the switch leaves evenly. -->
        <div class="flex min-w-0 flex-1 items-center gap-1 sm:contents">
          <!-- Via (one place) or from → to (two), for every kind of place. -->
          <div
            class="hidden h-11 shrink-0 gap-0.5 rounded-full bg-primary-50/[0.07] p-1 sm:flex"
            role="group"
            :aria-label="t('gallery.kind.label')"
          >
            <button
              v-for="item in kinds"
              :key="item.value"
              type="button"
              class="flex cursor-pointer items-center gap-1 rounded-full px-4 text-sm whitespace-nowrap transition"
              :class="
                kind === item.value
                  ? 'bg-primary-50/[0.18] font-semibold text-white'
                  : 'text-primary-50/70 hover:text-primary-50'
              "
              :aria-pressed="kind === item.value"
              @click="kind = item.value"
            >
              <template v-if="item.value === 'fromTo'">
                {{ t('gallery.search.from') }}
                <AppIcon :path="mdiArrowRight" :size="14" />
                {{ t('gallery.search.toLower') }}
              </template>
              <template v-else>{{ item.label }}</template>
            </button>
          </div>
          <Select
            v-model="kind"
            :options="kinds"
            option-value="value"
            option-label="label"
            :aria-label="t('gallery.kind.label')"
            :unstyled="true"
            :pt="kindMenuPt"
            class="sm:hidden"
          />
          <div class="flex min-w-0 flex-1 flex-col">
            <OptionSelect
              :options="placeOptions(0)"
              :placeholder="placePlaceholder(0)"
              :empty-text="t('gallery.search.noPlaces')"
              @select="pickPlace(0, $event)"
            >
              <SearchField
                :label="fieldLabelA"
                :show-label="fromTo"
                :value="labelA"
                :icon="TAB_ICONS[tab]"
                :placeholder="placePlaceholder(0)"
                @clear="clearPick(0)"
              />
              <template #empty="{ query }">
                <a
                  :href="docsFeedbackUrl(FEEDBACK_TOPIC_MISSING_STOP, query)"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="mt-1 block cursor-pointer text-sm font-semibold text-primary-50 underline underline-offset-2"
                >
                  {{ t('proposal.missingStopLink') }}
                </a>
              </template>
            </OptionSelect>
          </div>
        </div>
        <template v-if="fromTo">
          <div class="mx-3 my-1 h-px bg-primary-50/15 sm:hidden" />
          <button
            type="button"
            class="hidden h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full border border-primary-50/20 text-primary-50/80 transition hover:bg-primary-50/10 sm:flex"
            :aria-label="t('gallery.search.swap')"
            @click="swapPicks"
          >
            <AppIcon :path="mdiSwapHorizontal" :size="18" />
          </button>
          <div class="flex min-w-0 flex-1 flex-col">
            <OptionSelect
              :options="placeOptions(1)"
              :placeholder="placePlaceholder(1)"
              :empty-text="t('gallery.search.noPlaces')"
              @select="pickPlace(1, $event)"
            >
              <SearchField
                :label="t('gallery.search.to')"
                show-label
                :value="labelB"
                :icon="TAB_ICONS[tab]"
                :placeholder="placePlaceholder(1)"
                @clear="clearPick(1)"
              />
              <template #empty="{ query }">
                <a
                  :href="docsFeedbackUrl(FEEDBACK_TOPIC_MISSING_STOP, query)"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="mt-1 block cursor-pointer text-sm font-semibold text-primary-50 underline underline-offset-2"
                >
                  {{ t('proposal.missingStopLink') }}
                </a>
              </template>
            </OptionSelect>
          </div>
        </template>
        <span class="hidden h-7 w-px shrink-0 bg-primary-50/15 lg:block" aria-hidden="true" />
        <div class="hidden shrink-0 lg:flex">
          <GalleryRangesChip
            bar
            :ranges="ranges"
            :open="rangesOpen"
            @open="rangesOpen = !rangesOpen"
            @clear="ranges = {}"
          />
        </div>
        <span class="hidden h-7 w-px shrink-0 bg-primary-50/15 lg:block" aria-hidden="true" />
        <!-- Greyed, not hidden, while existing trains alone are listed: nobody
             owns an ONTD row, and a control that vanished with the source would
             be one nobody could find again. -->
        <div class="hidden shrink-0 lg:flex">
          <Select
            v-model="whose"
            :options="whoseOptions"
            option-value="value"
            option-label="label"
            :disabled="existingOnly"
            :title="existingOnly ? t('gallery.filter.disabledHint') : undefined"
            :aria-label="t('gallery.filter.label')"
            :unstyled="true"
            :pt="whoseBarPt"
            :class="existingOnly ? 'opacity-40' : ''"
          >
            <template #value="{ value }">
              <span class="flex items-center gap-1.5">
                <AppIcon :path="mdiAccountOutline" :size="16" />
                {{ whoseOptions.find((o) => o.value === value)?.label }}
              </span>
            </template>
          </Select>
        </div>
      </div>
      <!-- What the kind means, in one line — "from → to" is both places touched,
           in either direction, which a reader would otherwise take for end
           points. Reset joins it on a desktop once anything differs from the
           default (on a phone it is in the Filters sheet). -->
      <div class="flex w-full items-center justify-center gap-4 px-4 lg:justify-between lg:px-5">
        <p class="text-center text-xs text-primary-50/55 lg:text-left">
          {{ t(`gallery.kind.hint.${kind}`) }}
        </p>
        <button
          v-if="!filtersAtDefault"
          type="button"
          class="hidden cursor-pointer text-sm text-primary-50/75 underline underline-offset-2 transition hover:text-primary-50 lg:block"
          @click="resetFilters"
        >
          {{ t('gallery.filters.reset') }}
        </button>
      </div>
    </div>

    <div
      v-if="rangesOpen"
      class="hidden rounded-xl border border-primary-50/10 bg-primary-50/[0.03] p-5 lg:block"
    >
      <GalleryDistribution
        v-model:ranges="ranges"
        :distributions="distributions"
        :status="distributionsStatus"
        @retry="loadDistributions"
      />
    </div>

    <!-- How many the search matched, then what the list is read on and in
         what order — across both columns, above the cards AND the map, since
         it describes both. The loading state lives up here, where the eye is:
         a spinner and a word while any page is in flight, the count otherwise
         (see shownTotal). Below lg the scenario moves into the Filters sheet
         and a Filters button takes its place. -->
    <div
      class="flex min-h-10 flex-wrap items-center justify-between gap-2 lg:border-t lg:border-primary-50/10 lg:pt-3"
    >
      <span
        v-if="loading"
        class="flex items-center gap-1.5 text-sm text-primary-50/60"
        role="status"
      >
        <AppSpinner :size="14" />
        {{ t('gallery.loading') }}
      </span>
      <p v-else-if="shownTotal !== null && !failure" class="text-sm text-primary-50/60">
        {{ t('gallery.matching', shownTotal) }}
      </p>
      <span v-else></span>
      <div class="flex items-center gap-2">
        <div class="hidden lg:block">
          <GalleryScenarioPanel
            v-model="galleryScenarioId"
            :scenarios="store.scenarios"
            :without-figures="withoutFigures"
            :disabled="existingOnly"
          />
        </div>
        <button
          type="button"
          class="flex cursor-pointer items-center gap-1.5 rounded-full border border-primary-50/20 px-3 py-1.5 text-sm leading-none text-primary-50 transition hover:bg-primary-50/10 lg:hidden"
          aria-haspopup="dialog"
          @click="openFilters"
        >
          <AppIcon :path="mdiTuneVariant" :size="16" />
          {{ t('gallery.filters.open') }}
          <span v-if="!filtersAtDefault" class="h-1.5 w-1.5 rounded-full bg-primary-300" />
        </button>
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
            <!-- The field's name is spoken but not shown on a phone, where
                 the count, Filters and the sort share one line. -->
            <span v-if="selectedSortOption" class="flex items-center gap-1.5">
              <AppIcon :path="selectedSortOption.icon" :size="16" />
              <span class="sr-only">{{ selectedSortOption.dirLabel }}</span>
              <span class="max-sm:sr-only">{{ selectedSortOption.label }}</span>
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
    </div>

    <!-- Below lg: the filters that sit in the chip row on a desktop, plus the
         scenario, in a sheet from the bottom of the screen. Its first screen
         names each in one row — the ranges preset as a switch, whose routes,
         the scenario — and the two that need room (the four histograms, the
         scenario switches) open a screen of their own with a way back. Every
         control applies at once, like everywhere else on the page; the
         button at the foot only closes the sheet. -->
    <Teleport to="body">
      <!-- The backdrop fades while the sheet slides up from the bottom edge,
           and back down on close: one transition on the overlay, whose
           `sheet-closed` marker the panel reads (in-[.sheet-closed]) for its
           own slide. Both instant for readers who ask for reduced motion. -->
      <Transition
        enter-from-class="sheet-closed opacity-0"
        enter-active-class="transition-opacity duration-250 ease-out motion-reduce:transition-none"
        leave-active-class="transition-opacity duration-250 ease-in motion-reduce:transition-none"
        leave-to-class="sheet-closed opacity-0"
      >
        <div
          v-if="filtersOpen"
          class="fixed inset-0 z-50 flex items-end bg-black/50 lg:hidden"
          @click.self="filtersOpen = false"
          @keydown.esc="filtersOpen = false"
        >
          <div
            class="flex max-h-[90vh] w-full flex-col rounded-t-2xl border-t border-primary-50/15 bg-sapphire-200 transition-transform duration-250 ease-out in-[.sheet-closed]:translate-y-full motion-reduce:transition-none"
            role="dialog"
            aria-modal="true"
            :aria-label="t('gallery.filters.title')"
          >
            <div
              class="flex items-center gap-1 py-2 pr-2 pl-5"
              :class="sheetView !== 'main' ? 'pl-1' : ''"
            >
              <button
                v-if="sheetView !== 'main'"
                type="button"
                class="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full text-primary-50/80 transition hover:bg-primary-50/10"
                :aria-label="t('gallery.filters.back')"
                @click="sheetView = 'main'"
              >
                <AppIcon :path="mdiChevronLeft" :size="22" />
              </button>
              <h2 class="flex-1 text-lg font-medium text-primary-50">
                {{
                  sheetView === 'ranges'
                    ? t('gallery.distribution.title')
                    : sheetView === 'scenario'
                      ? t('gallery.scenario.label')
                      : t('gallery.filters.title')
                }}
              </h2>
              <button
                type="button"
                class="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full text-primary-50/80 transition hover:bg-primary-50/10"
                :aria-label="t('gallery.filters.close')"
                @click="filtersOpen = false"
              >
                <AppIcon :path="mdiClose" :size="20" />
              </button>
            </div>

            <div class="thin-scroll overflow-x-hidden overflow-y-auto px-5 pt-2 pb-5">
              <!-- Into a screen of its own, the content slides in from the
                 right; back to the overview, from the left. -->
              <Transition
                mode="out-in"
                :enter-from-class="`${sheetView === 'main' ? '-translate-x-8' : 'translate-x-8'} opacity-0`"
                :leave-to-class="`${sheetView === 'main' ? 'translate-x-8' : '-translate-x-8'} opacity-0`"
                enter-active-class="transition duration-150 ease-out motion-reduce:transition-none"
                leave-active-class="transition duration-150 ease-in motion-reduce:transition-none"
              >
                <div v-if="sheetView === 'main'" key="main" class="flex flex-col gap-6">
                  <section class="flex flex-col gap-2">
                    <h3 :class="sheetHeadingClass">{{ t('gallery.filters.length') }}</h3>
                    <div class="flex flex-col rounded-xl bg-primary-50/[0.06]">
                      <label class="flex min-h-14 cursor-pointer items-center gap-3 px-4">
                        <span class="flex min-w-0 flex-1 flex-col">
                          <span class="text-[15px] text-primary-50">{{
                            t('gallery.filter.typical')
                          }}</span>
                          <span class="text-xs text-primary-50/55 tabular-nums">{{
                            typicalValues
                          }}</span>
                        </span>
                        <button
                          type="button"
                          role="switch"
                          :aria-checked="typicalOn"
                          class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition"
                          :class="typicalOn ? 'bg-primary-500' : 'bg-primary-50/20'"
                          @click="toggleTypical"
                        >
                          <span
                            class="absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all"
                            :class="typicalOn ? 'left-[1.375rem]' : 'left-0.5'"
                          />
                        </button>
                      </label>
                      <button
                        type="button"
                        class="flex min-h-13 cursor-pointer items-center justify-between gap-3 border-t border-primary-50/[0.08] px-4 text-left text-[15px] text-primary-50"
                        @click="sheetView = 'ranges'"
                      >
                        {{ t('gallery.filters.adjust') }}
                        <AppIcon
                          :path="mdiChevronRight"
                          :size="18"
                          class="shrink-0 text-primary-50/60"
                        />
                      </button>
                    </div>
                  </section>

                  <section class="flex flex-col gap-2" :class="existingOnly ? 'opacity-40' : ''">
                    <h3 :class="sheetHeadingClass">{{ t('gallery.filter.label') }}</h3>
                    <div class="grid grid-cols-2 gap-1 rounded-full bg-primary-50/[0.06] p-1">
                      <button
                        v-for="option in whoseOptions"
                        :key="option.value"
                        type="button"
                        class="min-h-10 rounded-full text-[15px] transition"
                        :class="[
                          whose === option.value
                            ? 'bg-primary-50/15 font-semibold text-primary-50'
                            : 'text-primary-50/65',
                          existingOnly ? 'cursor-not-allowed' : 'cursor-pointer',
                        ]"
                        :aria-pressed="whose === option.value"
                        :disabled="existingOnly"
                        @click="whose = option.value"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                  </section>

                  <section class="flex flex-col gap-2">
                    <h3 :class="sheetHeadingClass">{{ t('gallery.scenario.label') }}</h3>
                    <GalleryScenarioPanel
                      v-model="galleryScenarioId"
                      row
                      :scenarios="store.scenarios"
                      :without-figures="withoutFigures"
                      :disabled="existingOnly"
                      @open="sheetView = 'scenario'"
                    />
                    <p class="text-[13px] leading-relaxed text-primary-50/60">
                      {{ t('gallery.filters.figuresNote') }}
                    </p>
                  </section>
                </div>

                <GalleryDistribution
                  v-else-if="sheetView === 'ranges'"
                  key="ranges"
                  v-model:ranges="ranges"
                  :distributions="distributions"
                  :status="distributionsStatus"
                  @retry="loadDistributions"
                />

                <section v-else key="scenario" class="flex flex-col gap-4">
                  <p class="text-xs leading-relaxed text-primary-50/60">
                    {{ t('gallery.scenario.hint') }}
                  </p>
                  <ScenarioSwitches v-model="galleryScenarioId" :scenarios="store.scenarios" />
                </section>
              </Transition>
            </div>

            <div
              class="flex items-center justify-between gap-3 border-t border-primary-50/10 px-5 pt-3 pb-6"
            >
              <button
                v-if="!filtersAtDefault"
                type="button"
                class="cursor-pointer text-sm text-primary-50/75 underline underline-offset-2"
                @click="resetFilters"
              >
                {{ t('gallery.filters.reset') }}
              </button>
              <span v-else></span>
              <button
                type="button"
                :class="[ctaButtonClass, 'min-h-12']"
                @click="filtersOpen = false"
              >
                {{
                  shownTotal !== null
                    ? t('gallery.filters.show', shownTotal)
                    : t('gallery.filters.close')
                }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Results: controls + a scrolling card list (left) beside the map
         (right), the row exactly one screen tall (measureRow) from lg up. Both
         columns are that height, which is what puts the bottom of the card
         list on the bottom edge of the map: the list scrolls inside its own
         box rather than running down the page past the map's corner.

         Below lg the row is a column with no height of its own: the map first
         (order-first — it is the overview, and the DOM keeps it after the list
         for the two-column case), then the controls, then the cards running
         down the page. The measured height rides a custom property so only
         the lg: class applies it; an inline `height` would bind on a phone
         too. -->
    <div
      ref="resultsRow"
      class="flex flex-col gap-4 lg:h-(--row-height) lg:flex-row lg:gap-6"
      :style="{ '--row-height': rowHeight }"
    >
      <div class="flex w-full flex-col gap-3 lg:h-full lg:w-96 lg:shrink-0">
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

        <!-- The scrolling part of the column, from lg up. min-h-0 is what lets
             a flex child shrink below its content and scroll; pr-1 keeps the
             thin scrollbar off the cards. Below lg it is plain flow — the page
             scrolls, so an overflow box here would only clip. -->
        <div ref="cardScroller" class="thin-scroll lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:pr-1">
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

          <!-- Infinite-scroll sentinel. Deliberately silent: the loading state
               is announced at the head of the column, next to the count. -->
          <div ref="sentinel" class="h-8" aria-hidden="true"></div>

          <!-- Trailing CTA, at the end of the list it belongs to -->
          <div class="flex justify-center pb-2">
            <button
              type="button"
              :class="[ctaButtonClass, 'min-h-12 w-full sm:w-auto']"
              @click="createProposal"
            >
              <AppIcon :path="mdiPlus" :size="18" />
              {{ t('gallery.cta.create') }}
            </button>
          </div>
        </div>
      </div>

      <!-- A fixed height below lg: the map fills the row's height from lg up,
           and below it the row has none, so the box has to bring its own. -->
      <div
        class="order-first h-64 w-full overflow-hidden rounded-xl border border-primary-50/10 sm:h-96 lg:order-none lg:h-full lg:w-auto lg:flex-1"
      >
        <GalleryMap
          :corridors="corridors"
          :corridors-status="corridorsStatus"
          :routes="routeFeatures"
          :highlighted-row="hoveredRow"
          :highlighted-stops="hoveredStops"
          :anchor-stops="anchorStops"
          :highlighted-countries="highlightCountries"
          :search-summary="searchSummary"
          @retry-corridors="loadCorridors"
        />
      </div>
    </div>
  </div>
</template>
