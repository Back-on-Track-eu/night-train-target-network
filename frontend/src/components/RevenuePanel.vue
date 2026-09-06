<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import FactorInfoPopover from '@/components/FactorInfoPopover.vue'
import { mdiInformationOutline } from '@mdi/js'
import { formulaKeyForNode } from '@/lib/factorFeedback'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import type { Breakdown, FormulaMap } from '@/types/api'

// Revenue side of the cost/revenue split. One row today, and the row most
// in need of its explanation: ticket revenue is derived from the stopgap
// demand model, so the documentation page it links to is where that is
// said plainly.
const props = defineProps<{
  breakdown: Breakdown
  formulas: FormulaMap
}>()

const { t } = useI18n()
const { formatEur } = useEvaluationFormat()

const info = ref<InstanceType<typeof FactorInfoPopover> | null>(null)

const TICKET_REVENUE_NODE = 'ticket_revenue'
const hasInfo = () => formulaKeyForNode(TICKET_REVENUE_NODE) in props.formulas
// Rendered as the row label and handed to the popover as its title, so the
// two cannot drift apart.
const ticketRevenueLabel = computed(() => t(`proposal.evaluation.fields.${TICKET_REVENUE_NODE}`))
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
      <span class="flex items-center gap-1 text-sm text-primary-50/70">
        {{ ticketRevenueLabel }}
        <button
          v-if="hasInfo()"
          type="button"
          class="flex cursor-pointer text-primary-50/40 transition hover:text-primary-50"
          :aria-label="t('proposal.evaluation.info.iconLabel')"
          @mouseenter="info?.open(TICKET_REVENUE_NODE, ticketRevenueLabel, $event)"
          @mouseleave="info?.scheduleClose()"
          @click="info?.open(TICKET_REVENUE_NODE, ticketRevenueLabel, $event)"
        >
          <AppIcon :path="mdiInformationOutline" :size="14" />
        </button>
      </span>
      <span class="text-sm text-primary-50 tabular-nums">
        {{ formatEur(breakdown.revenue.ticket_revenue_eur) }}
      </span>
    </div>

    <FactorInfoPopover ref="info" :formulas="formulas" />
  </div>
</template>
