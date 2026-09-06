<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Popover from 'primevue/popover'
import AppIcon from '@/components/AppIcon.vue'
import CompositionFormation from '@/components/CompositionFormation.vue'
import { mdiSilverwareForkKnife, mdiChevronDown, mdiChevronRight } from '@mdi/js'
import { useStore } from '@/stores/store'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import {
  AMENITY_ICONS,
  buildFormation,
  classColor,
  classIcon,
  describeField,
} from '@/lib/compositionFormation'
import type { Composition } from '@/types/api'

// Detail overlay for the composition card: the formation drawn as a platform
// display, the hovered coach's type data, and the per-class and unit-cost
// figures. Everything that is a model input rather than a headline figure sits
// behind the details toggle. Opened from CompositionPanel's info icon through
// the exposed handlers — the same hover-intent pattern the cost-factor popover
// uses.
const props = defineProps<{ composition: Composition }>()

const { t } = useI18n()
const store = useStore()
const { locale, formatInt } = useLocaleFormat()
const { formatEur, formatShare } = useEvaluationFormat()

const popover = ref<InstanceType<typeof Popover> | null>(null)
const isOpen = ref(false)
let closeTimer: ReturnType<typeof setTimeout> | null = null

function cancelClose() {
  if (closeTimer !== null) {
    clearTimeout(closeTimer)
    closeTimer = null
  }
}

function open(event: Event) {
  cancelClose()
  if (isOpen.value) return
  popover.value?.show(event)
}

function scheduleClose() {
  cancelClose()
  closeTimer = setTimeout(() => popover.value?.hide(), 150)
}

defineExpose({ open, scheduleClose, cancelClose })

// --- Formation -------------------------------------------------------------

const catalog = computed(() => store.compositionCatalog)

const formation = computed(() =>
  buildFormation(props.composition, catalog.value.coach_types, catalog.value.classes),
)

const selectedPosition = ref<number | null>(null)
const selectedCoach = computed(
  () => formation.value.coaches.find((c) => c.position === selectedPosition.value) ?? null,
)

const showDetails = ref(false)

// A pinned coach from the previous composition would point at a position the
// new formation may not have.
watch(
  () => props.composition.composition_id,
  () => (selectedPosition.value = null),
)

const operator = computed(
  () =>
    catalog.value.operators.find((o) => o.operator_id === props.composition.operator_id) ?? null,
)

const decimal = (value: number, digits = 2) =>
  value.toLocaleString(locale.value, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })

const help = (section: string, field: string) =>
  describeField(catalog.value.descriptions, section, field)

// --- Headline subline ------------------------------------------------------

// The physical facts, condensed into one line under the name — they describe
// the train rather than the model, so they never need a tooltip or a row.
const subline = computed(() => {
  const r = props.composition.routing
  const loco = operator.value?.locos[0]
  const parts = [
    t('proposal.composition.strategy.' + props.composition.material_strategy),
    `${formatInt(props.composition.coaches.count)} ${t('proposal.composition.coaches')}`,
    `${decimal(r.total_length_m, 1)} m`,
    `${formatInt(r.total_weight_t)} t`,
    loco ? `${formatInt(r.n_locos)} × ${loco.loco_type_id}` : null,
    `${formatInt(r.max_speed_kmh)} km/h`,
    r.hsr_allowed ? t('proposal.composition.hsrAllowed') : null,
    `${formatInt(props.composition.capacity.total_places)} ${t('proposal.composition.places')}`,
  ]
  return parts.filter((part) => part !== null)
})

const compositionAmenities = computed(() =>
  AMENITY_ICONS.map(([flag, path, key]) => ({
    key,
    path,
    label: t(`proposal.composition.equipment.${key}`),
    present: props.composition.equipment[flag],
  })),
)

const coachAmenities = computed(() =>
  AMENITY_ICONS.filter(([flag]) => selectedCoach.value?.type.equipment[flag]).map(
    ([, path, key]) => ({
      key,
      path,
      label: t(`proposal.composition.equipment.${key}`),
    }),
  ),
)

// --- By class: what the train sells, and what it costs to carry ------------

const byClass = computed(() => {
  const capacity = props.composition.capacity
  const allocation = props.composition.cost_allocation.by_class_main
  return Object.entries(capacity.by_class)
    .map(([classMain, entry]) => ({
      classMain,
      label: t(`proposal.evaluation.classes.${classMain}`),
      color: classColor(classMain),
      icon: classIcon(classMain),
      places: entry.places,
      capacityShare: capacity.total_places > 0 ? entry.places / capacity.total_places : 0,
      costShare: allocation[classMain] ?? 0,
    }))
    .sort((a, b) => b.places - a.places)
})

// --- Indicative unit costs -------------------------------------------------
// Bars are scaled against the dearest composition in the catalogue, so the
// figure lands somewhere the reader can judge rather than floating alone.

const kpiScale = computed(() => {
  const kpis = store.compositions
    .map((c) => c.indicative?.kpis)
    .filter((k) => k !== undefined && k !== null)
  return {
    perTrainKm: Math.max(...kpis.map((k) => k.cost_eur_per_train_km), 0),
    perPlaceKm: Math.max(...kpis.map((k) => k.cost_ct_per_place_km), 0),
  }
})

const unitCosts = computed(() => {
  const kpis = props.composition.indicative?.kpis
  if (!kpis) return []
  return [
    {
      key: 'perTrainKm',
      label: t('proposal.composition.kpi.perTrainKm'),
      value: `${formatEur(kpis.cost_eur_per_train_km)}`,
      share:
        kpiScale.value.perTrainKm > 0 ? kpis.cost_eur_per_train_km / kpiScale.value.perTrainKm : 0,
    },
    {
      key: 'perPlaceKm',
      label: t('proposal.composition.kpi.perPlaceKm'),
      value: `${decimal(kpis.cost_ct_per_place_km)} ct`,
      share:
        kpiScale.value.perPlaceKm > 0 ? kpis.cost_ct_per_place_km / kpiScale.value.perPlaceKm : 0,
    },
  ]
})

// --- Details: the model inputs behind those figures ------------------------

interface FactRow {
  key: string
  label: string
  value: string
  help?: string
}

interface FactSection {
  key: string
  title: string
  rows: FactRow[]
}

const f = (key: string) => t(`proposal.composition.fields.${key}`)

const crewSection = computed<FactSection>(() => {
  const staff = props.composition.staff
  return {
    key: 'crew',
    title: t('proposal.composition.sections.crew'),
    rows: [
      {
        key: 'drivers',
        label: f('drivers'),
        value: decimal(staff.driver_factor, 1),
        help: help('staff', 'driver_factor'),
      },
      {
        key: 'attendants',
        label: f('attendants'),
        value: decimal(staff.crew_factor_coaches, 2),
        help: help('staff', 'crew_factor_coaches'),
      },
      {
        key: 'manager',
        label: f('trainManager'),
        value: decimal(staff.zugchef_crew_factor, 2),
        help: help('staff', 'zugchef_crew_factor'),
      },
      {
        key: 'crew_total',
        label: f('crewTotal'),
        value: decimal(staff.crew_factor_total, 2),
        help: help('staff', 'crew_factor_total'),
      },
      {
        key: 'staff_rate',
        label: f('staffRate'),
        value: `${formatEur(staff.costs_per_hour.total_staff_eur_h)}/h`,
        help: help('staff', 'costs_per_hour'),
      },
    ],
  }
})

const costSection = computed<FactSection>(() => {
  const fixed = props.composition.fixed_costs
  return {
    key: 'cost',
    title: t('proposal.composition.sections.cost'),
    rows: [
      {
        key: 'purchase',
        label: f('purchase'),
        // Served per coach; the whole train is the figure worth reading.
        value: formatEur(fixed.purchase_coach_eur * props.composition.coaches.count),
        help: help('fixed_costs', 'purchase_coach_eur'),
      },
      {
        key: 'availability',
        label: f('availability'),
        value: formatShare(fixed.coach_avail_per),
        help: help('fixed_costs', 'coach_avail_per'),
      },
      {
        key: 'amortisation',
        label: f('amortisation'),
        value: `${formatInt(fixed.coach_amort_years)} a`,
        help: help('fixed_costs', 'coach_amort_years'),
      },
      {
        key: 'cleaning',
        label: f('cleaning'),
        value: `${formatEur(fixed.cleaning_services_eur_day)}/d`,
        help: help('fixed_costs', 'cleaning_services_eur_day'),
      },
      {
        key: 'maintenance',
        label: f('maintenance'),
        value: `${formatEur(props.composition.variable_km.coach_maint_eur_km)}/km`,
        help: help('variable_km', 'coach_maint_eur_km'),
      },
    ],
  }
})

// What one place costs in train, shown under the unit costs: the same
// per-place reading, in metres and tonnes rather than euros.
const spaceRows = computed<FactRow[]>(() => {
  const capacity = props.composition.capacity
  return [
    {
      key: 'length_per_place',
      label: f('densityLength'),
      value: `${decimal(capacity.avg_density_length_m_per_place)} m`,
      help: help('capacity', 'avg_density_length_m_per_place'),
    },
    {
      key: 'weight_per_place',
      label: f('densityWeight'),
      value: `${decimal(capacity.avg_density_weight_t_per_place)} t`,
      help: help('capacity', 'avg_density_weight_t_per_place'),
    },
  ]
})

const detailSections = computed<FactSection[]>(() => [crewSection.value, costSection.value])

const sources = computed(() =>
  props.composition.source_ids
    .map((id) => catalog.value.sources[String(id)])
    .filter((source) => source !== undefined),
)
</script>

<template>
  <Popover
    ref="popover"
    :pt="{
      root: {
        class: 'composition-detail-overlay !rounded-xl !shadow-2xl',
        onMouseenter: cancelClose,
        onMouseleave: scheduleClose,
      },
      content: { class: '!p-5 !bg-transparent' },
    }"
    @show="isOpen = true"
    @hide="isOpen = false"
  >
    <div class="flex w-[46rem] max-w-full flex-col gap-4 text-left">
      <!-- Headline: name, what it is, and the train itself in one subline -->
      <div class="flex flex-col gap-1">
        <div class="flex flex-wrap items-baseline gap-x-3">
          <h3 class="text-lg font-semibold text-primary-50">{{ composition.composition_id }}</h3>
          <span class="text-sm text-primary-50/60">{{ composition.description }}</span>
        </div>
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-primary-50/50">
          <template v-for="(part, i) in subline" :key="part">
            <span v-if="i > 0" class="text-primary-50/25">·</span>
            <span>{{ part }}</span>
          </template>
          <span class="ml-1 flex items-center gap-1.5">
            <AppIcon
              v-for="amenity in compositionAmenities"
              :key="amenity.key"
              :path="amenity.path"
              :size="14"
              :class="amenity.present ? 'text-primary-50/70' : 'text-primary-50/20'"
            />
          </span>
          <span class="flex items-center gap-1" :title="help('equipment', 'food_and_beverages')">
            <AppIcon :path="mdiSilverwareForkKnife" :size="14" />
            {{ composition.equipment.food_and_beverages }}
          </span>
        </div>
      </div>

      <!-- Formation: the platform display, with the pointed-at coach below it -->
      <div class="flex flex-col gap-2 rounded-xl bg-primary-50/5 px-4 pt-3 pb-2">
        <CompositionFormation
          :formation="formation"
          :selected="selectedPosition"
          @select="selectedPosition = $event"
        />

        <div
          class="flex min-h-9 flex-wrap items-center gap-x-4 gap-y-1 border-t border-primary-50/10 pt-2 text-xs"
        >
          <template v-if="selectedCoach">
            <span class="font-semibold text-primary-50">{{ selectedCoach.coachTypeId }}</span>
            <span class="text-primary-50/50">
              {{
                t('proposal.composition.coachPosition', {
                  position: selectedCoach.position,
                  count: composition.coaches.count,
                })
              }}
            </span>
            <span class="text-primary-50/70 tabular-nums">
              {{ decimal(selectedCoach.type.length_m, 1) }} m ·
              {{ decimal(selectedCoach.type.weight_gross_t, 1) }} t ·
              {{ decimal(selectedCoach.type.crew_factor, 2) }}
              {{ t('proposal.composition.fields.crewFactor') }}
            </span>
            <span
              v-for="section in selectedCoach.sections"
              :key="section.label"
              class="flex items-center gap-1.5 text-primary-50/70"
            >
              <AppIcon
                v-if="classIcon(section.classMain)"
                :path="classIcon(section.classMain)!"
                :size="14"
                :color="classColor(section.classMain)"
              />
              {{ section.places }} × {{ section.label }}
            </span>
            <span v-if="selectedCoach.isService" class="text-primary-50/50">
              {{ t('proposal.composition.serviceCoach') }}
            </span>
            <span class="ml-auto flex items-center gap-1.5 text-primary-50/60">
              <AppIcon
                v-for="amenity in coachAmenities"
                :key="amenity.key"
                :path="amenity.path"
                :size="14"
              />
            </span>
          </template>
          <span v-else class="text-primary-50/40">{{ t('proposal.composition.coachHint') }}</span>
        </div>
      </div>

      <!-- Places sold per class against the cost share each class carries -->
      <div class="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
        <section class="flex flex-col gap-1">
          <h4 class="text-[11px] font-semibold tracking-wide text-primary-50 uppercase">
            {{ t('proposal.composition.byClass.title') }}
          </h4>
          <!-- Column captions sit on the row grid so each one lands over the
               figure it names — the two bars are otherwise indistinguishable. -->
          <div
            class="grid grid-cols-[1fr_2.5rem_1fr_1fr] gap-x-3 text-[11px] tracking-wide text-primary-50/40 uppercase"
          >
            <span />
            <span class="text-right">{{ t('proposal.composition.byClass.places') }}</span>
            <span>{{ t('proposal.composition.byClass.capacity') }}</span>
            <span>{{ t('proposal.composition.byClass.cost') }}</span>
          </div>
          <div
            v-for="row in byClass"
            :key="row.classMain"
            class="grid grid-cols-[1fr_2.5rem_1fr_1fr] items-center gap-x-3 py-0.5 text-sm"
          >
            <span class="flex items-center gap-1.5 text-primary-50/60">
              <AppIcon
                v-if="row.icon"
                :path="row.icon"
                :size="16"
                :color="row.color"
                class="shrink-0"
              />
              {{ row.label }}
            </span>
            <span class="text-right text-primary-50 tabular-nums">{{ formatInt(row.places) }}</span>
            <span class="flex items-center gap-1.5">
              <span class="h-1.5 flex-1 rounded-full bg-primary-50/10">
                <span
                  class="block h-full rounded-full"
                  :style="{ width: `${row.capacityShare * 100}%`, backgroundColor: row.color }"
                />
              </span>
              <span class="w-8 text-right text-xs text-primary-50/50 tabular-nums">
                {{ formatShare(row.capacityShare) }}
              </span>
            </span>
            <span class="flex items-center gap-1.5">
              <span class="h-1.5 flex-1 rounded-full bg-primary-50/10">
                <span
                  class="block h-full rounded-full"
                  :style="{ width: `${row.costShare * 100}%`, backgroundColor: row.color }"
                />
              </span>
              <span class="w-8 text-right text-xs text-primary-50/50 tabular-nums">
                {{ formatShare(row.costShare) }}
              </span>
            </span>
          </div>
        </section>

        <section v-if="unitCosts.length" class="flex flex-col gap-1">
          <h4 class="text-[11px] font-semibold tracking-wide text-primary-50 uppercase">
            {{ t('proposal.composition.kpi.title') }}
          </h4>
          <div v-for="kpi in unitCosts" :key="kpi.key" class="flex flex-col gap-1 py-0.5">
            <div class="flex items-baseline justify-between gap-3 text-sm">
              <span class="text-primary-50/60">{{ kpi.label }}</span>
              <span class="font-semibold text-primary-50 tabular-nums">{{ kpi.value }}</span>
            </div>
            <span class="h-1.5 rounded-full bg-primary-50/10">
              <span
                class="block h-full rounded-full bg-primary-500"
                :style="{ width: `${kpi.share * 100}%` }"
              />
            </span>
          </div>
          <div
            v-for="row in spaceRows"
            :key="row.key"
            class="flex items-baseline justify-between gap-3 pt-0.5 text-sm"
            :title="row.help"
          >
            <span class="text-primary-50/60">{{ row.label }}</span>
            <span class="text-primary-50 tabular-nums">{{ row.value }}</span>
          </div>
          <p class="text-[11px] text-primary-50/40">{{ t('proposal.composition.kpi.caption') }}</p>
        </section>
      </div>

      <!-- Model inputs — folded away until asked for -->
      <div class="border-t border-primary-50/10 pt-2">
        <button
          type="button"
          class="flex cursor-pointer items-center gap-1 text-xs text-primary-50/50 transition hover:text-primary-50"
          :aria-expanded="showDetails"
          @click="showDetails = !showDetails"
        >
          <AppIcon :path="showDetails ? mdiChevronDown : mdiChevronRight" :size="16" />
          {{ t('proposal.composition.moreDetails') }}
        </button>

        <div v-if="showDetails" class="mt-3 flex flex-col gap-4">
          <div class="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-3">
            <section v-for="section in detailSections" :key="section.key" class="flex flex-col">
              <h4 class="text-[11px] font-semibold tracking-wide text-primary-50 uppercase">
                {{ section.title }}
              </h4>
              <div
                v-for="row in section.rows"
                :key="row.key"
                class="flex items-baseline justify-between gap-3 border-b border-primary-50/10 py-1 text-sm last:border-b-0"
                :title="row.help"
              >
                <span class="text-primary-50/60">{{ row.label }}</span>
                <span class="text-right whitespace-nowrap text-primary-50 tabular-nums">
                  {{ row.value }}
                </span>
              </div>
            </section>
          </div>

          <p v-if="sources.length" class="text-xs text-primary-50/40">
            {{ t('proposal.composition.sources') }}:
            <span v-for="(source, i) in sources" :key="source.source_id">
              <template v-if="i > 0">; </template>
              <a
                v-if="source.source_url"
                :href="source.source_url"
                target="_blank"
                rel="noopener"
                class="underline hover:text-primary-50"
              >
                {{ source.source_description || source.source_url }}
              </a>
              <template v-else>{{ source.source_description }}</template>
            </span>
          </p>
        </div>
      </div>
    </div>
  </Popover>
</template>

<style>
.composition-detail-overlay {
  background: #23263d !important;
  border: 1px solid color-mix(in srgb, var(--p-primary-50) 20%, transparent) !important;
  max-width: calc(100vw - 2rem);
}
</style>
