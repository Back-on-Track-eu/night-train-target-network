<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import FactorInfoPopover from '@/components/FactorInfoPopover.vue'
import { mdiChevronDown, mdiChevronRight, mdiInformationOutline } from '@mdi/js'
import { formulaKeyForNode } from '@/lib/factorFeedback'
import { fundedCostEur } from '@/lib/breakdownTotals'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import type { Breakdown, FormulaMap } from '@/types/api'

// Cost tree (left column of the cost/revenue split) plus its cost-factor
// detail popover — a one-line summary, a link to the factor's documentation
// page, and a feedback form scoped to the factor the popover is showing.
//
// The formula, the input legend and the resolved rates used to live in this
// popover. They are on the documentation site now: a rates table with its
// sources is a page, not something to read in a hover box.
const props = defineProps<{
  breakdown: Breakdown
  formulas: FormulaMap
}>()

const { t } = useI18n()
const { formatEur, formatShare } = useEvaluationFormat()

// --- Cost tree: hierarchical node spec, flattened for rendering ------------
interface CostNode {
  key: string
  label: string
  value: number
  children?: CostNode[]
}

const costTree = computed<CostNode[]>(() => {
  const b = props.breakdown
  const f = (k: string) => t(`proposal.evaluation.fields.${k}`)
  const g = (k: string) => t(`proposal.evaluation.groups.${k}`)
  const v = b.cost.operator.variable
  const x = b.cost.operator.fixed
  const i = b.cost.infrastructure
  return [
    {
      key: 'operator',
      label: g('operator'),
      value: b.cost.operator.total_eur,
      children: [
        {
          key: 'variable',
          label: g('variable'),
          value: v.total_eur,
          children: [
            { key: 'driver', label: f('driver'), value: v.driver_eur },
            { key: 'crew', label: f('crew'), value: v.crew_eur },
            {
              key: 'coach_maintenance',
              label: f('coach_maintenance'),
              value: v.coach_maintenance_eur,
            },
            { key: 'loco', label: f('loco'), value: v.loco_eur },
            { key: 'svc_stockings', label: f('svc_stockings'), value: v.svc_stockings_eur },
            { key: 'var_overhead', label: f('var_overhead'), value: v.var_overhead_eur },
          ],
        },
        {
          key: 'fixed',
          label: g('fixed'),
          value: x.total_eur,
          children: [
            {
              key: 'coach_amortisation',
              label: f('coach_amortisation'),
              value: x.coach_amortisation_eur,
            },
            { key: 'financing', label: f('financing'), value: x.financing_eur },
            { key: 'fix_overhead', label: f('fix_overhead'), value: x.fix_overhead_eur },
            { key: 'cleaning', label: f('cleaning'), value: x.cleaning_eur },
            { key: 'shunting', label: f('shunting'), value: x.shunting_eur },
          ],
        },
      ],
    },
    {
      key: 'infrastructure',
      label: g('infrastructure'),
      value: i.total_eur,
      children: [
        { key: 'tac', label: f('tac'), value: i.tac_eur },
        { key: 'energy', label: f('energy'), value: i.energy_eur },
        { key: 'station_charge', label: f('station_charge'), value: i.station_charge_eur },
        { key: 'parking', label: f('parking'), value: i.parking_eur },
      ],
    },
    // The operator's expected margin is a profit carve-out rather than a cost,
    // so the backend keeps it out of cost.total_eur — but the subsidy figure
    // beside this tree does include it. It therefore sits here as a peer of
    // operator and infrastructure, not inside operator, whose own total would
    // otherwise disagree with the children under it.
    { key: 'ebit_margin', label: g('margin'), value: b.margin.ebit_margin_eur },
  ]
})

const expanded = ref(new Set<string>(['operator', 'infrastructure']))

function toggleExpand(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

interface CostRow {
  key: string
  label: string
  value: number
  depth: number
  hasChildren: boolean
  isExpanded: boolean
  share: number | null
}

const costRows = computed<CostRow[]>(() => {
  const total = fundedCostEur(props.breakdown)
  const rows: CostRow[] = []
  const visit = (nodes: CostNode[], depth: number) => {
    for (const n of nodes) {
      const isExpanded = expanded.value.has(n.key)
      rows.push({
        key: n.key,
        label: n.label,
        value: n.value,
        depth,
        hasChildren: (n.children?.length ?? 0) > 0,
        isExpanded,
        share: total !== 0 ? n.value / total : null,
      })
      if (n.children && isExpanded) visit(n.children, depth + 1)
    }
  }
  visit(costTree.value, 0)
  return rows
})

// --- Cost-factor detail popover --------------------------------------------
// A tree node's key maps to its formula key via factorFeedback — leaves by
// appending "_eur", the four subtotal rows by name (operator →
// operator_total_eur). The icon shows only where a formula exists, which
// before that mapping silently excluded every subtotal row.
const formulaKey = formulaKeyForNode
function hasInfo(nodeKey: string): boolean {
  return formulaKey(nodeKey) in props.formulas
}

const info = ref<InstanceType<typeof FactorInfoPopover> | null>(null)
</script>

<template>
  <div class="w-1/2 rounded-xl bg-primary-50/5 p-4">
    <div class="mb-2 flex items-center gap-1 border-b border-primary-50/10 pb-2">
      <span class="w-5 shrink-0" />
      <span class="flex-1 font-semibold text-primary-50">
        {{ t('proposal.evaluation.groups.cost') }}
      </span>
      <span class="w-12 text-right text-xs text-primary-50/40 tabular-nums">
        {{ formatShare(1) }}
      </span>
      <span class="w-24 text-right font-semibold text-primary-50 tabular-nums">
        {{ formatEur(fundedCostEur(breakdown)) }}
      </span>
    </div>
    <div
      v-for="row in costRows"
      :key="row.key"
      class="flex items-center gap-1 py-1"
      :style="{ paddingLeft: `${row.depth * 16}px` }"
    >
      <button
        v-if="row.hasChildren"
        class="flex w-5 shrink-0 cursor-pointer justify-center text-primary-50/40 transition hover:text-primary-50"
        @click="toggleExpand(row.key)"
      >
        <AppIcon :path="row.isExpanded ? mdiChevronDown : mdiChevronRight" :size="16" />
      </button>
      <span v-else class="w-5 shrink-0" />
      <span
        class="flex flex-1 items-center gap-1 text-sm"
        :class="row.depth === 0 || row.hasChildren ? 'text-primary-50' : 'text-primary-50/70'"
      >
        {{ row.label }}
        <button
          v-if="hasInfo(row.key)"
          type="button"
          class="flex cursor-pointer text-primary-50/40 transition hover:text-primary-50"
          :aria-label="t('proposal.evaluation.info.iconLabel')"
          @mouseenter="info?.open(row.key, $event)"
          @mouseleave="info?.scheduleClose()"
          @click="info?.open(row.key, $event)"
        >
          <AppIcon :path="mdiInformationOutline" :size="14" />
        </button>
      </span>
      <span class="w-12 text-right text-xs text-primary-50/40 tabular-nums">
        {{ formatShare(row.share) }}
      </span>
      <span class="w-24 text-right text-sm text-primary-50 tabular-nums">
        {{ formatEur(row.value) }}
      </span>
    </div>

    <!-- Shared detail popover, driven by the info icons above -->
    <FactorInfoPopover ref="info" :formulas="formulas" />
  </div>
</template>
