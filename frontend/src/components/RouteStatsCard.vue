<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { mdiArrowLeftRight, mdiSpeedometerMedium, mdiCalendarSync } from '@mdi/js'

// Headline figures for the displayed trip, all taken straight from the
// /api/route/plan response (per-trip general_parameters + route schedule).
const props = defineProps<{
  distanceKm: number
  avgSpeedKmh: number
  // Raw Frequency enum values from the route's seasonal schedules (deduped).
  frequencies: string[]
}>()

const { t, te } = useI18n()

// Map each raw frequency value to its localized label, falling back to the raw
// value if no translation exists. Usually a single value ("daily").
const frequencyLabel = computed(() =>
  props.frequencies
    .map((f) => (te(`proposal.frequency.${f}`) ? t(`proposal.frequency.${f}`) : f))
    .join(', '),
)

const stats = computed(() => [
  { icon: mdiArrowLeftRight, value: `${Math.round(props.distanceKm)} km` },
  { icon: mdiSpeedometerMedium, value: `${Math.round(props.avgSpeedKmh)} km/h` },
  { icon: mdiCalendarSync, value: frequencyLabel.value },
])
</script>

<template>
  <div class="overflow-hidden rounded-xl bg-primary-50/5 mx-16 py-5">
    <div class="flex flex-wrap justify-center gap-x-8 gap-y-4 text-primary-50/70">
      <div v-for="stat in stats" :key="stat.icon" class="flex items-center gap-2">
        <AppIcon :path="stat.icon" :size="20" />
        <span class="text-base font-semibold">{{ stat.value }}</span>
      </div>
    </div>
  </div>
</template>
