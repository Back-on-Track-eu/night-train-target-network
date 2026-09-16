<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Breakdown, ProposalCalcSummary } from '@/types/api'
import { CATERING_COLOR, CATERING_ICON, CLASS_ICONS, classColor } from '@/lib/compositionFormation'
import { useCompareFormat } from '@/composables/useCompareFormat'
import AppIcon from '@/components/AppIcon.vue'
import DetailPanel from '@/components/details/DetailPanel.vue'

// Demand — what the interim assumption produces, with the catering
// contribution shown beside the ticket revenue rather than folded into it:
// the two are earned in different ways and one of them can be negative.
//
// "Passengers" is passengers_per_year — the places actually sold, the base the
// contribution multiplies — NOT demand_trips_per_year, which is a placeholder
// derived from revenue and would not reconcile with the figure beside it.
//
// The whole panel waits on both scopes: nothing here is arithmetic the page
// can do, because the demand distribution is the backend's.
const props = defineProps<{
  summary: ProposalCalcSummary | null
  breakdown: Breakdown | null
  /** Ticket revenue per class_main, from the route view's class cells — the
   *  card has them, this panel only draws them. */
  classRevenue: Record<string, number> | null
  awaiting: boolean
}>()

const { t } = useI18n()
const fmt = useCompareFormat()

const ticketRevenue = computed(() => props.breakdown?.revenue.ticket_revenue_eur ?? null)
const catering = computed(() => props.breakdown?.revenue.catering_contribution_eur ?? null)
const totalRevenue = computed(() => props.breakdown?.revenue.total_eur ?? null)

const rows = computed(() => [
  {
    key: 'passengers',
    value:
      props.summary?.passengers_per_year === undefined
        ? null
        : fmt.count(props.summary.passengers_per_year),
  },
  {
    key: 'placeKmSold',
    value:
      props.summary?.sold_place_km_per_year === undefined
        ? null
        : fmt.count(props.summary.sold_place_km_per_year),
  },
  {
    key: 'utilisation',
    value:
      props.summary?.sold_place_km_per_year && props.summary?.available_place_km_per_year
        ? fmt.percent(
            (props.summary.sold_place_km_per_year / props.summary.available_place_km_per_year) *
              100,
          )
        : null,
  },
])

/** Ticket revenue by class from the route view's class cells — the same
 *  colours the formation, the prices table and the comparison table use. */
const classSplit = computed(() => {
  const total = ticketRevenue.value
  if (!total) return []
  return CLASS_ICONS.map(([classMain]) => ({
    classMain,
    color: classColor(classMain),
    eur: props.classRevenue?.[classMain] ?? 0,
  }))
    .filter((row) => row.eur > 0)
    .map((row) => ({ ...row, share: row.eur / total }))
})
</script>

<template>
  <div class="grid gap-3 xl:grid-cols-[1fr_18rem]">
    <DetailPanel
      :title="t('proposal.details.demand.title')"
      :info="t('proposal.details.demand.info')"
      :caption="t('proposal.details.demand.caption')"
      :awaiting="awaiting"
    >
      <dl class="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-xs">
        <template v-for="row in rows" :key="row.key">
          <dt class="text-primary-50/65">{{ t(`proposal.details.demand.${row.key}`) }}</dt>
          <dd class="text-right font-semibold tabular-nums text-primary-50">
            {{ row.value ?? '—' }}
          </dd>
        </template>

        <dt class="border-t border-primary-50/10 pt-1.5 text-primary-50/65">
          {{ t('proposal.details.demand.ticketRevenue') }}
        </dt>
        <dd
          class="border-t border-primary-50/10 pt-1.5 text-right font-semibold tabular-nums text-primary-50"
        >
          {{ ticketRevenue === null ? '—' : fmt.millionEur(ticketRevenue / 1_000_000) }}
        </dd>

        <dt class="flex items-center gap-1.5 text-primary-50/65">
          <AppIcon :path="CATERING_ICON" :size="13" :style="{ color: CATERING_COLOR }" />
          {{ t('proposal.details.demand.cateringContribution') }}
        </dt>
        <dd
          class="text-right font-semibold tabular-nums"
          :class="
            catering === null
              ? 'text-primary-50'
              : catering > 0
                ? 'text-yellow-green'
                : catering < 0
                  ? 'text-amber-300'
                  : 'text-primary-50'
          "
        >
          <template v-if="catering === null">—</template>
          <template v-else>
            {{ catering > 0 ? '+ ' : '' }}{{ fmt.millionEur(catering / 1_000_000) }}
          </template>
        </dd>

        <dt class="border-t border-primary-50/25 pt-1.5 font-semibold text-primary-50">
          {{ t('proposal.details.demand.totalRevenue') }}
        </dt>
        <dd
          class="border-t border-primary-50/25 pt-1.5 text-right font-semibold tabular-nums text-primary-50"
        >
          {{ totalRevenue === null ? '—' : fmt.millionEur(totalRevenue / 1_000_000) }}
        </dd>
      </dl>

      <template v-if="classSplit.length > 0">
        <p class="mt-2 text-[11px] text-primary-50/50">
          {{ t('proposal.details.demand.byClass') }}
        </p>
        <span class="flex h-2 w-full overflow-hidden rounded bg-primary-50/10">
          <span
            v-for="row in classSplit"
            :key="row.classMain"
            :style="{ width: `${row.share * 100}%`, background: row.color }"
            :title="`${t(`proposal.evaluation.classes.${row.classMain}`)} ${fmt.percent(row.share * 100)}`"
          />
        </span>
        <div class="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-primary-50/60">
          <span v-for="row in classSplit" :key="row.classMain" class="flex items-center gap-1.5">
            <i class="h-2.5 w-2.5 rounded-sm" :style="{ background: row.color }" />
            {{ t(`proposal.evaluation.classes.${row.classMain}`) }}
            {{ fmt.millionEur(row.eur / 1_000_000) }} · {{ fmt.percent(row.share * 100) }}
          </span>
        </div>
      </template>
    </DetailPanel>

    <DetailPanel
      :title="t('proposal.details.demand.restsOn')"
      :info="t('proposal.details.demand.restsOnInfo')"
    >
      <p class="text-xs leading-relaxed text-primary-50/65">
        {{ t('proposal.settings.demand.intro') }}
      </p>
      <ul class="list-disc pl-4 text-[11px] leading-relaxed text-primary-50/55">
        <li>{{ t('proposal.settings.demand.source') }}</li>
        <li>{{ t('proposal.settings.demand.modes') }}</li>
      </ul>
      <p class="text-[11px] leading-relaxed text-primary-50/45">
        {{ t('proposal.details.demand.whenItLands') }}
      </p>
      <p class="text-[11px] text-primary-50/45">
        {{ t('proposal.details.demand.pricesElsewhere') }}
      </p>
    </DetailPanel>
  </div>
</template>
