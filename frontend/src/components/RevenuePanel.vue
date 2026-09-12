<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import FactorInfoPopover from '@/components/FactorInfoPopover.vue'
import LedgerTree from '@/components/LedgerTree.vue'
import { formulaKeyForNode } from '@/lib/factorFeedback'
import { classColor } from '@/lib/compositionFormation'
import type { Breakdown, FormulaMap } from '@/types/api'
import type { LedgerRow } from '@/lib/ledgerRows'

// Revenue side of the split, in the same LedgerTree as the cost side: same
// chevron gutter, same share column, same figure column, so the two read as
// one table rather than as a tree next to a list.
//
// Three top-level rows, the three parts of the tariff:
//
//   Base fare revenue      expandable into the accommodation classes
//   Additional services    bikes, luggage, reservations
//   Catering, net          SIGNED — green when it contributes, amber when the
//                          tickets carry it
//
// Only the base fare expands. Cost deliberately does not split by class at
// all — a class cell of a driver's wage is an allocation, not a measurement —
// but revenue per class IS measured: places sold times what they sold for.
const props = defineProps<{
  breakdown: Breakdown
  classSplit: { classMain: string; breakdown: Breakdown }[]
  formulas: FormulaMap
}>()

const { t, te } = useI18n()

const info = ref<InstanceType<typeof FactorInfoPopover> | null>(null)
const expanded = ref(new Set<string>(['ticket_revenue']))

function toggleExpand(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

function hasInfo(node: string) {
  return formulaKeyForNode(node) in props.formulas
}

const total = computed(() => props.breakdown.revenue.total_eur)

function share(value: number): number | null {
  return total.value ? value / total.value : null
}

const rows = computed<LedgerRow[]>(() => {
  const r = props.breakdown.revenue
  const isOpen = expanded.value.has('ticket_revenue')
  const classRows = props.classSplit
    .map((entry) => ({
      classMain: entry.classMain,
      eur: entry.breakdown.revenue.ticket_revenue_eur,
    }))
    .filter((row) => row.eur !== 0)
    .sort((a, b) => b.eur - a.eur)

  const out: LedgerRow[] = [
    {
      key: 'ticket_revenue',
      label: t('proposal.evaluation.fields.ticket_revenue'),
      value: r.ticket_revenue_eur,
      depth: 0,
      hasChildren: classRows.length > 0,
      isExpanded: isOpen,
      share: share(r.ticket_revenue_eur),
    },
  ]
  if (isOpen) {
    for (const row of classRows) {
      out.push({
        key: `class:${row.classMain}`,
        label: te(`proposal.evaluation.classes.${row.classMain}`)
          ? t(`proposal.evaluation.classes.${row.classMain}`)
          : row.classMain,
        value: row.eur,
        depth: 1,
        hasChildren: false,
        isExpanded: false,
        share: share(row.eur),
        color: classColor(row.classMain),
      })
    }
  }
  out.push({
    key: 'services_revenue',
    label: t('proposal.evaluation.fields.services_revenue'),
    value: r.services_revenue_eur ?? 0,
    depth: 0,
    hasChildren: false,
    isExpanded: false,
    share: share(r.services_revenue_eur ?? 0),
  })
  out.push({
    key: 'catering_contribution',
    label: t('proposal.evaluation.fields.catering_contribution'),
    value: r.catering_contribution_eur ?? 0,
    depth: 0,
    hasChildren: false,
    isExpanded: false,
    share: share(r.catering_contribution_eur ?? 0),
    signed: true,
  })
  return out
})
</script>

<template>
  <LedgerTree
    :title="t('proposal.evaluation.groups.revenue')"
    :total="total"
    :rows="rows"
    :has-info="hasInfo"
    @toggle="toggleExpand"
    @info="(key, label, event) => info?.open(key, label, event)"
    @info-close="info?.scheduleClose()"
  />

  <FactorInfoPopover ref="info" :formulas="formulas" />
</template>
