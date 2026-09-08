<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { Composition, EvaluationResponse, MapScope, ProposalCalcSummary } from '@/types/api'
import type { CalcMatrix } from '@/composables/useCalcMatrix'
import { messageKey } from '@/lib/apiError'
import ScenarioSwitches from '@/components/ScenarioSwitches.vue'
import MainKpiGrid from '@/components/MainKpiGrid.vue'
import CompareSection from '@/components/CompareSection.vue'
import SettingsSection from '@/components/SettingsSection.vue'
import MobileSettingsCard from '@/components/MobileSettingsCard.vue'
import CostRevenueBreakdown from '@/components/CostRevenueBreakdown.vue'
import Skeleton from 'primevue/skeleton'

// Everything below the route header and map, top to bottom:
//   A  scenario switches + main KPIs (gold card)   — what every visitor wants
//   B  compare across scenarios / compositions      — the matrix
//   C  discussion                                    — slot, owned by the parent
//   D  detail settings (supply / demand)            — collapsible, desktop
//   E  costs and revenue in detail                  — collapsible, desktop
//
// The parent (ProposalViewport) still owns the calc, the stale flag and the
// selections: this component reads the selected cell's figures from the
// /calc response and the comparisons from the matrix, and reports every
// choice back up. Zones A/B/D/E are greyed and put behind the Recalculate
// control while the selection differs from what was computed; C never is —
// a thread is about the proposal, not about the figures.
const props = defineProps<{
  result: EvaluationResponse
  summary: ProposalCalcSummary
  stops: { stop_id: string; name: string }[]
  compositions: Composition[]
  selectedCompositionId: string | null
  // Summary grid (bars, combination grid, supply table) and the full-detail
  // scenario matrix (the KPI baseline, and what makes a scenario switch
  // instant — see ProposalViewport).
  gridMatrix: CalcMatrix
  scenarioMatrix: CalcMatrix
  paramsStale: boolean
  // The itinerary has been edited: figures no longer describe it. Greys the
  // same zones as paramsStale, without the Recalculate control (that path
  // is the Evaluate button's).
  dimmed: boolean
  scheduleMode: string | null
}>()
const emit = defineEmits<{
  selectComposition: [compositionId: string]
  recalculate: []
  scopeChange: [scope: MapScope]
  retryMatrix: []
}>()

const { t, te } = useI18n()
const store = useStore()

const selectedScenario = computed(
  () => store.scenarios.find((s) => s.scenario_id === store.selectedScenarioId) ?? null,
)
const selectedComposition = computed(
  () => props.compositions.find((c) => c.composition_id === props.selectedCompositionId) ?? null,
)
const frequencyLabel = computed(() => {
  const key = props.scheduleMode ? `proposal.supply.schedule.${props.scheduleMode}` : null
  return key && te(key) ? t(key) : props.scheduleMode
})

// Baseline for the delta arrows: base network, nothing switched on, SAME
// composition as on screen — the comparison a visitor expects when they
// flip a switch. Comes from the matrix; null until that cell has arrived.
const baseScenario = computed(() => store.scenarios.find((s) => s.is_current_base) ?? null)
const baselineSummary = computed(() => {
  if (!baseScenario.value || !props.selectedCompositionId) return null
  return (
    props.scenarioMatrix.okCell(baseScenario.value.scenario_id, props.selectedCompositionId)
      ?.summary ??
    props.gridMatrix.okCell(baseScenario.value.scenario_id, props.selectedCompositionId)?.summary ??
    null
  )
})
const isBaseline = computed(() => store.selectedScenarioId === baseScenario.value?.scenario_id)

const cellsByScenario = computed(() =>
  props.selectedCompositionId
    ? props.gridMatrix.byScenario(props.selectedCompositionId)
    : new Map(),
)
const cellsByComposition = computed(() =>
  store.selectedScenarioId !== null
    ? props.gridMatrix.byComposition(store.selectedScenarioId)
    : new Map(),
)
const axisCompositions = computed(() => props.gridMatrix.document.value?.axes.compositions ?? [])
const matrixError = computed(() => {
  const f = props.gridMatrix.failure.value ?? props.scenarioMatrix.failure.value
  return f ? t(messageKey(f)) : null
})

const greyed = computed(() =>
  props.paramsStale || props.dimmed ? 'pointer-events-none opacity-40' : '',
)

function scrollToSettings() {
  document
    .getElementById('proposal-settings')
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
            <h2 class="text-base font-semibold text-primary-50">
              {{ t('proposal.compare.scenarioTitle') }}
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

          <p class="inputs-line">
            <span>
              {{
                t('proposal.compare.evaluatedWith', {
                  composition: selectedComposition?.description ?? selectedCompositionId ?? '—',
                  frequency: frequencyLabel ?? '—',
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
        </section>

        <!-- Zone B -->
        <CompareSection
          class="mt-6"
          :scenarios="store.scenarios"
          :compositions="axisCompositions"
          :cells-by-scenario="cellsByScenario"
          :cells="gridMatrix.cells.value"
          :status="gridMatrix.status.value"
          :received="gridMatrix.received.value"
          :n-cells="gridMatrix.document.value?.n_cells ?? null"
          :selected-scenario-id="store.selectedScenarioId"
          :selected-composition-id="selectedCompositionId"
          :error-message="matrixError"
          :grid-available="axisCompositions.length > 1"
          @select-scenario="(id) => (store.selectedScenarioId = id)"
          @select-cell="
            (scenarioId, compositionId) => {
              store.selectedScenarioId = scenarioId
              emit('selectComposition', compositionId)
            }
          "
          @retry="emit('retryMatrix')"
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
    <div class="hidden items-center gap-3 text-xs text-primary-50/40 sm:flex">
      <span class="h-px flex-1 bg-primary-50/10" />
      {{ t('proposal.settings.divider') }}
      <span class="h-px flex-1 bg-primary-50/10" />
    </div>

    <!-- Zones D + E — desktop -->
    <div
      id="proposal-settings"
      class="hidden flex-col gap-4 transition-opacity duration-200 sm:flex"
      :class="greyed"
    >
      <SettingsSection
        :compositions="compositions"
        :cells-by-composition="cellsByComposition"
        :selected-composition-id="selectedCompositionId"
        :summary="summary"
        :schedule-mode="scheduleMode"
        @select-composition="(id) => emit('selectComposition', id)"
      />
      <CostRevenueBreakdown
        :result="result"
        :stops="stops"
        @scope-change="emit('scopeChange', $event)"
      />
    </div>

    <!-- Mobile replacement -->
    <MobileSettingsCard
      class="sm:hidden"
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
