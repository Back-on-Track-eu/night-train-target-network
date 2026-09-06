<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import { fundedCostEur } from '@/lib/breakdownTotals'
import type { Breakdown } from '@/types/api'

defineProps<{
  breakdown: Breakdown
}>()

const { t } = useI18n()
const { formatEur } = useEvaluationFormat()
</script>

<template>
  <div class="flex justify-around rounded-xl bg-primary-50/5 p-4">
    <div class="flex flex-col items-center gap-1">
      <span class="text-xs tracking-wide text-primary-50/50 uppercase">
        {{ t('proposal.evaluation.kpi.revenue') }}
      </span>
      <span class="text-xl font-bold text-primary-50 tabular-nums">
        {{ formatEur(breakdown.total_revenue_eur) }}
      </span>
    </div>
    <div class="flex flex-col items-center gap-1">
      <span class="text-xs tracking-wide text-primary-50/50 uppercase">
        {{ t('proposal.evaluation.kpi.cost') }}
      </span>
      <!-- Cost plus the operator's expected margin: the subsidy beside it is
           revenue minus BOTH (net_eur), so the bare cost total would leave the
           three figures failing to add up. See lib/breakdownTotals.ts. -->
      <span class="text-xl font-bold text-primary-50 tabular-nums">
        {{ formatEur(fundedCostEur(breakdown)) }}
      </span>
    </div>
    <div class="flex flex-col items-center gap-1">
      <span class="text-xs tracking-wide text-primary-50/50 uppercase">
        {{ t('proposal.evaluation.kpi.subsidies') }}
      </span>
      <span class="text-xl font-bold text-primary-50 tabular-nums">
        {{ formatEur(-breakdown.net_eur) }}
      </span>
    </div>
  </div>
</template>
