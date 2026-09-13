<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  MONTH_KEYS,
  SCHEDULE_PRESETS,
  peakMonth,
  presetOf,
  type SchedulePreset,
} from '@/lib/detailsScope'

// Days per week for each of the twelve months, as twelve vertical sliders:
// the shape of a year is a picture, and a column of steppers is not one.
// Drag, click a track, or use the arrow keys — each slider is a real
// role="slider" so the grid is reachable without a pointer.
//
// PrimeVue's Slider is not used here: twelve of them side by side would each
// bring their own theme wrapper and none of them can carry the value above
// and the month below without a second element anyway.
const props = defineProps<{ months: number[] }>()
const emit = defineEmits<{ 'update:months': [months: number[]] }>()

const { t } = useI18n()

const MAX = 7
const PRESET_ORDER: SchedulePreset[] = ['daily', 'three', 'once', 'summer', 'custom']

const active = computed(() => presetOf(props.months))
const peak = computed(() => peakMonth(props.months))

function setMonth(index: number, days: number) {
  const next = [...props.months]
  next[index] = Math.min(MAX, Math.max(0, Math.round(days)))
  emit('update:months', next)
}

function applyPreset(preset: SchedulePreset) {
  const grid = SCHEDULE_PRESETS[preset as Exclude<SchedulePreset, 'custom'>]
  // "Custom" is a description of the grid, not a grid — clicking it does
  // nothing, which is why it lights by itself rather than being chosen.
  if (grid) emit('update:months', [...grid])
}

/** Pointer position → days, measured from the bottom of the track. */
function fromPointer(event: PointerEvent, index: number) {
  const track = event.currentTarget as HTMLElement
  const box = track.getBoundingClientRect()
  const y = Math.min(Math.max(box.bottom - event.clientY, 0), box.height)
  setMonth(index, (y / box.height) * MAX)
}

function onDown(event: PointerEvent, index: number) {
  const el = event.currentTarget as HTMLElement
  el.setPointerCapture(event.pointerId)
  fromPointer(event, index)
}

function onMove(event: PointerEvent, index: number) {
  const el = event.currentTarget as HTMLElement
  if (el.hasPointerCapture(event.pointerId)) fromPointer(event, index)
}

function onKey(event: KeyboardEvent, index: number) {
  const delta = event.key === 'ArrowUp' ? 1 : event.key === 'ArrowDown' ? -1 : 0
  if (delta === 0) return
  event.preventDefault()
  setMonth(index, props.months[index] + delta)
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex flex-wrap items-center gap-1">
      <button
        v-for="preset in PRESET_ORDER"
        :key="preset"
        type="button"
        class="cursor-pointer rounded-full px-2.5 py-0.5 text-[11px] transition"
        :class="
          active === preset
            ? 'bg-primary-50/15 text-primary-50'
            : 'text-primary-50/55 hover:text-primary-50'
        "
        :aria-pressed="active === preset"
        :disabled="preset === 'custom'"
        @click="applyPreset(preset)"
      >
        {{ t(`proposal.details.schedule.presets.${preset}`) }}
      </button>
    </div>

    <div class="flex items-end gap-1">
      <div
        v-for="(days, i) in months"
        :key="MONTH_KEYS[i]"
        class="flex flex-1 flex-col items-center gap-1"
      >
        <span
          class="text-[11px] tabular-nums"
          :class="days ? 'text-primary-50' : 'text-primary-50/30'"
        >
          {{ days }}
        </span>
        <div
          class="track relative h-24 w-full max-w-6 cursor-pointer rounded-sm bg-primary-50/8 outline-offset-2"
          role="slider"
          tabindex="0"
          :aria-label="t(`proposal.details.schedule.months.${MONTH_KEYS[i]}`)"
          aria-valuemin="0"
          :aria-valuemax="MAX"
          :aria-valuenow="days"
          @pointerdown="onDown($event, i)"
          @pointermove="onMove($event, i)"
          @keydown="onKey($event, i)"
        >
          <span
            v-for="tick in [1, 2, 3, 4, 5, 6]"
            :key="tick"
            class="absolute inset-x-0 h-px bg-primary-50/10"
            :style="{ bottom: `${(tick / MAX) * 100}%` }"
          />
          <span
            class="absolute inset-x-0 bottom-0 rounded-sm bg-sky-300/70"
            :style="{ height: `${(days / MAX) * 100}%` }"
          />
          <span
            class="absolute inset-x-0 h-0.5 bg-sky-200"
            :style="{ bottom: `calc(${(days / MAX) * 100}% - 1px)` }"
          />
        </div>
        <span
          class="text-[10px]"
          :class="peak === i ? 'font-semibold text-amber-300' : 'text-primary-50/45'"
        >
          {{ t(`proposal.details.schedule.months.${MONTH_KEYS[i]}`) }}
        </span>
      </div>
    </div>
    <p class="text-[11px] text-primary-50/40">{{ t('proposal.details.schedule.dragHint') }}</p>
  </div>
</template>

<style scoped>
.track:focus-visible {
  outline: 2px solid var(--color-sky-300);
}
</style>
