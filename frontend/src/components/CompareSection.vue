<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MatrixCompositionAxisEntry, MatrixCell, Scenario } from '@/types/api'
import type { MatrixStatus } from '@/composables/useCalcMatrix'
import { COMPARE_KPIS, type CompareKpiKey } from '@/lib/compareKpis'
import ScenarioCompareBars from '@/components/ScenarioCompareBars.vue'
import ScenarioCompositionGrid from '@/components/ScenarioCompositionGrid.vue'
import InlineAlert from '@/components/InlineAlert.vue'

// Zone B: compare across scenarios. KPI picker + two views over the grid
// matrix — bars (the selected composition across scenarios) and the full
// scenario × composition grid. The grid arrives in one response; a partial
// one (a scenario this deployment cannot route, say) is labelled as such
// rather than passed off as the whole picture.
defineProps<{
  scenarios: Scenario[]
  compositions: MatrixCompositionAxisEntry[]
  cellsByScenario: Map<number, MatrixCell>
  cells: Map<string, MatrixCell>
  status: MatrixStatus
  received: number
  nCells: number | null
  selectedScenarioId: number | null
  selectedCompositionId: string | null
  errorMessage: string | null
  gridAvailable: boolean
}>()
const emit = defineEmits<{
  selectScenario: [scenarioId: number]
  selectCell: [scenarioId: number, compositionId: string]
  retry: []
}>()

const { t } = useI18n()
const kpi = ref<CompareKpiKey>('subsidy')
const view = ref<'bars' | 'grid'>('bars')
const kpiOptions = computed(() =>
  COMPARE_KPIS.map((k) => ({ key: k.key, label: t(`proposal.compare.kpis.${k.labelKey}`) })),
)
</script>

<template>
  <section class="flex flex-col gap-3 rounded-xl border border-primary-50/10 p-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex flex-col">
        <h2 class="text-base font-semibold text-primary-50">{{ t('proposal.compare.title') }}</h2>
        <p class="text-xs text-primary-50/60">
          <template v-if="status === 'loading'">{{ t('proposal.compare.loading') }}</template>
          <template v-else-if="status === 'complete'">
            {{ t('proposal.compare.complete') }}
          </template>
          <template v-else-if="status === 'partial'">
            {{ t('proposal.compare.partial', { received, total: nCells ?? received }) }}
          </template>
          <template v-else>{{ t('proposal.compare.body') }}</template>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <select
          v-model="kpi"
          class="rounded-full border border-primary-50/20 bg-transparent px-3 py-1 text-sm text-primary-50"
          :aria-label="t('proposal.compare.kpiPicker')"
        >
          <option
            v-for="option in kpiOptions"
            :key="option.key"
            :value="option.key"
            class="text-sapphire"
          >
            {{ option.label }}
          </option>
        </select>
        <div class="inline-flex rounded-full border border-primary-50/15 p-0.5" role="group">
          <button
            type="button"
            class="cursor-pointer rounded-full px-3 py-1 text-xs transition"
            :class="view === 'bars' ? 'bg-primary-50/15 text-primary-50' : 'text-primary-50/60'"
            :aria-pressed="view === 'bars'"
            @click="view = 'bars'"
          >
            {{ t('proposal.compare.viewBars') }}
          </button>
          <button
            v-if="gridAvailable"
            type="button"
            class="cursor-pointer rounded-full px-3 py-1 text-xs transition"
            :class="view === 'grid' ? 'bg-primary-50/15 text-primary-50' : 'text-primary-50/60'"
            :aria-pressed="view === 'grid'"
            @click="view = 'grid'"
          >
            {{ t('proposal.compare.viewGrid') }}
          </button>
        </div>
      </div>
    </div>

    <InlineAlert v-if="errorMessage" :message="errorMessage">
      <button
        type="button"
        class="w-fit cursor-pointer text-xs font-semibold underline underline-offset-2"
        @click="emit('retry')"
      >
        {{ t('errors.retry') }}
      </button>
    </InlineAlert>

    <ScenarioCompareBars
      v-if="view === 'bars' || !gridAvailable"
      :scenarios="scenarios"
      :cells="cellsByScenario"
      :kpi="kpi"
      :selected-scenario-id="selectedScenarioId"
      @select="(id) => emit('selectScenario', id)"
    />
    <ScenarioCompositionGrid
      v-else
      :scenarios="scenarios"
      :compositions="compositions"
      :cells="cells"
      :kpi="kpi"
      :selected-scenario-id="selectedScenarioId"
      :selected-composition-id="selectedCompositionId"
      @select="(scenarioId, compositionId) => emit('selectCell', scenarioId, compositionId)"
    />
  </section>
</template>
