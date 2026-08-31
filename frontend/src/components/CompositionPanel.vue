<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Composition } from '@/types/api'
import AppIcon from '@/components/AppIcon.vue'
import CompositionDetailOverlay from '@/components/CompositionDetailOverlay.vue'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { AMENITY_ICONS, CLASS_ICONS, classColor } from '@/lib/compositionFormation'
import {
  mdiChevronLeft,
  mdiChevronRight,
  mdiInformationOutline,
  mdiTrainCarPassenger,
} from '@mdi/js'

// The composition of the computed route: enough to judge it at a glance —
// name, size, speed, the places it sells per class, and what is on board.
// Everything else — the formation drawing, densities, crew and cost inputs —
// lives in the detail overlay behind the info icon. Switching is a recompute,
// which the parent owns.
const props = defineProps<{
  compositions: Composition[]
  selectedId?: string | null
}>()
const emit = defineEmits<{ select: [compId: string] }>()

const { t } = useI18n()
const { formatInt } = useLocaleFormat()

const direction = ref<'forward' | 'backward'>('forward')

const count = computed(() => props.compositions.length)

// The selection lives in the parent (selectedId); the card only reflects it,
// so the shown card can never drift out of range when the list changes.
const currentIndex = computed(() => {
  if (props.selectedId) {
    const i = props.compositions.findIndex((c) => c.composition_id === props.selectedId)
    if (i >= 0) return i
  }
  return 0
})

const current = computed(() => props.compositions[currentIndex.value])

// Places per class, in the catalogue's fixed class order, skipping classes
// this train doesn't carry.
const capacityStats = computed(() => {
  const byClass = current.value?.capacity.by_class ?? {}
  return CLASS_ICONS.map(([classMain, icon]) => ({
    icon,
    color: classColor(classMain),
    label: t(`proposal.evaluation.classes.${classMain}`),
    places: byClass[classMain]?.places ?? 0,
  })).filter((stat) => stat.places > 0)
})

const amenities = computed(() =>
  AMENITY_ICONS.map(([flag, path, key]) => ({
    key,
    path,
    label: t(`proposal.composition.equipment.${key}`),
    present: current.value?.equipment[flag] ?? false,
  })),
)

function navigate(dir: 'prev' | 'next') {
  direction.value = dir === 'next' ? 'forward' : 'backward'
  const n = count.value
  if (n === 0) return
  const next = dir === 'next' ? (currentIndex.value + 1) % n : (currentIndex.value - 1 + n) % n
  emit('select', props.compositions[next].composition_id)
}

const detailOverlay = ref<InstanceType<typeof CompositionDetailOverlay> | null>(null)

const transitionName = computed(() => `slide-${direction.value}`)

// Keep the parent holding a valid selection: emit a default whenever the list
// is populated but selectedId is missing or no longer present in it.
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
  <!-- Column, so the box can carry a label above its content the way the
       scenario box does; the card itself stays the centred row below it. -->
  <div class="relative flex h-full w-full flex-col gap-3 rounded-xl bg-primary-50/5 p-4">
    <!-- Details in the corner: the overlay is far wider than this box, and
         PrimeVue anchors it to the trigger's left edge — opening it from the
         left keeps it over the page instead of pushed off the right side. -->
    <button
      type="button"
      class="absolute top-3 left-3 flex cursor-pointer text-primary-50/40 transition hover:text-primary-50"
      :aria-label="t('proposal.composition.detailsAria')"
      @mouseenter="detailOverlay?.open($event)"
      @mouseleave="detailOverlay?.scheduleClose()"
      @click="detailOverlay?.open($event)"
    >
      <AppIcon :path="mdiInformationOutline" :size="18" />
    </button>

    <span class="text-center text-xs tracking-wide text-primary-50/50 uppercase">
      {{ t('proposal.composition.label') }}
    </span>

    <div class="flex flex-1 items-center gap-2">
      <button
        v-if="count > 1"
        class="shrink-0 cursor-pointer text-primary-50/40 transition hover:text-primary-50"
        :aria-label="t('proposal.composition.previous')"
        @click="navigate('prev')"
      >
        <AppIcon :path="mdiChevronLeft" :size="20" />
      </button>

      <Transition :name="transitionName" mode="out-in">
        <div :key="current?.composition_id" class="flex flex-1 flex-col items-center gap-2">
          <div class="flex flex-wrap items-center justify-center gap-x-2 gap-y-1">
            <AppIcon :path="mdiTrainCarPassenger" :size="18" color="var(--p-primary-50)" />
            <span class="text-base font-bold text-primary-50">{{ current.composition_id }}</span>
            <span
              class="rounded-full border border-primary-50/20 px-2 py-0.5 text-xs text-primary-50/60"
            >
              {{ t(`proposal.composition.strategy.${current.material_strategy}`) }}
            </span>
          </div>

          <div class="text-sm text-primary-50/60">
            {{ formatInt(current.coaches.count) }} {{ t('proposal.composition.coaches') }} ·
            {{ formatInt(current.capacity.total_places) }} {{ t('proposal.composition.places') }} ·
            {{ formatInt(current.routing.max_speed_kmh) }} km/h
          </div>

          <!-- Places per class -->
          <div class="flex flex-wrap justify-center gap-x-5 gap-y-1">
            <div
              v-for="stat in capacityStats"
              :key="stat.label"
              class="flex items-center gap-1.5"
              :title="stat.label"
              :aria-label="`${stat.places} ${stat.label}`"
            >
              <AppIcon :path="stat.icon" :size="18" :color="stat.color" />
              <span class="text-sm font-semibold text-primary-50/80">{{ stat.places }}</span>
            </div>
          </div>

          <!-- On board — dimmed where the train doesn't have it -->
          <div class="flex gap-2">
            <AppIcon
              v-for="amenity in amenities"
              :key="amenity.key"
              :path="amenity.path"
              :size="15"
              :class="amenity.present ? 'text-primary-50/60' : 'text-primary-50/15'"
            />
          </div>
        </div>
      </Transition>

      <button
        v-if="count > 1"
        class="shrink-0 cursor-pointer text-primary-50/40 transition hover:text-primary-50"
        :aria-label="t('proposal.composition.next')"
        @click="navigate('next')"
      >
        <AppIcon :path="mdiChevronRight" :size="20" />
      </button>
    </div>

    <!-- Formation drawing + full parameter set for the shown composition -->
    <CompositionDetailOverlay v-if="current" ref="detailOverlay" :composition="current" />
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
