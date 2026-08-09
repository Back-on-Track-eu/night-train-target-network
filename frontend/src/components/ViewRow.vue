<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Select from 'primevue/select'
import RouteSectionSlider from '@/components/RouteSectionSlider.vue'
import { selectPillPt } from '@/lib/selectPillPt'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import type {
  Breakdown,
  EvaluationViews,
  FilteredCell,
  FilterValue,
  MapScope,
  Normalisations,
  NormKey,
  ViewKey,
} from '@/types/api'
import { NORM_KEYS, VIEW_KEYS } from '@/types/api'

// The "cube": view (grouping) × drill-down keys (sel1/sel2) × normalisation
// (unit) × class (CALC 0.9.9: every normalisation is class-keyed) — pick one
// value on each axis and you land on exactly one Breakdown, emitted up via
// update:breakdown. The geographic scope implied by the same selection is
// emitted via scopeChange so the map can dim the unselected part.
const props = defineProps<{
  views: EvaluationViews
  // Ordered stops (outbound) backing the "route section" slider.
  stops: { stop_id: string; name: string }[]
}>()
const emit = defineEmits<{
  scopeChange: [scope: MapScope]
  'update:breakdown': [breakdown: Breakdown | null]
}>()

const { t, te } = useI18n()
const { countryName } = useLocaleFormat()

const view = ref<ViewKey>('route')
const normalisation = ref<NormKey>('per_year')
// Class selection — active for EVERY normalisation since CALC 0.9.9; options
// come from the landed cell's own keys ("all" + class_mains).
const classSel = ref<string>('all')
const sel1 = ref('all')
const sel2 = ref('all')

// "By route section" uses a two-thumb range slider over the ordered stops
// ([originIndex, destIndex] into props.stops) to pick a physical section, which
// lands directly on the backend's per_trip_pair_per_section cell for that
// origin→destination — no client-side aggregation.
const sectionRange = ref<number[]>([0, 0])
const isRouteSectionView = computed(() => view.value === 'per_trip_pair_per_section')
const sectionOrigin = computed(() => props.stops[sectionRange.value[0]])
const sectionDestination = computed(() => props.stops[sectionRange.value[1]])

// A-B routes have a single trip pair, which makes "By trip pair" redundant with
// the whole-route view — hide it until there are ≥2 pairs (e.g. Y-routes).
const tripPairCount = computed(
  () => Object.keys(props.views.per_trip_pair.data).filter((k) => k !== 'all').length,
)
const visibleViewKeys = computed<ViewKey[]>(() =>
  VIEW_KEYS.filter((v) => v !== 'per_trip_pair' || tripPairCount.value > 1),
)
const viewOptions = computed(() =>
  visibleViewKeys.value.map((v) => ({ value: v, label: t(`proposal.evaluation.views.${v}`) })),
)
watch(
  visibleViewKeys,
  (keys) => {
    if (!keys.includes(view.value)) view.value = 'route'
  },
  { immediate: true },
)
const normOptions = computed(() =>
  NORM_KEYS.map((n) => ({ value: n, label: t(`proposal.evaluation.norms.${n}`) })),
)

// --- Drill-down levels, discovered generically from the payload -----------
// Dimension names and human-readable option labels both come from each data
// point's backend-provided "filter" dict — no per-view frontend logic, so a
// new view/dimension on the backend needs no change here.
interface DrillOption {
  key: string
  label: string
}
interface DrillLevel {
  dim: string
  options: DrillOption[]
}

const MATRIX_VIEWS = [
  'per_trip_pair_per_country',
  'per_trip_pair_per_section',
  'per_trip_per_stop',
] as const
type MatrixViewKey = (typeof MATRIX_VIEWS)[number]

function isMatrixView(v: ViewKey): v is MatrixViewKey {
  return (MATRIX_VIEWS as readonly string[]).includes(v)
}

// "all" reads as a full self-describing label ("All countries"), so the
// dropdown needs no separate field label beside it. Non-"all" keys use the
// backend-provided human label.
function allLabel(dim: string): string {
  const key = `proposal.evaluation.filters.${dim}`
  return te(key) ? t(key) : t('proposal.evaluation.filters.default')
}

// Accommodation-class keys ("Seat", "Couchette", "Sleeper", "Capsule") arrive
// as English class_main values from the backend; translate them, falling back
// to the raw key when no translation exists.
function classLabel(key: string): string {
  const k = `proposal.evaluation.classes.${key}`
  return te(k) ? t(k) : key
}

// Compose (and localise) a drill-down option label from its backend filter
// value. Proper-noun dims (trip_pair, stop) arrive as ready strings; country
// codes and the translatable trip/OD/section parts are localised here.
function optionLabel(key: string, value: FilterValue | undefined, dim: string): string {
  if (key === 'all') return allLabel(dim)
  if (dim === 'country') return countryName(key)
  if (value && typeof value === 'object') {
    if ('direction' in value) {
      const dir = t(`proposal.evaluation.direction.${value.direction}`)
      return `${value.origin} → ${value.destination} (${dir})`
    }
    const cls =
      value.class_main === 'all'
        ? t('proposal.evaluation.classes.all')
        : classLabel(value.class_main)
    return `${value.origin} → ${value.destination} (${cls})`
  }
  return typeof value === 'string' ? value : key
}

const level1 = computed<DrillLevel | null>(() => {
  const v = view.value
  if (v === 'route') return null
  if (v === 'per_trip_pair') {
    const entries = Object.entries(props.views.per_trip_pair.data)
    if (entries.length === 0) return null
    const dim = Object.keys(entries[0][1].filter)[0] ?? 'trip_pair'
    return {
      dim,
      options: entries.map(([key, cell]) => ({
        key,
        label: optionLabel(key, cell.filter[dim], dim),
      })),
    }
  }
  const entries = Object.entries(props.views[v].data)
  if (entries.length === 0) return null
  const sample: FilteredCell | undefined = Object.values(entries[0][1])[0]
  const dim = sample ? (Object.keys(sample.filter)[0] ?? '') : ''
  return {
    dim,
    options: entries.map(([key, inner]) => {
      const cell: FilteredCell | undefined = Object.values(inner)[0]
      return { key, label: optionLabel(key, cell?.filter[dim], dim) }
    }),
  }
})

const level2 = computed<DrillLevel | null>(() => {
  const v = view.value
  if (!isMatrixView(v)) return null
  const inner = props.views[v].data[sel1.value]
  if (!inner) return null
  const entries = Object.entries(inner)
  if (entries.length === 0) return null
  const dims = Object.keys(entries[0][1].filter)
  const dim = dims[1] ?? dims[0] ?? ''
  return {
    dim,
    options: entries.map(([key, cell]) => ({
      key,
      label: optionLabel(key, cell.filter[dim], dim),
    })),
  }
})

function pickDefault(level: DrillLevel | null): string {
  if (!level) return 'all'
  return level.options.some((o) => o.key === 'all') ? 'all' : (level.options[0]?.key ?? 'all')
}

watch(view, () => {
  sel1.value = pickDefault(level1.value)
  sel2.value = pickDefault(level2.value)
})
watch(sel1, () => {
  sel2.value = pickDefault(level2.value)
})

// Initialise / reset the section slider to the whole route whenever the stop
// list loads or changes — so sectionRange always holds valid indices,
// independent of which view is active.
watch(
  () => props.stops,
  (s) => {
    if (s.length > 0) sectionRange.value = [0, s.length - 1]
  },
  { immediate: true },
)

// A drill level is only worth a dropdown when it offers a real choice — more
// than one non-"all" option. For a single trip pair, the trip-pair level
// collapses to "all" silently.
function hasChoice(level: DrillLevel | null): boolean {
  return !!level && level.options.filter((o) => o.key !== 'all').length > 1
}
const showLevel1 = computed(() => hasChoice(level1.value))
const showLevel2 = computed(() => hasChoice(level2.value))

// Emit the current geographic scope so the map can dim the unselected part.
const mapScope = computed<MapScope>(() => {
  if (view.value === 'per_trip_pair_per_country' && sel2.value !== 'all') {
    return { kind: 'country', country: sel2.value }
  }
  if (view.value === 'per_trip_pair_per_section') {
    const origin = sectionOrigin.value?.stop_id
    const destination = sectionDestination.value?.stop_id
    if (origin && destination && origin !== destination) {
      return { kind: 'od', originStopId: origin, destinationStopId: destination }
    }
  }
  if (view.value === 'per_trip_per_stop' && sel2.value !== 'all') {
    return { kind: 'stop', stopId: sel2.value }
  }
  return { kind: 'all' }
})
watch(mapScope, (s) => emit('scopeChange', s), { immediate: true })

// --- Resolve the landed Breakdown ------------------------------------------
const currentNorms = computed<Normalisations | null>(() => {
  const v = view.value
  if (v === 'route') return props.views.route.data
  if (v === 'per_trip_pair') {
    return props.views.per_trip_pair.data[sel1.value]?.values ?? null
  }
  if (v === 'per_trip_pair_per_section') {
    // The slider picks a physical section; land on the backend's pre-built,
    // section-normalised "__all" cell for that origin→destination. Its values
    // are already class-keyed (per-unit norms divided by the section's own
    // physics), so no client-side aggregation is needed.
    const pairData = props.views.per_trip_pair_per_section.data[sel1.value]
    const origin = sectionOrigin.value?.stop_id
    const destination = sectionDestination.value?.stop_id
    if (!pairData || !origin || !destination || origin === destination) return null
    return pairData[`${origin}__${destination}__all`]?.values ?? null
  }
  return props.views[v].data[sel1.value]?.[sel2.value]?.values ?? null
})

// Classes available in the landed cell for the selected normalisation —
// "all" pinned first, class_mains sorted after it. Options carry labels so
// "all" can render as a translated "All classes".
const classOptions = computed(() => {
  const dict = currentNorms.value?.[normalisation.value] ?? null
  if (!dict) return []
  const keys = Object.keys(dict).sort()
  const ordered = keys.includes('all') ? ['all', ...keys.filter((k) => k !== 'all')] : keys
  return ordered.map((k) => ({
    value: k,
    label: k === 'all' ? t('proposal.evaluation.classes.all') : classLabel(k),
  }))
})
watch(
  classOptions,
  (opts) => {
    const keys = opts.map((o) => o.value)
    if (!keys.includes(classSel.value)) classSel.value = keys[0] ?? 'all'
  },
  { immediate: true },
)

const currentBreakdown = computed<Breakdown | null>(() => {
  const norms = currentNorms.value
  if (!norms) return null
  const dict = norms[normalisation.value]
  if (!dict) return null
  return dict[classSel.value] ?? null
})
watch(currentBreakdown, (b) => emit('update:breakdown', b), { immediate: true })
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- Cube controls: view tabs (left) · drill-downs · class · normalisation. -->
    <div class="mt-6 flex flex-wrap items-center gap-3">
      <div class="flex overflow-hidden rounded-full border border-primary-50/20">
        <button
          v-for="opt in viewOptions"
          :key="opt.value"
          class="cursor-pointer px-3 py-1.5 text-sm leading-none transition"
          :class="
            view === opt.value
              ? 'bg-primary-50/20 text-primary-50'
              : 'text-primary-50/60 hover:bg-primary-50/10'
          "
          @click="view = opt.value"
        >
          {{ opt.label }}
        </button>
      </div>

      <Select
        v-if="showLevel1 && level1"
        v-model="sel1"
        :options="level1.options"
        option-value="key"
        option-label="label"
        :unstyled="true"
        :pt="selectPillPt"
      />
      <Select
        v-if="showLevel2 && level2 && !isRouteSectionView"
        v-model="sel2"
        :options="level2.options"
        option-value="key"
        option-label="label"
        :unstyled="true"
        :pt="selectPillPt"
      />

      <div class="ml-auto flex items-center gap-2">
        <!-- Class axis (CALC 0.9.9) — active for every normalisation -->
        <Select
          v-if="classOptions.length > 1"
          v-model="classSel"
          :options="classOptions"
          option-value="value"
          option-label="label"
          :unstyled="true"
          :pt="selectPillPt"
        />
        <Select
          v-model="normalisation"
          :options="normOptions"
          option-value="value"
          option-label="label"
          :unstyled="true"
          :pt="selectPillPt"
        />
      </div>
    </div>

    <!-- Route section: two-thumb slider with per-stop labels, on its own row -->
    <RouteSectionSlider
      v-if="isRouteSectionView && stops.length > 1"
      v-model="sectionRange"
      :stops="stops"
      class="w-4/5 self-center"
    />
  </div>
</template>
