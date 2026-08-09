<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ScenarioPanel from '@/components/ScenarioPanel.vue'
import EffectPanel from '@/components/EffectPanel.vue'
import ViewRow from '@/components/ViewRow.vue'
import CostBreakdownPanel from '@/components/CostBreakdownPanel.vue'
import type { Breakdown, EvaluationResponse, MapScope, ProposalCalcSummary } from '@/types/api'

// Top-level layout only — the "cube" selection state (view/drill-downs/
// class/normalisation) lives in ViewRow, which resolves it against
// `result.views` and reports back the landed Breakdown (for
// CostBreakdownPanel) and the geographic scope (forwarded to the map).
const props = defineProps<{
  result: EvaluationResponse
  // Ordered stops (outbound) backing the "route section" slider.
  stops: { stop_id: string; name: string }[]
  // Route-level gallery KPI summary (demand / modal shift / emissions). Absent
  // on hydration paths that don't carry it; EffectPanel hides itself when null.
  summary?: ProposalCalcSummary | null
}>()
const emit = defineEmits<{ scopeChange: [scope: MapScope] }>()

const { t } = useI18n()

const breakdown = ref<Breakdown | null>(null)
</script>

<template>
  <div class="flex flex-col gap-4">
    <ScenarioPanel />
    <EffectPanel :summary="summary" />
    <ViewRow
      :views="result.views"
      :stops="stops"
      @scope-change="emit('scopeChange', $event)"
      @update:breakdown="breakdown = $event"
    />
    <CostBreakdownPanel
      :breakdown="breakdown"
      :formulas="result.models.evaluation.formulas"
      :input="result.input"
      :stops="stops"
    />

    <!-- Footer: calc version -->
    <div class="flex flex-col gap-1 text-xs text-primary-50/40">
      <span>{{ t('proposal.evaluation.calcVersion') }} {{ result.calc_version }}</span>
    </div>
  </div>
</template>
