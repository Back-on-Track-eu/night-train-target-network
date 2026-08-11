<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import FinancialKPIPanel from '@/components/FinancialKPIPanel.vue'
import CostPanel from '@/components/CostPanel.vue'
import RevenuePanel from '@/components/RevenuePanel.vue'
import type { Breakdown, EvaluationInput, FormulaMap } from '@/types/api'

// The landed cube cell (ViewRow's currentBreakdown), rendered as the
// financial KPI strip plus its cost tree | revenue split — or a "no data"
// placeholder when the current view/drill-down/normalisation combination
// doesn't land on a cell (e.g. an empty route section).
defineProps<{
  breakdown: Breakdown | null
  formulas: FormulaMap
  input: EvaluationInput
  // Ordered stops (outbound) — costFactorRates scopes rates to the route.
  stops: { stop_id: string; name: string }[]
}>()

const { t } = useI18n()
</script>

<template>
  <template v-if="breakdown">
    <FinancialKPIPanel :breakdown="breakdown" />

    <!-- Cost tree (left, EBIT margin is a point under Operator) | Revenue (right) -->
    <div class="flex items-start gap-4">
      <CostPanel :breakdown="breakdown" :formulas="formulas" :input="input" :stops="stops" />
      <RevenuePanel :breakdown="breakdown" />
    </div>
  </template>
  <div v-else class="rounded-xl bg-primary-50/5 p-4 text-sm text-primary-50/60">
    {{ t('proposal.evaluation.noData') }}
  </div>
</template>
