<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MatrixCell, Scenario } from '@/types/api'
import { buildScenarioAxes, conditionLabelKey } from '@/lib/scenarioAxes'
import { compareKpi, type CompareKpiKey } from '@/lib/compareKpis'
import { useCompareFormat } from '@/composables/useCompareFormat'

// Zone B, "current measures" view: one bar per offered scenario for the
// selected composition — the six operating conditions across both
// networks. Zero-based axis with a dashed zero line: for the subsidy KPI a
// surplus goes below the line in green and is labelled as one. Cells that
// have not arrived yet render as a placeholder, error cells as a struck-out
// bar; clicking a bar selects that scenario.
const props = defineProps<{
  scenarios: Scenario[]
  cells: Map<number, MatrixCell>
  kpi: CompareKpiKey
  selectedScenarioId: number | null
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
    }
  })
})

const scale = computed(() => {
  const values = bars.value.map((b) => b.value).filter((v): v is number => v !== null)
  const max = Math.max(0, ...values)
  const min = Math.min(0, ...values)
  const range = max - min || 1
  return { max, min, range, zeroY: 12 + (max / range) * H }
})

function geometry(value: number) {
  const h = (Math.abs(value) / scale.value.range) * H
  const top = value >= 0 ? scale.value.zeroY - h : scale.value.zeroY
  return { top, h }
}

function label(value: number): string {
  if (props.kpi === 'subsidy' && value < 0)
    return t('proposal.compare.surplus', { value: fmt.millionEur(-value) })
  return kpiDef.value.format(value, fmt)
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="relative" :style="{ height: `${H + 40}px` }">
      <div
        class="absolute right-0 left-0 border-t border-dashed border-primary-50/30"
        :style="{ top: `${scale.zeroY}px` }"
      >
        <span v-if="scale.min < 0" class="absolute -top-4 right-0 text-[10px] text-primary-50/50">
          {{ t('proposal.compare.zeroLine') }}
        </span>
      </div>
      <div
        class="absolute inset-0 grid gap-2"
        :style="{ gridTemplateColumns: `repeat(${bars.length}, 1fr)` }"
      >
        <button
          v-for="bar in bars"
          :key="bar.scenario.scenario_id"
          type="button"
          class="relative cursor-pointer"
          :title="bar.scenario.scenario_name"
          @click="emit('select', bar.scenario.scenario_id)"
        >
          <template v-if="bar.value !== null">
            <span
              class="absolute right-2 left-2 rounded-t"
              :class="[
                bar.value < 0 ? 'rounded-t-none rounded-b bg-yellow-green' : 'bg-sky-blue',
                bar.selected ? 'ring-2 ring-amber-400' : '',
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
