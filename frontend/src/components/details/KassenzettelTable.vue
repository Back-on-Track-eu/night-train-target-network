<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useCompareFormat } from '@/composables/useCompareFormat'
import type { ReceiptLine } from '@/lib/detailsScope'

// The receipt every cost panel shows: one line per item with what it was
// charged on, the euros for ONE trip, and that line's share of the panel's
// total — then a bold total row. Shares are of the panel, not of the route:
// the question a receipt answers is "what is this made of".
//
// One component for all of them so the column widths, the number alignment
// and the total rule cannot drift between Train operation, Overhead and (once
// §6.5 lands) Infrastructure.
//
// Column widths are FIXED and shared with the strip beneath (TripCycleYearStrip)
// and with the staff table in the same panel: the item column is always
// 15 rem, so every receipt's second column starts on the same x; the euro
// column is always 7 rem, right-aligned with the same padding, so the figures
// in three stacked receipts and their three strips sit on one vertical line.

const props = defineProps<{
  lines: ReceiptLine[]
  totalLabel: string
  totalEur: number
  /** Column head for the basis column — panels charge on different things. */
  basisLabel?: string | null
  /** Head note under the basis column, e.g. "per-year lines ÷ 732 dep." */
  basisNote?: string | null
  /** Shares are meaningless where lines are a base rather than a bill. */
  showShare?: boolean
}>()

const { t } = useI18n()
const fmt = useCompareFormat()

function share(eur: number): string {
  if (!props.totalEur) return '—'
  return fmt.percent((eur / props.totalEur) * 100)
}
</script>

<template>
  <div class="overflow-x-auto">
    <table
      class="w-full table-fixed border-collapse text-xs"
      :class="basisLabel ? 'min-w-[22rem]' : ''"
    >
      <!-- Fixed layout so the widths below are exact, not minimums. With a
           basis column (Train operation): 15 rem item, the basis
           left-aligned after it, a spacer, and the euros right-aligned in
           7 rem — the staff table in the same panel follows the identical
           scheme. Without one (Overhead's narrow three-abreast panels): the
           item column takes what is left, no spacer, same euro column. -->
      <colgroup>
        <col :class="basisLabel ? 'w-[15rem]' : ''" />
        <col v-if="basisLabel" class="w-56" />
        <col v-if="basisLabel" />
        <col class="w-28" />
        <col v-if="showShare !== false" class="w-14" />
      </colgroup>
      <thead>
        <tr class="text-[11px] text-primary-50/50">
          <th class="py-1 pr-2 pl-3 text-left font-normal">
            {{ t('proposal.details.receipt.item') }}
          </th>
          <th v-if="basisLabel" class="py-1 pr-2 text-left font-normal">
            {{ basisLabel }}
            <span v-if="basisNote" class="block text-[9px] text-primary-50/35">{{
              basisNote
            }}</span>
          </th>
          <th v-if="basisLabel" />
          <th class="py-1 pr-2 text-right font-normal whitespace-nowrap">
            {{ t('proposal.details.receipt.perTrip') }}
          </th>
          <th v-if="showShare !== false" class="py-1 pr-2 text-right font-normal">
            {{ t('proposal.details.receipt.share') }}
          </th>
        </tr>
      </thead>
      <tbody>
        <template v-for="(line, i) in lines" :key="i">
          <tr v-if="line.note" class="border-t border-primary-50/5">
            <td
              :colspan="(basisLabel ? 4 : 2) + (showShare === false ? 0 : 1)"
              class="py-1.5 pr-2 pl-3 text-[11px] leading-snug text-primary-50/45"
            >
              {{ line.label }}
            </td>
          </tr>
          <tr v-else class="border-t border-primary-50/5">
            <td class="py-1 pr-2 pl-3 text-primary-50/85">{{ line.label }}</td>
            <td v-if="basisLabel" class="py-1 pr-2 text-[11px] text-primary-50/55">
              {{ line.basis ?? '—' }}
            </td>
            <td v-if="basisLabel" />
            <td class="py-1 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50">
              {{ fmt.eur2(line.eur) }}
            </td>
            <td
              v-if="showShare !== false"
              class="py-1 pr-2 text-right tabular-nums text-primary-50/50"
            >
              {{ share(line.eur) }}
            </td>
          </tr>
        </template>
        <tr class="border-t border-primary-50/25 font-semibold">
          <td class="py-1.5 pr-2 pl-3 text-primary-50">{{ totalLabel }}</td>
          <td v-if="basisLabel"></td>
          <td v-if="basisLabel" />
          <td class="py-1.5 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50">
            {{ fmt.eur2(totalEur) }}
          </td>
          <td
            v-if="showShare !== false"
            class="py-1.5 pr-2 text-right tabular-nums text-primary-50/60"
          >
            {{ totalEur ? '100 %' : '—' }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
