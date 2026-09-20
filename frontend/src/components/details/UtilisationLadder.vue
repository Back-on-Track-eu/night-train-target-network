<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Composition } from '@/types/api'
import type { DemandInputs } from '@/lib/detailsScope'
import {
  allocate,
  CLASS_ORDER,
  GROUP_ORDER,
  splitByGroup,
  type ClassMain,
} from '@/lib/demandAllocation'
import { classColor } from '@/lib/compositionFormation'
import { useCompareFormat } from '@/composables/useCompareFormat'
import DetailPanel from '@/components/details/DetailPanel.vue'
import PreviewChip from '@/components/details/PreviewChip.vue'

// Demand · Utilisation by composition (D20–D24): the same demand allocated
// to every composition of the family, so one demand reads as a utilisation
// on each train. Grey bar = the composition's places in the unit shown; fill
// = places served in the class colour (All classes: stacked); the
// utilisation inside the fill; the place count after the bar end. Not served
// is a faint dashed line under the bar from served to asked, with the figure
// on the selected composition only — and only in the All-classes view, since
// "not served" is a property of a group, not of a class.
//
// This is the "fit to demand" column the comparison table once reserved.
const props = defineProps<{
  compositions: Composition[]
  demand: DemandInputs
  departures: number
  daysPerWeek: number
  selectedCompositionId: string | null
  previewing: boolean
}>()
const emit = defineEmits<{ selectComposition: [id: string]; goToSupply: [] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

type Unit = 'trip' | 'month' | 'year'
type Sort = 'capacity' | 'utilisation' | 'unserved'
const UNITS: Unit[] = ['trip', 'month', 'year']
const SORTS: Sort[] = ['capacity', 'utilisation', 'unserved']
const unit = ref<Unit>('trip')
const view = ref<ClassMain | 'all'>('all')
const sort = ref<Sort>('capacity')

/** Departures in the unit on screen; a month is a twelfth of the year. */
const factor = computed(() =>
  unit.value === 'trip' ? 1 : props.departures / (unit.value === 'month' ? 12 : 1),
)

const perTrip = computed(() =>
  splitByGroup(
    props.departures > 0 ? props.demand.passengersPerYear / props.departures : 0,
    props.demand.groupSharesPct,
  ),
)
const askedPerTrip = computed(() => GROUP_ORDER.reduce((s, g) => s + perTrip.value[g], 0))

const rows = computed(() => {
  const all = view.value === 'all'
  const c = view.value as ClassMain
  const list = props.compositions.map((k) => {
    const places: Record<string, number> = {}
    for (const q of CLASS_ORDER) places[q] = k.capacity.by_class[q]?.places ?? 0
    const a = allocate(places, perTrip.value)
    const cap = all ? k.capacity.total_places : places[c]
    const served = all ? a.served : a.byClass[c]
    return { k, a, places, cap, served, util: cap ? served / cap : -1 }
  })
  const by: Record<Sort, (r: (typeof list)[number]) => number> = {
    capacity: (r) => r.cap,
    utilisation: (r) => r.util,
    unserved: (r) => r.a.notServed,
  }
  list.sort((x, y) => by[sort.value](y) - by[sort.value](x) || y.cap - x.cap)
  return list
})

/** The scale: the widest bar or the demand asked, plus air. */
const max = computed(() => {
  const all = view.value === 'all'
  const widest = Math.max(0, ...rows.value.map((r) => r.cap), all ? askedPerTrip.value : 0)
  return widest * 1.18 * factor.value || 1
})
const pct = (v: number) => `${(v / max.value) * 100}%`

function fillSegments(r: (typeof rows.value)[number]) {
  if (view.value !== 'all') return []
  let x = 0
  return CLASS_ORDER.map((q) => {
    const width = r.a.byClass[q] * factor.value
    const seg = { classMain: q, left: pct(x), width: pct(width), value: width }
    x += width
    return seg
  }).filter((s) => s.value > 0)
}

function whoSits(r: (typeof rows.value)[number], c: ClassMain): string {
  return GROUP_ORDER.filter((g) => r.a.byGroupByClass[g][c] > 0.5)
    .map(
      (g) =>
        `${t(`proposal.details.groups.${g}`)} ${fmt.int(r.a.byGroupByClass[g][c] * factor.value)}`,
    )
    .join(' · ')
}

const colour = (c: string) => (c === 'all' ? 'var(--color-amber-300)' : classColor(c))

/** The utilisation label sits inside the fill when the fill is wide enough
 *  and either leaves room after it or the train is full; otherwise just
 *  after the fill, in the fill colour. */
function labelInside(r: (typeof rows.value)[number]): boolean {
  const fill = (r.served * factor.value) / max.value
  const room = ((r.cap - r.served) * factor.value) / max.value
  return fill >= 0.1 && (room >= 0.08 || r.served >= r.cap - 0.5)
}
</script>

<template>
  <DetailPanel
    :title="t('proposal.details.ladder.title')"
    :info="t('proposal.details.ladder.info')"
  >
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <PreviewChip v-if="previewing" />
      <span class="text-[11px] text-primary-50/50">
        {{ t('proposal.details.ladder.sameDemand') }}
        <button
          type="button"
          class="cursor-pointer text-sky-300 hover:underline"
          @click="emit('goToSupply')"
        >
          {{
            t('proposal.details.ladder.atFrequency', {
              days: daysPerWeek,
              departures: fmt.int(departures),
            })
          }}
        </button>
      </span>
    </div>

    <div class="flex flex-wrap items-center gap-1 text-[11px]">
      <button
        v-for="u in UNITS"
        :key="u"
        type="button"
        class="cursor-pointer rounded-full px-2.5 py-0.5 transition"
        :class="
          unit === u
            ? 'bg-primary-50/15 text-primary-50'
            : 'text-primary-50/55 hover:text-primary-50'
        "
        :aria-pressed="unit === u"
        @click="unit = u"
      >
        {{ t(`proposal.details.ladder.units.${u}`) }}
      </button>
      <span class="mx-1 h-3 w-px bg-primary-50/15" />
      <button
        v-for="c in CLASS_ORDER"
        :key="c"
        type="button"
        class="flex cursor-pointer items-center gap-1 rounded-full px-2.5 py-0.5 transition"
        :class="
          view === c
            ? 'bg-primary-50/15 text-primary-50'
            : 'text-primary-50/55 hover:text-primary-50'
        "
        :aria-pressed="view === c"
        @click="view = c"
      >
        <i class="h-2 w-2 rounded-sm" :style="{ background: classColor(c) }" />
        {{ t(`proposal.evaluation.classes.${c}`) }}
      </button>
      <button
        type="button"
        class="cursor-pointer rounded-full px-2.5 py-0.5 transition"
        :class="
          view === 'all'
            ? 'bg-primary-50/15 text-primary-50'
            : 'text-primary-50/55 hover:text-primary-50'
        "
        :aria-pressed="view === 'all'"
        @click="view = 'all'"
      >
        {{ t('proposal.details.ladder.allClasses') }}
      </button>
      <span class="mx-1 h-3 w-px bg-primary-50/15" />
      <span class="text-primary-50/40">{{ t('proposal.details.ladder.sort') }}</span>
      <button
        v-for="s in SORTS"
        :key="s"
        type="button"
        class="cursor-pointer rounded-full px-2.5 py-0.5 transition"
        :class="
          sort === s
            ? 'bg-primary-50/15 text-primary-50'
            : 'text-primary-50/55 hover:text-primary-50'
        "
        :aria-pressed="sort === s"
        @click="sort = s"
      >
        {{ t(`proposal.details.ladder.sorts.${s}`) }}
      </button>
    </div>

    <div
      class="ladder grid grid-cols-[9.5rem_minmax(0,1fr)] items-center text-xs"
      :style="{ '--cc': colour(view) }"
    >
      <template v-for="r in rows" :key="r.k.composition_id">
        <button
          type="button"
          class="h-7 cursor-pointer overflow-hidden rounded-l-md pr-3 pl-1.5 text-left leading-7 whitespace-nowrap text-ellipsis"
          :class="
            r.k.composition_id === selectedCompositionId
              ? 'bg-amber-400/10 font-semibold text-primary-50'
              : 'text-primary-50/60 hover:text-primary-50'
          "
          :title="r.k.composition_id"
          @click="emit('selectComposition', r.k.composition_id)"
        >
          {{ r.k.composition_id }}
        </button>
        <div
          class="relative h-7 rounded-r-md"
          :class="r.k.composition_id === selectedCompositionId ? 'bg-amber-400/10' : ''"
        >
          <span
            v-if="r.cap > 0"
            class="absolute top-[5px] h-3 rounded-[3px] bg-primary-50/15"
            :style="{ width: pct(r.cap * factor) }"
          />
          <template v-if="view === 'all'">
            <span
              v-for="seg in fillSegments(r)"
              :key="seg.classMain"
              class="absolute top-[5px] h-3"
              :style="{ left: seg.left, width: seg.width, background: classColor(seg.classMain) }"
              :title="`${t(`proposal.evaluation.classes.${seg.classMain}`)} ${fmt.int(seg.value)} · ${whoSits(r, seg.classMain)}`"
            />
          </template>
          <span
            v-else-if="r.served > 0"
            class="absolute top-[5px] h-3 rounded-l-[3px]"
            :style="{ width: pct(r.served * factor), background: colour(view) }"
            :title="whoSits(r, view as ClassMain)"
          />
          <template v-if="r.cap > 0">
            <span
              class="absolute top-[5px] h-3 px-1 text-[10px] leading-3 font-bold whitespace-nowrap"
              :class="labelInside(r) ? 'label-inside text-primary-900' : 'text-[var(--cc)]'"
              :style="{ left: pct(r.served * factor) }"
            >
              {{ fmt.percent((r.served / r.cap) * 100) }}
            </span>
            <span
              class="absolute top-[5px] h-3 px-1 text-[10px] leading-3 text-primary-50/60"
              :style="{ left: pct(r.cap * factor) }"
            >
              {{ fmt.int(r.cap * factor) }}
            </span>
          </template>
          <span v-else class="absolute top-[5px] text-[10px] leading-3 text-primary-50/40">
            {{
              t('proposal.details.ladder.noClass', { c: t(`proposal.evaluation.classes.${view}`) })
            }}
          </span>
          <template v-if="view === 'all' && r.a.notServed > 0.5">
            <span
              class="miss absolute top-5 h-[3px] opacity-40"
              :style="{ left: pct(r.served * factor), width: pct(r.a.notServed * factor) }"
            />
            <span
              v-if="r.k.composition_id === selectedCompositionId"
              class="absolute top-4 ml-1.5 text-[9px] leading-[10px] whitespace-nowrap text-amber-300/80"
              :style="{ left: pct((r.served + r.a.notServed) * factor) }"
            >
              {{ t('proposal.details.ladder.notServed', { n: fmt.int(r.a.notServed * factor) }) }}
            </span>
          </template>
        </div>
      </template>
      <span />
      <span
        class="mt-1 flex justify-between border-t border-primary-50/10 pt-0.5 text-[9px] text-primary-50/40"
      >
        <span>0</span>
        <span>
          {{
            view === 'all'
              ? t('proposal.details.ladder.axisAll', {
                  unit: t(`proposal.details.ladder.per.${unit}`),
                })
              : t('proposal.details.ladder.axisClass', {
                  c: t(`proposal.evaluation.classes.${view}`),
                  unit: t(`proposal.details.ladder.per.${unit}`),
                })
          }}
        </span>
        <span>{{ fmt.int(max) }}</span>
      </span>
    </div>

    <p class="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-primary-50/50">
      <span
        ><i class="mr-1 inline-block h-1.5 w-3.5 rounded-full bg-primary-50/15 align-middle" />{{
          t('proposal.details.ladder.legendPlaces')
        }}</span
      >
      <span
        ><i class="mr-1 inline-block h-1.5 w-3.5 rounded-full bg-primary-50/60 align-middle" />{{
          t('proposal.details.ladder.legendFill')
        }}</span
      >
      <span>{{ t('proposal.details.ladder.legendCount') }}</span>
      <span
        ><i
          class="miss mr-1 inline-block h-1 w-3.5 align-middle"
          style="--cc: var(--color-amber-300)"
        />{{ t('proposal.details.ladder.legendMiss') }}</span
      >
    </p>
  </DetailPanel>
</template>

<style scoped>
.label-inside {
  transform: translateX(-100%);
}
.miss {
  background: repeating-linear-gradient(90deg, var(--cc) 0 4px, transparent 4px 8px);
}
</style>
