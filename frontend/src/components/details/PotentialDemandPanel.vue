<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DemandInputs } from '@/lib/detailsScope'
import { useCompareFormat } from '@/composables/useCompareFormat'
import DetailPanel from '@/components/details/DetailPanel.vue'
import { DOCS_DETAIL_PANEL } from '@/lib/docsLinks'
import PreviewChip from '@/components/details/PreviewChip.vue'

// Demand · Potential demand (D10–D13): passengers per year over both
// directions, the one fixed quantity. Four levels are presets that write the
// figure; any figure can be typed, which makes the level "custom". The
// frequency under Supply turns the year into a load per departure, which is
// what the note under the field says.
const props = defineProps<{
  demand: DemandInputs
  /** The registry's levels, in order, and their totals. */
  levels: Record<string, number>
  previewing: boolean
  departures: number
  daysPerWeek: number
  selectedCompositionId: string | null
  selectedPlaces: number
}>()
const emit = defineEmits<{ 'update:demand': [demand: DemandInputs] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

const activeLevel = computed(
  () =>
    Object.entries(props.levels).find(
      ([, total]) => total === props.demand.passengersPerYear,
    )?.[0] ?? 'custom',
)

function setTotal(total: number, level?: string) {
  const passengersPerYear = Math.max(0, Math.round(total))
  const match = Object.entries(props.levels).find(([, v]) => v === passengersPerYear)?.[0]
  emit('update:demand', { ...props.demand, passengersPerYear, level: level ?? match ?? 'custom' })
}

function onInput(event: Event) {
  const raw = (event.target as HTMLInputElement).value.replace(/[^\d]/g, '')
  setTotal(Number(raw) || 0)
}

const perDeparture = computed(() =>
  props.departures > 0 ? props.demand.passengersPerYear / props.departures : 0,
)
const note = computed(() => {
  const parts = [
    activeLevel.value !== 'custom'
      ? t(`proposal.details.potential.levels.${activeLevel.value}.name`)
      : null,
    t('proposal.details.potential.perDeparture', {
      n: fmt.int(perDeparture.value),
      days: props.daysPerWeek,
    }),
    props.selectedCompositionId && props.selectedPlaces > 0
      ? t('proposal.details.potential.ofPlaces', {
          pct: fmt.percent((perDeparture.value / props.selectedPlaces) * 100),
          composition: props.selectedCompositionId,
        })
      : null,
  ]
  return parts.filter(Boolean).join(' · ')
})
</script>

<template>
  <DetailPanel
    :title="t('proposal.details.potential.title')"
    :info="t('proposal.details.potential.info')"
    :doc-path="DOCS_DETAIL_PANEL.potential"
  >
    <PreviewChip v-if="previewing" />
    <div class="flex flex-wrap items-center gap-1" role="group">
      <button
        v-for="(total, level) in levels"
        :key="level"
        type="button"
        class="cursor-pointer rounded-full px-2.5 py-0.5 text-[11px] transition"
        :class="
          activeLevel === level
            ? 'bg-primary-50/15 text-primary-50'
            : 'text-primary-50/55 hover:text-primary-50'
        "
        :aria-pressed="activeLevel === level"
        :title="
          t('proposal.details.potential.levelTitle', {
            name: t(`proposal.details.potential.levels.${level}.name`),
            n: fmt.int(total),
          })
        "
        @click="setTotal(total, String(level))"
      >
        {{ t(`proposal.details.potential.levels.${level}.short`) }}
      </button>
      <span
        class="rounded-full px-2.5 py-0.5 text-[11px]"
        :class="
          activeLevel === 'custom' ? 'bg-primary-50/15 text-primary-50' : 'text-primary-50/35'
        "
      >
        {{ t('proposal.details.potential.levels.custom.short') }}
      </span>
    </div>
    <label class="flex items-center gap-2 text-xs">
      <input
        class="w-28 rounded border border-primary-50/15 bg-transparent px-2 py-0.5 text-right text-sm font-semibold tabular-nums text-primary-50 outline-none focus:border-sky-300"
        :class="previewing ? 'border-amber-400/40' : ''"
        inputmode="numeric"
        :value="fmt.int(demand.passengersPerYear)"
        @change="onInput"
      />
      <span class="text-primary-50/55">{{ t('proposal.details.potential.unit') }}</span>
    </label>
    <p class="text-[11px] leading-snug text-primary-50/50">{{ note }}</p>
  </DetailPanel>
</template>
