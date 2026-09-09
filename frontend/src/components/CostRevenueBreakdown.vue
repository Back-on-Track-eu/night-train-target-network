<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { Breakdown, EvaluationResponse, MapScope } from '@/types/api'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import { fundedCostEur } from '@/lib/breakdownTotals'
import ViewRow from '@/components/ViewRow.vue'
import CostBreakdownPanel from '@/components/CostBreakdownPanel.vue'
import AppIcon from '@/components/AppIcon.vue'
import Skeleton from 'primevue/skeleton'
import { mdiChevronDown } from '@mdi/js'

// Zone E — the collapsible cost/revenue detail ("Kassenzettel"). Two
// stacked bars on one shared scale for the landed Breakdown (cost by
// category incl. the operator's margin, revenue by class/source), with a
// dashed outline on the shorter bar marking the gap: gold "necessary
// subsidy" or green "revenue exceeds cost". Below it the existing cube
// selectors (ViewRow) and the ledgers (CostBreakdownPanel) unchanged —
// the drill-down is exactly what it was, only folded away by default.
//
// The views arrive on their own request after the family document (see
// ProposalViewport's loadViews); until then result.views is null and this
// zone shows a skeleton. The formulas the ledgers' popovers key into are the
// store's model registry (GET /api/models), no longer part of a member.
defineProps<{
  result: EvaluationResponse
  stops: { stop_id: string; name: string }[]
  defaultOpen?: boolean
}>()
const emit = defineEmits<{ scopeChange: [scope: MapScope] }>()

const { t } = useI18n()
const { formatEur } = useEvaluationFormat()
const store = useStore()
const formulas = computed(() => store.models?.evaluation.formulas ?? {})
const open = ref(false)
const breakdown = ref<Breakdown | null>(null)

const bars = computed(() => {
  const b = breakdown.value
  if (!b) return null
  const cost = [
    { key: 'operatorVariable', value: b.cost.operator.variable.total_eur, color: '#3c8fd6' },
    { key: 'operatorFixed', value: b.cost.operator.fixed.total_eur, color: '#2271b3' },
    { key: 'trackAccess', value: b.cost.infrastructure.tac_eur, color: '#d4a54a' },
    { key: 'stationCharges', value: b.cost.infrastructure.station_charge_eur, color: '#b8862f' },
    { key: 'energy', value: b.cost.infrastructure.energy_eur, color: '#92d051' },
    { key: 'margin', value: b.margin.total_eur, color: '#8b93b8' },
  ].filter((s) => s.value > 0)
  const revenue = [{ key: 'tickets', value: b.revenue.total_eur, color: '#f1f3f6' }].filter(
    (s) => s.value > 0,
  )
  const costTotal = fundedCostEur(b)
  const revenueTotal = b.revenue.total_eur
  const scale = Math.max(costTotal, revenueTotal) || 1
  return { cost, revenue, costTotal, revenueTotal, scale, gap: costTotal - revenueTotal }
})
</script>

<template>
  <details
    class="group rounded-xl border border-primary-50/10"
    :open="open || defaultOpen"
    @toggle="open = ($event.target as HTMLDetailsElement).open"
  >
    <summary class="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3">
      <span class="flex flex-col">
        <span class="text-base font-semibold text-primary-50">{{
          t('proposal.evaluation.sections.finance.title')
        }}</span>
        <span class="text-xs text-primary-50/60">{{
          t('proposal.evaluation.sections.finance.body')
        }}</span>
      </span>
      <AppIcon
        :path="mdiChevronDown"
        :size="20"
        class="text-primary-50/60 transition group-open:rotate-180"
      />
    </summary>
    <div
      v-if="result.views === null"
      class="flex flex-col gap-3 border-t border-primary-50/10 px-4 py-3"
      :aria-label="t('proposal.evaluation.viewsLoading')"
    >
      <Skeleton height="2rem" class="w-full" />
      <Skeleton height="6rem" class="w-full" />
      <Skeleton height="12rem" class="w-full" />
    </div>
    <div v-else class="flex flex-col gap-4 border-t border-primary-50/10 px-4 py-3">
      <ViewRow
        :views="result.views"
        :stops="stops"
        @scope-change="emit('scopeChange', $event)"
        @update:breakdown="breakdown = $event"
      />

      <div v-if="bars" class="flex flex-col gap-2 text-xs">
        <div
          v-for="side in ['cost', 'revenue'] as const"
          :key="side"
          class="grid grid-cols-[6rem_1fr] items-center gap-2"
        >
          <span class="text-primary-50/70">{{ t(`proposal.breakdown.${side}`) }}</span>
          <div class="relative h-6">
            <div
              class="flex h-full overflow-hidden rounded"
              :style="{
                width: `${((side === 'cost' ? bars.costTotal : bars.revenueTotal) / bars.scale) * 100}%`,
              }"
            >
              <span
                v-for="segment in side === 'cost' ? bars.cost : bars.revenue"
                :key="segment.key"
                class="h-full"
                :style="{
                  width: `${(segment.value / (side === 'cost' ? bars.costTotal : bars.revenueTotal)) * 100}%`,
                  background: segment.color,
                }"
                :title="`${t(`proposal.breakdown.segments.${segment.key}`)} · ${formatEur(segment.value)}`"
              />
            </div>
            <!-- The gap: dashed outline on whichever bar is shorter. -->
            <span
              v-if="(side === 'revenue' && bars.gap > 0) || (side === 'cost' && bars.gap < 0)"
              class="absolute top-0 h-full rounded border border-dashed"
              :class="bars.gap > 0 ? 'border-amber-400' : 'border-yellow-green'"
              :style="{
                left: `${(Math.min(bars.costTotal, bars.revenueTotal) / bars.scale) * 100}%`,
                width: `${(Math.abs(bars.gap) / bars.scale) * 100}%`,
              }"
              :title="
                bars.gap > 0
                  ? t('proposal.breakdown.gapSubsidy', { value: formatEur(bars.gap) })
                  : t('proposal.breakdown.gapSurplus', { value: formatEur(-bars.gap) })
              "
            />
          </div>
        </div>
        <div class="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-primary-50/60">
          <span
            v-for="segment in [...bars.cost, ...bars.revenue]"
            :key="segment.key"
            class="flex items-center gap-1"
          >
            <span class="inline-block h-2 w-2 rounded-sm" :style="{ background: segment.color }" />
            {{ t(`proposal.breakdown.segments.${segment.key}`) }}
          </span>
          <span
            class="ml-auto font-semibold"
            :class="bars.gap > 0 ? 'text-amber-300' : 'text-yellow-green'"
          >
            {{
              bars.gap > 0
                ? t('proposal.breakdown.gapSubsidy', { value: formatEur(bars.gap) })
                : t('proposal.breakdown.gapSurplus', { value: formatEur(-bars.gap) })
            }}
          </span>
        </div>
      </div>

      <CostBreakdownPanel :breakdown="breakdown" :formulas="formulas" />
      <div class="text-xs text-primary-50/40">
        {{ t('proposal.evaluation.calcVersion') }} {{ result.calc_version }}
      </div>
    </div>
  </details>
</template>
