<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ProposalCalcSummary } from '@/types/api'
import { useCompareFormat } from '@/composables/useCompareFormat'

// Zone D's "Frequency & supply" column: what the selected composition puts
// on the rails per year, both directions, from the summary's annual supply
// figures (CALC 0.9.25). Frequency is read off the resolved request's
// schedule_mode; the train-set count is the sketch's fleet line and stays
// out until the roster model exposes it per route.
const props = defineProps<{
  summary: ProposalCalcSummary
  compositionPlaces: number | null
  scheduleMode: string | null
}>()

const { t, te } = useI18n()
const fmt = useCompareFormat()

const rows = computed(() => {
  const s = props.summary
  const departures =
    s.operating_days_per_year != null && s.train_km_per_year != null && s.total_distance_km
      ? s.operating_days_per_year * 2
      : null
  const utilisation =
    s.sold_place_km_per_year != null && s.available_place_km_per_year
      ? (s.sold_place_km_per_year / s.available_place_km_per_year) * 100
      : null
  return [
    { key: 'departures', value: departures === null ? null : fmt.int(departures) },
    { key: 'trainKm', value: s.train_km_per_year == null ? null : fmt.count(s.train_km_per_year) },
    {
      key: 'places',
      value:
        departures === null || props.compositionPlaces === null
          ? null
          : fmt.count(departures * props.compositionPlaces),
    },
    {
      key: 'placeKm',
      value:
        s.available_place_km_per_year == null ? null : fmt.count(s.available_place_km_per_year),
    },
    { key: 'utilisation', value: utilisation === null ? null : fmt.percent(utilisation) },
  ]
})

const frequency = computed(() => {
  const key = props.scheduleMode ? `proposal.supply.schedule.${props.scheduleMode}` : null
  return key && te(key) ? t(key) : (props.scheduleMode ?? '—')
})
</script>

<template>
  <aside class="flex flex-col gap-2 rounded-lg border border-primary-50/10 p-3 text-xs">
    <h3 class="text-sm font-semibold text-primary-50">{{ t('proposal.supply.sidebar.title') }}</h3>
    <div class="flex items-center justify-between text-primary-50/70">
      <span>{{ t('proposal.supply.sidebar.frequency') }}</span>
      <span class="font-semibold text-primary-50">{{ frequency }}</span>
    </div>
    <p class="text-[11px] text-primary-50/50">{{ t('proposal.supply.sidebar.perYear') }}</p>
    <dl class="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
      <template v-for="row in rows" :key="row.key">
        <dt class="text-primary-50/70">{{ t(`proposal.supply.sidebar.${row.key}`) }}</dt>
        <dd class="text-right font-semibold text-primary-50">{{ row.value ?? '—' }}</dd>
      </template>
    </dl>
    <p class="text-[11px] text-primary-50/40">{{ t('proposal.supply.sidebar.utilisationNote') }}</p>
  </aside>
</template>
