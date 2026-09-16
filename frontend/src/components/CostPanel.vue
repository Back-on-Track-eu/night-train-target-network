<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import FactorInfoPopover from '@/components/FactorInfoPopover.vue'
import LedgerTree from '@/components/LedgerTree.vue'
import { formulaKeyForNode } from '@/lib/factorFeedback'
import type { Breakdown, FormulaMap } from '@/types/api'
import type { LedgerRow } from '@/lib/ledgerRows'

// Cost tree (left column of the cost/revenue split) plus its cost-factor
// detail popover — a one-line summary and a link to the factor's
// documentation page.
//
// The table itself is LedgerTree, shared with the revenue side so the two
// columns line up column for column.
//
// The formula, the input legend and the resolved rates used to live in this
// popover. They are on the documentation site now: a rates table with its
// sources is a page, not something to read in a hover box.
const props = defineProps<{
  breakdown: Breakdown
  formulas: FormulaMap
}>()

const { t } = useI18n()

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
  ]
})

const expanded = ref(new Set<string>(['operator', 'infrastructure']))

function toggleExpand(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

// Operating cost only. The operator's expected margin is a profit carve-out,
// not a cost — the backend keeps it out of cost.total_eur — and it has its
// own panel (MarginPanel) rather than a row here, so this total is the sum
// of the rows under it and nothing else.
const costRows = computed<LedgerRow[]>(() => {
  const total = props.breakdown.cost.total_eur
  const rows: LedgerRow[] = []
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
  <LedgerTree
    :title="t('proposal.evaluation.groups.cost')"
    :total="breakdown.cost.total_eur"
    :rows="costRows"
    :has-info="hasInfo"
    @toggle="toggleExpand"
    @info="(key, label, event) => info?.open(key, label, event)"
    @info-close="info?.scheduleClose()"
  />

  <!-- Shared detail popover, driven by the info icons in the ledger -->
  <FactorInfoPopover ref="info" :formulas="formulas" />
</template>
