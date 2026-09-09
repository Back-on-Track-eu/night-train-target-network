<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Composition, FamilyMember, Scenario } from '@/types/api'
import { buildScenarioAxes, conditionLabelKey } from '@/lib/scenarioAxes'
import { compareKpi, goodness, type CompareKpiKey } from '@/lib/compareKpis'
import { useCompareFormat } from '@/composables/useCompareFormat'

// Zone B, "all combinations" view: rows = scenarios (network × operating
// condition), columns = every composition the family computed, colour =
// worse → better for the picked KPI. Clicking a cell selects both the
// scenario and the composition above. This replaces the sketch's
// measures heatmap until the measures axis exists (WP17) — it is exactly
// the members POST /api/proposal/family delivers.
const props = defineProps<{
  scenarios: Scenario[]
  compositions: Composition[]
  cells: Map<string, FamilyMember>
  kpi: CompareKpiKey
  selectedScenarioId: number | null
  selectedCompositionId: string | null
}>()
const emit = defineEmits<{ select: [scenarioId: number, compositionId: string] }>()

const { t } = useI18n()
const fmt = useCompareFormat()
const kpiDef = computed(() => compareKpi(props.kpi))

const rows = computed(() => {
  const axes = buildScenarioAxes(props.scenarios)
  return axes.ordered.map((scenario) => {
    const state = axes.stateOf(scenario.scenario_id)
    return {
      scenario,
      network: state?.network ?? '',
      condition: state ? t(`proposal.compare.conditionsShort.${conditionLabelKey(state)}`) : '',
      cells: props.compositions.map((composition) => {
        const cell = props.cells.get(`${scenario.scenario_id}:${composition.composition_id}`)
        return {
          composition,
          cell,
          value: cell?.status === 'ok' ? kpiDef.value.value(cell.summary) : null,
        }
      }),
    }
  })
})

const range = computed(() => {
  const values = rows.value
    .flatMap((r) => r.cells.map((c) => c.value))
    .filter((v): v is number => v !== null)
  return { min: Math.min(...values), max: Math.max(...values) }
})

function lerp(a: number[], b: number[], t: number) {
  return a.map((c, i) => Math.round(c + (b[i] - c) * t))
}
// 0..1 → dark blue → sky blue → yellow-green (the brand's "better" colour).
function heat(value: number): string {
  const t = goodness(kpiDef.value, value, range.value.min, range.value.max)
  const c =
    t < 0.5
      ? lerp([32, 53, 90], [34, 113, 179], t * 2)
      : lerp([34, 113, 179], [146, 208, 81], (t - 0.5) * 2)
  return `rgb(${c.join(',')})`
}

function label(value: number): string {
  if (props.kpi === 'subsidy' && value < 0) return fmt.millionEur(-value)
  return kpiDef.value.format(value, fmt)
}

const bestLabel = computed(() => {
  if (!Number.isFinite(range.value.min)) return null
  const best = kpiDef.value.lowerIsBetter ? range.value.min : range.value.max
  const worst = kpiDef.value.lowerIsBetter ? range.value.max : range.value.min
  return { best: label(best), worst: label(worst) }
})
</script>

<template>
  <div class="flex flex-col gap-2 overflow-x-auto">
    <table class="w-full border-separate border-spacing-1 text-[11px]">
      <thead>
        <tr>
          <th class="text-left font-normal text-primary-50/50"></th>
          <th
            v-for="composition in compositions"
            :key="composition.composition_id"
            class="max-w-24 truncate px-1 text-center font-normal text-primary-50/70"
            :class="
              composition.composition_id === selectedCompositionId
                ? 'font-semibold text-amber-300'
                : ''
            "
            :title="composition.description"
          >
            {{ composition.composition_id }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.scenario.scenario_id">
          <th class="pr-2 text-left font-normal whitespace-nowrap text-primary-50/70">
            {{ t('proposal.compare.axes.infra', { network: row.network }) }} · {{ row.condition }}
          </th>
          <td v-for="entry in row.cells" :key="entry.composition.composition_id" class="p-0">
            <button
              v-if="entry.value !== null"
              type="button"
              class="h-9 w-full cursor-pointer rounded px-1 text-center text-white"
              :class="
                row.scenario.scenario_id === selectedScenarioId &&
                entry.composition.composition_id === selectedCompositionId
                  ? 'ring-2 ring-amber-400'
                  : ''
              "
              :style="{ background: heat(entry.value) }"
              :title="`${row.scenario.scenario_name} · ${entry.composition.description}`"
              @click="emit('select', row.scenario.scenario_id, entry.composition.composition_id)"
            >
              <small
                v-if="kpi === 'subsidy' && entry.value < 0"
                class="block text-[9px] opacity-80"
              >
                {{ t('proposal.compare.surplusShort') }}
              </small>
              {{ label(entry.value) }}
            </button>
            <div
              v-else
              class="h-9 w-full rounded"
              :class="
                entry.cell?.status === 'error' ? 'bg-red-400/20' : 'animate-pulse bg-primary-50/10'
              "
              :title="
                entry.cell?.status === 'error'
                  ? t(`proposal.compare.cellErrors.${entry.cell.error}`, entry.cell.error)
                  : t('proposal.compare.pending')
              "
            />
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="bestLabel" class="flex items-center gap-2 text-[10px] text-primary-50/50">
      <span>{{ t('proposal.compare.worse') }} {{ bestLabel.worst }}</span>
      <span
        class="h-2 flex-1 rounded"
        style="
          background: linear-gradient(90deg, rgb(32, 53, 90), rgb(34, 113, 179), rgb(146, 208, 81));
        "
      />
      <span>{{ bestLabel.best }} {{ t('proposal.compare.better') }}</span>
    </div>
  </div>
</template>
