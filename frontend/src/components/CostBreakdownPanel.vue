<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import FinancialKPIPanel from '@/components/FinancialKPIPanel.vue'
import CostPanel from '@/components/CostPanel.vue'
import RevenuePanel from '@/components/RevenuePanel.vue'
import type { Breakdown, FormulaMap } from '@/types/api'

// The landed cube cell (ViewRow's currentBreakdown), rendered as the
// financial KPI strip plus its cost tree | revenue split — or a "no data"
// placeholder when the current view/drill-down/normalisation combination
// doesn't land on a cell (e.g. an empty route section).
defineProps<{
  breakdown: Breakdown | null
  /** The same cell split by accommodation class — the revenue ledger lists
   *  ticket revenue per class under its own row. Empty where the view has no
   *  class axis. */
  classSplit: { classMain: string; breakdown: Breakdown }[]
  formulas: FormulaMap
}>()

const { t } = useI18n()
</script>

<template>
  <template v-if="breakdown">
    <!-- No heading here: the zone's <summary> already carries the title and
         the same sentence, and repeating both a few hundred pixels apart read
         as two sections rather than one. -->
    <FinancialKPIPanel :breakdown="breakdown" />

    <!-- The stacked cost/revenue bars. Slotted rather than rendered here so
         they sit between the KPI strip and the ledgers without this component
         needing to know how they are built — and, more to the point, so they
         are nowhere near the route-section slider's rotated stop labels,
         which they used to collide with. -->
    <slot name="bars" />

    <!-- Revenue (left) | Cost (right) — the order the bars above use and the
         order the verdict reads in: what comes in, what goes out. The
         operator's expected margin is neither and lives in the KPI strip. -->
    <div class="flex flex-col items-stretch gap-4 xl:flex-row xl:items-start">
      <RevenuePanel :breakdown="breakdown" :class-split="classSplit" :formulas="formulas" />
      <CostPanel :breakdown="breakdown" :formulas="formulas" />
    </div>
  </template>
  <div v-else class="rounded-xl bg-primary-50/5 p-4 text-sm text-primary-50/60">
    {{ t('proposal.evaluation.noData') }}
  </div>
</template>
