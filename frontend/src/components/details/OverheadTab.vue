<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Breakdown, Operator } from '@/types/api'
import { useCompareFormat } from '@/composables/useCompareFormat'
import DetailPanel from '@/components/details/DetailPanel.vue'
import { DOCS_DETAIL_PANEL } from '@/lib/docsLinks'
import TripCycleYearStrip from '@/components/details/TripCycleYearStrip.vue'

// Overhead — the company-related costs, on the MODEL'S OWN bases rather than
// as shares of the full cost, which is what makes the three panels worth
// showing separately:
//
//   variable overhead   8 % of TICKET REVENUE (base fare + services)
//   fixed overhead     12 % of operator cost excl. variable overhead and
//                           infrastructure
//   expected margin    10 % of TICKET REVENUE, deducted in the net result
//                           and paid to no one
//
// All three panels are ONE shape, top to bottom: the headline share, what it
// covers, then a three-row receipt — the BASE with a description of what is
// in it, the FACTOR, the OUTCOME per trip — and the trip → cycle → year strip.
// The base is a single line even where it is a sum of eight items: the
// description names them; listing them as rows made one panel three times
// the height of its neighbours and buried the one figure that matters.
//
// Catering is outside all three bases: the contribution is already net of
// the service's own sales, costs and overhead, so charging distribution
// overhead on it would count the same overhead twice. The variable-overhead
// description says so.
const props = defineProps<{
  breakdown: Breakdown | null
  operator: Operator | null
  departuresPerYear: number | null
  operatingDaysPerYear: number | null
  awaitingSchedule: boolean
  awaitingPrices: boolean
}>()

const { t } = useI18n()
const fmt = useCompareFormat()

function perTrip(annual: number | undefined | null): number {
  if (annual === undefined || annual === null || !props.departuresPerYear) return 0
  return annual / props.departuresPerYear
}

const days = computed(() => props.operatingDaysPerYear ?? 0)

// The base of the two revenue shares is TICKET revenue: the base fare plus
// the services sold with it (CALC 0.9.30). Catering is the one revenue leaf
// outside it.
const ticketBase = computed(() => {
  const r = props.breakdown?.revenue
  return r ? perTrip(r.ticket_revenue_eur + (r.services_revenue_eur ?? 0)) : 0
})
const cateringTrip = computed(() => perTrip(props.breakdown?.revenue.catering_contribution_eur))

const fixBase = computed(() => {
  const v = props.breakdown?.cost.operator.variable
  const f = props.breakdown?.cost.operator.fixed
  if (!v || !f) return 0
  return perTrip(v.total_eur - v.var_overhead_eur + f.total_eur - f.fix_overhead_eur)
})

interface Receipt {
  key: 'variable' | 'fixed' | 'margin'
  share: number | null
  ofWhat: string
  baseEur: number
  baseItems: string
  outcomeEur: number
  awaiting: boolean
}

// Each receipt's own cost page — the ⓘ hands over to the formula behind it.
const OVERHEAD_DOCS: Record<Receipt['key'], string> = {
  variable: DOCS_DETAIL_PANEL.overheadVariable,
  fixed: DOCS_DETAIL_PANEL.overheadFixed,
  margin: DOCS_DETAIL_PANEL.overheadMargin,
}

const receipts = computed<Receipt[]>(() => {
  const b = props.breakdown
  const cateringNote = t('proposal.details.overhead.cateringOutside', {
    value: `${cateringTrip.value > 0 ? '+' : ''}${fmt.eur2(cateringTrip.value)}`,
  })
  return [
    {
      key: 'variable',
      share: props.operator?.var_overhead_per ?? null,
      ofWhat: t('proposal.details.overhead.ofTicketRevenue'),
      baseEur: ticketBase.value,
      baseItems: `${t('proposal.details.overhead.ticketBaseItems')} ${cateringNote}`,
      outcomeEur: perTrip(b?.cost.operator.variable.var_overhead_eur),
      awaiting: props.awaitingSchedule || props.awaitingPrices,
    },
    {
      key: 'fixed',
      share: props.operator?.fix_overhead_quota_per ?? null,
      ofWhat: t('proposal.details.overhead.ofOperatorCost'),
      baseEur: fixBase.value,
      baseItems: t('proposal.details.overhead.fixedBaseItems'),
      outcomeEur: perTrip(b?.cost.operator.fixed.fix_overhead_eur),
      awaiting: props.awaitingSchedule,
    },
    {
      key: 'margin',
      share: props.operator?.ebit_margin_per ?? null,
      ofWhat: t('proposal.details.overhead.ofTicketRevenue'),
      baseEur: ticketBase.value,
      baseItems: `${t('proposal.details.overhead.ticketBaseItems')} ${t('proposal.details.overhead.marginNote')}`,
      outcomeEur: perTrip(b?.margin.ebit_margin_eur),
      awaiting: props.awaitingSchedule || props.awaitingPrices,
    },
  ]
})

function pct(share: number | null): string {
  return share === null ? '—' : fmt.percent(share * 100)
}
</script>

<template>
  <div class="grid min-w-0 gap-3 xl:grid-cols-3">
    <DetailPanel
      v-for="r in receipts"
      :key="r.key"
      class="min-w-0"
      :title="t(`proposal.details.overhead.${r.key}.title`)"
      :info="t(`proposal.details.overhead.${r.key}.info`)"
      :doc-path="OVERHEAD_DOCS[r.key]"
      :caption="t(`proposal.details.overhead.${r.key}.caption`)"
      :awaiting="r.awaiting"
    >
      <p class="headline">
        {{ pct(r.share) }}
        <span class="headline-aside">{{ r.ofWhat }}</span>
      </p>
      <p class="covers">{{ t(`proposal.details.overhead.${r.key}.covers`) }}</p>

      <!-- The receipt: three rows, same in all three panels. The item column
           takes what is left; the euro column is the 7 rem every receipt on
           the card uses, so the figures of the three panels sit on one
           edge. -->
      <table class="w-full table-fixed border-collapse text-xs">
        <colgroup>
          <col />
          <col class="w-28" />
        </colgroup>
        <thead>
          <tr class="text-[11px] text-primary-50/50">
            <th class="py-1 pr-2 pl-3 text-left font-normal">
              {{ t('proposal.details.receipt.item') }}
            </th>
            <th class="py-1 pr-2 text-right font-normal whitespace-nowrap">
              {{ t('proposal.details.receipt.perTrip') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr class="border-t border-primary-50/5 align-top">
            <td class="py-1 pr-2 pl-3 text-primary-50/85">
              {{ t('proposal.details.overhead.base') }}
              <span class="block text-[11px] leading-snug text-primary-50/45">{{
                r.baseItems
              }}</span>
            </td>
            <td class="py-1 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50">
              {{ fmt.eur2(r.baseEur) }}
            </td>
          </tr>
          <tr class="border-t border-primary-50/5">
            <td class="py-1 pr-2 pl-3 text-primary-50/85">
              {{ t('proposal.details.overhead.factor') }}
            </td>
            <td class="py-1 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50/70">
              × {{ pct(r.share) }}
            </td>
          </tr>
          <tr class="border-t border-primary-50/25 font-semibold">
            <td class="py-1.5 pr-2 pl-3 text-primary-50">
              {{ t(`proposal.details.overhead.${r.key}.outcome`) }}
            </td>
            <td class="py-1.5 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50">
              {{ fmt.eur2(r.outcomeEur) }}
            </td>
          </tr>
        </tbody>
      </table>

      <div class="mt-auto">
        <TripCycleYearStrip
          :label="t(`proposal.details.overhead.${r.key}.strip`)"
          :per-trip="r.outcomeEur"
          :operating-days="days"
          compact
        />
      </div>
    </DetailPanel>
  </div>
</template>

<style scoped>
.headline {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--color-primary-50);
}

.headline-aside {
  font-size: 11px;
  font-weight: 400;
  color: color-mix(in srgb, var(--color-primary-50) 55%, transparent);
}

.covers {
  min-height: 2.6em;
  font-size: 11px;
  line-height: 1.45;
  color: color-mix(in srgb, var(--color-primary-50) 50%, transparent);
}
</style>
