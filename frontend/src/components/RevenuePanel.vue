<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import type { Breakdown } from '@/types/api'

defineProps<{
  breakdown: Breakdown
}>()

const { t } = useI18n()
const { formatEur } = useEvaluationFormat()
</script>

<template>
  <div class="flex-1 rounded-xl bg-primary-50/5 p-4">
    <div class="mb-2 flex items-baseline justify-between border-b border-primary-50/10 pb-2">
      <span class="font-semibold text-primary-50">
        {{ t('proposal.evaluation.groups.revenue') }}
      </span>
      <span class="font-semibold text-primary-50 tabular-nums">
        {{ formatEur(breakdown.revenue.total_eur) }}
      </span>
    </div>
    <div class="flex items-center justify-between py-1">
      <span class="text-sm text-primary-50/70">
        {{ t('proposal.evaluation.fields.ticket_revenue') }}
      </span>
      <span class="text-sm text-primary-50 tabular-nums">
        {{ formatEur(breakdown.revenue.ticket_revenue_eur) }}
      </span>
    </div>
  </div>
</template>
