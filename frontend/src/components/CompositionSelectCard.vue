<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Composition } from '@/types/api'
import AppIcon from '@/components/AppIcon.vue'
import {
  mdiSeatPassenger,
  mdiBunkBed,
  mdiBed,
  mdiWeight,
  mdiSpeedometer,
  mdiChevronLeft,
  mdiChevronRight,
} from '@mdi/js'

const props = defineProps<{ compositions: Composition[] }>()
const emit = defineEmits<{ select: [compId: string] }>()

const currentIndex = ref(0)
const direction = ref<'forward' | 'backward'>('forward')

const count = computed(() => props.compositions.length)

function navigate(dir: 'prev' | 'next') {
  direction.value = dir === 'next' ? 'forward' : 'backward'
  const n = count.value
  currentIndex.value =
    dir === 'next' ? (currentIndex.value + 1) % n : (currentIndex.value - 1 + n) % n
}

const current = computed(() => props.compositions[currentIndex.value])

function sumPlacesByDensity(comp: Composition, density: number): number {
  return Object.values(comp.capacity)
    .filter((c) => Math.abs(c.density - density) < 0.005)
    .reduce((sum, c) => sum + c.places, 0)
}

const capacityStats = computed(() => {
  const c = current.value
  const stats: { icon: string; count: number }[] = []
  const seats = sumPlacesByDensity(c, 1 / 64)
  const couchettes = sumPlacesByDensity(c, 1 / 20)
  const sleepers = sumPlacesByDensity(c, 1 / 12)
  if (seats > 0) stats.push({ icon: mdiSeatPassenger, count: seats })
  if (couchettes > 0) stats.push({ icon: mdiBunkBed, count: couchettes })
  if (sleepers > 0) stats.push({ icon: mdiBed, count: sleepers })
  return stats
})

const transitionName = computed(() => `slide-${direction.value}`)

watch(current, (c) => emit('select', c.comp_id), { immediate: true })
</script>

<template>
  <div class="overflow-hidden rounded-xl bg-primary-50/5 mx-16 py-5">
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
        <p class="text-base font-bold text-primary-50">{{ current.description }}</p>
        <button
          v-if="count > 1"
          class="shrink-0 cursor-pointer text-primary-50/40 transition hover:text-primary-50"
          @click="navigate('next')"
        >
          <AppIcon :path="mdiChevronRight" :size="20" />
        </button>
      </div>

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
        <div :key="currentIndex" class="flex flex-col items-center gap-4 mt-4">
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
          <div class="flex justify-center gap-8 text-primary-50/70">
            <div class="flex items-center gap-2">
              <AppIcon :path="mdiWeight" :size="20" />
              <span class="text-base font-semibold"
                >{{ Math.round(current.routing.total_weight_t) }} t</span
              >
            </div>
            <div class="flex items-center gap-2">
              <AppIcon :path="mdiSpeedometer" :size="20" />
              <span class="text-base font-semibold"
                >max. {{ current.routing.max_speed_kmh }} km/h</span
              >
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
