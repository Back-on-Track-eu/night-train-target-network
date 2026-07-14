<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import Select from 'primevue/select'
import Popover from 'primevue/popover'
import AppIcon from '@/components/AppIcon.vue'
import RouteSectionSlider from '@/components/RouteSectionSlider.vue'
import { mdiChevronDown, mdiChevronRight, mdiInformationOutline } from '@mdi/js'
import { resolveFactorRates, type RateRow } from '@/lib/costFactorRates'
import type {
  Breakdown,
  EvaluationResponse,
  FilteredCell,
  MapScope,
  Normalisations,
  NormKey,
  ViewKey,
} from '@/types/api'
import { NORM_KEYS, VIEW_KEYS } from '@/types/api'

const props = defineProps<{
  result: EvaluationResponse
  // Ordered stops (outbound) backing the "route section" slider.
  stops: { stop_id: string; name: string }[]
}>()
const emit = defineEmits<{ scopeChange: [scope: MapScope] }>()

const { t, te } = useI18n()

// --- Selection state: the three axes of the result cube -------------------
// view (grouping) × drill-down keys (sel1/sel2) × normalisation (unit)
// pick one value on each axis and you land on exactly one Breakdown.
const view = ref<ViewKey>('route')
const normalisation = ref<NormKey>('per_year')
const sel1 = ref('all')
const sel2 = ref('all')

// "By route section" replaces the OD dropdown with a two-thumb range slider
// over the ordered stops: [originIndex, destIndex] into props.stops.
const odRange = ref<number[]>([0, 0])
const isRouteSectionView = computed(() => view.value === 'per_trip_pair_per_od')
const sectionOrigin = computed(() => props.stops[odRange.value[0]])
const sectionDestination = computed(() => props.stops[odRange.value[1]])

// A-B routes have a single trip pair, which makes "By trip pair" redundant with
// the whole-route view — hide it until there are ≥2 pairs (e.g. Y-routes).
const tripPairCount = computed(
  () => Object.keys(props.result.views.per_trip_pair.data).filter((k) => k !== 'all').length,
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
  'per_trip_pair_per_od',
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

// Country dimension keys are ISO codes ("CZ"); show the full name instead.
const regionNames = new Intl.DisplayNames(['en'], { type: 'region' })
function countryName(code: string): string {
  try {
    return regionNames.of(code.toUpperCase()) ?? code
  } catch {
    return code
  }
}

function optionLabel(key: string, backendLabel: string | undefined, dim: string): string {
  if (key === 'all') return allLabel(dim)
  if (dim === 'country') return countryName(key)
  return backendLabel ?? key
}

const level1 = computed<DrillLevel | null>(() => {
  const v = view.value
  if (v === 'route') return null
  if (v === 'per_trip_pair') {
    const entries = Object.entries(props.result.views.per_trip_pair.data)
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
  const entries = Object.entries(props.result.views[v].data)
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
  const inner = props.result.views[v].data[sel1.value]
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
// list loads or changes — so odRange always holds valid indices, independent
// of which view is active.
watch(
  () => props.stops,
  (s) => {
    if (s.length > 0) odRange.value = [0, s.length - 1]
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
  if (view.value === 'per_trip_pair_per_od') {
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

// --- Route-section aggregation --------------------------------------------
// A section (origin→dest) has one OD cell per ticket class. Every normaliser's
// divisor is trip-pair-level (constant across classes — see views.py), so the
// section total is the class-wise sum of the already-normalised breakdowns.
function sumBreakdowns(bs: Breakdown[]): Breakdown {
  const acc: Breakdown = {
    cost: {
      operator: {
        variable: {
          driver_eur: 0,
          crew_eur: 0,
          coach_maintenance_eur: 0,
          loco_eur: 0,
          svc_stockings_eur: 0,
          var_overhead_eur: 0,
          total_eur: 0,
        },
        fixed: {
          coach_amortisation_eur: 0,
          financing_eur: 0,
          fix_overhead_eur: 0,
          cleaning_eur: 0,
          shunting_eur: 0,
          total_eur: 0,
        },
        total_eur: 0,
      },
      infrastructure: {
        tac_eur: 0,
        energy_eur: 0,
        station_charge_eur: 0,
        parking_eur: 0,
        total_eur: 0,
      },
      total_eur: 0,
    },
    revenue: { ticket_revenue_eur: 0, total_eur: 0 },
    margin: { ebit_margin_eur: 0, total_eur: 0 },
    total_cost_eur: 0,
    total_revenue_eur: 0,
    net_eur: 0,
  }
  for (const b of bs) {
    const av = acc.cost.operator.variable
    const bv = b.cost.operator.variable
    av.driver_eur += bv.driver_eur
    av.crew_eur += bv.crew_eur
    av.coach_maintenance_eur += bv.coach_maintenance_eur
    av.loco_eur += bv.loco_eur
    av.svc_stockings_eur += bv.svc_stockings_eur
    av.var_overhead_eur += bv.var_overhead_eur
    av.total_eur += bv.total_eur
    const af = acc.cost.operator.fixed
    const bf = b.cost.operator.fixed
    af.coach_amortisation_eur += bf.coach_amortisation_eur
    af.financing_eur += bf.financing_eur
    af.fix_overhead_eur += bf.fix_overhead_eur
    af.cleaning_eur += bf.cleaning_eur
    af.shunting_eur += bf.shunting_eur
    af.total_eur += bf.total_eur
    acc.cost.operator.total_eur += b.cost.operator.total_eur
    const ai = acc.cost.infrastructure
    const bi = b.cost.infrastructure
    ai.tac_eur += bi.tac_eur
    ai.energy_eur += bi.energy_eur
    ai.station_charge_eur += bi.station_charge_eur
    ai.parking_eur += bi.parking_eur
    ai.total_eur += bi.total_eur
    acc.cost.total_eur += b.cost.total_eur
    acc.revenue.ticket_revenue_eur += b.revenue.ticket_revenue_eur
    acc.revenue.total_eur += b.revenue.total_eur
    acc.margin.ebit_margin_eur += b.margin.ebit_margin_eur
    acc.margin.total_eur += b.margin.total_eur
    acc.total_cost_eur += b.total_cost_eur
    acc.total_revenue_eur += b.total_revenue_eur
    acc.net_eur += b.net_eur
  }
  return acc
}

function sumNorms(cells: Normalisations[]): Normalisations {
  const out = {} as Normalisations
  for (const nk of NORM_KEYS) out[nk] = sumBreakdowns(cells.map((c) => c[nk]))
  return out
}

// --- Resolve the landed Breakdown ------------------------------------------
const currentNorms = computed<Normalisations | null>(() => {
  const v = view.value
  if (v === 'route') return props.result.views.route.data
  if (v === 'per_trip_pair') {
    return props.result.views.per_trip_pair.data[sel1.value]?.values ?? null
  }
  if (v === 'per_trip_pair_per_od') {
    const pairData = props.result.views.per_trip_pair_per_od.data[sel1.value]
    const origin = sectionOrigin.value?.stop_id
    const destination = sectionDestination.value?.stop_id
    if (!pairData || !origin || !destination || origin === destination) return null
    const prefix = `${origin}__${destination}__`
    const cells = Object.entries(pairData)
      .filter(([k]) => k.startsWith(prefix))
      .map(([, cell]) => cell.values)
    return cells.length ? sumNorms(cells) : null
  }
  return props.result.views[v].data[sel1.value]?.[sel2.value]?.values ?? null
})

const currentBreakdown = computed<Breakdown | null>(
  () => currentNorms.value?.[normalisation.value] ?? null,
)

// --- Cost tree: hierarchical node spec, flattened for rendering ------------
interface CostNode {
  key: string
  label: string
  value: number
  children?: CostNode[]
}

const costTree = computed<CostNode[]>(() => {
  const b = currentBreakdown.value
  if (!b) return []
  const f = (k: string) => t(`proposal.evaluation.fields.${k}`)
  const g = (k: string) => t(`proposal.evaluation.groups.${k}`)
  const v = b.cost.operator.variable
  const x = b.cost.operator.fixed
  const i = b.cost.infrastructure
  return [
    {
      key: 'operator',
      label: g('operator'),
      value: b.cost.operator.total_eur,
      children: [
        {
          key: 'variable',
          label: g('variable'),
          value: v.total_eur,
          children: [
            { key: 'driver', label: f('driver'), value: v.driver_eur },
            { key: 'crew', label: f('crew'), value: v.crew_eur },
            {
              key: 'coach_maintenance',
              label: f('coach_maintenance'),
              value: v.coach_maintenance_eur,
            },
            { key: 'loco', label: f('loco'), value: v.loco_eur },
            { key: 'svc_stockings', label: f('svc_stockings'), value: v.svc_stockings_eur },
            { key: 'var_overhead', label: f('var_overhead'), value: v.var_overhead_eur },
          ],
        },
        {
          key: 'fixed',
          label: g('fixed'),
          value: x.total_eur,
          children: [
            {
              key: 'coach_amortisation',
              label: f('coach_amortisation'),
              value: x.coach_amortisation_eur,
            },
            { key: 'financing', label: f('financing'), value: x.financing_eur },
            { key: 'fix_overhead', label: f('fix_overhead'), value: x.fix_overhead_eur },
            { key: 'cleaning', label: f('cleaning'), value: x.cleaning_eur },
            { key: 'shunting', label: f('shunting'), value: x.shunting_eur },
          ],
        },
      ],
    },
    {
      key: 'infrastructure',
      label: g('infrastructure'),
      value: i.total_eur,
      children: [
        { key: 'tac', label: f('tac'), value: i.tac_eur },
        { key: 'energy', label: f('energy'), value: i.energy_eur },
        { key: 'station_charge', label: f('station_charge'), value: i.station_charge_eur },
        { key: 'parking', label: f('parking'), value: i.parking_eur },
      ],
    },
  ]
})

const expanded = ref(new Set<string>(['operator', 'infrastructure']))

function toggleExpand(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

interface CostRow {
  key: string
  label: string
  value: number
  depth: number
  hasChildren: boolean
  isExpanded: boolean
  share: number | null
}

const costRows = computed<CostRow[]>(() => {
  const total = currentBreakdown.value?.cost.total_eur ?? 0
  const rows: CostRow[] = []
  const visit = (nodes: CostNode[], depth: number) => {
    for (const n of nodes) {
      const isExpanded = expanded.value.has(n.key)
      rows.push({
        key: n.key,
        label: n.label,
        value: n.value,
        depth,
        hasChildren: (n.children?.length ?? 0) > 0,
        isExpanded,
        share: total !== 0 ? n.value / total : null,
      })
      if (n.children && isExpanded) visit(n.children, depth + 1)
    }
  }
  visit(costTree.value, 0)
  return rows
})

// --- Cost-factor detail popover --------------------------------------------
// A tree node's key maps to its formula/field key by appending "_eur"
// (driver → driver_eur); the info icon shows only where a formula exists.
const formulas = computed(() => props.result.models.evaluation.formulas)
const formulaKey = (nodeKey: string) => `${nodeKey}_eur`
function hasInfo(nodeKey: string): boolean {
  return formulaKey(nodeKey) in formulas.value
}

const infoPopover = ref<InstanceType<typeof Popover> | null>(null)
const activeKey = ref<string | null>(null)
// Key whose popover is currently shown — lets us skip a redundant show()
// (and the flicker it causes) when the cursor re-enters the same icon.
const openKey = ref<string | null>(null)
let closeTimer: ReturnType<typeof setTimeout> | null = null

function cancelClose() {
  if (closeTimer !== null) {
    clearTimeout(closeTimer)
    closeTimer = null
  }
}

// Hover-intent: open on icon hover, keep open while the cursor is over the
// popover, and close only after a short delay once it has left both — so
// moving from the icon into the popover doesn't flicker-close it.
function openInfo(nodeKey: string, event: Event) {
  cancelClose()
  if (openKey.value === nodeKey) return
  activeKey.value = nodeKey
  infoPopover.value?.show(event)
}

function scheduleClose() {
  cancelClose()
  closeTimer = setTimeout(() => infoPopover.value?.hide(), 150)
}

function onInfoShow() {
  openKey.value = activeKey.value
}
function onInfoHide() {
  openKey.value = null
}

const activeFactor = computed(() => {
  const key = activeKey.value
  if (!key) return null
  const formula = formulas.value[formulaKey(key)]
  if (!formula) return null
  return {
    title: t(`proposal.evaluation.fields.${key}`),
    description: formula.description,
    // Inline layout + \displaystyle so the box hugs the formula's natural
    // width (displayMode would stretch it to full width and centre it).
    latexHtml: katex.renderToString(`\\displaystyle ${formula.latex}`, {
      throwOnError: false,
      displayMode: false,
    }),
    rates: resolveFactorRates(formulaKey(key), props.result.input, props.stops),
  }
})

const fmtRate = new Intl.NumberFormat('en', { maximumFractionDigits: 4 })

// Quota fields are stored as fractions (0.1) but described in "%" — render
// them as a percentage for readability; other units are shown verbatim.
function formatRateValue(row: RateRow): string {
  const value = row.unit.startsWith('%') ? row.value * 100 : row.value
  return fmtRate.format(value)
}

// --- Formatting -------------------------------------------------------------
const fmtCompact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 })
const fmtInt = new Intl.NumberFormat('en', { maximumFractionDigits: 0 })
const fmtSmall = new Intl.NumberFormat('en', { maximumSignificantDigits: 3 })
const fmtPct = new Intl.NumberFormat('en', { style: 'percent', maximumFractionDigits: 1 })

function formatEur(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 100_000) return `${fmtCompact.format(value)} €`
  if (abs >= 100) return `${fmtInt.format(value)} €`
  return `${fmtSmall.format(value)} €`
}

function formatShare(share: number | null): string {
  return share === null ? '' : fmtPct.format(share)
}

// --- Raw JSON fallback (lazily stringified, only when opened) --------------
const rawOpen = ref(false)
const rawJson = computed(() => (rawOpen.value ? JSON.stringify(props.result, null, 2) : ''))

function onRawToggle(event: Event) {
  rawOpen.value = (event.target as HTMLDetailsElement).open
}

// Shared pill styling for the unstyled Selects — same pass-through classes as
// the trip selector in ProposalViewport.vue.
const selectPt = {
  root: {
    class:
      'flex cursor-pointer items-center rounded-full border border-primary-50/20 bg-transparent transition hover:bg-primary-50/10',
  },
  label: { class: 'px-3 py-1.5 text-sm text-primary-50 leading-none' },
  dropdown: { class: 'flex items-center pr-3 text-primary-50/60' },
  overlay: {
    class:
      'z-50 mt-1 overflow-hidden rounded-xl border border-primary-50/20 bg-sapphire-100 shadow-xl',
  },
  listContainer: { class: 'overflow-auto' },
  option: {
    class: 'cursor-pointer px-4 py-2 text-sm text-primary-50 transition hover:bg-primary-50/10',
  },
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- Controls: view tabs (left) · drill-downs · unit (right) -->
    <div class="flex flex-wrap items-center gap-3">
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
        :pt="selectPt"
      />
      <Select
        v-if="showLevel2 && level2 && !isRouteSectionView"
        v-model="sel2"
        :options="level2.options"
        option-value="key"
        option-label="label"
        :unstyled="true"
        :pt="selectPt"
      />

      <div class="ml-auto">
        <Select
          v-model="normalisation"
          :options="normOptions"
          option-value="value"
          option-label="label"
          :unstyled="true"
          :pt="selectPt"
        />
      </div>
    </div>

    <!-- Route section: two-thumb slider with per-stop labels, on its own row -->
    <RouteSectionSlider
      v-if="isRouteSectionView && stops.length > 1"
      v-model="odRange"
      :stops="stops"
      class="w-4/5 self-center"
    />

    <template v-if="currentBreakdown">
      <!-- KPI box -->
      <div class="flex justify-around rounded-xl bg-primary-50/5 p-4">
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.kpi.revenue') }}
          </span>
          <span class="text-xl font-bold text-primary-50 tabular-nums">
            {{ formatEur(currentBreakdown.total_revenue_eur) }}
          </span>
        </div>
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.kpi.cost') }}
          </span>
          <span class="text-xl font-bold text-primary-50 tabular-nums">
            {{ formatEur(currentBreakdown.total_cost_eur) }}
          </span>
        </div>
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs tracking-wide text-primary-50/50 uppercase">
            {{ t('proposal.evaluation.kpi.net') }}
          </span>
          <span
            class="text-xl font-bold tabular-nums"
            :class="currentBreakdown.net_eur >= 0 ? 'text-green-400' : 'text-red-400'"
          >
            {{ formatEur(currentBreakdown.net_eur) }}
          </span>
        </div>
      </div>

      <!-- Cost tree (left) | Revenue (right) -->
      <div class="flex items-start gap-4">
        <div class="w-1/2 rounded-xl bg-primary-50/5 p-4">
          <div class="mb-2 flex items-center gap-1 border-b border-primary-50/10 pb-2">
            <span class="w-5 shrink-0" />
            <span class="flex-1 font-semibold text-primary-50">
              {{ t('proposal.evaluation.groups.cost') }}
            </span>
            <span class="w-12 text-right text-xs text-primary-50/40 tabular-nums">
              {{ formatShare(1) }}
            </span>
            <span class="w-24 text-right font-semibold text-primary-50 tabular-nums">
              {{ formatEur(currentBreakdown.cost.total_eur) }}
            </span>
          </div>
          <div
            v-for="row in costRows"
            :key="row.key"
            class="flex items-center gap-1 py-1"
            :style="{ paddingLeft: `${row.depth * 16}px` }"
          >
            <button
              v-if="row.hasChildren"
              class="flex w-5 shrink-0 cursor-pointer justify-center text-primary-50/40 transition hover:text-primary-50"
              @click="toggleExpand(row.key)"
            >
              <AppIcon :path="row.isExpanded ? mdiChevronDown : mdiChevronRight" :size="16" />
            </button>
            <span v-else class="w-5 shrink-0" />
            <span
              class="flex flex-1 items-center gap-1 text-sm"
              :class="row.hasChildren ? 'text-primary-50' : 'text-primary-50/70'"
            >
              {{ row.label }}
              <button
                v-if="hasInfo(row.key)"
                type="button"
                class="flex cursor-pointer text-primary-50/40 transition hover:text-primary-50"
                :aria-label="t('proposal.evaluation.info.iconLabel')"
                @mouseenter="openInfo(row.key, $event)"
                @mouseleave="scheduleClose"
                @click="openInfo(row.key, $event)"
              >
                <AppIcon :path="mdiInformationOutline" :size="14" />
              </button>
            </span>
            <span class="w-12 text-right text-xs text-primary-50/40 tabular-nums">
              {{ formatShare(row.share) }}
            </span>
            <span class="w-24 text-right text-sm text-primary-50 tabular-nums">
              {{ formatEur(row.value) }}
            </span>
          </div>
        </div>

        <div class="flex-1 rounded-xl bg-primary-50/5 p-4">
          <div class="mb-2 flex items-baseline justify-between border-b border-primary-50/10 pb-2">
            <span class="font-semibold text-primary-50">
              {{ t('proposal.evaluation.groups.revenue') }}
            </span>
            <span class="font-semibold text-primary-50 tabular-nums">
              {{ formatEur(currentBreakdown.revenue.total_eur) }}
            </span>
          </div>
          <div class="flex items-center justify-between py-1">
            <span class="text-sm text-primary-50/70">
              {{ t('proposal.evaluation.fields.ticket_revenue') }}
            </span>
            <span class="text-sm text-primary-50 tabular-nums">
              {{ formatEur(currentBreakdown.revenue.ticket_revenue_eur) }}
            </span>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="rounded-xl bg-primary-50/5 p-4 text-sm text-primary-50/60">
      {{ t('proposal.evaluation.noData') }}
    </div>

    <!-- Footer: calc version + raw JSON fallback -->
    <div class="flex flex-col gap-1 text-xs text-primary-50/40">
      <span>{{ t('proposal.evaluation.calcVersion') }} {{ result.calc_version }}</span>
      <details @toggle="onRawToggle">
        <summary class="cursor-pointer select-none">
          {{ t('proposal.evaluation.showRaw') }}
        </summary>
        <pre
          v-if="rawOpen"
          class="mt-2 max-h-96 overflow-auto rounded-lg bg-black/20 p-3 text-primary-50/60"
          >{{ rawJson }}</pre
        >
      </details>
    </div>

    <!-- Cost-factor detail popover: title · explanation · formula · rates -->
    <Popover
      ref="infoPopover"
      :pt="{
        root: {
          class: 'cost-info-overlay !rounded-xl !shadow-2xl',
          onMouseenter: cancelClose,
          onMouseleave: scheduleClose,
        },
        content: { class: '!p-6 !bg-transparent' },
      }"
      @show="onInfoShow"
      @hide="onInfoHide"
    >
      <div v-if="activeFactor" class="flex flex-col gap-6">
        <h3 class="text-xl font-semibold text-primary-50">{{ activeFactor.title }}</h3>
        <p class="text-sm text-primary-50/70" style="text-align: justify">
          {{ activeFactor.description }}
        </p>
        <!-- Rendered LaTeX; formula is backend-controlled, so v-html is safe. -->
        <!-- eslint-disable vue/no-v-html -->
        <div
          class="cost-info-formula max-w-full self-center overflow-x-auto rounded-lg bg-black/20 px-5 py-3 text-primary-50"
          v-html="activeFactor.latexHtml"
        />
        <!-- eslint-enable vue/no-v-html -->
        <template v-if="activeFactor.rates.length">
          <table class="w-full text-left text-sm">
            <thead>
              <tr class="text-xs text-primary-50/40">
                <th class="pr-3 pb-1 font-medium">
                  {{ t('proposal.evaluation.info.rateCol') }}
                </th>
                <th class="pr-3 pb-1 text-right font-medium">
                  {{ t('proposal.evaluation.info.valueCol') }}
                </th>
                <th class="pb-1 font-medium">
                  {{ t('proposal.evaluation.info.sourceCol') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(rate, idx) in activeFactor.rates"
                :key="idx"
                class="border-t border-primary-50/10 align-top"
              >
                <td class="py-1.5 pr-3">
                  <div class="text-primary-50">
                    {{ t(`proposal.evaluation.rates.${rate.id}`) }}
                    <span v-if="rate.scope" class="text-primary-50/50">· {{ rate.scope }}</span>
                  </div>
                  <div v-if="rate.description" class="text-xs text-primary-50/40">
                    {{ rate.description }}
                  </div>
                </td>
                <td class="py-1.5 pr-3 text-right whitespace-nowrap text-primary-50 tabular-nums">
                  {{ formatRateValue(rate) }}
                  <span v-if="rate.unit" class="text-primary-50/50">{{ rate.unit }}</span>
                </td>
                <td class="py-1.5 text-xs text-primary-50/60">
                  <span
                    v-if="rate.isDefault"
                    class="mr-1 mb-1 inline-block rounded-full bg-primary-50/10 px-1.5 py-0.5 text-primary-50/50"
                  >
                    {{ t('proposal.evaluation.info.defaultBadge') }}
                  </span>
                  <span v-for="(src, i) in rate.sources" :key="i" class="block">
                    <a
                      v-if="src.source_url"
                      :href="src.source_url"
                      target="_blank"
                      rel="noopener"
                      class="underline hover:text-primary-50"
                    >
                      {{ src.source_description || src.source_url }}
                    </a>
                    <span v-else>{{ src.source_description }}</span>
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </Popover>
  </div>
</template>

<style>
.cost-info-overlay {
  background: #23263d !important;
  border: 1px solid color-mix(in srgb, var(--p-primary-50) 20%, transparent) !important;
  /* Grow to fit a wide formula; only the viewport bounds the width. */
  max-width: calc(100vw - 2rem);
}
/* KaTeX inherits the box's text colour; keep the formula on one baseline. */
.cost-info-formula .katex {
  font-size: 1.05em;
}
</style>
