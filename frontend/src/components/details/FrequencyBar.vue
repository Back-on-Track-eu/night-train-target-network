<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { MAX_DAYS_PER_WEEK, MIN_DAYS_PER_WEEK, operatingDaysPerYear } from '@/lib/detailsScope'
import {
  FREQUENCY_TICKS,
  frequencyFromKey,
  frequencyFromPointer,
  frequencyPosition,
  frequencyQualifier,
} from '@/lib/frequencyBar'
import { useCompareFormat } from '@/composables/useCompareFormat'

// Days per week as one stepped bar, ticks 1 – 7 (D6): drag, click a tick, or
// use the arrow keys — a real role="slider" so the value is reachable without
// a pointer. The value label sits under it with the two qualifiers the range
// ends deserve, then the operating days and the honest line that which
// weekdays the train runs is not modelled.
//
// PrimeVue's Slider is not used: it cannot carry the tick labels without a
// second element, and the whole control is eight spans.
const props = defineProps<{ modelValue: number }>()
const emit = defineEmits<{ 'update:modelValue': [daysPerWeek: number] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

const position = computed(() => `${frequencyPosition(props.modelValue) * 100}%`)
const label = computed(() => {
  const qualifier = frequencyQualifier(props.modelValue)
  const base = t('proposal.details.schedule.daysPerWeek', { n: props.modelValue })
  return qualifier ? `${base} — ${t(`proposal.details.schedule.qualifier.${qualifier}`)}` : base
})
const note = computed(() =>
  t('proposal.details.schedule.operatingDaysNote', {
    days: fmt.int(operatingDaysPerYear(props.modelValue)),
  }),
)

function set(value: number) {
  if (value !== props.modelValue) emit('update:modelValue', value)
}

function fromPointer(event: PointerEvent) {
  const box = (event.currentTarget as HTMLElement).getBoundingClientRect()
  set(frequencyFromPointer(event.clientX - box.left, box.width))
}

function onDown(event: PointerEvent) {
  const el = event.currentTarget as HTMLElement
  el.setPointerCapture(event.pointerId)
  fromPointer(event)
}

function onMove(event: PointerEvent) {
  const el = event.currentTarget as HTMLElement
  if (el.hasPointerCapture(event.pointerId)) fromPointer(event)
}

function onKey(event: KeyboardEvent) {
  const next = frequencyFromKey(event.key, props.modelValue)
  if (next === null) return
  event.preventDefault()
  set(next)
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <div
      class="bar relative mx-1 mt-1 h-9 cursor-pointer touch-none outline-offset-4"
      role="slider"
      tabindex="0"
      :aria-label="t('proposal.details.schedule.title')"
      :aria-valuemin="MIN_DAYS_PER_WEEK"
      :aria-valuemax="MAX_DAYS_PER_WEEK"
      :aria-valuenow="modelValue"
      :aria-valuetext="label"
      @pointerdown="onDown"
      @pointermove="onMove"
      @keydown="onKey"
    >
      <span class="absolute inset-x-0 top-2 h-1 rounded-full bg-primary-50/15" />
      <span
        class="absolute left-0 top-2 h-1 rounded-full bg-sky-300/80"
        :style="{ width: position }"
      />
      <template v-for="tick in FREQUENCY_TICKS" :key="tick">
        <span
          class="absolute top-1.5 h-2 w-0.5 -translate-x-px bg-primary-50/25"
          :style="{ left: `${frequencyPosition(tick) * 100}%` }"
        />
        <span
          class="absolute top-5 -translate-x-1/2 text-[9px] tabular-nums"
          :class="tick === modelValue ? 'font-semibold text-primary-50' : 'text-primary-50/40'"
          :style="{ left: `${frequencyPosition(tick) * 100}%` }"
        >
          {{ tick }}
        </span>
      </template>
      <span
        class="thumb absolute top-0.5 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-sky-300 bg-primary-900"
        :style="{ left: position }"
      />
    </div>
    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <b class="text-sm font-semibold text-primary-50">{{ label }}</b>
      <span class="text-[11px] text-primary-50/45">{{ note }}</span>
    </div>
  </div>
</template>

<style scoped>
.bar:focus-visible {
  outline: 2px solid var(--color-sky-300);
}
.bar:hover .thumb,
.bar:focus-visible .thumb {
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-sky-300) 30%, transparent);
}
</style>
