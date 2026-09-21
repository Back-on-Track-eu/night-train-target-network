<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Composition, FamilyMember, Scenario } from '@/types/api'
import { buildScenarioAxes, conditionLabelKey } from '@/lib/scenarioAxes'
import { compareKpi, type CompareKpiKey } from '@/lib/compareKpis'
import { buildHeatScale } from '@/lib/compareHeat'
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

// Row labels are the operating condition alone; the network is named once,
// above the first row of its group, since it is the same for every row in
// that group. A label carrying both on every row ("Infrastructure 2026 ·
// HSR + TT OPT") was wider than two cells and pushed twelve compositions
// into a horizontal scroll on a full-width screen.
const rows = computed(() => {
  const axes = buildScenarioAxes(props.scenarios)
  return axes.ordered.map((scenario, i, ordered) => {
    const state = axes.stateOf(scenario.scenario_id)
    const network = state?.network ?? ''
    const previous = i > 0 ? axes.stateOf(ordered[i - 1].scenario_id)?.network : undefined
    return {
      scenario,
      network,
      startsGroup: network !== previous,
      condition: state ? t(`proposal.compare.conditionsShort.${conditionLabelKey(state)}`) : '',
      cells: props.compositions.map((composition) => {
        const cell = props.cells.get(`${scenario.scenario_id}:${composition.composition_id}`)
        return {
          composition,
          cell,
          value: cell?.status === 'ok' ? kpiDef.value.value(cell.summary) : null,
          // The route builder ANDs the composition's own hsr_allowed with the
          // scenario's, so a 160 km/h loco-hauled rake gains nothing from the
          // permission: the cell is a copy of the same composition without it.
          // Dimmed, not removed — the member is real and still selectable.
          hsrInert: (state?.hsr ?? false) && !composition.routing.hsr_allowed,
        }
      }),
    }
  })
})

const scale = computed(() => {
  const values = rows.value
    .flatMap((r) => r.cells.map((c) => c.value))
    .filter((v): v is number => v !== null)
  return buildHeatScale(kpiDef.value, values)
})

function label(value: number): string {
  if (props.kpi === 'subsidy' && value < 0) return fmt.millionEur(-value)
  return kpiDef.value.format(value, fmt)
}

// Which cell actually holds the best value, so the grid can point at it
// rather than leaving the reader to compare twelve shades. Ties keep the
// first in reading order — naming one winner is the whole point.
const bestCell = computed(() => {
  const best = scale.value.best
  if (best === null) return null
  for (const row of rows.value) {
    for (const entry of row.cells) {
      if (entry.value === best) {
        return {
          value: best,
          scenarioId: row.scenario.scenario_id,
          compositionId: entry.composition.composition_id,
          where: `${entry.composition.composition_id} · ${t('proposal.compare.axes.infra', { network: row.network })} · ${row.condition}`,
        }
      }
    }
  }
  return null
})

const legend = computed(() => {
  const { best, worst } = scale.value
  if (best === null || worst === null) return null
  return { best: label(best), worst: label(worst) }
})
</script>

<template>
  <div class="thin-scroll flex flex-col gap-2 overflow-x-auto">
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
            <span v-if="row.startsGroup" class="block text-[9px] text-primary-50/40">
              {{ t('proposal.compare.axes.infra', { network: row.network }) }}
            </span>
            {{ row.condition }}
          </th>
          <td v-for="entry in row.cells" :key="entry.composition.composition_id" class="p-0">
            <button
              v-if="entry.value !== null"
              type="button"
              class="h-9 w-full cursor-pointer rounded px-1 text-center text-white"
              :class="[
                row.scenario.scenario_id === selectedScenarioId &&
                entry.composition.composition_id === selectedCompositionId
                  ? 'ring-2 ring-amber-400'
                  : '',
                entry.hsrInert ? 'opacity-35' : '',
                bestCell &&
                bestCell.scenarioId === row.scenario.scenario_id &&
                bestCell.compositionId === entry.composition.composition_id
                  ? 'font-semibold outline outline-1 outline-primary-50/70'
                  : '',
              ]"
              :style="{ background: scale.color(entry.value) }"
              :title="
                `${row.scenario.scenario_name} · ${entry.composition.description}` +
                (entry.hsrInert ? ` — ${t('proposal.compare.hsrInert')}` : '')
              "
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
    <div v-if="legend" class="flex flex-col gap-1">
      <div class="flex items-center gap-2 text-[10px] text-primary-50/50">
        <span>{{ t('proposal.compare.worse') }} {{ legend.worst }}</span>
        <!-- The bar carries the scale's own gradient, so a diverging KPI shows
             its break-even boundary here too, in the right place. -->
        <span class="relative h-2 flex-1 rounded" :style="{ background: scale.gradient }">
          <span
            v-if="scale.zeroAt !== null"
            class="absolute -top-0.5 h-3 w-px bg-primary-50/70"
            :style="{ left: `${scale.zeroAt * 100}%` }"
          />
        </span>
        <span>{{ legend.best }} {{ t('proposal.compare.better') }}</span>
      </div>
      <div class="flex flex-wrap items-center gap-x-3 text-[10px]">
        <span v-if="scale.zeroAt !== null" class="text-primary-50/50">
          {{ t('proposal.compare.breakEven') }}
        </span>
        <span v-if="bestCell" class="text-primary-50/70">
          {{ t('proposal.compare.bestIs', { where: bestCell.where }) }}
        </span>
      </div>
    </div>
  </div>
</template>
