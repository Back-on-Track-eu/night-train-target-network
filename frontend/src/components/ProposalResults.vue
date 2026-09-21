<script setup lang="ts">
import { computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { Composition, EvaluationResponse, MapScope, ProposalCalcSummary } from '@/types/api'
import type { ProposalFamily } from '@/composables/useProposalFamily'
import type { ExampleOd } from '@/lib/detailsScope'
import { daysPerWeekFromRequest, demandFromRequest } from '@/lib/detailsScope'
import ScenarioSwitches from '@/components/ScenarioSwitches.vue'
import MainKpiGrid from '@/components/MainKpiGrid.vue'
import CompareSection from '@/components/CompareSection.vue'
import DetailsSection from '@/components/DetailsSection.vue'
import MobileSettingsCard from '@/components/MobileSettingsCard.vue'
import CostRevenueBreakdown from '@/components/CostRevenueBreakdown.vue'
import InfoHint from '@/components/InfoHint.vue'
import ModelVersions from '@/components/ModelVersions.vue'
import { DOCS_SCENARIO } from '@/lib/docsLinks'
import Skeleton from 'primevue/skeleton'

// Everything below the route header and map, top to bottom:
//   A  scenario switches + main KPIs (gold card)   — what every visitor wants
//   B  compare across scenarios / compositions      — the matrix
//   C  discussion                                    — slot, owned by the parent
//   E  costs and revenue in detail                  — collapsible, desktop
//   D  details (supply / operation / … / demand)    — collapsible, desktop
//
// E before D on purpose: the headline question is what the route costs and
// what it earns, and only a reader who has that wants the receipts and the
// inputs behind it. The letters are the zones' original names and are kept
// so the plan documents still resolve; the ORDER is the one below.
//
// The parent (ProposalViewport) still owns the family, the stale flag and the
// selections: this component reads the member on screen's figures from the
// evaluation bundle and the comparisons from the family, and reports every
// choice back up. Zones A/B/E are greyed and put behind the Recalculate
// control while the selection differs from what was computed; C never is —
// a thread is about the proposal, not about the figures — and neither is D,
// which is where the inputs live: greying it would make the stale state
// unfixable. D greys its own panels instead, per scope (DetailsSection).
const props = defineProps<{
  result: EvaluationResponse
  summary: ProposalCalcSummary
  stops: { stop_id: string; name: string }[]
  compositions: Composition[]
  selectedCompositionId: string | null
  // Every scenario × composition of the route on screen (the KPI baseline,
  // the bars, the combination grid, the supply table, and what makes a
  // switch instant — see ProposalViewport).
  family: ProposalFamily
  paramsStale: boolean
  // The itinerary has been edited: figures no longer describe it. Greys the
  // same zones as paramsStale, without the Recalculate control (that path
  // is the Evaluate button's).
  dimmed: boolean
  scheduleMode: string | null
  // Zone D: what the figures were computed with, and the two journeys the
  // price table prices a fare on (ProposalViewport owns the route).
  committedRequest: Record<string, unknown> | null
  cycleDistanceKm: number
  longestOd: ExampleOd | null
  shortestOd: ExampleOd | null
}>()
const emit = defineEmits<{
  selectComposition: [compositionId: string]
  recalculate: []
  scopeChange: [scope: MapScope]
}>()

const { t } = useI18n()
const store = useStore()

const selectedScenario = computed(
  () => store.scenarios.find((s) => s.scenario_id === store.selectedScenarioId) ?? null,
)
const selectedComposition = computed(
  () => props.compositions.find((c) => c.composition_id === props.selectedCompositionId) ?? null,
)
// What the figures were computed with, in the reader's words rather than the
// request's: the one frequency, with the qualifier the two ends of the
// range deserve.
const frequencyLabel = computed(() => {
  const days = daysPerWeekFromRequest(
    props.committedRequest?.schedule as Record<string, number> | null | undefined,
  )
  const base = t('proposal.details.schedule.daysPerWeek', { n: days })
  if (days >= 7) return `${base} — ${t('proposal.details.schedule.qualifier.everyDay')}`
  if (days <= 1) return `${base} — ${t('proposal.details.schedule.qualifier.onceAWeek')}`
  return base
})

// The demand level behind the passenger figures, by its name (S/M/L/XL or
// custom) — the one demand input that shapes the result today. Fares are
// deliberately not on this line: they change the revenue, not the demand,
// and naming them here suggested a price elasticity the model does not have.
const demandLabel = computed(() => {
  const demand = demandFromRequest(props.committedRequest)
  if (!demand) return null
  return t('proposal.compare.demandPart', {
    name: t(`proposal.details.potential.levels.${demand.level}.name`, demand.level),
  })
})

// Baseline for the delta arrows: base network, nothing switched on, SAME
// composition as on screen — the comparison a visitor expects when they
// flip a switch. Comes from the family; null until the document is here.
const baseScenario = computed(() => store.scenarios.find((s) => s.is_current_base) ?? null)
const baselineSummary = computed(() => {
  if (!baseScenario.value || !props.selectedCompositionId) return null
  return (
    props.family.okMember(baseScenario.value.scenario_id, props.selectedCompositionId)?.summary ??
    null
  )
})
const isBaseline = computed(() => store.selectedScenarioId === baseScenario.value?.scenario_id)

const cellsByScenario = computed(() =>
  props.selectedCompositionId ? props.family.byScenario(props.selectedCompositionId) : new Map(),
)
const cellsByComposition = computed(() =>
  store.selectedScenarioId !== null
    ? props.family.byComposition(store.selectedScenarioId)
    : new Map(),
)
// The document's composition axis carries ids only; the catalog entries
// (description, formation) are the store's, in the axis order.
const axisCompositions = computed(() => {
  const ids = props.family.document.value?.axes.compositions ?? []
  return ids
    .map((id) => props.compositions.find((c) => c.composition_id === id))
    .filter((c): c is Composition => c !== undefined)
})
const greyed = computed(() =>
  props.paramsStale || props.dimmed ? 'pointer-events-none opacity-40' : '',
)

// "change ↓" on the inputs line: open the Details card (its open state lives
// in the store, see DetailsSection) and bring it into view. Opened first, so
// the scroll lands on a card that already has its height.
async function scrollToSettings() {
  store.detailsOpen = true
  await nextTick()
  document
    .getElementById('proposal-details')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <div class="flex w-full flex-col gap-6">
    <!-- Zones A + B behind the one Recalculate control while stale. -->
    <div class="relative flex flex-col gap-6">
      <div class="transition-opacity duration-200" :class="greyed">
        <!-- Zone A -->
        <section class="scenario-gold-box flex flex-col gap-4 rounded-xl p-4">
          <div class="flex flex-col gap-1">
            <h2 class="flex items-center gap-1.5 text-base font-semibold text-primary-50">
              {{ t('proposal.compare.scenarioTitle') }}
              <InfoHint
                :text="t('proposal.compare.scenarioHint')"
                :docs-href="DOCS_SCENARIO"
                feedback-topic="kpis"
              />
            </h2>
            <p class="text-xs text-primary-50/60">{{ t('proposal.compare.scenarioBody') }}</p>
          </div>

          <div v-if="store.scenariosStatus === 'loading'" class="flex gap-4">
            <Skeleton width="12rem" height="2rem" border-radius="9999px" />
            <Skeleton width="10rem" height="2rem" />
          </div>
          <p v-else-if="store.scenariosFailure" class="text-sm text-amber-200" role="alert">
            {{ t('errors.scenariosUnavailable') }}
            <button
              type="button"
              class="ml-2 cursor-pointer font-semibold underline underline-offset-2"
              @click="store.fetchScenarios()"
            >
              {{ t('errors.retry') }}
            </button>
          </p>
          <ScenarioSwitches
            v-else
            :scenarios="store.scenarios"
            :model-value="store.selectedScenarioId"
            @update:model-value="(id) => (store.selectedScenarioId = id)"
          />

          <!-- What the switches above currently mean, then what the figures
               below were computed with. Rules rather than paragraphs: the
               scenario reads as a quoted definition (left rule, gold name),
               the measures line hangs off it, and the inputs line is fenced
               off by a full-width rule because it is about the train, not
               the scenario. -->
          <div class="scen-desc">
            <template v-if="selectedScenario">
              <b>{{ selectedScenario.scenario_name }}</b>
              <span v-if="selectedScenario.description">{{ selectedScenario.description }}</span>
            </template>
            <div class="reg">{{ t('proposal.compare.measuresNone') }}</div>
          </div>

          <!-- The composition is named by its id, not its description: the id
               is what the comparison grid's columns, the supply table and the
               published proposal all use, and a sentence is not a name. The
               description stays reachable as the element's title. -->
          <p class="inputs-line">
            <span :title="selectedComposition?.description ?? undefined">
              {{
                t('proposal.compare.evaluatedWith', {
                  composition: selectedCompositionId ?? '—',
                  frequency: frequencyLabel ?? '—',
                  demand: demandLabel ?? '—',
                })
              }}
            </span>
            <button
              type="button"
              class="cursor-pointer text-sky-300 hover:text-sky-200"
              @click="scrollToSettings"
            >
              {{ t('proposal.compare.change') }}
            </button>
            <span
              v-if="paramsStale"
              class="rounded-full bg-amber-400/20 px-2 py-px text-[10px] text-amber-200"
            >
              {{ t('proposal.compare.staleMarker') }}
            </span>
          </p>

          <MainKpiGrid :summary="summary" :baseline="baselineSummary" :is-baseline="isBaseline" />
          <p v-if="summary.demand_kpis_placeholder" class="text-[11px] text-primary-50/40">
            {{ t('proposal.evaluation.impact.placeholder') }}
          </p>
          <!-- Every model a tile reads: journey time from the route builder,
               passengers from demand, subsidy from the cost model, CO₂e from
               emissions. The demand block travels with the member views, so
               until they land (or for a stored proposal without them) the
               registry's version stands in. -->
          <ModelVersions
            :items="[
              { label: t('proposal.models.routeBuilder'), version: result.route_builder_version },
              { label: t('proposal.models.cost'), version: result.calc_version },
              {
                label: t('proposal.models.demand'),
                version: result.demand?.model_version ?? store.models?.demand?.version,
              },
              { label: t('proposal.models.emissions'), version: store.models?.emissions?.version },
            ]"
          />
        </section>

        <!-- Zone B -->
        <CompareSection
          class="mt-6"
          :scenarios="store.scenarios"
          :compositions="axisCompositions"
          :cells-by-scenario="cellsByScenario"
          :cells="family.cells.value"
          :status="family.status.value"
          :received="family.received.value"
          :n-cells="family.document.value?.stats.n_members ?? null"
          :selected-scenario-id="store.selectedScenarioId"
          :selected-composition-id="selectedCompositionId"
          :grid-available="axisCompositions.length > 1"
          @select-scenario="(id) => (store.selectedScenarioId = id)"
          @select-cell="
            (scenarioId, compositionId) => {
              store.selectedScenarioId = scenarioId
              emit('selectComposition', compositionId)
            }
          "
        />
      </div>

      <!-- Stale results: the whole area is the recompute control. -->
      <Transition name="fade">
        <button
          v-if="paramsStale"
          type="button"
          class="absolute inset-0 flex cursor-pointer items-start justify-center rounded-xl bg-sapphire/60 pt-12 backdrop-blur-[2px]"
          @click="emit('recalculate')"
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

    <!-- Zone C -->
    <slot name="discussion" />

    <!-- Divider -->
    <div class="hidden items-center gap-3 text-xs text-primary-50/40 lg:flex">
      <span class="h-px flex-1 bg-primary-50/10" />
      {{ t('proposal.settings.divider') }}
      <span class="h-px flex-1 bg-primary-50/10" />
    </div>

    <!-- Zones E then D — desktop and tablet, lg and up. Below that the two
         fold away entirely: a receipt with six columns and a twelve-month
         slider grid cannot be made readable at phone width, and the card
         below says so rather than pretending. -->
    <div id="proposal-details-zone" class="hidden flex-col gap-4 lg:flex">
      <!-- E — greyed behind the Recalculate control while stale, like A and B. -->
      <div class="transition-opacity duration-200" :class="greyed">
        <CostRevenueBreakdown
          :result="result"
          :stops="stops"
          @scope-change="emit('scopeChange', $event)"
        />
      </div>

      <!-- D — never greyed: it owns the inputs that make the rest stale. -->
      <DetailsSection
        :compositions="compositions"
        :cells-by-composition="cellsByComposition"
        :selected-composition-id="selectedCompositionId"
        :summary="summary"
        :result="result"
        :committed-request="committedRequest"
        :cycle-distance-km="cycleDistanceKm"
        :longest-od="longestOd"
        :shortest-od="shortestOd"
        @select-composition="(id) => emit('selectComposition', id)"
        @recalculate="emit('recalculate')"
      />
    </div>

    <!-- Mobile replacement -->
    <MobileSettingsCard
      class="lg:hidden"
      :composition="selectedComposition?.description ?? null"
      :frequency="frequencyLabel"
    />
  </div>
</template>

<style scoped>
/* Scenario summary: a quoted definition, not a paragraph among paragraphs.
   One type size throughout — the name is set apart by weight, colour and its
   own row, the measures line by a rule, so nothing needs to shrink to be
   read as secondary. */
.scen-desc {
  border-left: 1px solid color-mix(in srgb, var(--color-primary-50) 15%, transparent);
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.6;
  color: color-mix(in srgb, var(--color-primary-50) 65%, transparent);
}

.scen-desc b {
  display: block;
  margin-bottom: 6px;
  font-weight: 700;
  color: #fbbf24;
}

.scen-desc .reg {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid color-mix(in srgb, var(--color-primary-50) 10%, transparent);
  color: color-mix(in srgb, var(--color-primary-50) 50%, transparent);
}

/* What the figures were computed with — fenced off, it is about the train. */
.inputs-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  padding-top: 14px;
  border-top: 1px solid color-mix(in srgb, var(--color-primary-50) 10%, transparent);
  font-size: 13px;
  color: color-mix(in srgb, var(--color-primary-50) 70%, transparent);
}

.scenario-gold-box {
  background: linear-gradient(
    135deg,
    color-mix(in srgb, #fcd34d 12%, transparent) 0%,
    color-mix(in srgb, #fbbf24 6%, transparent) 100%
  );
  border: 1px solid color-mix(in srgb, #fbbf24 25%, transparent);
}
</style>
