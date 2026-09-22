<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Breakdown, Operations, ParkingEntry, TripInfrastructure } from '@/types/api'
import { useCompareFormat } from '@/composables/useCompareFormat'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import DetailPanel from '@/components/details/DetailPanel.vue'
import { DOCS_DETAIL_PANEL } from '@/lib/docsLinks'
import TripCycleYearStrip from '@/components/details/TripCycleYearStrip.vue'

// Infrastructure — what the route pays to use the network, laid out as the
// sketch has it: four compact tables two abreast (track access | stations;
// facilities | energy), each with its trip → cycle → year strip, and one
// full-width row of per-year tiles with a stacked share bar.
//
// Where the euros come from and why it matters: track access, energy and
// station charges are per TRIP in `operations.infrastructure` — the two
// directions differ where a night band catches one and not the other — so
// the tables show the outbound trip and the strips take it to the cycle.
// Parking is per operating DAY per stabling location, which is how the leaf
// is built; its "per trip" is one stay averaged over both ends.
//
// The "charged on" column is a row of TAGS, not a sentence: one tag per term
// the country actually levied — "distance", "night rate", "gross weight",
// "congestion". A tag says what a charge is; it does not try to explain the
// tariff, which is what the ⓘ is for.
//
// Every figure that came from a default rather than from the country's or
// the stop's own row says so with a "default" tag beside it. The reader is
// looking at placeholders and should know which.
const props = defineProps<{
  operations: Operations | null
  breakdown: Breakdown | null
  departuresPerYear: number | null
  operatingDaysPerYear: number | null
  awaiting: boolean
}>()

const { t, te } = useI18n()
const fmt = useCompareFormat()
const { countryName } = useLocaleFormat()

/** Outbound by name, never by position. */
const trip = computed<TripInfrastructure | null>(
  () =>
    props.operations?.infrastructure.trips.find((tr) => tr.direction === 'outbound') ??
    props.operations?.infrastructure.trips[0] ??
    null,
)
const days = computed(() => props.operatingDaysPerYear ?? 0)

// --- Track access ------------------------------------------------------------

function termTag(term: string): string {
  const key = `proposal.details.infrastructure.terms.${term}`
  return te(key) ? t(key) : term
}

/** The tags for one country: its levied terms, "night rate" where part of
 *  the distance was priced at it, "default" where the country has no row. */
function tacTags(c: TripInfrastructure['track_access']['countries'][number]): string[] {
  const tags = c.terms.map(({ term }) => termTag(term))
  if (c.night_km > 0) tags.splice(1, 0, t('proposal.details.infrastructure.terms.night_rate'))
  return tags
}

const tacTotal = computed(() => trip.value?.track_access.eur ?? 0)
const tacKm = computed(() => trip.value?.track_access.countries.reduce((s, c) => s + c.km, 0) ?? 0)
const tacRows = computed(() =>
  (trip.value?.track_access.countries ?? []).map((c) => ({
    key: c.country_code,
    name: countryName(c.country_code),
    code: c.country_code,
    km: c.km,
    tags: tacTags(c),
    defaulted: c.defaulted,
    perTrainKm: c.km ? c.eur / c.km : null,
    eur: c.eur,
    share: tacTotal.value ? c.eur / tacTotal.value : 0,
  })),
)
const passageRows = computed(() =>
  (trip.value?.track_access.passages ?? []).map((p) => ({
    key: p.passage_id,
    name: p.passage_id.replace(/_/g, ' '),
    tags: [
      p.fixed_eur > 0 ? t('proposal.details.infrastructure.terms.passage_fixed') : null,
      p.per_passenger_eur > 0
        ? t('proposal.details.infrastructure.terms.passage_per_passenger')
        : null,
    ].filter((x): x is string => x !== null),
    eur: p.eur,
    share: tacTotal.value ? p.eur / tacTotal.value : 0,
  })),
)

// --- Station charges ---------------------------------------------------------

const stationTotal = computed(() => trip.value?.stations.eur ?? 0)
const stationRows = computed(() =>
  (trip.value?.stations.calls ?? []).map((call) => ({
    key: `${call.stop_id}`,
    name: call.stop_name,
    code: call.country_code,
    category: call.category,
    defaulted: call.defaulted === true,
    eur: call.eur,
    share: stationTotal.value ? call.eur / stationTotal.value : 0,
  })),
)
const calls = computed(() => trip.value?.stations.calls.length ?? 0)

// --- Service facilities (parking) --------------------------------------------

const parkings = computed<ParkingEntry[]>(() => props.operations?.infrastructure.parkings ?? [])
const parkingPerDay = computed(() =>
  parkings.value.reduce((s, p) => s + p.eur_per_operating_day, 0),
)
// One operating day carries one cycle, so per day IS per cycle; "per trip"
// is one stay averaged over both ends.
const parkingPerTrip = computed(() => (parkings.value.length ? parkingPerDay.value / 2 : 0))
const parkingRows = computed(() =>
  parkings.value.map((p) => ({
    key: p.stop_id,
    name: p.stop_name,
    code: p.country_code,
    hours: p.hours,
    basis: te(`proposal.details.infrastructure.parkingBasis.${p.basis}`)
      ? t(`proposal.details.infrastructure.parkingBasis.${p.basis}`)
      : p.basis,
    perHour: p.hours ? p.eur_per_operating_day / p.hours : null,
    defaulted: p.defaulted,
    eur: p.eur_per_operating_day,
  })),
)
const parkingHoursAvg = computed(() =>
  parkings.value.length
    ? parkings.value.reduce((s, p) => s + p.hours, 0) / parkings.value.length
    : null,
)

// --- Energy ------------------------------------------------------------------

const energyTotal = computed(() => trip.value?.energy.eur ?? 0)
const energyKwh = computed(() => trip.value?.energy.kwh ?? 0)
const energyRows = computed(() =>
  (trip.value?.energy.countries ?? []).map((c) => ({
    key: c.country_code,
    name: countryName(c.country_code),
    code: c.country_code,
    km: c.km,
    kwhPerKm: c.km ? c.kwh / c.km : null,
    kwh: c.kwh,
    eurPerKwh: c.tariff ? c.tariff.day_eur_kwh : c.kwh ? c.price_eur / c.kwh : null,
    nightShare: c.kwh && c.night_kwh > 0 ? c.night_kwh / c.kwh : null,
    nightEurPerKwh: c.tariff?.night_eur_kwh ?? null,
    catenary: c.catenary_eur,
    defaulted: c.tariff?.defaulted === true,
    eur: c.eur,
  })),
)

// --- Per year: the four leaves side by side ---------------------------------

const yearTiles = computed(() => {
  const i = props.breakdown?.cost.infrastructure
  if (!i) return []
  const trainKm =
    props.departuresPerYear && tacKm.value ? props.departuresPerYear * tacKm.value : null
  const tile = (key: string, eur: number, tone: string) => ({
    key,
    eur,
    tone,
    perTrainKm: trainKm ? eur / trainKm : null,
    share: i.total_eur ? eur / i.total_eur : 0,
  })
  // Four steps of one blue, dark to light — one hue family, so the bar
  // reads as one quantity made of parts, and the steps are far enough
  // apart to tell at a glance.
  return [
    tile('tac', i.tac_eur, '#2f6fb0'),
    tile('stations', i.station_charge_eur, '#4a90d9'),
    tile('parking', i.parking_eur, '#7fb4e8'),
    tile('energy', i.energy_eur, '#b9d6f3'),
  ]
})
const yearTotal = computed(() => props.breakdown?.cost.infrastructure.total_eur ?? 0)
const yearPerTrainKm = computed(() =>
  props.departuresPerYear && tacKm.value
    ? yearTotal.value / (props.departuresPerYear * tacKm.value)
    : null,
)

const th = 'py-1 pr-2 text-left font-normal whitespace-nowrap'
const thFirst = 'py-1 pr-2 pl-3 text-left font-normal whitespace-nowrap'
const thR = 'py-1 pr-2 text-right font-normal whitespace-nowrap'
const td = 'py-1 pr-2 text-primary-50/85'
const tdFirst = 'py-1 pr-2 pl-3 text-primary-50/85'
const tdN = 'py-1 pr-2 whitespace-nowrap tabular-nums text-primary-50/85'
const tdE = 'py-1 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50'
const tdS = 'py-1 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50/50'
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="grid gap-3 xl:grid-cols-2">
      <!-- Track access -->
      <DetailPanel
        class="min-w-0"
        :title="t('proposal.details.infrastructure.tac.title')"
        :info="t('proposal.details.infrastructure.tac.info')"
        :doc-path="DOCS_DETAIL_PANEL.tac"
        :caption="trip ? t('proposal.details.infrastructure.outboundTrip') : null"
        :awaiting="awaiting"
      >
        <div class="scroller">
          <table class="w-full border-collapse text-xs">
            <thead class="sticky top-0 z-10 bg-sapphire">
              <tr class="text-[11px] text-primary-50/50">
                <th :class="thFirst">{{ t('proposal.details.infrastructure.country') }}</th>
                <th :class="thR">km</th>
                <th :class="th">{{ t('proposal.details.infrastructure.chargedOn') }}</th>
                <th :class="thR">{{ t('proposal.details.infrastructure.eurPerTrainKm') }}</th>
                <th :class="thR">{{ t('proposal.details.receipt.perTrip') }}</th>
                <th :class="thR">{{ t('proposal.details.receipt.share') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in tacRows" :key="row.key" class="border-t border-primary-50/5">
                <td :class="tdFirst">
                  {{ row.name }} <span class="text-primary-50/40">{{ row.code }}</span>
                </td>
                <td :class="[tdN, 'text-right']">{{ fmt.int(row.km) }}</td>
                <td class="py-1 pr-2">
                  <span class="flex flex-wrap gap-1">
                    <span v-for="tag in row.tags" :key="tag" class="tag">{{ tag }}</span>
                    <span v-if="row.defaulted" class="tag tag-default">
                      {{ t('proposal.details.infrastructure.defaultTag') }}
                    </span>
                  </span>
                </td>
                <td :class="tdN + ' text-right'">
                  {{ row.perTrainKm === null ? '—' : fmt.dec2(row.perTrainKm) }}
                </td>
                <td :class="tdE">{{ fmt.eur2(row.eur) }}</td>
                <td :class="tdS">{{ fmt.percent(row.share * 100) }}</td>
              </tr>
              <tr v-for="row in passageRows" :key="row.key" class="border-t border-primary-50/5">
                <td :class="tdFirst" colspan="2">
                  {{ t('proposal.details.infrastructure.crossing', { id: row.name }) }}
                </td>
                <td class="py-1 pr-2">
                  <span class="flex flex-wrap gap-1">
                    <span v-for="tag in row.tags" :key="tag" class="tag">{{ tag }}</span>
                  </span>
                </td>
                <td :class="tdN + ' text-right'">—</td>
                <td :class="tdE">{{ fmt.eur2(row.eur) }}</td>
                <td :class="tdS">{{ fmt.percent(row.share * 100) }}</td>
              </tr>
              <tr v-if="trip && passageRows.length === 0" class="border-t border-primary-50/5">
                <td :class="tdFirst" colspan="2">
                  {{ t('proposal.details.infrastructure.crossingsRow') }}
                </td>
                <td class="py-1 pr-2 text-[11px] text-primary-50/45">
                  {{ t('proposal.details.infrastructure.noCrossings') }}
                </td>
                <td :class="tdN + ' text-right'">—</td>
                <td :class="tdE">—</td>
                <td :class="tdS"></td>
              </tr>
              <tr
                class="sticky bottom-0 z-10 border-t border-primary-50/25 bg-sapphire font-semibold"
              >
                <td :class="td + ' text-primary-50'">
                  {{ t('proposal.details.infrastructure.route') }}
                </td>
                <td :class="[tdN, 'text-right text-primary-50']">{{ fmt.int(tacKm) }}</td>
                <td />
                <td :class="tdN + ' text-right text-primary-50'">
                  {{ tacKm ? fmt.dec2(tacTotal / tacKm) : '—' }}
                </td>
                <td :class="tdE">{{ fmt.eur2(tacTotal) }}</td>
                <td :class="tdS">100 %</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mt-auto">
          <TripCycleYearStrip
            :label="t('proposal.details.infrastructure.tac.strip')"
            :per-trip="tacTotal"
            :operating-days="days"
          />
        </div>
      </DetailPanel>

      <!-- Station charges -->
      <DetailPanel
        class="min-w-0"
        :title="t('proposal.details.infrastructure.stations.title')"
        :info="t('proposal.details.infrastructure.stations.info')"
        :doc-path="DOCS_DETAIL_PANEL.stations"
        :caption="trip ? t('proposal.details.infrastructure.outboundTrip') : null"
        :awaiting="awaiting"
      >
        <div class="scroller">
          <table class="w-full border-collapse text-xs">
            <thead class="sticky top-0 z-10 bg-sapphire">
              <tr class="text-[11px] text-primary-50/50">
                <th :class="thFirst">
                  {{ t('proposal.details.infrastructure.stations.station') }}
                </th>
                <th :class="th">{{ t('proposal.details.infrastructure.stations.category') }}</th>
                <th :class="thR">{{ t('proposal.details.infrastructure.stations.perStop') }}</th>
                <th :class="thR">{{ t('proposal.details.receipt.share') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in stationRows" :key="row.key" class="border-t border-primary-50/5">
                <td :class="tdFirst">
                  {{ row.name }} <span class="text-primary-50/40">{{ row.code }}</span>
                </td>
                <td class="py-1 pr-2">
                  <span class="flex flex-wrap gap-1">
                    <span class="tag">{{ row.category ?? '—' }}</span>
                    <span v-if="row.defaulted" class="tag tag-default">
                      {{ t('proposal.details.infrastructure.defaultTag') }}
                    </span>
                  </span>
                </td>
                <td :class="tdE">{{ fmt.eur2(row.eur) }}</td>
                <td :class="tdS">{{ fmt.percent(row.share * 100) }}</td>
              </tr>
              <tr
                class="sticky bottom-0 z-10 border-t border-primary-50/25 bg-sapphire font-semibold"
              >
                <td :class="tdFirst + ' text-primary-50'" colspan="2">
                  {{ t('proposal.details.infrastructure.stations.stopsPerTrip', { n: calls }) }}
                </td>
                <td :class="tdE">{{ fmt.eur2(stationTotal) }}</td>
                <td :class="tdS">100 %</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mt-auto">
          <TripCycleYearStrip
            :label="
              t('proposal.details.infrastructure.stations.strip', {
                cycle: fmt.int(calls * 2),
                year: fmt.count(calls * 2 * days),
              })
            "
            :per-trip="stationTotal"
            :operating-days="days"
          />
        </div>
      </DetailPanel>

      <!-- Service facilities -->
      <DetailPanel
        class="min-w-0"
        :title="t('proposal.details.infrastructure.facilities.title')"
        :info="t('proposal.details.infrastructure.facilities.info')"
        :doc-path="DOCS_DETAIL_PANEL.facilities"
        :caption="t('proposal.details.infrastructure.facilities.caption')"
        :awaiting="awaiting"
      >
        <div class="scroller">
          <table class="w-full border-collapse text-xs">
            <thead class="sticky top-0 z-10 bg-sapphire">
              <tr class="text-[11px] text-primary-50/50">
                <th :class="thFirst">
                  {{ t('proposal.details.infrastructure.facilities.terminal') }}
                </th>
                <th :class="th">{{ t('proposal.details.infrastructure.facilities.basis') }}</th>
                <th :class="thR">
                  {{ t('proposal.details.infrastructure.facilities.hoursPerStay') }}
                </th>
                <th :class="thR">
                  {{ t('proposal.details.infrastructure.facilities.eurPerHour') }}
                </th>
                <th :class="thR">
                  {{ t('proposal.details.infrastructure.facilities.eurPerStay') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in parkingRows" :key="row.key" class="border-t border-primary-50/5">
                <td :class="tdFirst">
                  {{ row.name }} <span class="text-primary-50/40">{{ row.code }}</span>
                </td>
                <td class="py-1 pr-2">
                  <span class="flex flex-wrap gap-1">
                    <span class="tag">{{ row.basis }}</span>
                    <span v-if="row.defaulted" class="tag tag-default">
                      {{ t('proposal.details.infrastructure.defaultTag') }}
                    </span>
                  </span>
                </td>
                <td :class="tdN + ' text-right'">{{ fmt.dec1(row.hours) }}</td>
                <td :class="tdN + ' text-right'">
                  {{ row.perHour === null ? '—' : fmt.dec2(row.perHour) }}
                </td>
                <td :class="tdE">{{ fmt.eur2(row.eur) }}</td>
              </tr>
              <tr v-if="parkingRows.length === 0">
                <td :class="td" colspan="5">
                  {{ t('proposal.details.infrastructure.facilities.none') }}
                </td>
              </tr>
              <tr
                class="sticky bottom-0 z-10 border-t border-primary-50/25 bg-sapphire font-semibold"
              >
                <td :class="tdFirst + ' text-primary-50'" colspan="2">
                  {{ t('proposal.details.infrastructure.facilities.perTripRow') }}
                </td>
                <td :class="tdN + ' text-right text-primary-50'">
                  {{ parkingHoursAvg === null ? '—' : fmt.dec1(parkingHoursAvg) }}
                </td>
                <td :class="tdN + ' text-right'">—</td>
                <td :class="tdE">{{ fmt.eur2(parkingPerTrip) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mt-auto">
          <TripCycleYearStrip
            :label="t('proposal.details.infrastructure.facilities.strip')"
            :per-trip="parkingPerTrip"
            :operating-days="days"
          />
        </div>
      </DetailPanel>

      <!-- Energy -->
      <DetailPanel
        class="min-w-0"
        :title="t('proposal.details.infrastructure.energy.title')"
        :info="t('proposal.details.infrastructure.energy.info')"
        :doc-path="DOCS_DETAIL_PANEL.energy"
        :caption="trip ? t('proposal.details.infrastructure.outboundTrip') : null"
        :awaiting="awaiting"
      >
        <div class="scroller">
          <table class="w-full border-collapse text-xs">
            <thead class="sticky top-0 z-10 bg-sapphire">
              <tr class="text-[11px] text-primary-50/50">
                <th :class="thFirst">{{ t('proposal.details.infrastructure.country') }}</th>
                <th :class="thR">km</th>
                <th :class="thR">
                  {{ t('proposal.details.infrastructure.energy.kwhPerTrainKm') }}
                </th>
                <th :class="thR">{{ t('proposal.details.infrastructure.energy.kwhPerTrip') }}</th>
                <th :class="th">{{ t('proposal.details.infrastructure.energy.tariff') }}</th>
                <th :class="thR">{{ t('proposal.details.receipt.perTrip') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in energyRows" :key="row.key" class="border-t border-primary-50/5">
                <td :class="tdFirst">
                  {{ row.name }} <span class="text-primary-50/40">{{ row.code }}</span>
                </td>
                <td :class="tdN + ' text-right'">{{ fmt.int(row.km) }}</td>
                <td :class="tdN + ' text-right'">
                  {{ row.kwhPerKm === null ? '—' : fmt.dec1(row.kwhPerKm) }}
                </td>
                <td :class="tdN + ' text-right'">{{ fmt.count(row.kwh) }}</td>
                <td class="py-1 pr-2">
                  <span class="flex flex-wrap gap-1">
                    <span class="tag tabular-nums">
                      {{ row.eurPerKwh === null ? '—' : `${fmt.dec2(row.eurPerKwh)} €/kWh` }}
                    </span>
                    <span
                      v-if="row.nightShare !== null && row.nightEurPerKwh !== null"
                      class="tag tabular-nums"
                    >
                      {{
                        t('proposal.details.infrastructure.energy.nightTag', {
                          rate: fmt.dec2(row.nightEurPerKwh),
                          share: fmt.percent(row.nightShare * 100),
                        })
                      }}
                    </span>
                    <span v-if="row.catenary > 0" class="tag tabular-nums">
                      {{
                        t('proposal.details.infrastructure.catenary', {
                          value: fmt.eur2(row.catenary),
                        })
                      }}
                    </span>
                    <span v-if="row.defaulted" class="tag tag-default">
                      {{ t('proposal.details.infrastructure.defaultTag') }}
                    </span>
                  </span>
                </td>
                <td :class="tdE">{{ fmt.eur2(row.eur) }}</td>
              </tr>
              <tr
                class="sticky bottom-0 z-10 border-t border-primary-50/25 bg-sapphire font-semibold"
              >
                <td :class="td + ' text-primary-50'">
                  {{ t('proposal.details.infrastructure.route') }}
                </td>
                <td :class="tdN + ' text-right text-primary-50'">{{ fmt.int(tacKm) }}</td>
                <td :class="tdN + ' text-right text-primary-50'">
                  {{ tacKm ? fmt.dec1(energyKwh / tacKm) : '—' }}
                </td>
                <td :class="tdN + ' text-right text-primary-50'">{{ fmt.count(energyKwh) }}</td>
                <td class="py-1 pr-2 text-[11px] whitespace-nowrap tabular-nums text-primary-50/60">
                  {{
                    energyKwh
                      ? t('proposal.details.infrastructure.energy.weighted', {
                          rate: fmt.dec2(energyTotal / energyKwh),
                        })
                      : '—'
                  }}
                </td>
                <td :class="tdE">{{ fmt.eur2(energyTotal) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mt-auto">
          <TripCycleYearStrip
            :label="t('proposal.details.infrastructure.energy.strip')"
            :per-trip="energyTotal"
            :operating-days="days"
            :unit="{ name: 'kWh', perTrip: energyKwh }"
          />
        </div>
      </DetailPanel>
    </div>

    <!-- Per year: the four leaves side by side, and the share bar -->
    <DetailPanel
      class="mt-3"
      :title="t('proposal.details.infrastructure.year.title')"
      :info="t('proposal.details.infrastructure.year.info')"
      :doc-path="DOCS_DETAIL_PANEL.infrastructureYear"
      :awaiting="awaiting"
    >
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <div
          v-for="tile in yearTiles"
          :key="tile.key"
          class="rounded-md border border-primary-50/10 p-3"
        >
          <p class="flex items-center gap-1.5 text-[11px] text-primary-50/55">
            <i class="h-2.5 w-2.5 rounded-sm" :style="{ background: tile.tone }" />
            {{ t(`proposal.details.infrastructure.year.${tile.key}`) }}
          </p>
          <p class="text-lg font-semibold whitespace-nowrap tabular-nums text-primary-50">
            {{ fmt.eur(tile.eur) }}
            <span class="text-[11px] font-normal text-primary-50/50">
              {{
                tile.perTrainKm === null
                  ? ''
                  : t('proposal.details.infrastructure.year.perTrainKm', {
                      value: fmt.eur2(tile.perTrainKm),
                    })
              }}
            </span>
          </p>
        </div>
        <div class="min-w-0 overflow-hidden rounded-md border border-primary-50/30 p-3">
          <p class="text-[11px] text-primary-50/55">
            {{ t('proposal.details.infrastructure.year.total') }}
          </p>
          <p class="text-lg font-semibold whitespace-nowrap tabular-nums text-primary-50">
            {{ fmt.eur(yearTotal) }}
            <span class="text-[11px] font-normal text-primary-50/50">
              {{
                yearPerTrainKm === null
                  ? ''
                  : t('proposal.details.infrastructure.year.perTrainKm', {
                      value: fmt.eur2(yearPerTrainKm),
                    })
              }}
            </span>
          </p>
        </div>
      </div>
      <span class="mt-1 flex h-2 w-full overflow-hidden rounded bg-primary-50/10">
        <span
          v-for="tile in yearTiles"
          :key="tile.key"
          :style="{ width: `${tile.share * 100}%`, background: tile.tone }"
          :title="`${t(`proposal.details.infrastructure.year.${tile.key}`)} ${fmt.percent(tile.share * 100)}`"
        />
      </span>
      <p class="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-primary-50/55">
        <span v-for="tile in yearTiles" :key="tile.key" class="flex items-center gap-1.5">
          <i class="h-2.5 w-2.5 rounded-sm" :style="{ background: tile.tone }" />
          {{ t(`proposal.details.infrastructure.year.${tile.key}`) }}
          {{ fmt.percent(tile.share * 100) }}
        </span>
      </p>
      <p class="text-[11px] text-primary-50/40">
        <span class="tag tag-default mr-1">{{
          t('proposal.details.infrastructure.defaultTag')
        }}</span>
        {{ t('proposal.details.infrastructure.defaultLegend') }}
      </p>
    </DetailPanel>
  </div>
</template>

<style scoped>
/* The four tables share one scroller: horizontal for a wide row, vertical
   once the list outgrows the cap — a station list on a long route is twenty
   rows next to a track-access list of three. The head and the total row are
   sticky so the columns and the sum stay in view while the rows scroll. */
.scroller {
  max-height: 20rem;
  overflow: auto;
}

.tag {
  display: inline-block;
  border-radius: 0.25rem;
  padding: 1px 6px;
  font-size: 10px;
  line-height: 1.4;
  white-space: nowrap;
  color: color-mix(in srgb, var(--color-primary-50) 80%, transparent);
  background: color-mix(in srgb, var(--color-primary-50) 10%, transparent);
}

.tag-default {
  color: var(--color-amber-300);
  background: color-mix(in srgb, #fbbf24 12%, transparent);
}
</style>
