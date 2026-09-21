<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Breakdown, Composition, PairOperations, TripOperations } from '@/types/api'
import {
  AMENITY_ICONS,
  buildFormation,
  CATERING_ICON,
  classColor,
} from '@/lib/compositionFormation'
import { DAYS_IN_YEAR } from '@/lib/detailsScope'
import { useStore } from '@/stores/store'
import { useCompareFormat } from '@/composables/useCompareFormat'
import AppIcon from '@/components/AppIcon.vue'
import CompositionFormation from '@/components/CompositionFormation.vue'
import DetailPanel from '@/components/details/DetailPanel.vue'
import { DOCS_DETAIL_PANEL } from '@/lib/docsLinks'
import KassenzettelTable, { type ReceiptLine } from '@/components/details/KassenzettelTable.vue'
import TripCycleYearStrip from '@/components/details/TripCycleYearStrip.vue'

// Train operation · the composition on screen. Replaces the old detail
// overlay: everything it used to hide behind a click is here, in the panel
// the selection already highlights.
//
// Three stacked receipts, each the same shape — a headline KPI and the facts
// on the left, the per-trip Kassenzettel and its trip → cycle → year strip on
// the right. Stacked rather than three abreast because the card starts at
// 1,024 px and three receipts side by side would put their tables into a
// scrollbar each.
//
// Where the euros come from: the fleet lines are per-year leaves of the
// per_trip_pair breakdown divided by departures_per_year — `operations`
// deliberately does not repeat them, so there is no second copy to drift. The
// loco and staff euros ARE per trip in `operations`, because the two
// directions differ in running time and duty boundaries.
const props = defineProps<{
  composition: Composition
  /** The pair of the selected direction. A Y-route has more than one, so
   *  never assume [0] — the caller picks and names it in the caption. */
  pair: PairOperations | null
  /** The per_trip_pair cell for that pair, annual euros. */
  breakdown: Breakdown | null
  departuresPerYear: number | null
  operatingDaysPerYear: number | null
  awaiting: boolean
  pairCaption: string | null
}>()

const { t } = useI18n()
const fmt = useCompareFormat()
const store = useStore()

const formation = computed(() =>
  buildFormation(
    props.composition,
    store.compositionCatalog.coach_types,
    store.compositionCatalog.classes,
  ),
)

// Which coach the inspector describes. The drawing previews on hover and pins
// on click; this is the pin. Reset when the composition changes, or position
// 7 of a 14-coach rake would go on describing a coach that is no longer there.
const selectedCoach = ref<number | null>(null)
watch(
  () => props.composition.composition_id,
  () => (selectedCoach.value = null),
)

/** What the whole train has: the composition's own OR-aggregate over its
 *  coaches. Shown for every amenity, fitted or not, so "no bicycle places"
 *  is visible rather than merely unstated. */
const trainAmenities = computed(() =>
  AMENITY_ICONS.map(([flag, path, key]) => ({
    fitted: props.composition.equipment[flag],
    path,
    key,
  })),
)

/** The pinned coach, with everything the inspector prints: what it is, how
 *  long, what it carries, and — the part that was missing entirely — what is
 *  fitted in it. Amenities are as-built per coach TYPE, not the composition's
 *  OR-aggregate, so "wifi" here means wifi in this coach. */
const coachDetail = computed(() => {
  const coach = formation.value.coaches.find((c) => c.position === selectedCoach.value)
  if (!coach) return null
  return {
    position: coach.position,
    typeId: coach.coachTypeId,
    lengthM: coach.type.length_m,
    weightT: coach.type.weight_gross_t,
    places: coach.type.places_total,
    isService: coach.isService,
    sections: coach.sections.map((section) => ({
      classMain: section.classMain,
      places: section.places,
      color: classColor(section.classMain),
    })),
    amenities: AMENITY_ICONS.map(([flag, path, key]) => ({
      fitted: coach.type.equipment[flag],
      path,
      key,
    })),
  }
})

/** Outbound by name, never by position. */
const trip = computed<TripOperations | null>(
  () => props.pair?.trips.find((tr) => tr.direction === 'outbound') ?? props.pair?.trips[0] ?? null,
)

const subline = computed(() => {
  const c = props.composition
  const parts = [
    t(`proposal.composition.strategy.${c.material_strategy}`, c.material_strategy),
    t('proposal.details.operation.coaches', { n: c.coaches.count }),
    `${fmt.int(c.routing.total_length_m)} m`,
    `${fmt.int(c.routing.total_weight_t)} t`,
    `${c.routing.max_speed_kmh} km/h`,
    t('proposal.details.operation.places', { n: fmt.int(c.capacity.total_places) }),
  ]
  return parts.join(' · ')
})

/** A per-year breakdown leaf as one trip's share. */
function perTrip(annual: number | undefined): number {
  if (annual === undefined || !props.departuresPerYear) return 0
  return annual / props.departuresPerYear
}

const fleetLines = computed<ReceiptLine[]>(() => {
  const v = props.breakdown?.cost.operator.variable
  const f = props.breakdown?.cost.operator.fixed
  const basis = props.pair?.fleet
  return [
    {
      label: t('proposal.details.operation.fleet.maintenance'),
      basis: basis ? `${fmt.eur2(basis.coach_maint_eur_km)}/km` : null,
      eur: perTrip(v?.coach_maintenance_eur),
    },
    {
      label: t('proposal.details.operation.fleet.cleaning'),
      basis: basis
        ? t('proposal.details.operation.fleet.cleaningBasis', {
            rate: fmt.eur2(basis.cleaning_eur_coach_day),
          })
        : null,
      eur: perTrip(f?.cleaning_eur),
    },
    {
      label: t('proposal.details.operation.fleet.shunting'),
      basis: basis
        ? t('proposal.details.operation.fleet.shuntingBasis', {
            n: basis.shunting_events_per_trip_cycle,
          })
        : null,
      eur: perTrip(f?.shunting_eur),
    },
    {
      label: t('proposal.details.operation.fleet.amortisation'),
      basis: f ? `${fmt.millionEur(f.coach_amortisation_eur / 1_000_000)}/a` : null,
      eur: perTrip(f?.coach_amortisation_eur),
    },
    {
      label: t('proposal.details.operation.fleet.financing'),
      basis: f ? `${fmt.millionEur(f.financing_eur / 1_000_000)}/a` : null,
      eur: perTrip(f?.financing_eur),
    },
  ]
})
const fleetTotal = computed(() => fleetLines.value.reduce((sum, l) => sum + l.eur, 0))

const fleetFacts = computed(() => {
  const p = props.pair
  if (!p) return []
  return [
    {
      label: t('proposal.details.operation.fleet.cycle'),
      value:
        p.trainsets.cycle_days === null
          ? '—'
          : t('proposal.details.operation.fleet.days', { n: p.trainsets.cycle_days }),
    },
    {
      // The fleet is sized to the frequency (ROUTE_BUILDER 0.9.40: one
      // figure over the year; the busiest month of the grid underneath is
      // every month). Read back from the operating days the result carries.
      label: t('proposal.details.operation.fleet.sizedBy'),
      value:
        props.operatingDaysPerYear === null
          ? '—'
          : t('proposal.details.schedule.daysPerWeek', {
              n: Math.round((props.operatingDaysPerYear * 7) / DAYS_IN_YEAR),
            }),
    },
    {
      label: t('proposal.details.operation.fleet.turnaround'),
      value: `${p.trainsets.min_turnaround_min} min`,
    },
    {
      label: t('proposal.details.operation.fleet.availability'),
      value: fmt.percent(p.trainsets.coach_avail_per * 100),
    },
    {
      label: t('proposal.details.operation.fleet.purchase'),
      value: `${fmt.millionEur(p.fleet.purchase_coach_eur / 1_000_000)} · ${p.fleet.amort_years} a`,
    },
  ]
})

const locoLines = computed<ReceiptLine[]>(() => {
  const lh = trip.value?.loco_hours
  const perTripEur = perTrip(props.breakdown?.cost.operator.variable.loco_eur)
  if (!lh || lh.total === 0) return []
  // The lease is priced on hours, so the two rows are the hours split at the
  // rate the total implies — the total itself is the cost model's own figure.
  const rate = perTripEur / lh.total
  return [
    {
      label: t('proposal.details.operation.loco.running'),
      basis: `${fmt.hours(lh.running)}`,
      eur: lh.running * rate,
    },
    {
      label: t('proposal.details.operation.loco.atStops'),
      basis: `${fmt.hours(lh.at_stops)}`,
      eur: lh.at_stops * rate,
    },
  ]
})
const locoTotal = computed(() => perTrip(props.breakdown?.cost.operator.variable.loco_eur))

const STAFF_ROLES = ['drivers', 'train_chief', 'attendants'] as const

const staffRows = computed(() => {
  const s = trip.value?.staffing
  if (!s) return []
  return STAFF_ROLES.filter((role) => s[role] && s[role].on_board > 0).map((role) => ({
    role,
    ...s[role],
  }))
})
const staffTotal = computed(() => trip.value?.staffing.total ?? null)
</script>

<template>
  <DetailPanel
    :title="composition.composition_id"
    :info="t('proposal.details.operation.selectedInfo')"
    :doc-path="DOCS_DETAIL_PANEL.selectedComposition"
    :caption="pairCaption"
    :awaiting="awaiting"
    class="selected-composition"
  >
    <p class="-mt-1 text-[11px] text-primary-50/60">{{ composition.description }}</p>
    <p class="text-[11px] text-primary-50/45">{{ subline }}</p>
    <!-- What the TRAIN has, OR-aggregated over its coaches — the question a
         reader asks before picking a coach. The inspector below answers the
         same question for one coach. -->
    <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
      <span
        v-for="amenity in trainAmenities"
        :key="amenity.key"
        class="flex items-center gap-1"
        :class="amenity.fitted ? 'text-primary-50/80' : 'text-primary-50/25'"
        :title="t(`proposal.composition.equipment.${amenity.key}`)"
      >
        <AppIcon :path="amenity.path" :size="14" />
        {{ t(`proposal.composition.equipment.${amenity.key}`) }}
      </span>
      <span
        v-if="composition.equipment.food_and_beverages"
        class="flex items-center gap-1 text-primary-50/80"
      >
        <AppIcon :path="CATERING_ICON" :size="14" />
        {{ composition.equipment.food_and_beverages }}
      </span>
    </p>

    <div>
      <CompositionFormation
        :formation="formation"
        :selected="selectedCoach"
        @select="selectedCoach = selectedCoach === $event ? null : $event"
      />
    </div>

    <!-- The pinned coach. Click a vehicle to open it, click it again to
         close — hovering only previews the label above the drawing. -->
    <div
      v-if="coachDetail"
      class="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-md bg-primary-50/5 px-3 py-2 text-xs"
    >
      <span class="font-semibold text-primary-50">
        {{ t('proposal.composition.coachPosition', { n: coachDetail.position }) }} ·
        {{ coachDetail.typeId }}
      </span>
      <span class="text-primary-50/60">
        {{ fmt.dec1(coachDetail.lengthM) }} m · {{ fmt.dec1(coachDetail.weightT) }} t ·
        {{ fmt.int(coachDetail.places) }} {{ t('proposal.composition.places') }}
      </span>
      <span
        v-for="section in coachDetail.sections"
        :key="section.classMain"
        class="flex items-center gap-1.5"
      >
        <i class="h-2.5 w-2.5 rounded-sm" :style="{ background: section.color }" />
        <span class="text-primary-50/80">
          {{ t(`proposal.evaluation.classes.${section.classMain}`) }}
          {{ fmt.int(section.places) }}
        </span>
      </span>
      <span v-if="coachDetail.isService" class="text-primary-50/60">
        {{ t('proposal.composition.serviceCoach') }}
      </span>
      <span class="ml-auto flex items-center gap-2">
        <span
          v-for="amenity in coachDetail.amenities"
          :key="amenity.key"
          :title="t(`proposal.composition.equipment.${amenity.key}`)"
          :class="amenity.fitted ? 'text-primary-50' : 'text-primary-50/20'"
        >
          <AppIcon :path="amenity.path" :size="15" />
        </span>
      </span>
    </div>
    <p v-else class="text-[11px] text-primary-50/40">
      {{ t('proposal.composition.pickCoach') }}
    </p>

    <!-- Fleet -->
    <div class="receipt grid gap-3 lg:grid-cols-[15.5rem_1fr]">
      <div class="flex flex-col gap-1.5">
        <p class="kpi">
          {{ pair ? fmt.int(pair.trainsets.physical) : '—' }}
          <span v-if="pair" class="kpi-aside">
            · {{ pair.trainsets.theoretical.toFixed(2) }}
            {{ t('proposal.details.operation.fleet.withReserve') }}
          </span>
        </p>
        <p class="kpi-label">{{ t('proposal.details.operation.fleet.trainsets') }}</p>
        <dl class="facts">
          <template v-for="fact in fleetFacts" :key="fact.label">
            <dt>{{ fact.label }}</dt>
            <dd>{{ fact.value }}</dd>
          </template>
        </dl>
      </div>
      <div>
        <KassenzettelTable
          :lines="fleetLines"
          :total-label="t('proposal.details.operation.fleet.total')"
          :total-eur="fleetTotal"
          :basis-label="t('proposal.details.receipt.basis')"
          :basis-note="
            departuresPerYear
              ? t('proposal.details.receipt.perYearNote', { n: fmt.int(departuresPerYear) })
              : null
          "
        />
        <TripCycleYearStrip
          :label="t('proposal.details.operation.fleet.strip')"
          :per-trip="fleetTotal"
          :operating-days="operatingDaysPerYear ?? 0"
        />
      </div>
    </div>

    <!-- Locomotive leasing -->
    <div class="receipt grid gap-3 lg:grid-cols-[15.5rem_1fr]">
      <div class="flex flex-col gap-1.5">
        <p class="kpi">{{ pair ? fmt.count(pair.loco_hours.per_year) : '—' }}</p>
        <p class="kpi-label">{{ t('proposal.details.operation.loco.hoursPerYear') }}</p>
        <dl class="facts">
          <dt>{{ t('proposal.details.operation.loco.perTrain') }}</dt>
          <dd>{{ pair ? pair.loco_hours.n_locos : '—' }}</dd>
          <dt>{{ t('proposal.details.operation.loco.perCycle') }}</dt>
          <dd>{{ pair ? fmt.hours(pair.loco_hours.per_trip_cycle) : '—' }}</dd>
        </dl>
      </div>
      <div>
        <KassenzettelTable
          :lines="locoLines"
          :total-label="t('proposal.details.operation.loco.total')"
          :total-eur="locoTotal"
          :basis-label="t('proposal.details.operation.loco.hours')"
        />
        <TripCycleYearStrip
          :label="t('proposal.details.operation.loco.strip')"
          :per-trip="locoTotal"
          :operating-days="operatingDaysPerYear ?? 0"
          :unit="trip ? { name: 'h', perTrip: trip.loco_hours.total } : null"
        />
      </div>
    </div>

    <!-- Staff -->
    <div class="receipt grid gap-3 lg:grid-cols-[15.5rem_1fr]">
      <div class="flex flex-col gap-1.5">
        <p class="kpi">
          {{ staffTotal ? fmt.dec1(staffTotal.on_board) : '—' }}
          <span v-if="staffTotal" class="kpi-aside">
            · {{ staffTotal.factor_equivalents.toFixed(2) }}
            {{ t('proposal.details.operation.staff.weighted') }}
          </span>
        </p>
        <p class="kpi-label">{{ t('proposal.details.operation.staff.onBoard') }}</p>
        <dl class="facts">
          <dt>{{ t('proposal.details.operation.staff.hoursOnTrain') }}</dt>
          <dd>{{ staffTotal ? fmt.hours(staffTotal.hours_on_train) : '—' }}</dd>
          <dt>{{ t('proposal.details.operation.staff.paidHours') }}</dt>
          <dd>{{ staffTotal ? fmt.hours(staffTotal.paid_hours) : '—' }}</dd>
        </dl>
      </div>
      <div>
        <div class="overflow-x-auto">
          <!-- The same column discipline as the two receipts above: the role
               column is the receipts' 15 rem item column, every figure
               column after it is LEFT-aligned and packed against that edge
               (as Basis and h / trip are), a spacer takes the middle, and
               only the euros are right-aligned in the receipts' 7 rem. No
               column mixes alignments. Read left to right as the money is
               made: who is on board, for how long, what the roster turns
               that into, what the cost model charges each head at, and the
               euros — the factor sits between paid hours and euros because
               that is the only step it enters. -->
          <table class="w-full min-w-[40rem] table-fixed border-collapse text-xs">
            <colgroup>
              <col class="w-[15rem]" />
              <col class="w-16" />
              <col class="w-20" />
              <col class="w-16" />
              <col class="w-20" />
              <col class="w-16" />
              <col />
              <col class="w-28" />
            </colgroup>
            <thead>
              <tr class="text-[11px] text-primary-50/50">
                <th class="py-1 pr-2 pl-3 text-left font-normal">
                  {{ t('proposal.details.operation.staff.role') }}
                </th>
                <th class="py-1 pr-2 text-left font-normal">
                  {{ t('proposal.details.operation.staff.headcount') }}
                </th>
                <th class="py-1 pr-2 text-left font-normal">
                  {{ t('proposal.details.operation.staff.onTrain') }}
                </th>
                <th class="py-1 pr-2 text-left font-normal">
                  {{ t('proposal.details.operation.staff.roster') }}
                </th>
                <th class="py-1 pr-2 text-left font-normal">
                  {{ t('proposal.details.operation.staff.paid') }}
                </th>
                <th class="py-1 pr-2 text-left font-normal">
                  {{ t('proposal.details.operation.staff.factor') }}
                </th>
                <th />
                <th class="py-1 pr-2 text-right font-normal">
                  {{ t('proposal.details.receipt.perTrip') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in staffRows" :key="row.role" class="border-t border-primary-50/5">
                <td class="py-1 pr-2 pl-3 text-primary-50/85">
                  {{ t(`proposal.details.operation.staff.roles.${row.role}`) }}
                </td>
                <!-- Heads, or the crew-factor sum where the composition
                     staffs by coach: half an attendant per coach is three
                     and a half on seven coaches. -->
                <td class="py-1 pr-2 whitespace-nowrap tabular-nums text-primary-50/85">
                  {{ fmt.dec1(row.on_board) }}
                </td>
                <td class="py-1 pr-2 whitespace-nowrap tabular-nums text-primary-50/85">
                  {{ fmt.hours(row.hours_on_train) }}
                </td>
                <td class="py-1 pr-2 whitespace-nowrap tabular-nums text-primary-50/55">
                  {{ fmt.percent(row.roster_efficiency * 100) }}
                </td>
                <td class="py-1 pr-2 whitespace-nowrap tabular-nums text-primary-50/85">
                  {{ fmt.hours(row.paid_hours) }}
                </td>
                <td class="py-1 pr-2 whitespace-nowrap tabular-nums text-primary-50/55">
                  {{ row.factor === 1 ? '—' : `× ${row.factor.toFixed(2)}` }}
                </td>
                <td />
                <td class="py-1 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50">
                  {{ fmt.eur2(row.eur) }}
                </td>
              </tr>
              <tr v-if="staffTotal" class="border-t border-primary-50/25 font-semibold">
                <td class="py-1.5 pr-2 pl-3 text-primary-50">
                  {{ t('proposal.details.operation.staff.total') }}
                </td>
                <td class="py-1.5 pr-2 whitespace-nowrap tabular-nums text-primary-50">
                  {{ fmt.dec1(staffTotal.on_board) }}
                </td>
                <td class="py-1.5 pr-2 whitespace-nowrap tabular-nums text-primary-50">
                  {{ fmt.hours(staffTotal.hours_on_train) }}
                </td>
                <td class="py-1.5 pr-2 whitespace-nowrap tabular-nums text-primary-50/60">
                  {{
                    staffTotal.paid_hours
                      ? fmt.percent((staffTotal.hours_on_train / staffTotal.paid_hours) * 100)
                      : '—'
                  }}
                </td>
                <td class="py-1.5 pr-2 whitespace-nowrap tabular-nums text-primary-50">
                  {{ fmt.hours(staffTotal.paid_hours) }}
                </td>
                <td class="py-1.5 pr-2 whitespace-nowrap tabular-nums text-primary-50/60">
                  {{ staffTotal.factor_equivalents.toFixed(2) }}
                </td>
                <td />
                <td class="py-1.5 pr-2 text-right whitespace-nowrap tabular-nums text-primary-50">
                  {{ fmt.eur2(staffTotal.eur) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <TripCycleYearStrip
          v-if="staffTotal"
          :label="t('proposal.details.operation.staff.strip')"
          :per-trip="staffTotal.eur"
          :operating-days="operatingDaysPerYear ?? 0"
          :unit="{
            name: t('proposal.details.operation.staff.paidUnit'),
            perTrip: staffTotal.paid_hours,
          }"
        />
      </div>
    </div>
  </DetailPanel>
</template>

<style scoped>
.selected-composition {
  border-color: color-mix(in srgb, #fbbf24 35%, transparent);
}

.receipt {
  border-top: 1px solid color-mix(in srgb, var(--color-primary-50) 10%, transparent);
  padding-top: 12px;
}

.kpi {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--color-primary-50);
}

.kpi-aside {
  font-size: 12px;
  font-weight: 400;
  color: color-mix(in srgb, var(--color-primary-50) 55%, transparent);
}

.kpi-label {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: color-mix(in srgb, var(--color-primary-50) 75%, transparent);
}

.facts {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 2px 10px;
  margin-top: 6px;
  font-size: 11px;
}

.facts dt {
  color: color-mix(in srgb, var(--color-primary-50) 55%, transparent);
}

.facts dd {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-primary-50) 85%, transparent);
}
</style>
