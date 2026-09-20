<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { mdiChevronDown } from '@mdi/js'
import { useStore } from '@/stores/store'
import type {
  Breakdown,
  Composition,
  DemandBlock,
  EvaluationResponse,
  FamilyMember,
  Operations,
  ProposalCalcSummary,
} from '@/types/api'
import {
  TAB_AWAITS,
  daysPerWeekFromRequest,
  demandFromRequest,
  dirtyScopes,
  isAwaiting,
  supplyFigures,
  tariffFromRequest,
  type DetailsInputs,
  type ExampleOd,
  type Tariff,
  type Scope,
} from '@/lib/detailsScope'
import AppIcon from '@/components/AppIcon.vue'
import SupplyTable from '@/components/SupplyTable.vue'
import SchedulePanel from '@/components/details/SchedulePanel.vue'
import PlacesPricesPanel from '@/components/details/PlacesPricesPanel.vue'
import WhatFollowsPanel from '@/components/details/WhatFollowsPanel.vue'
import SelectedComposition from '@/components/details/SelectedComposition.vue'
import OverheadTab from '@/components/details/OverheadTab.vue'
import InfrastructureTab from '@/components/details/InfrastructureTab.vue'
import DemandTab from '@/components/details/DemandTab.vue'
import DetailPanel from '@/components/details/DetailPanel.vue'

// Zone D — "Details". What runs the route, what it costs to operate and to
// use, and who rides it. Five tabs, one card, one Recalculate.
//
// The change-scope rule is the behaviour the whole card shares. Three inputs
// change the calculation: the SCHEDULE and the PRICES on Supply, the DEMAND
// on Demand (D2). A panel that OWNS a changed input previews its own figures
// on the page and marks them; every panel that DEPENDS on one keeps the
// figures it has, greys to 45 % and lights its waiting badge; a panel that
// depends on neither is untouched. Change a price and Infrastructure stays
// lit — track access does not depend on what a ticket sells for.
//
// The card is NOT greyed out while stale, unlike the zones above it: it is
// where the inputs live, so it has to stay usable. That is why the waiting
// state is per panel rather than per card.
const props = defineProps<{
  compositions: Composition[]
  cellsByComposition: Map<string, FamilyMember>
  selectedCompositionId: string | null
  summary: ProposalCalcSummary | null
  result: EvaluationResponse | null
  /** The resolved request the figures on screen were computed with. */
  committedRequest: Record<string, unknown> | null
  /** The route's own km over both directions, and the example OD pairs the
   *  price table prices — both from the route on screen. */
  cycleDistanceKm: number
  longestOd: ExampleOd | null
  shortestOd: ExampleOd | null
}>()
const emit = defineEmits<{
  selectComposition: [compositionId: string]
  recalculate: []
}>()

const { t } = useI18n()
const store = useStore()

type TabKey = 'demand' | 'supply' | 'operation' | 'infrastructure' | 'overhead'
// D1: Demand opens first.
const TABS: TabKey[] = ['demand', 'supply', 'operation', 'infrastructure', 'overhead']

// Both live in the store — see the note there. A Recalculate pressed inside
// this card must leave the card open, on the tab it was pressed on.
const open = computed({
  get: () => store.detailsOpen,
  set: (value: boolean) => (store.detailsOpen = value),
})
const tab = computed({
  get: () => (TABS.includes(store.detailsTab as TabKey) ? (store.detailsTab as TabKey) : 'demand'),
  set: (value: TabKey) => (store.detailsTab = value),
})

const selected = computed(
  () => props.compositions.find((c) => c.composition_id === props.selectedCompositionId) ?? null,
)

// --- what the figures were computed with ------------------------------------

const committed = computed<DetailsInputs | null>(() => {
  const request = props.committedRequest
  if (!request) return null
  return {
    daysPerWeek: daysPerWeekFromRequest(
      request.schedule as Record<string, number> | null | undefined,
    ),
    tariff: tariffFromRequest(request),
    demand: demandFromRequest(request),
  }
})

const current = computed<DetailsInputs>(() => ({
  daysPerWeek: store.scheduleDaysPerWeek,
  tariff: {
    faresPerKm: store.faresEurPerKm,
    faresPerPax: store.faresEurPerPax,
    servicesPerPax: store.servicesEurPerPax,
    cateringPerPax: store.cateringEurPerPax,
  },
  demand: store.demand,
}))

const dirty = computed(() => dirtyScopes(current.value, committed.value))
const stale = computed(() => dirty.value.size > 0)

/** The panel edits one cell at a time and hands back the whole tariff; the
 *  four maps live in the store separately because that is how the request
 *  posts them. */
function applyTariff(tariff: Tariff) {
  store.faresEurPerKm = tariff.faresPerKm
  store.faresEurPerPax = tariff.faresPerPax
  store.servicesEurPerPax = tariff.servicesPerPax
  store.cateringEurPerPax = tariff.cateringPerPax
}

function awaits(...scopes: Scope[]) {
  return isAwaiting(scopes, dirty.value)
}

/** Which tabs hold a waiting panel — the dot beside the tab label, so the
 *  reader does not have to open all five to find out (D2's map). */
const tabAwaiting = computed<Record<TabKey, boolean>>(() => ({
  supply: awaits(...TAB_AWAITS.supply),
  operation: awaits(...TAB_AWAITS.operation),
  infrastructure: awaits(...TAB_AWAITS.infrastructure),
  overhead: awaits(...TAB_AWAITS.overhead),
  demand: awaits(...TAB_AWAITS.demand),
}))

const staleText = computed(() => {
  const names = [...dirty.value].map((scope) => t(`proposal.details.scopes.${scope}`))
  return t(names.length > 1 ? 'proposal.details.staleMany' : 'proposal.details.staleOne', {
    what: names.join(t('proposal.details.and')),
  })
})

// --- what the last calculation produced -------------------------------------

const operations = computed<Operations | null>(() => props.result?.operations ?? null)

/** The pair of the composition on screen. A Y-route has more than one, so
 *  this matches on composition_id rather than taking [0]. */
const pair = computed(() => {
  const pairs = operations.value?.trip_pairs ?? []
  return pairs.find((p) => p.composition_id === props.selectedCompositionId) ?? pairs[0] ?? null
})
const pairCaption = computed(() => {
  const pairs = operations.value?.trip_pairs ?? []
  return pairs.length > 1 ? t('proposal.details.operation.onePairOfMany') : null
})

const routeBreakdown = computed<Breakdown | null>(
  () => props.result?.views?.route.data.per_year?.all ?? null,
)

const operator = computed(() => {
  const id = selected.value?.operator_id
  if (!id) return null
  return store.compositionCatalog.operators.find((o) => o.operator_id === id) ?? null
})

const departuresPerYear = computed(
  () => operations.value?.route.departures_per_year ?? props.summary?.departures_per_year ?? null,
)
const operatingDaysPerYear = computed(
  () =>
    operations.value?.route.operating_days_per_year ??
    props.summary?.operating_days_per_year ??
    null,
)

const committedSupply = computed(() => ({
  // The exact annualisers from the operations block where it has arrived;
  // the summary's rounded copies until then.
  operatingDays: operatingDaysPerYear.value,
  departures: departuresPerYear.value,
  trainKm: props.summary?.train_km_per_year ?? null,
  placesOffered:
    departuresPerYear.value !== null && selected.value
      ? departuresPerYear.value * selected.value.capacity.total_places
      : null,
  placeKmOffered: props.summary?.available_place_km_per_year ?? null,
  trainsets: props.summary?.trainsets_physical ?? null,
}))

/** Departures a year at the frequency as the bar has it — what the Demand
 *  tab's per-trip figures and ladder are drawn against (D9, finding 3). */
const currentDepartures = computed(
  () =>
    supplyFigures(
      store.scheduleDaysPerWeek,
      props.cycleDistanceKm,
      0,
      null,
      operations.value?.trip_pairs.length ?? 1,
    ).departures,
)

/** The backend's demand block for the composition on screen — the family
 *  carries one per member, so switching compositions needs no request. */
const committedBlock = computed<DemandBlock | null>(() => {
  const member = props.selectedCompositionId
    ? props.cellsByComposition.get(props.selectedCompositionId)
    : undefined
  return member?.status === 'ok' ? member.demand : (props.result?.demand ?? null)
})

const demandDefaults = computed(() => {
  const d = store.demandDefaults
  return d
    ? {
        faresPerKm: d.fares_eur_per_km,
        faresPerPax: d.fares_eur_per_pax,
        servicesPerPax: d.services_eur_per_pax,
        cateringPerPax: d.catering_eur_per_pax,
      }
    : null
})
</script>

<template>
  <details
    id="proposal-details"
    class="group rounded-xl border border-primary-50/10"
    :open="open"
    @toggle="open = ($event.target as HTMLDetailsElement).open"
  >
    <summary class="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3">
      <span class="flex flex-col">
        <span class="flex items-center gap-2 text-base font-semibold text-primary-50">
          {{ t('proposal.details.title') }}
          <span
            v-if="stale && !open"
            class="rounded-full bg-amber-400/20 px-2 py-px text-[10px] font-normal text-amber-200"
          >
            {{ t('proposal.details.staleChip') }}
          </span>
        </span>
        <span class="text-xs text-primary-50/60">{{ t('proposal.details.body') }}</span>
      </span>
      <AppIcon
        :path="mdiChevronDown"
        :size="20"
        class="shrink-0 text-primary-50/60 transition group-open:rotate-180"
      />
    </summary>

    <div class="flex flex-col gap-3 border-t border-primary-50/10 px-4 py-3">
      <!-- The stale row: the only Recalculate inside the card, and the only
           place that names what changed. -->
      <Transition name="fade">
        <div
          v-if="stale"
          class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2"
        >
          <p class="flex-1 text-xs leading-snug text-amber-100">{{ staleText }}</p>
          <button
            type="button"
            class="flex cursor-pointer items-center gap-2 rounded-full bg-primary-500 px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-primary-600"
            @click="emit('recalculate')"
          >
            {{ t('proposal.recalculate') }}
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </Transition>

      <div
        class="flex w-fit max-w-full flex-wrap rounded-full border border-primary-50/15 p-0.5"
        role="tablist"
      >
        <button
          v-for="key in TABS"
          :key="key"
          type="button"
          role="tab"
          class="flex cursor-pointer items-center gap-1.5 rounded-full px-3 py-1 text-xs transition"
          :class="
            tab === key
              ? 'bg-primary-50/15 text-primary-50'
              : 'text-primary-50/60 hover:text-primary-50'
          "
          :aria-selected="tab === key"
          @click="tab = key"
        >
          {{ t(`proposal.details.tabs.${key}`) }}
          <span
            v-if="tabAwaiting[key]"
            class="h-1.5 w-1.5 rounded-full bg-amber-300"
            :aria-label="t('proposal.details.awaiting')"
          />
        </button>
      </div>

      <!-- Supply -->
      <div v-if="tab === 'supply'" class="flex flex-col gap-3">
        <SchedulePanel
          :days-per-week="store.scheduleDaysPerWeek"
          :previewing="dirty.has('schedule')"
          :cycle-distance-km="cycleDistanceKm"
          :places="selected?.capacity.total_places ?? 0"
          :cycle-days="pair?.trainsets.cycle_days ?? null"
          :trip-pairs="operations?.trip_pairs.length ?? 1"
          :committed="committedSupply"
          @update:days-per-week="store.scheduleDaysPerWeek = $event"
        />
        <PlacesPricesPanel
          :composition="selected"
          :tariff="current.tariff"
          :defaults="demandDefaults"
          :longest="longestOd"
          :shortest="shortestOd"
          :days-per-week="store.scheduleDaysPerWeek"
          :schedule-previewing="dirty.has('schedule')"
          :prices-previewing="dirty.has('prices')"
          :cycle-distance-km="cycleDistanceKm"
          :cycle-days="pair?.trainsets.cycle_days ?? null"
          :trip-pairs="operations?.trip_pairs.length ?? 1"
          :committed="committedSupply"
          @update:tariff="applyTariff"
        />
        <WhatFollowsPanel
          :composition="selected"
          :days-per-week="store.scheduleDaysPerWeek"
          :tariff="current.tariff"
          :trip-pairs="operations?.trip_pairs.length ?? 1"
          :cycle-distance-km="cycleDistanceKm"
          :committed-demand="committed?.demand ?? null"
          :committed-block="committedBlock"
          :previewing="dirty.has('schedule') || dirty.has('prices')"
          :awaiting="awaits('demand')"
        />
      </div>

      <!-- Train operation -->
      <div v-else-if="tab === 'operation'" class="flex flex-col gap-3">
        <DetailPanel
          :title="t('proposal.details.operation.compareTitle')"
          :info="t('proposal.details.operation.compareInfo')"
          :awaiting="awaits('schedule', 'prices', 'demand')"
        >
          <SupplyTable
            :compositions="compositions"
            :cells="cellsByComposition"
            :selected-composition-id="selectedCompositionId"
            @select="(id) => emit('selectComposition', id)"
          />
        </DetailPanel>
        <SelectedComposition
          v-if="selected"
          :composition="selected"
          :pair="pair"
          :breakdown="routeBreakdown"
          :departures-per-year="departuresPerYear"
          :operating-days-per-year="operatingDaysPerYear"
          :awaiting="awaits('schedule')"
          :pair-caption="pairCaption"
        />
      </div>

      <!-- Infrastructure -->
      <InfrastructureTab
        v-else-if="tab === 'infrastructure'"
        :operations="operations"
        :breakdown="routeBreakdown"
        :departures-per-year="departuresPerYear"
        :operating-days-per-year="operatingDaysPerYear"
        :awaiting="awaits('schedule')"
      />

      <!-- Overhead -->
      <OverheadTab
        v-else-if="tab === 'overhead'"
        :breakdown="routeBreakdown"
        :operator="operator"
        :departures-per-year="departuresPerYear"
        :operating-days-per-year="operatingDaysPerYear"
        :awaiting-schedule="awaits('schedule')"
        :awaiting-prices="awaits('prices') || awaits('demand')"
      />

      <!-- Demand -->
      <DemandTab
        v-else
        :compositions="compositions"
        :selected-composition-id="selectedCompositionId"
        :committed-block="committedBlock"
        :days-per-week="store.scheduleDaysPerWeek"
        :departures="currentDepartures"
        :previewing="dirty.has('demand')"
        @select-composition="(id) => emit('selectComposition', id)"
        @go-to-supply="tab = 'supply'"
      />
    </div>
  </details>
</template>
