<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { mdiRefresh } from '@mdi/js'
import type { Composition } from '@/types/api'
import { CLASS_ICONS, classColor } from '@/lib/compositionFormation'
import {
  exampleFare,
  partIsSigned,
  supplyFigures,
  TARIFF_PARTS,
  type ExampleOd,
  type Tariff,
  type TariffPart,
} from '@/lib/detailsScope'
import { useCompareFormat } from '@/composables/useCompareFormat'
import AppIcon from '@/components/AppIcon.vue'
import DetailPanel from '@/components/details/DetailPanel.vue'
import PreviewChip from '@/components/details/PreviewChip.vue'

// Supply · Places and prices — one table, one row per accommodation class:
// how many places it has, what share of the train that is, its per-km fare,
// and what that fare comes to on the two journeys a reader can picture (the
// longest and the shortest OD pair the route actually sells).
//
// €/km alone is too abstract to judge. The two example columns are arithmetic
// on the field beside them, so they preview live while the fare is edited.
//
// The last row is catering, and it is NOT a fare: the restaurant is not
// modelled as a business of its own, so one SIGNED net figure per passenger
// carries its sales less its costs. It sells no places, which is why it sits
// below the class total rather than inside it.
const props = defineProps<{
  composition: Composition | null
  tariff: Tariff
  defaults: Tariff | null
  longest: ExampleOd | null
  shortest: ExampleOd | null
  // Schedule-owned, so they preview with the grid rather than with the prices.
  months: number[]
  schedulePreviewing: boolean
  pricesPreviewing: boolean
  cycleDistanceKm: number
  cycleDays: number | null
  tripPairs: number
  committed: { placesOffered: number | null; placeKmOffered: number | null }
}>()
const emit = defineEmits<{ 'update:tariff': [tariff: Tariff] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

const totalPlaces = computed(() => props.composition?.capacity.total_places ?? 0)

const classRows = computed(() =>
  CLASS_ICONS.map(([classMain]) => {
    const places = props.composition?.capacity.by_class[classMain]?.places ?? 0
    const perPax = props.tariff.faresPerPax[classMain] ?? 0
    const perKm = props.tariff.faresPerKm[classMain] ?? 0
    return {
      classMain,
      color: classColor(classMain),
      places,
      share: totalPlaces.value > 0 ? places / totalPlaces.value : 0,
      // One cell per tariff part, so the template does not repeat the
      // stepper markup four times per class.
      cells: TARIFF_PARTS.map((part) => {
        const value = props.tariff[part][classMain] ?? 0
        const fallback = props.defaults?.[part][classMain]
        return {
          part,
          value,
          default: fallback ?? null,
          changed: fallback !== undefined && value !== fallback,
          signed: partIsSigned(part),
        }
      }),
      // The fare for the berth over each example journey — fixed part plus
      // distance part. Services and catering are not in it: this column
      // answers "what does the ticket cost", not "what does the passenger
      // spend".
      longEur: props.longest ? exampleFare(perPax, perKm, props.longest.km) : null,
      shortEur: props.shortest ? exampleFare(perPax, perKm, props.shortest.km) : null,
      fareChanged:
        perPax !== props.defaults?.faresPerPax[classMain] ||
        perKm !== props.defaults?.faresPerKm[classMain],
      services: props.tariff.servicesPerPax[classMain] ?? 0,
      catering: props.tariff.cateringPerPax[classMain] ?? 0,
    }
  }).filter((row) => row.places > 0),
)

const live = computed(() =>
  supplyFigures(
    props.months,
    props.cycleDistanceKm,
    totalPlaces.value,
    props.cycleDays,
    props.tripPairs,
  ),
)
const placesOffered = computed(() =>
  props.schedulePreviewing ? live.value.placesOffered : props.committed.placesOffered,
)
const placeKmOffered = computed(() =>
  props.schedulePreviewing ? live.value.placeKmOffered : props.committed.placeKmOffered,
)

/** The step each part moves by: cents for a per-km rate, ten cents for the
 *  figures that are whole euros a passenger pays. */
const STEP: Record<TariffPart, number> = {
  faresPerPax: 1,
  faresPerKm: 0.01,
  servicesPerPax: 0.1,
  cateringPerPax: 0.1,
}

function setPart(part: TariffPart, classMain: string, value: number) {
  // Only catering may go below zero — the backend rejects the rest, so the
  // field should not let you type what it will refuse.
  const clamped = partIsSigned(part) ? value : Math.max(0, value)
  emit('update:tariff', {
    ...props.tariff,
    [part]: { ...props.tariff[part], [classMain]: Math.round(clamped * 100) / 100 },
  })
}

function stepPart(part: TariffPart, classMain: string, direction: number) {
  setPart(part, classMain, (props.tariff[part][classMain] ?? 0) + direction * STEP[part])
}

/** The "All classes" row: every tariff column and both example fares as the
 *  average for a passenger of this train — each class weighted by the places
 *  it offers, which is the mix the stopgap demand model fills. */
const averageRow = computed(() => {
  const rows = classRows.value
  const places = rows.reduce((sum, r) => sum + r.places, 0)
  const avg = (pick: (row: (typeof rows)[number]) => number | null) =>
    places ? rows.reduce((sum, r) => sum + (pick(r) ?? 0) * r.places, 0) / places : null
  return {
    places,
    cells: TARIFF_PARTS.map((part) => ({
      part,
      value: avg((r) => r.cells.find((c) => c.part === part)?.value ?? 0),
    })),
    longEur: props.longest ? avg((r) => r.longEur) : null,
    shortEur: props.shortest ? avg((r) => r.shortEur) : null,
  }
})

function parseField(event: Event): number {
  const raw = (event.target as HTMLInputElement).value.replace(',', '.')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) ? value : 0
}

const numCell =
  'w-16 rounded border border-primary-50/15 bg-transparent px-1.5 py-0.5 text-right tabular-nums text-primary-50 focus:border-sky-300 focus:outline-none'
</script>

<template>
  <DetailPanel
    :title="t('proposal.details.prices.title')"
    :info="t('proposal.details.prices.info')"
    :caption="
      composition
        ? t('proposal.details.prices.caption', {
            composition: composition.composition_id,
            places: fmt.int(totalPlaces),
          })
        : null
    "
  >
    <!-- Negative margin + matching padding: the scroller spans the panel's
         full width, so the last column scrolls to the edge instead of being
         clipped by the panel's own padding. -->
    <div class="-mx-3 overflow-x-auto px-3">
      <table class="w-full min-w-[54rem] border-collapse text-xs">
        <thead>
          <tr class="align-bottom text-[11px] text-primary-50/50">
            <th class="py-1 pr-2 text-left font-normal">
              {{ t('proposal.details.prices.class') }}
            </th>
            <th class="py-1 pr-2 text-right font-normal">
              {{ t('proposal.details.prices.places') }}
            </th>
            <th class="py-1 pr-3 text-right font-normal">
              {{ t('proposal.details.prices.shareOfTrain') }}
            </th>
            <th
              v-for="part in TARIFF_PARTS"
              :key="part"
              class="border-l border-primary-50/10 py-1 pr-2 pl-2 text-right font-normal"
            >
              {{ t(`proposal.details.prices.parts.${part}.label`) }}
              <span class="block text-[9px] text-primary-50/35">
                {{ t(`proposal.details.prices.parts.${part}.unit`) }}
              </span>
            </th>
            <th
              class="border-l border-primary-50/10 py-1 pr-2 pl-2 text-right font-normal whitespace-nowrap"
            >
              {{ t('proposal.details.prices.exampleLongest') }}
              <span class="block text-[9px] text-primary-50/35">
                {{ longest ? `${longest.name} · ${fmt.int(longest.km)} km` : '—' }}
              </span>
            </th>
            <th class="py-1 pr-1 text-right font-normal whitespace-nowrap">
              {{ t('proposal.details.prices.exampleShortest') }}
              <span class="block text-[9px] text-primary-50/35">
                {{ shortest ? `${shortest.name} · ${fmt.int(shortest.km)} km` : '—' }}
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in classRows" :key="row.classMain" class="border-t border-primary-50/5">
            <td class="py-1 pr-2">
              <span class="flex items-center gap-1.5 text-primary-50/85">
                <i class="h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ background: row.color }" />
                {{ t(`proposal.evaluation.classes.${row.classMain}`) }}
              </span>
            </td>
            <td class="py-1 pr-2 text-right tabular-nums text-primary-50/85">
              {{ fmt.int(row.places) }}
            </td>
            <td class="py-1 pr-3">
              <span class="flex items-center justify-end gap-1.5">
                <span class="flex h-1 w-10 overflow-hidden rounded bg-primary-50/10">
                  <span :style="{ width: `${row.share * 100}%`, background: row.color }" />
                </span>
                <span class="w-9 text-right text-[11px] tabular-nums text-primary-50/55">
                  {{ fmt.percent(row.share * 100) }}
                </span>
              </span>
            </td>

            <!-- One editable cell per tariff part -->
            <td
              v-for="cell in row.cells"
              :key="cell.part"
              class="border-l border-primary-50/10 py-1 pr-2 pl-2 text-right"
            >
              <span class="inline-flex items-center gap-1">
                <button
                  v-if="cell.changed && cell.default !== null"
                  type="button"
                  class="cursor-pointer text-primary-50/40 hover:text-primary-50"
                  :aria-label="t('proposal.details.prices.reset')"
                  :title="t('proposal.details.prices.resetTo', { value: cell.default.toFixed(2) })"
                  @click="setPart(cell.part, row.classMain, cell.default)"
                >
                  <AppIcon :path="mdiRefresh" :size="12" />
                </button>
                <input
                  :class="[numCell, cell.changed ? 'border-amber-400/50' : '']"
                  inputmode="decimal"
                  :value="cell.value.toFixed(2)"
                  :aria-label="t(`proposal.details.prices.parts.${cell.part}.label`)"
                  @change="setPart(cell.part, row.classMain, parseField($event))"
                />
                <span class="flex flex-col leading-none">
                  <button
                    type="button"
                    class="cursor-pointer px-0.5 text-[9px] text-primary-50/50 hover:text-primary-50"
                    :aria-label="t('proposal.details.prices.increase')"
                    @click="stepPart(cell.part, row.classMain, 1)"
                  >
                    ▲
                  </button>
                  <button
                    type="button"
                    class="cursor-pointer px-0.5 text-[9px] text-primary-50/50 hover:text-primary-50"
                    :aria-label="t('proposal.details.prices.decrease')"
                    @click="stepPart(cell.part, row.classMain, -1)"
                  >
                    ▼
                  </button>
                </span>
              </span>
            </td>

            <td
              class="border-l border-primary-50/10 py-1 pr-2 pl-2 text-right tabular-nums"
              :class="pricesPreviewing && row.fareChanged ? 'preview-value' : 'text-primary-50/85'"
            >
              {{ row.longEur === null ? '—' : fmt.eur2(row.longEur) }}
            </td>
            <td
              class="py-1 pr-1 text-right tabular-nums"
              :class="pricesPreviewing && row.fareChanged ? 'preview-value' : 'text-primary-50/85'"
            >
              {{ row.shortEur === null ? '—' : fmt.eur2(row.shortEur) }}
            </td>
          </tr>

          <!-- Average per passenger, weighted by places — one figure per
               column, so the eight cells above read as a position. -->
          <tr class="border-t border-primary-50/25 font-semibold">
            <td class="py-1.5 pr-2 text-primary-50">
              {{ t('proposal.details.prices.allClasses') }}
              <span class="block text-[9px] font-normal text-primary-50/40">
                {{ t('proposal.details.prices.weightedAverage') }}
              </span>
            </td>
            <td class="py-1.5 pr-2 text-right tabular-nums text-primary-50">
              {{ fmt.int(totalPlaces) }}
            </td>
            <td class="py-1.5 pr-3 text-right text-[11px] text-primary-50/50">100 %</td>
            <td
              v-for="cell in averageRow.cells"
              :key="cell.part"
              class="border-l border-primary-50/10 py-1.5 pr-2 pl-2 text-right tabular-nums text-primary-50"
            >
              {{ cell.value === null ? '—' : fmt.eur2(cell.value) }}
            </td>
            <td
              class="border-l border-primary-50/10 py-1.5 pr-2 pl-2 text-right tabular-nums text-primary-50"
            >
              {{ averageRow.longEur === null ? '—' : fmt.eur2(averageRow.longEur) }}
            </td>
            <td class="py-1.5 pr-1 text-right tabular-nums text-primary-50">
              {{ averageRow.shortEur === null ? '—' : fmt.eur2(averageRow.shortEur) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Schedule-owned, so previewed with the grid and not with the prices. -->
    <div
      class="mt-1 flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-primary-50/10 pt-2"
    >
      <PreviewChip v-if="schedulePreviewing" />
      <span class="text-[11px] text-primary-50/50">{{ t('proposal.details.prices.perYear') }}</span>
      <span class="flex items-baseline gap-1.5 text-xs">
        <span class="text-primary-50/65">{{ t('proposal.details.prices.placesOffered') }}</span>
        <b class="tabular-nums" :class="schedulePreviewing ? 'preview-value' : 'text-primary-50'">
          {{ placesOffered === null ? '—' : fmt.count(placesOffered) }}
        </b>
      </span>
      <span class="flex items-baseline gap-1.5 text-xs">
        <span class="text-primary-50/65">{{ t('proposal.details.prices.placeKmOffered') }}</span>
        <b class="tabular-nums" :class="schedulePreviewing ? 'preview-value' : 'text-primary-50'">
          {{ placeKmOffered === null ? '—' : fmt.count(placeKmOffered) }}
        </b>
      </span>
    </div>
  </DetailPanel>
</template>

<style scoped>
.preview-value {
  color: var(--color-amber-300);
  font-style: italic;
}
</style>
