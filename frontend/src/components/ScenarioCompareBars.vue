<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FamilyMember, Scenario } from '@/types/api'
import { buildScenarioAxes, conditionLabelKey } from '@/lib/scenarioAxes'
import { compareKpi, type CompareKpiKey } from '@/lib/compareKpis'
import { useCompareFormat } from '@/composables/useCompareFormat'
import { chooseScale } from '@/lib/compareScale'

// Zone B, "current measures" view: one bar per offered scenario for the
// selected composition — the six operating conditions across both networks.
// Cells that have not arrived yet render as a placeholder, error cells as a
// struck-out bar; clicking a bar selects that scenario.
//
// THE AXIS ZOOMS. Scenarios differ by a percent or two, and on a zero-based
// axis four bars within 1 % of each other are four identical rectangles —
// the comparison the panel exists for is the one it hid. So when the spread
// is small against the values themselves, the axis starts near the lowest
// bar instead of at zero.
//
// That is a dangerous thing to do quietly, because the eye reads bar LENGTH
// as quantity, so the zoom is never quiet:
//
//   · the axis carries a break glyph — the two short parallel strokes used on
//     a broken scale — between the axis label column and the first gridline,
//     and the baseline is labelled with the value it actually stands for;
//   · each bar fades out over its bottom few pixels instead of ending on a
//     hard edge, so it reads as continuing below the plot. A hatched or
//     zig-zag edge was tried first and was visual noise at this size: six
//     bars of stripes competing with the figures above them.
//   · the zoom only engages under the conditions in lib/compareScale.ts,
//     which owns that decision and is tested on its own.
const props = defineProps<{
  scenarios: Scenario[]
  cells: Map<number, FamilyMember>
  kpi: CompareKpiKey
  selectedScenarioId: number | null
  // Whether the composition these bars are for may use high-speed lines. A
  // scenario that permits them changes nothing for one that cannot.
  hsrAllowed: boolean
}>()
const emit = defineEmits<{ select: [scenarioId: number] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

const H = 150
const kpiDef = computed(() => compareKpi(props.kpi))

const bars = computed(() => {
  const axes = buildScenarioAxes(props.scenarios)
  return axes.ordered.map((scenario) => {
    const cell = props.cells.get(scenario.scenario_id)
    const value = cell?.status === 'ok' ? kpiDef.value.value(cell.summary) : null
    const state = axes.stateOf(scenario.scenario_id)
    return {
      scenario,
      value,
      error: cell?.status === 'error' ? cell.error : null,
      pending: cell === undefined,
      network: state?.network ?? '',
      condition: state ? t(`proposal.compare.conditionsShort.${conditionLabelKey(state)}`) : '',
      selected: scenario.scenario_id === props.selectedScenarioId,
      hsrInert: (state?.hsr ?? false) && !props.hsrAllowed,
    }
  })
})

const scale = computed(() => {
  const values = bars.value.map((b) => b.value).filter((v): v is number => v !== null)
  const chosen = chooseScale(values)
  // Where zero sits on a non-zoomed axis; a zoomed one has no zero on it.
  const zeroY = chosen.zoomed ? 12 + H : 12 + (chosen.top / chosen.range) * H
  return { ...chosen, zeroY }
})

/** Bars grow from the baseline, which is zero on a normal axis and the
 *  zoomed floor otherwise. */
function geometry(value: number) {
  const { baseline, range, zoomed } = scale.value
  if (zoomed) {
    const h = ((value - baseline) / range) * H
    return { top: 12 + H - h, h }
  }
  const h = (Math.abs(value) / range) * H
  const top = value >= 0 ? scale.value.zeroY - h : scale.value.zeroY
  return { top, h }
}

/** Four gridlines across the plot, labelled in the KPI's own unit. The axis
 *  had none at all before: a reader could see that one bar was taller and
 *  not by how much. */
const ticks = computed(() => {
  const { range, top, zoomed } = scale.value
  // The plot's floor: the zoomed baseline, or the axis minimum (which is
  // zero, or negative when a surplus dips below it).
  const from = zoomed ? scale.value.baseline : top - range
  const steps = 4
  return Array.from({ length: steps + 1 }, (_, i) => {
    const value = from + (range * i) / steps
    return {
      value,
      y: 12 + H - ((value - from) / range) * H,
      label: kpiDef.value.format(value, fmt),
      isZero: !zoomed && Math.abs(value) < range / 1000,
    }
  })
})

function label(value: number): string {
  if (props.kpi === 'subsidy' && value < 0)
    return t('proposal.compare.surplus', { value: fmt.millionEur(-value) })
  return kpiDef.value.format(value, fmt)
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <!-- Axis title on its own line. It used to be absolutely positioned over
         the plot, where it sat on top of the highest gridline label. -->
    <div class="flex items-baseline gap-2 text-[11px]">
      <span class="font-medium text-primary-50/60">
        {{ t(`proposal.compare.kpis.${kpiDef.labelKey}`) }}
      </span>
      <span v-if="scale.zoomed" class="text-amber-300/90">
        {{ t('proposal.compare.axisBreak', { value: kpiDef.format(scale.baseline, fmt) }) }}
      </span>
    </div>

    <div class="relative pl-16" :style="{ height: `${H + 34}px` }">
      <!-- Gridlines, labelled in the KPI's own unit, so a difference can be
           read off rather than guessed at. -->
      <div
        v-for="tick in ticks"
        :key="tick.value"
        class="pointer-events-none absolute right-0 left-16 border-t"
        :class="tick.isZero ? 'border-dashed border-primary-50/40' : 'border-primary-50/10'"
        :style="{ top: `${tick.y}px` }"
      >
        <span class="absolute -top-2 -left-16 w-14 pr-2 text-right text-[10px] text-primary-50/45">
          {{ tick.label }}
        </span>
      </div>

      <!-- The break glyph: two short parallel strokes across the axis below
           the lowest gridline, the conventional mark that the scale is cut.
           On the axis, not on the bars — one mark rather than six. -->
      <svg
        v-if="scale.zoomed"
        class="pointer-events-none absolute left-14 h-3 w-4 overflow-visible text-amber-300"
        :style="{ top: `${12 + H - 4}px` }"
        viewBox="0 0 16 12"
        aria-hidden="true"
      >
        <path
          d="M1 10 L9 2 M6 10 L14 2"
          stroke="currentColor"
          stroke-width="1.5"
          fill="none"
          stroke-linecap="round"
        />
      </svg>

      <div
        class="absolute inset-y-0 right-0 left-16 grid gap-2"
        :style="{ gridTemplateColumns: `repeat(${bars.length}, 1fr)` }"
      >
        <button
          v-for="bar in bars"
          :key="bar.scenario.scenario_id"
          type="button"
          class="relative cursor-pointer"
          :class="bar.hsrInert ? 'opacity-40' : ''"
          :title="
            bar.scenario.scenario_name +
            (bar.hsrInert ? ` — ${t('proposal.compare.hsrInert')}` : '')
          "
          @click="emit('select', bar.scenario.scenario_id)"
        >
          <template v-if="bar.value !== null">
            <span
              class="absolute right-2 left-2 rounded-t"
              :class="[
                bar.value < 0 && !scale.zoomed
                  ? 'rounded-t-none rounded-b bg-yellow-green'
                  : bar.value < 0
                    ? 'bg-yellow-green'
                    : 'bg-sky-blue',
                bar.selected ? 'ring-2 ring-amber-400' : '',
                // A zoomed bar is cut off at the bottom, and says so: the
                // torn edge is the conventional mark for a broken scale.
                // Fades out at the bottom instead of ending on a hard edge.
                scale.zoomed ? 'bar-cut' : '',
              ]"
              :style="{
                top: `${geometry(bar.value).top}px`,
                height: `${Math.max(2, geometry(bar.value).h)}px`,
              }"
            />
            <span
              class="absolute right-0 left-0 text-center text-[10px] text-primary-50/80"
              :style="{
                top: `${bar.value >= 0 ? geometry(bar.value).top - 14 : geometry(bar.value).top + geometry(bar.value).h + 2}px`,
              }"
            >
              {{ label(bar.value) }}
            </span>
          </template>
          <span
            v-else
            class="absolute right-2 left-2 h-1 rounded"
            :class="bar.error ? 'bg-red-400/60' : 'animate-pulse bg-primary-50/20'"
            :style="{ top: `${scale.zeroY - 1}px` }"
            :title="
              bar.error
                ? t(`proposal.compare.cellErrors.${bar.error}`, bar.error)
                : t('proposal.compare.pending')
            "
          />
        </button>
      </div>
    </div>
    <div class="grid gap-2" :style="{ gridTemplateColumns: `repeat(${bars.length}, 1fr)` }">
      <div
        v-for="bar in bars"
        :key="bar.scenario.scenario_id"
        class="text-center text-[11px] leading-tight"
      >
        <div :class="bar.selected ? 'font-semibold text-amber-300' : 'text-primary-50/70'">
          {{ bar.condition }}
        </div>
        <div class="text-primary-50/40">
          {{ t('proposal.compare.axes.infra', { network: bar.network }) }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* A bar on a cut axis does not end at its bottom edge, it continues below the
   plot — so it fades over the last few pixels rather than stopping on a hard
   line. Quiet enough to survive six bars side by side, which a hatched or
   zig-zag edge was not: six columns of stripes competed with the figures
   above them and read as damage rather than as notation. The break itself is
   stated once, on the axis. */
.bar-cut {
  -webkit-mask-image: linear-gradient(to top, transparent 0, #000 9px);
  mask-image: linear-gradient(to top, transparent 0, #000 9px);
}
</style>
