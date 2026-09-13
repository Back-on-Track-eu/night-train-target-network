<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Composition, FamilyMember, Scenario } from '@/types/api'
import type { FamilyStatus } from '@/composables/useProposalFamily'
import { COMPARE_KPIS, type CompareKpiKey } from '@/lib/compareKpis'
import Select from 'primevue/select'
import { selectPillPt } from '@/lib/selectPillPt'
import ScenarioCompareBars from '@/components/ScenarioCompareBars.vue'
import ScenarioCompositionGrid from '@/components/ScenarioCompositionGrid.vue'
import InlineAlert from '@/components/InlineAlert.vue'

// Zone B: compare across scenarios. KPI picker + two views over the grid
// matrix — bars (the selected composition across scenarios) and the full
// scenario × composition grid. The grid arrives in one response; a partial
// one (a scenario this deployment cannot route, say) is labelled as such
// rather than passed off as the whole picture.
const props = defineProps<{
  scenarios: Scenario[]
  compositions: Composition[]
  cellsByScenario: Map<number, FamilyMember>
  cells: Map<string, FamilyMember>
  status: FamilyStatus
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
// A composition that cannot use high-speed lines makes the HSR scenarios
// inert — the route builder ANDs the two flags. Resolved once here and passed
// to both views so they dim the same cells.
const selectedHsrAllowed = computed(
  () =>
    props.compositions.find((c) => c.composition_id === props.selectedCompositionId)?.routing
      .hsr_allowed ?? true,
)
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
        <Select
          v-model="kpi"
          :options="kpiOptions"
          option-value="key"
          option-label="label"
          :unstyled="true"
          :pt="selectPillPt"
          :aria-label="t('proposal.compare.kpiPicker')"
        />
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
      :hsr-allowed="selectedHsrAllowed"
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
