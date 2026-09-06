<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import type { ProposalCalcSummary } from '@/types/api'

// Demand & modal shift — whole-route, annual figures. The backend serves no
// per-view/-class/-section split and no per-unit demand normalisation, so
// this box is independent of ViewRow's cube dropdowns entirely — only the
// scenario selector (a full recompute) changes it.
const props = defineProps<{
  summary?: ProposalCalcSummary | null
}>()

const { t } = useI18n()
const { formatCount } = useEvaluationFormat()

const demand = computed(() => {
  const s = props.summary
  if (!s || s.demand_trips_per_year == null) return null
  return {
    trips: s.demand_trips_per_year ?? 0,
    airTrips: s.shift_air_trips_per_year ?? 0,
    airTripKm: s.shift_air_trip_km_per_year ?? 0,
    carTrips: s.shift_car_trips_per_year ?? 0,
    carTripKm: s.shift_car_trip_km_per_year ?? 0,
    co2SavingsT: s.co2_savings_t_per_year ?? 0,
    co2PerPaxKm: s.co2_g_per_pax_km ?? null,
    subsidyPerTCo2: s.subsidy_eur_per_t_co2 ?? null,
    placeholder: s.demand_kpis_placeholder === true,
  }
})
</script>

<template>
  <div v-if="demand" class="flex flex-col gap-3">
    <div class="flex flex-col gap-1">
      <h2 class="text-base font-semibold text-primary-50">
        {{ t('proposal.evaluation.sections.impact.title') }}
      </h2>
      <p class="text-sm leading-relaxed text-primary-50/70">
        {{ t('proposal.evaluation.sections.impact.body') }}
      </p>
    </div>
    <div class="rounded-xl bg-primary-50/5 p-4">
      <div v-if="demand.placeholder" class="mb-2 flex justify-end">
        <span
          class="rounded-full bg-amber-400/15 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-amber-300 uppercase"
          :title="t('proposal.evaluation.demand.estimateHint')"
        >
          {{ t('proposal.evaluation.demand.estimate') }}
        </span>
      </div>

      <div class="grid grid-cols-3 gap-x-4 gap-y-5">
        <!-- Row 1: CO₂ saved · Subsidy per t CO₂ · CO₂ intensity -->
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.demand.co2Saved') }}
          </span>
          <span class="text-xl font-bold text-primary-50 tabular-nums">
            {{ formatCount(demand.co2SavingsT) }}
            {{ t('proposal.evaluation.demand.units.tCo2PerYear') }}
          </span>
        </div>
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.demand.subsidyPerCo2') }}
          </span>
          <span class="text-xl font-bold text-primary-50 tabular-nums">
            {{
              demand.subsidyPerTCo2 != null
                ? `${formatCount(demand.subsidyPerTCo2)} ${t('proposal.evaluation.demand.units.eurPerTCo2')}`
                : '—'
            }}
          </span>
        </div>
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.demand.co2Intensity') }}
          </span>
          <span class="text-xl font-bold text-primary-50 tabular-nums">
            {{
              demand.co2PerPaxKm != null
                ? `${formatCount(demand.co2PerPaxKm)} ${t('proposal.evaluation.demand.units.gPerPaxKm')}`
                : '—'
            }}
          </span>
        </div>
        <!-- Row 2: Passenger trips · Shifted from air · Shifted from car -->
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.demand.trips') }}
          </span>
          <span class="text-xl font-bold text-primary-50 tabular-nums">
            {{ formatCount(demand.trips) }} {{ t('proposal.evaluation.demand.units.tripsPerYear') }}
          </span>
        </div>
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.demand.fromAir') }}
          </span>
          <span class="text-xl font-bold text-primary-50 tabular-nums">
            {{ formatCount(demand.airTrips) }}
            {{ t('proposal.evaluation.demand.units.tripsPerYear') }}
          </span>
          <span class="text-[10px] text-primary-50/40">
            {{ formatCount(demand.airTripKm) }} {{ t('proposal.evaluation.demand.units.paxKm') }}
          </span>
        </div>
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.demand.fromCar') }}
          </span>
          <span class="text-xl font-bold text-primary-50 tabular-nums">
            {{ formatCount(demand.carTrips) }}
            {{ t('proposal.evaluation.demand.units.tripsPerYear') }}
          </span>
          <span class="text-[10px] text-primary-50/40">
            {{ formatCount(demand.carTripKm) }} {{ t('proposal.evaluation.demand.units.paxKm') }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
