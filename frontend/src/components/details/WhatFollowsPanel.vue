<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Composition, DemandBlock } from '@/types/api'
import { CLASS_ORDER, GROUP_CLASS_PREFERENCES, GROUP_ORDER } from '@/lib/demandAllocation'
import { classColor } from '@/lib/compositionFormation'
import { cateringSign, supplyFigures, type DemandInputs, type Tariff } from '@/lib/detailsScope'
import { follows } from '@/lib/whatFollows'
import { useCompareFormat } from '@/composables/useCompareFormat'
import DetailPanel from '@/components/details/DetailPanel.vue'
import { DOCS_DETAIL_PANEL } from '@/lib/docsLinks'
import PreviewChip from '@/components/details/PreviewChip.vue'

// Supply · What follows (D2, D4) — what the schedule and the prices earn
// against the COMMITTED demand: passengers, places sold per departure,
// utilisation in places and place-km, ticket revenue and the catering
// contribution per year, and who sits where on the selected train. Schedule
// and price edits preview here live (the client-side port of the sketch's
// follows(), pinned to the backend by the parity tests); a demand edit is
// not previewed here — this panel waits for the recalculation, because its
// figures would otherwise mix a previewed demand with a calculated one.
//
// The table has to fit ~900 px without a horizontal scrollbar: group names
// without their preference chains (they sit in the title attribute), places
// offered as its own row, 11 px type.
const props = defineProps<{
  composition: Composition | null
  daysPerWeek: number
  tariff: Tariff
  tripPairs: number
  cycleDistanceKm: number
  /** The demand the figures on screen were computed with — the resolved
   *  request echo's block — and the backend's OD spread of it for this
   *  composition, which carries the share-weighted journey length. */
  committedDemand: DemandInputs | null
  committedBlock: DemandBlock | null
  previewing: boolean
  awaiting: boolean
}>()

const { t } = useI18n()
const fmt = useCompareFormat()

const places = computed(() => {
  const out: Record<string, number> = {}
  for (const c of CLASS_ORDER) out[c] = props.composition?.capacity.by_class[c]?.places ?? 0
  return out
})
const totalPlaces = computed(() => props.composition?.capacity.total_places ?? 0)

const supply = computed(() =>
  supplyFigures(props.daysPerWeek, props.cycleDistanceKm, totalPlaces.value, null, props.tripPairs),
)

const result = computed(() => {
  const demand = props.committedDemand
  const block = props.committedBlock
  if (!demand || !block || !props.composition) return null
  return follows(
    demand.passengersPerYear,
    demand.groupSharesPct,
    places.value,
    supply.value.departures,
    block.od.average_distance_km,
    props.tariff,
  )
})

const askedPerDeparture = computed(() => {
  const f = result.value
  return f && f.departures > 0 ? props.committedDemand!.passengersPerYear / f.departures : 0
})

const kpis = computed(() => {
  const f = result.value
  if (!f) return []
  const util = totalPlaces.value ? (f.soldPerDeparture / totalPlaces.value) * 100 : 0
  const utilKm = supply.value.placeKmOffered
    ? (f.placeKmSold / supply.value.placeKmOffered) * 100
    : 0
  return [
    {
      key: 'soldPerDeparture',
      value: fmt.int(f.soldPerDeparture),
      note: t('proposal.details.follows.ofAsked', { n: fmt.int(askedPerDeparture.value) }),
    },
    { key: 'utilisationPlaces', value: fmt.percent(util) },
    { key: 'placeKmSold', value: fmt.count(f.placeKmSold) },
    { key: 'utilisationPlaceKm', value: fmt.percent(utilKm) },
    { key: 'ticketRevenue', value: fmt.eur(f.ticketEur), total: true },
    {
      key: 'catering',
      value: `${f.cateringEur > 0 ? '+ ' : ''}${fmt.eur(f.cateringEur)}`,
      sign: cateringSign(f.cateringEur),
    },
    { key: 'total', value: fmt.eur(f.ticketEur + f.cateringEur), total: true },
  ]
})

/** A per-departure figure scaled to the year, or a dot for nothing. */
function yearCell(perTrip: number): string | null {
  const v = perTrip * (result.value?.departures ?? 0)
  return v > 0.5 ? fmt.int(v) : null
}

const groupRows = computed(() => {
  const f = result.value
  if (!f) return []
  const dep = f.departures
  return GROUP_ORDER.map((g) => {
    const notServed = f.allocation.notServedByGroup[g] * dep
    return {
      key: g,
      prefs: GROUP_CLASS_PREFERENCES[g].join(' › '),
      asks: fmt.int(f.allocation.demandByGroup[g] * dep),
      cells: CLASS_ORDER.map((c) => yearCell(f.allocation.byGroupByClass[g][c])),
      served: fmt.int((f.allocation.demandByGroup[g] - f.allocation.notServedByGroup[g]) * dep),
      notServed: notServed > 0.5 ? fmt.int(notServed) : null,
    }
  })
})

const classRows = computed(() => result.value?.rows ?? [])
const revenueShares = computed(() => {
  const f = result.value
  if (!f || f.ticketEur <= 0) return []
  return f.rows.map((r) => ({ classMain: r.classMain, share: (r.ticketEur / f.ticketEur) * 100 }))
})
</script>

<template>
  <DetailPanel
    :title="t('proposal.details.follows.title')"
    :info="t('proposal.details.follows.info')"
    :doc-path="DOCS_DETAIL_PANEL.follows"
    :caption="
      composition
        ? t('proposal.details.follows.caption', { composition: composition.composition_id })
        : null
    "
    :awaiting="awaiting"
  >
    <PreviewChip v-if="previewing && !awaiting" />
    <p v-if="!result" class="text-xs text-primary-50/50">
      {{ t('proposal.details.follows.noDemand') }}
    </p>
    <div v-else class="grid gap-4 lg:grid-cols-[14rem_1fr]">
      <div class="flex flex-col gap-2">
        <div class="flex flex-col">
          <span
            class="text-2xl font-semibold tabular-nums"
            :class="previewing ? 'preview-value' : 'text-primary-50'"
          >
            {{ fmt.int(result.passengers) }}
          </span>
          <span class="text-[11px] text-primary-50/50">
            {{ t('proposal.details.follows.passengersPerYear') }}
          </span>
        </div>
        <dl class="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-xs">
          <template v-for="row in kpis" :key="row.key">
            <dt
              class="text-primary-50/65"
              :class="
                row.total ? 'border-t border-primary-50/10 pt-1 font-semibold text-primary-50' : ''
              "
            >
              {{ t(`proposal.details.follows.${row.key}`) }}
            </dt>
            <dd
              class="text-right tabular-nums"
              :class="[
                previewing ? 'preview-value' : 'text-primary-50',
                row.total ? 'border-t border-primary-50/10 pt-1 font-semibold' : '',
                row.sign === 'positive'
                  ? 'text-emerald-300'
                  : row.sign === 'negative'
                    ? 'text-amber-300'
                    : '',
              ]"
            >
              {{ row.value }}
              <small v-if="row.note" class="ml-1 text-[10px] text-primary-50/45">{{
                row.note
              }}</small>
            </dd>
          </template>
        </dl>
      </div>

      <div class="flex min-w-0 flex-col gap-2">
        <table class="w-full border-collapse text-[11px] tabular-nums">
          <thead>
            <tr class="text-primary-50/50">
              <th class="py-1 pr-2 text-left font-normal">
                {{ t('proposal.details.follows.perYear') }}
              </th>
              <th class="px-1.5 py-1 text-right font-normal">
                {{ t('proposal.details.follows.asks') }}
              </th>
              <th v-for="c in CLASS_ORDER" :key="c" class="px-1.5 py-1 text-right font-normal">
                <span class="inline-flex items-center gap-1">
                  <i class="h-2 w-2 rounded-sm" :style="{ background: classColor(c) }" />
                  {{ t(`proposal.evaluation.classes.${c}`) }}
                </span>
              </th>
              <th class="px-1.5 py-1 text-right font-normal">
                {{ t('proposal.details.follows.served') }}
              </th>
              <th class="pl-1.5 py-1 text-right font-normal">
                {{ t('proposal.details.follows.notServed') }}
              </th>
            </tr>
          </thead>
          <tbody :class="previewing ? 'preview-value' : 'text-primary-50'">
            <tr v-for="row in groupRows" :key="row.key" class="border-t border-primary-50/8">
              <td class="py-0.5 pr-2 text-left" :title="row.prefs">
                {{ t(`proposal.details.groups.${row.key}`) }}
              </td>
              <td class="px-1.5 py-0.5 text-right">{{ row.asks }}</td>
              <td v-for="(cell, i) in row.cells" :key="i" class="px-1.5 py-0.5 text-right">
                <span v-if="cell">{{ cell }}</span>
                <span v-else class="text-primary-50/25">·</span>
              </td>
              <td class="px-1.5 py-0.5 text-right">{{ row.served }}</td>
              <td
                class="pl-1.5 py-0.5 text-right"
                :class="row.notServed ? 'text-amber-300' : 'text-primary-50/40'"
              >
                {{ row.notServed ?? '—' }}
              </td>
            </tr>
            <tr class="border-t border-primary-50/20 font-semibold">
              <td class="py-0.5 pr-2 text-left">{{ t('proposal.details.follows.passengers') }}</td>
              <td class="px-1.5 py-0.5 text-right">
                {{ fmt.int(committedDemand!.passengersPerYear) }}
              </td>
              <td v-for="r in classRows" :key="r.classMain" class="px-1.5 py-0.5 text-right">
                {{ fmt.int(r.passengers) }}
              </td>
              <td class="px-1.5 py-0.5 text-right">{{ fmt.int(result.passengers) }}</td>
              <td
                class="pl-1.5 py-0.5 text-right"
                :class="result.allocation.notServed > 0.5 ? 'text-amber-300' : 'text-primary-50/40'"
              >
                {{
                  result.allocation.notServed > 0.5
                    ? fmt.int(result.allocation.notServed * result.departures)
                    : '—'
                }}
              </td>
            </tr>
            <tr class="border-t border-primary-50/8 text-primary-50/70">
              <td class="py-0.5 pr-2 text-left">
                {{ t('proposal.details.follows.placesOffered') }}
              </td>
              <td />
              <td v-for="r in classRows" :key="r.classMain" class="px-1.5 py-0.5 text-right">
                {{ fmt.int(r.places * result.departures) }}
              </td>
              <td class="px-1.5 py-0.5 text-right">
                {{ fmt.int(totalPlaces * result.departures) }}
              </td>
              <td />
            </tr>
            <tr class="text-primary-50/70">
              <td class="py-0.5 pr-2 text-left">{{ t('proposal.details.follows.utilisation') }}</td>
              <td />
              <td v-for="r in classRows" :key="r.classMain" class="px-1.5 py-0.5 text-right">
                {{ r.places ? fmt.percent((r.served / r.places) * 100) : '—' }}
              </td>
              <td class="px-1.5 py-0.5 text-right">
                {{ totalPlaces ? fmt.percent((result.soldPerDeparture / totalPlaces) * 100) : '—' }}
              </td>
              <td />
            </tr>
            <tr class="text-primary-50/70">
              <td class="py-0.5 pr-2 text-left">
                {{ t('proposal.details.follows.ticketRevenue') }}
              </td>
              <td />
              <td v-for="r in classRows" :key="r.classMain" class="px-1.5 py-0.5 text-right">
                {{ fmt.eur(r.ticketEur) }}
              </td>
              <td class="px-1.5 py-0.5 text-right">{{ fmt.eur(result.ticketEur) }}</td>
              <td />
            </tr>
          </tbody>
        </table>

        <div v-if="revenueShares.length" class="flex flex-col gap-1">
          <span class="text-[10px] tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.details.follows.revenueByClass') }}
          </span>
          <div class="flex h-2 w-full overflow-hidden rounded-full bg-primary-50/8">
            <i
              v-for="s in revenueShares"
              :key="s.classMain"
              :style="{ width: `${s.share}%`, background: classColor(s.classMain) }"
              :title="`${t(`proposal.evaluation.classes.${s.classMain}`)} ${fmt.percent(s.share)}`"
            />
          </div>
        </div>
        <p v-if="previewing && !awaiting" class="text-[11px] leading-snug text-primary-50/45">
          {{ t('proposal.details.follows.previewHint') }}
        </p>
      </div>
    </div>
  </DetailPanel>
</template>

<style scoped>
.preview-value {
  color: var(--color-amber-300);
  font-style: italic;
}
</style>
