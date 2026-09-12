<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCompareFormat } from '@/composables/useCompareFormat'
import { supplyFigures } from '@/lib/detailsScope'
import DetailPanel from '@/components/details/DetailPanel.vue'
import MonthSliders from '@/components/details/MonthSliders.vue'
import PreviewChip from '@/components/details/PreviewChip.vue'

// Supply · Schedule — the grid on the left, the four figures that follow from
// it on the right. This panel OWNS the schedule scope: its own figures
// recompute on the page and are marked as a preview, while every panel that
// merely depends on the schedule greys out and waits.
//
// The trainset count is exact rather than estimated even here: the cycle
// length is a property of the timetable, which only the backend can redo, so
// it is taken from the last result and multiplied by the busiest month's
// days-per-week. Without a cycle (no operations yet) the figure holds still.
const props = defineProps<{
  months: number[]
  previewing: boolean
  cycleDistanceKm: number
  places: number
  cycleDays: number | null
  tripPairs: number
  /** The figures as last calculated — shown whenever nothing is previewed, so
   *  the panel never mixes a previewed number with a calculated one. */
  committed: {
    operatingDays: number | null
    departures: number | null
    trainKm: number | null
    placesOffered: number | null
    placeKmOffered: number | null
    trainsets: number | null
  }
}>()
const emit = defineEmits<{ 'update:months': [months: number[]] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

const live = computed(() =>
  supplyFigures(
    props.months,
    props.cycleDistanceKm,
    props.places,
    props.cycleDays,
    props.tripPairs,
  ),
)

const rows = computed(() => {
  const shown = props.previewing
    ? {
        operatingDays: live.value.operatingDays,
        departures: live.value.departures,
        trainKm: live.value.trainKm,
        trainsets: live.value.trainsets,
      }
    : {
        operatingDays: props.committed.operatingDays,
        departures: props.committed.departures,
        trainKm: props.committed.trainKm,
        trainsets: props.committed.trainsets,
      }
  return [
    {
      key: 'operatingDays',
      value:
        shown.operatingDays === null
          ? null
          : fmt.int(
              Math.round(shown.operatingDays * 10) / 10 === Math.round(shown.operatingDays)
                ? shown.operatingDays
                : shown.operatingDays,
            ),
    },
    { key: 'departures', value: shown.departures === null ? null : fmt.int(shown.departures) },
    { key: 'trainKm', value: shown.trainKm === null ? null : `${fmt.count(shown.trainKm)} km` },
    { key: 'trainsets', value: shown.trainsets === null ? null : fmt.int(shown.trainsets) },
  ]
})
</script>

<template>
  <DetailPanel
    :title="t('proposal.details.schedule.title')"
    :info="t('proposal.details.schedule.info')"
    :caption="t('proposal.details.schedule.caption')"
  >
    <div class="grid gap-4 xl:grid-cols-[1fr_13rem]">
      <MonthSliders :months="months" @update:months="emit('update:months', $event)" />

      <div class="flex flex-col gap-2 rounded-md border border-primary-50/10 p-3">
        <PreviewChip v-if="previewing" />
        <dl class="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-xs">
          <template v-for="row in rows" :key="row.key">
            <dt class="text-primary-50/65">{{ t(`proposal.details.schedule.${row.key}`) }}</dt>
            <dd
              class="text-right font-semibold tabular-nums"
              :class="previewing ? 'preview-value' : 'text-primary-50'"
            >
              {{ row.value ?? '—' }}
            </dd>
          </template>
        </dl>
        <p v-if="previewing" class="text-[11px] leading-snug text-primary-50/45">
          {{
            cycleDays === null
              ? t('proposal.details.schedule.previewHintNoCycle')
              : t('proposal.details.schedule.previewHint', { cycle: cycleDays })
          }}
        </p>
      </div>
    </div>
  </DetailPanel>
</template>

<style scoped>
/* Previewed figures are amber and italic wherever they appear — the one
   visual rule that separates "estimated here" from "calculated". */
.preview-value {
  color: var(--color-amber-300);
  font-style: italic;
}
</style>
