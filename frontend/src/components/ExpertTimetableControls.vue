<script setup lang="ts">
/**
 * The departure control of expert timetable mode — the row above the
 * timetable that pins or nudges a direction's first departure.
 *
 * Per-leg add-ons are NOT here: they belong between two timetable rows, so
 * they are rendered inline by ProposalViewport's table (a leg strip cannot
 * be lifted out of the rows it sits between without duplicating the whole
 * table). This component owns the one control that has a place of its own,
 * and the state arithmetic for both lives in lib/expertTimetable.ts.
 *
 * Two things this control has to make legible, because they are what the
 * user is actually choosing:
 *   - pinned vs following. A pinned departure keeps its clock time through
 *     a reroute; a following one keeps its distance from the automatic
 *     value and moves when that value moves. The chip says which, and the
 *     line beneath says what it means for this route rather than in the
 *     abstract.
 *   - that there IS an automatic value to go back to — hence the reset,
 *     which is the only way back to "let the model decide".
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { formatClock } from '@/lib/tripClock'
import {
  resolveDeparture,
  setDeparture,
  shiftDeparture,
  toggleDepartureMode,
  type DepartureOverride,
} from '@/lib/expertTimetable'
import { mdiLock, mdiLockOpenVariant, mdiRestore } from '@mdi/js'

const props = defineProps<{
  /** The override in force, or null while the timetable is automatic. */
  departure: DepartureOverride | null
  /** The departure the automatic timetable computed for this direction —
   *  the value a shift is measured from and a reset returns to. */
  autoMin: number
}>()
const emit = defineEmits<{ update: [value: DepartureOverride | null] }>()

const { t } = useI18n()

// Minutes on the service-day scale; the input shows a wall clock, which is
// exactly what formatClock exists for (an overnight value wraps rather than
// reading "26:15").
const currentMin = computed(() => resolveDeparture(props.departure, props.autoMin))
const currentClock = computed(() => formatClock(currentMin.value) ?? '')
const autoClock = computed(() => formatClock(props.autoMin) ?? '')
const pinned = computed(() => props.departure?.mode !== 'shift')
const shiftMin = computed(() => currentMin.value - props.autoMin)

const STEPS = [-30, -5, 5, 30]

function nudge(delta: number) {
  emit('update', shiftDeparture(props.departure, props.autoMin, delta))
}

/**
 * A typed "HH:MM" names a time of day, not a service-day minute — 23:55 is
 * minute 1435 on day one and −5 on a mirrored return. Resolve it to the
 * candidate day that lands nearest where the departure already is, so
 * typing a time never jumps the train a day; the +1 markers in the table
 * then show what that time actually means.
 */
function onTimeInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  const [h, m] = value.split(':').map(Number)
  if (!Number.isFinite(h) || !Number.isFinite(m)) return
  const DAY = 1440
  const base = Math.floor(currentMin.value / DAY) * DAY + h * 60 + m
  const candidate = [base - DAY, base, base + DAY].reduce((best, c) =>
    Math.abs(c - currentMin.value) < Math.abs(best - currentMin.value) ? c : best,
  )
  emit('update', setDeparture(props.departure, props.autoMin, candidate))
}
</script>

<template>
  <div class="expert-box flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl px-3.5 py-3">
    <span class="text-xs tracking-wide text-primary-50/70 uppercase">
      {{ t('proposal.expert.firstDeparture') }}
    </span>

    <!-- Pinned / follows automatic. Written as a chip rather than a checkbox
         because it is a state of the value, not an extra option. -->
    <button
      type="button"
      class="flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs leading-none transition"
      :class="
        pinned
          ? 'border-amber-300/50 bg-amber-300/10 text-amber-200'
          : 'border-primary-50/20 bg-primary-50/5 text-primary-50/70'
      "
      :aria-pressed="pinned"
      @click="emit('update', toggleDepartureMode(departure, autoMin))"
    >
      <AppIcon :path="pinned ? mdiLock : mdiLockOpenVariant" :size="14" />
      {{ pinned ? t('proposal.expert.pinned') : t('proposal.expert.follows') }}
    </button>

    <div class="flex items-center gap-1">
      <button
        v-for="step in STEPS"
        :key="step"
        type="button"
        class="h-8 min-w-10 cursor-pointer rounded-lg border border-primary-50/20 bg-primary-50/5 px-2 text-xs tabular-nums text-primary-50 transition hover:bg-primary-50/15"
        :aria-label="t('proposal.expert.nudgeAria', { minutes: step })"
        @click="nudge(step)"
      >
        {{ step > 0 ? `+${step}` : step }}
      </button>
      <input
        type="time"
        step="60"
        class="h-8 rounded-lg border border-amber-300/40 bg-sapphire px-2 text-sm tabular-nums text-primary-50"
        :value="currentClock"
        :aria-label="t('proposal.expert.firstDeparture')"
        @change="onTimeInput"
      />
    </div>

    <!-- What this setting means for THIS route, not in the abstract. -->
    <div class="ml-auto flex items-center gap-3 text-right">
      <p class="text-xs leading-snug text-primary-50/50">
        <template v-if="departure === null">
          {{ t('proposal.expert.automatic') }}
        </template>
        <template v-else-if="pinned">
          {{ t('proposal.expert.pinnedHint', { auto: autoClock }) }}
        </template>
        <template v-else>
          {{
            t('proposal.expert.followsHint', {
              auto: autoClock,
              delta: shiftMin > 0 ? `+${shiftMin}` : String(shiftMin),
            })
          }}
        </template>
      </p>
      <button
        v-if="departure !== null"
        type="button"
        class="flex cursor-pointer items-center gap-1 text-xs text-primary-50/60 underline underline-offset-2 transition hover:text-primary-50"
        @click="emit('update', null)"
      >
        <AppIcon :path="mdiRestore" :size="14" />
        {{ t('proposal.expert.reset') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
/* The same gold wash ComputeInputsPanel uses for the scenario box: in this
   app that colour already means "a value you chose", which is exactly what
   a manual departure is. */
.expert-box {
  background: linear-gradient(
    135deg,
    color-mix(in srgb, #fcd34d 12%, transparent) 0%,
    color-mix(in srgb, #fbbf24 6%, transparent) 100%
  );
  border: 1px solid color-mix(in srgb, #fbbf24 25%, transparent);
}
</style>
