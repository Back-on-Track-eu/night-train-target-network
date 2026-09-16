<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCompareFormat } from '@/composables/useCompareFormat'

// Every receipt in the card ends with the same three rungs: what one trip
// costs, what the pair of trips costs, what the year costs. The multipliers
// are printed because they are the whole point — a reader should be able to
// check the last row with their eyes.
//
// operatingDays comes from operations.route, not from the schedule grid on
// screen: the figures above are the backend's, so they have to be taken to
// the year by the number the backend used.
const props = defineProps<{
  label: string
  perTrip: number
  operatingDays: number
  tripsPerCycle?: number
  /** A second quantity the strip carries alongside the euros — loco hours,
   *  paid staff hours, kWh. Shown in small type before the money. */
  unit?: { name: string; perTrip: number } | null
  /** Narrow panels (Overhead, three abreast) cannot hold the receipt grid's
   *  fixed 14.25 rem label column: the figure was pushed out of the box.
   *  Compact drops the fixed label and quantity columns — label | × |
   *  figure — and keeps the 7 rem euro column so it still lines up with
   *  the table above it. */
  compact?: boolean
}>()

const { t } = useI18n()
const fmt = useCompareFormat()

const trips = computed(() => props.tripsPerCycle ?? 2)
const perCycle = computed(() => props.perTrip * trips.value)
const perYear = computed(() => perCycle.value * props.operatingDays)
const unitPerCycle = computed(() => (props.unit ? props.unit.perTrip * trips.value : null))
const unitPerYear = computed(() =>
  unitPerCycle.value === null ? null : unitPerCycle.value * props.operatingDays,
)

// Per-trip and per-cycle are bills — exact to the cent, because a reader
// checks them against the receipt above. The year is a figure to read, so it
// follows the shared scaled rule (lib/money.ts) and turns into millions when
// it gets there.
</script>

<template>
  <!-- Five fixed columns, the same in every strip whether or not it carries
       a unit quantity: label 15 rem | multiplier 4 rem | unit quantity
       6 rem | spacer | figure 7 rem. The label column is the receipt's item
       column to the rem, so "× 2" starts exactly where the receipt's second
       column starts, and the multiplier is the staff table's "On board"
       column to the rem, so "12.2 h" starts where "h on train" starts; the figure column is the receipt's euro column to the
       rem and the padding. The box is pulled left by its own padding so the
       text inside it sits on the receipt's left edge rather than a step in.

       One text size for every cell and rows aligned on their centre, not
       their baseline: with two sizes and baseline alignment the cells of a
       row sat at different heights, and a rule drawn per cell broke into
       four pieces. The rule above the year row is ONE element spanning the
       row. -->
  <div class="strip mt-2 rounded-md bg-primary-50/5 py-2 pr-2 pl-3">
    <p class="mb-1 text-[11px] text-primary-50/50">{{ label }}</p>
    <dl
      class="grid items-center gap-y-1 text-xs"
      :class="compact ? 'grid-cols-[1fr_3rem_7rem]' : 'grid-cols-[14.25rem_4rem_6rem_1fr_7rem]'"
    >
      <dt class="text-primary-50/70">{{ t('proposal.details.strip.perTrip') }}</dt>
      <dd />
      <template v-if="!compact">
        <dd class="whitespace-nowrap tabular-nums text-primary-50/50">
          <template v-if="unit">{{ fmt.dec1(unit.perTrip) }} {{ unit.name }}</template>
        </dd>
        <dd />
      </template>
      <dd class="text-right whitespace-nowrap tabular-nums text-primary-50">
        {{ fmt.eur2(perTrip) }}
      </dd>

      <dt class="text-primary-50/70">
        {{ t('proposal.details.strip.perCycle') }}
        <span class="text-primary-50/45">{{ t('proposal.details.strip.bothWays') }}</span>
      </dt>
      <dd class="whitespace-nowrap text-primary-50/40">× {{ trips }}</dd>
      <template v-if="!compact">
        <dd class="whitespace-nowrap tabular-nums text-primary-50/50">
          <template v-if="unitPerCycle !== null">
            {{ fmt.dec1(unitPerCycle) }} {{ unit?.name }}
          </template>
        </dd>
        <dd />
      </template>
      <dd class="text-right whitespace-nowrap tabular-nums text-primary-50">
        {{ fmt.eur2(perCycle) }}
      </dd>

      <div
        class="my-0.5 border-t border-primary-50/10"
        :class="compact ? 'col-span-3' : 'col-span-5'"
        role="presentation"
      />

      <dt class="font-semibold text-primary-50">{{ t('proposal.details.strip.perYear') }}</dt>
      <dd class="whitespace-nowrap text-primary-50/40">× {{ fmt.int(operatingDays) }}</dd>
      <template v-if="!compact">
        <dd class="whitespace-nowrap tabular-nums text-primary-50/50">
          <template v-if="unitPerYear !== null">
            {{ fmt.count(unitPerYear) }} {{ unit?.name }}
          </template>
        </dd>
        <dd />
      </template>
      <dd class="text-right font-semibold whitespace-nowrap tabular-nums text-primary-50">
        {{ fmt.eur(perYear) }}
      </dd>
    </dl>
  </div>
</template>
