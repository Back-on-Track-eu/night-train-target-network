<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import { computed } from 'vue'
import type { Breakdown } from '@/types/api'

// The top line: the four figures that make the verdict, and the verdict.
//
//   revenue − cost − margin = net
//
// Cost is the OPERATING cost — the ledger's total, nothing else. The
// operator's expected margin is its own tile, because it is neither a cost
// nor revenue: a profit carve-out that the surplus has to cover first and the
// subsidy has to reach. Showing it here and nowhere else is deliberate — it
// used to be a row inside the cost tree, which made that tree's total
// disagree with the rows under it.
const props = defineProps<{
  breakdown: Breakdown
}>()

const { t } = useI18n()
const { formatEur, formatShare } = useEvaluationFormat()

// The same surplus rule the KPI grid follows (lib/compareKpis subsidyDisplay):
// a route that covers its own cost and margin has a surplus; one that does
// not needs a subsidy — of exactly the amount that gets the operator to its
// margin.
const net = computed(() => ({
  surplus: props.breakdown.net_eur > 0,
  amount: Math.abs(props.breakdown.net_eur),
}))

const marginShare = computed(() => {
  const ticket =
    props.breakdown.revenue.ticket_revenue_eur + (props.breakdown.revenue.services_revenue_eur ?? 0)
  return ticket ? props.breakdown.margin.total_eur / ticket : null
})
</script>

<template>
  <div class="flex flex-wrap justify-around gap-y-3 rounded-xl bg-primary-50/5 p-4">
    <div class="flex flex-col items-center gap-1">
      <span class="text-xs tracking-wide text-primary-50/50 uppercase">
        {{ t('proposal.evaluation.kpi.revenue') }}
      </span>
      <span class="text-xl font-bold tabular-nums text-primary-50">
        {{ formatEur(breakdown.total_revenue_eur) }}
      </span>
    </div>
    <div class="flex flex-col items-center gap-1">
      <span class="text-xs tracking-wide text-primary-50/50 uppercase">
        {{ t('proposal.evaluation.kpi.cost') }}
      </span>
      <span class="text-xl font-bold tabular-nums text-primary-50">
        {{ formatEur(breakdown.cost.total_eur) }}
      </span>
    </div>
    <div class="flex flex-col items-center gap-1">
      <span class="text-xs tracking-wide text-primary-50/50 uppercase">
        {{ t('proposal.evaluation.kpi.margin') }}
      </span>
      <span class="text-xl font-bold tabular-nums text-primary-50">
        {{ formatEur(breakdown.margin.total_eur) }}
      </span>
      <span v-if="marginShare !== null" class="text-[11px] text-primary-50/45">
        {{ t('proposal.evaluation.kpi.marginShare', { share: formatShare(marginShare) }) }}
      </span>
    </div>
    <div class="flex flex-col items-center gap-1">
      <span class="text-xs tracking-wide text-primary-50/50 uppercase">
        {{
          net.surplus
            ? t('proposal.evaluation.kpi.surplus')
            : t('proposal.evaluation.kpi.subsidies')
        }}
      </span>
      <span
        class="text-xl font-bold tabular-nums"
        :class="net.surplus ? 'text-yellow-green' : 'text-amber-300'"
      >
        {{ formatEur(net.amount) }}
      </span>
      <span class="text-[11px] text-primary-50/45">
        {{
          net.surplus
            ? t('proposal.evaluation.kpi.afterMargin')
            : t('proposal.evaluation.kpi.toReachMargin')
        }}
      </span>
    </div>
  </div>
</template>
