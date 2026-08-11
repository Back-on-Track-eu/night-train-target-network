<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Composition } from '@/types/api'
import AppIcon from '@/components/AppIcon.vue'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import {
  mdiSeatPassenger,
  mdiBunkBed,
  mdiBed,
  mdiBedOutline,
  mdiWeight,
  mdiSpeedometer,
  mdiChevronLeft,
  mdiChevronRight,
  mdiTrainCarPassenger,
  mdiArrowLeftRight,
  mdiSpeedometerMedium,
  mdiCalendarSync,
} from '@mdi/js'

// compact: display mode — show only the name and capacities, hiding the
// description and physical specs (weight / max. speed). routeStats: the
// headline route figures (distance/speed/frequency) merged in alongside the
// composition, shown only once a route exists (compact mode).
const props = defineProps<{
  compositions: Composition[]
  selectedId?: string | null
  compact?: boolean
  routeStats?: { distanceKm: number; avgSpeedKmh: number; frequencies: string[] } | null
}>()
const emit = defineEmits<{ select: [compId: string] }>()

const { t, te } = useI18n()
const { formatInt } = useLocaleFormat()

const direction = ref<'forward' | 'backward'>('forward')

const count = computed(() => props.compositions.length)

// The selection lives in the parent (selectedId); the card only reflects it.
// That keeps the shown card correct when the parent locks the list down to a
// single composition (display) and reopens it to the full set (edit) — the
// index can never drift out of range.
const currentIndex = computed(() => {
  if (props.selectedId) {
    const i = props.compositions.findIndex((c) => c.composition_id === props.selectedId)
    if (i >= 0) return i
  }
  return 0
})

function navigate(dir: 'prev' | 'next') {
  direction.value = dir === 'next' ? 'forward' : 'backward'
  const n = count.value
  if (n === 0) return
  const next = dir === 'next' ? (currentIndex.value + 1) % n : (currentIndex.value - 1 + n) % n
  emit('select', props.compositions[next].composition_id)
}

const current = computed(() => props.compositions[currentIndex.value])

// capacity.by_class is keyed by class_main directly (2026-07-22) — the
// old density-constant matching is gone with the retired density column.
const capacityStats = computed(() => {
  const by = current.value?.capacity.by_class ?? {}
  const stats: { icon: string; count: number }[] = []
  const seats = by['Seat']?.places ?? 0
  const couchettes = by['Couchette']?.places ?? 0
  const sleepers = by['Sleeper']?.places ?? 0
  const capsules = by['Capsule']?.places ?? 0
  if (seats > 0) stats.push({ icon: mdiSeatPassenger, count: seats })
  if (couchettes > 0) stats.push({ icon: mdiBunkBed, count: couchettes })
  if (sleepers > 0) stats.push({ icon: mdiBed, count: sleepers })
  if (capsules > 0) stats.push({ icon: mdiBedOutline, count: capsules })
  return stats
})

// Merged in from the former RouteStatsCard — headline route figures shown
// below the composition once a route exists (display mode only).
const frequencyLabel = computed(() =>
  (props.routeStats?.frequencies ?? [])
    .map((f) => (te(`proposal.frequency.${f}`) ? t(`proposal.frequency.${f}`) : f))
    .join(', '),
)
const routeStatRows = computed(() => {
  const rs = props.routeStats
  if (!rs) return []
  return [
    { icon: mdiArrowLeftRight, value: `${formatInt(rs.distanceKm)} km` },
    { icon: mdiSpeedometerMedium, value: `${formatInt(rs.avgSpeedKmh)} km/h` },
    { icon: mdiCalendarSync, value: frequencyLabel.value },
  ]
})

const transitionName = computed(() => `slide-${direction.value}`)

// Keep the parent holding a valid selection: emit a default whenever the list
// is populated but selectedId is missing or no longer present in it (initial
// load, or the list changing underneath the current selection).
watch(
  () => [props.compositions, props.selectedId] as const,
  () => {
    if (props.compositions.length === 0) return
    const valid =
      props.selectedId && props.compositions.some((c) => c.composition_id === props.selectedId)
    if (!valid) emit('select', props.compositions[0].composition_id)
  },
  { immediate: true },
)
</script>

<template>
  <div class="max-w-md overflow-hidden rounded-xl bg-primary-50/5 mr-16 py-5 px-12">
    <div class="flex flex-col items-center gap-4 text-center">
      <!-- Name row with inline arrows -->
      <div class="flex items-center gap-2">
        <button
          v-if="count > 1"
          class="shrink-0 cursor-pointer text-primary-50/40 transition hover:text-primary-50"
          @click="navigate('prev')"
        >
          <AppIcon :path="mdiChevronLeft" :size="20" />
        </button>
        <span class="flex items-center gap-2">
          <AppIcon :path="mdiTrainCarPassenger" :size="18" color="var(--p-primary-50)" />
          <p class="text-base font-bold text-primary-50">{{ current.composition_id }}</p>
        </span>
        <button
          v-if="count > 1"
          class="shrink-0 cursor-pointer text-primary-50/40 transition hover:text-primary-50"
          @click="navigate('next')"
        >
          <AppIcon :path="mdiChevronRight" :size="20" />
        </button>
      </div>

      <!-- Description: smaller line below the headline -->
      <p v-if="!compact && current.description" class="-mt-3 text-sm text-primary-50/60">
        {{ current.description }}
      </p>

      <!-- Pagination dots -->
      <div v-if="count > 1" class="flex gap-1.5">
        <span
          v-for="i in count"
          :key="i"
          class="h-1.5 w-1.5 rounded-full transition-colors duration-200"
          :class="i - 1 === currentIndex ? 'bg-primary-50' : 'bg-primary-50/30'"
        />
      </div>

      <!-- Animated: capacity + physical specs -->
      <Transition :name="transitionName" mode="out-in">
        <div :key="current?.composition_id" class="flex flex-col items-center gap-4">
          <!-- Capacity -->
          <div v-if="capacityStats.length > 0" class="flex justify-center gap-8">
            <div
              v-for="stat in capacityStats"
              :key="stat.icon"
              class="flex items-center gap-2 text-primary-50/70"
            >
              <AppIcon :path="stat.icon" :size="20" />
              <span class="text-base font-semibold">{{ stat.count }}</span>
            </div>
          </div>

          <!-- Physical specs -->
          <div v-if="!compact" class="flex justify-center gap-8 text-primary-50/70">
            <div class="flex items-center gap-2">
              <AppIcon :path="mdiWeight" :size="20" />
              <span class="text-base font-semibold"
                >{{ formatInt(current.routing.total_weight_t) }} t</span
              >
            </div>
            <div class="flex items-center gap-2">
              <AppIcon :path="mdiSpeedometer" :size="20" />
              <span class="text-base font-semibold"
                >max. {{ formatInt(current.routing.max_speed_kmh) }} km/h</span
              >
            </div>
          </div>

          <!-- Route stats (merged in from RouteStatsCard, display mode only) -->
          <div
            v-if="routeStatRows.length > 0"
            class="flex flex-wrap justify-center gap-x-8 gap-y-4 text-primary-50/70"
          >
            <div v-for="stat in routeStatRows" :key="stat.icon" class="flex items-center gap-2">
              <AppIcon :path="stat.icon" :size="20" />
              <span class="text-base font-semibold">{{ stat.value }}</span>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.slide-forward-enter-active,
.slide-forward-leave-active,
.slide-backward-enter-active,
.slide-backward-leave-active {
  transition:
    transform 0.12s ease,
    opacity 0.12s ease;
}

.slide-forward-enter-from {
  transform: translateX(28px);
  opacity: 0;
}
.slide-forward-leave-to {
  transform: translateX(-28px);
  opacity: 0;
}

.slide-backward-enter-from {
  transform: translateX(-28px);
  opacity: 0;
}
.slide-backward-leave-to {
  transform: translateX(28px);
  opacity: 0;
}
</style>
