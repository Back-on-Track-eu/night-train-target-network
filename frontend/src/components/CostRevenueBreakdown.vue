<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { Breakdown, EvaluationResponse, MapScope, NormKey } from '@/types/api'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import { CATERING_COLOR, CLASS_COLORS } from '@/lib/compositionFormation'
import { layoutSegmentLabels, type SegmentLabel } from '@/lib/segmentLabels'
import ViewRow from '@/components/ViewRow.vue'
import CostBreakdownPanel from '@/components/CostBreakdownPanel.vue'
import AppIcon from '@/components/AppIcon.vue'
import Skeleton from 'primevue/skeleton'
import { mdiChevronDown } from '@mdi/js'

// Zone E — the collapsible cost/revenue detail ("Kassenzettel"). Two
// stacked bars on one shared scale for the landed Breakdown (cost by
// category incl. the operator's margin, revenue by class/source), with a
// dashed outline on the shorter bar marking the gap: gold "necessary
// subsidy" or green "revenue exceeds cost". Below it the existing cube
// selectors (ViewRow) and the ledgers (CostBreakdownPanel) unchanged —
// the drill-down is exactly what it was, only folded away by default.
//
// The views arrive on their own request after the family document (see
// ProposalViewport's loadViews); until then result.views is null and this
// zone shows a skeleton. The formulas the ledgers' popovers key into are the
// store's model registry (GET /api/models), no longer part of a member.
const props = defineProps<{
  result: EvaluationResponse
  stops: { stop_id: string; name: string }[]
  defaultOpen?: boolean
}>()
const emit = defineEmits<{ scopeChange: [scope: MapScope] }>()

const { t, te } = useI18n()
const { formatEur, formatShare } = useEvaluationFormat()
const store = useStore()
const formulas = computed(() => store.models?.evaluation.formulas ?? {})
const open = ref(false)
const breakdown = ref<Breakdown | null>(null)
// Per-class_main breakdowns of the landed cell, from ViewRow's own cube
// resolution. Revenue splits by class from these; cost does not, because the
// class cells are an ALLOCATION of the whole cell rather than a measurement,
// and splitting a driver's wage by berth type would read as a finding.
const classSplit = ref<{ classMain: string; breakdown: Breakdown }[]>([])
const normalisation = ref<NormKey>('per_year')

// THE REFERENCE the bars are drawn against: the full route, every country,
// section and stop, all classes — in the normalisation on screen. A selected
// cell's bars are as long as its share of that: pick Capsule and its bars
// shrink to Capsule's part of the route, they do not re-fill the track.
// Without this the bars re-scaled to whichever cell was showing, so every
// selection looked the same size and the comparison the selectors exist for
// was lost.
const reference = computed<Breakdown | null>(
  () => props.result.views?.route.data[normalisation.value]?.all ?? null,
)

// The cost bar is NOT colour-coded. Six hues for six cost groups meant a
// reader had to hold a colour key in their head, and the two blues were a
// step apart; the segments are one neutral fill now and each says its own
// name — an abbreviation, expanded in the legend below. Colour carries no
// information on this bar, so nothing is lost when a segment is too narrow
// to label: the legend lists every part regardless.
//
// Revenue is the opposite case and keeps its colours: they are the SAME
// colours each class has in the formation drawing, the supply table and the
// revenue ledger, so a sleeper-heavy bar looks like a sleeper-heavy train.
// Its segments carry the class name in full — an abbreviated "Cou" would be
// worse than the word it stands for.
// Neutral: the cost segments are one ghost tone of the page's own ink, with
// hairline separators, so the only colour on the cost bar is the green of the
// margin-and-surplus block that follows them. A solid blue next to that green
// looked like two charts fighting; this looks like one bar with a bright
// part.
const COST_FILL = 'rgba(241, 243, 246, 0.16)'
// Additional services on the revenue bar: a lighter ghost of the same ink,
// so it reads as revenue-but-not-a-class.
const SERVICES_FILL = 'rgba(241, 243, 246, 0.5)'
const CLASS_FALLBACK = '#f1f3f6'

const bars = computed(() => {
  const b = breakdown.value
  if (!b) return null

  // Cost: the operating cost only. The operator's expected margin is NOT a
  // segment here — it is drawn after the cost as its own green-dashed block,
  // the same treatment as the surplus it is the first slice of.
  const cost = [
    { key: 'operatorVariable', value: b.cost.operator.variable.total_eur },
    { key: 'operatorFixed', value: b.cost.operator.fixed.total_eur },
    { key: 'trackAccess', value: b.cost.infrastructure.tac_eur },
    { key: 'stationCharges', value: b.cost.infrastructure.station_charge_eur },
    { key: 'energy', value: b.cost.infrastructure.energy_eur },
    { key: 'parking', value: b.cost.infrastructure.parking_eur },
  ]
    .filter((s) => s.value > 0)
    .map((s) => ({
      ...s,
      color: COST_FILL,
      label: t(`proposal.breakdown.segments.${s.key}`),
      abbr: t(`proposal.breakdown.abbr.${s.key}`),
    }))

  // Revenue: the base fare split by class (the classes are an allocation of
  // the base fare, so they are rescaled onto it rather than trusted to sum
  // exactly), then additional services, then the catering contribution.
  const ticket = b.revenue.ticket_revenue_eur
  const services = b.revenue.services_revenue_eur ?? 0
  const catering = b.revenue.catering_contribution_eur ?? 0
  const split = classSplit.value.filter((c) => c.breakdown.revenue.ticket_revenue_eur > 0)
  const splitTotal = split.reduce((sum, c) => sum + c.breakdown.revenue.ticket_revenue_eur, 0)
  const classSegments =
    split.length > 1 && splitTotal > 0
      ? split.map((c) => ({
          key: c.classMain,
          value: (c.breakdown.revenue.ticket_revenue_eur / splitTotal) * ticket,
          color: CLASS_COLORS[c.classMain] ?? CLASS_FALLBACK,
          label: te(`proposal.evaluation.classes.${c.classMain}`)
            ? t(`proposal.evaluation.classes.${c.classMain}`)
            : c.classMain,
        }))
      : [
          {
            key: 'tickets',
            value: ticket,
            color: CLASS_FALLBACK,
            label: t('proposal.breakdown.segments.tickets'),
          },
        ]
  const revenue = [
    ...classSegments,
    {
      key: 'services',
      value: services,
      color: SERVICES_FILL,
      label: t('proposal.breakdown.segments.services'),
    },
    // Only a POSITIVE contribution is a segment. A negative one is drawn as
    // a deduction beyond the bar's end (see the template): the bar's length
    // is the net total, and the hatched piece after it is what the
    // restaurant took off.
    {
      key: 'catering',
      value: Math.max(0, catering),
      color: CATERING_COLOR,
      label: t('proposal.breakdown.segments.catering'),
    },
  ].filter((s) => s.value > 0)

  const costTotal = b.cost.total_eur
  const margin = b.margin.total_eur
  const required = costTotal + margin
  const revenueTotal = b.revenue.total_eur
  const cateringDeduction = Math.max(0, -catering)
  // The track is the FULL ROUTE: whichever is longer there, what it needs
  // (cost + margin) or what it earns, in this normalisation. A cell's bars
  // are drawn against that, so they shrink to the cell's share of the route.
  // The cell itself is the fallback only when the route view is not there.
  const ref = reference.value
  const refRequired = ref ? ref.cost.total_eur + ref.margin.total_eur : required
  const refRevenue = ref ? ref.revenue.total_eur : revenueTotal
  const scale = Math.max(refRequired, refRevenue, required, revenueTotal + cateringDeduction) || 1
  // net_eur = revenue - cost - margin, the backend's own figure. Positive is
  // surplus beyond the margin; negative is the subsidy that covers the cost
  // AND the margin.
  const net = revenueTotal - required
  return {
    cost,
    revenue,
    costTotal,
    margin,
    required,
    revenueTotal,
    cateringDeduction,
    scale,
    net,
    // Green area on the cost side = margin + surplus = revenue - cost.
    aboveCost: Math.max(0, revenueTotal - costTotal),
    // What the cell is of the route, for the caption beside each total —
    // null when the cell IS the route, so the caption only appears once
    // something narrower is selected.
    shareOfRoute: {
      cost: ref && ref.cost.total_eur && ref !== b ? costTotal / ref.cost.total_eur : null,
      revenue:
        ref && ref.revenue.total_eur && ref !== b ? revenueTotal / ref.revenue.total_eur : null,
    },
  }
})

// Segment labels, laid out in pixels against the MEASURED width of the
// track (lib/segmentLabels.ts): inside the segment where it fits, otherwise
// below the bar on a leader from the segment's centre, in up to two rows that
// never overlap. Percent-based estimates were tried twice and put labels
// under the wrong segment on narrow panels; this measures.
const trackEl = ref<HTMLElement | null>(null)
const trackWidth = ref(0)
let observer: ResizeObserver | null = null

function measure() {
  trackWidth.value = trackEl.value?.clientWidth ?? 0
}

// The track is inside a <details> and behind a v-if on the landed cell, so it
// is usually NOT there at mount. Attach the observer to whatever element the
// ref currently holds, and re-attach whenever that element changes.
onMounted(() => {
  observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
})
watch(
  trackEl,
  (el, previous) => {
    if (previous) observer?.unobserve(previous)
    if (el) observer?.observe(el)
    requestAnimationFrame(measure)
  },
  { flush: 'post' },
)
onBeforeUnmount(() => observer?.disconnect())

const LABEL_ROW_PX = 14

function labelsFor(side: 'cost' | 'revenue'): SegmentLabel[] {
  const b = bars.value
  if (!b || trackWidth.value === 0) return []
  const segments = side === 'cost' ? b.cost : b.revenue
  let x = 0
  const inputs = segments.map((segment) => {
    const width = (segment.value / b.scale) * trackWidth.value
    const input = {
      key: segment.key,
      text: side === 'cost' ? (segment.abbr ?? '') : segment.label,
      x,
      width,
    }
    x += width
    return input
  })
  return layoutSegmentLabels(inputs, { trackWidth: trackWidth.value })
}

const costLabels = computed(() => labelsFor('cost'))
const revenueLabels = computed(() => labelsFor('revenue'))

function insideText(side: 'cost' | 'revenue', key: string): string {
  const labels = side === 'cost' ? costLabels.value : revenueLabels.value
  const label = labels.find((l) => l.key === key)
  return label?.placement === 'inside' ? label.text : ''
}

function outsideLabels(side: 'cost' | 'revenue') {
  const labels = side === 'cost' ? costLabels.value : revenueLabels.value
  return labels.filter(
    (l): l is Extract<SegmentLabel, { placement: 'outside' }> => l.placement === 'outside',
  )
}

function rowsNeeded(side: 'cost' | 'revenue'): number {
  return outsideLabels(side).reduce((max, l) => Math.max(max, l.row + 1), 0)
}

/** Ink that stays legible on the fill it sits on — the cost fill is dark
 *  enough for white, the class palette runs to pale yellows. */
function segmentInk(color: string): string {
  // The ghost fills are rgba() and sit on the dark page: white ink.
  if (!color.startsWith('#')) return '#ffffff'
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16))
  return (r * 299 + g * 587 + b * 114) / 255000 > 0.6 ? '#12162b' : '#ffffff'
}
</script>

<template>
  <details
    class="group rounded-xl border border-primary-50/10"
    :open="open || defaultOpen"
    @toggle="open = ($event.target as HTMLDetailsElement).open"
  >
    <summary class="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3">
      <span class="flex flex-col">
        <span class="text-base font-semibold text-primary-50">{{
          t('proposal.evaluation.sections.finance.title')
        }}</span>
        <span class="text-xs text-primary-50/60">{{
          t('proposal.evaluation.sections.finance.body')
        }}</span>
      </span>
      <AppIcon
        :path="mdiChevronDown"
        :size="20"
        class="text-primary-50/60 transition group-open:rotate-180"
      />
    </summary>
    <div
      v-if="result.views === null"
      class="flex flex-col gap-3 border-t border-primary-50/10 px-4 py-3"
      :aria-label="t('proposal.evaluation.viewsLoading')"
    >
      <Skeleton height="2rem" class="w-full" />
      <Skeleton height="6rem" class="w-full" />
      <Skeleton height="12rem" class="w-full" />
    </div>
    <div v-else class="flex flex-col gap-4 border-t border-primary-50/10 px-4 py-3">
      <ViewRow
        :views="result.views"
        :stops="stops"
        @scope-change="emit('scopeChange', $event)"
        @update:breakdown="breakdown = $event"
        @update:class-breakdowns="classSplit = $event"
        @update:normalisation="normalisation = $event"
      />

      <!-- Moved out of the controls row and into CostBreakdownPanel's slot,
           below the KPI strip: up here it sat directly under the route-section
           slider and collided with its rotated stop labels. -->
      <CostBreakdownPanel :breakdown="breakdown" :class-split="classSplit" :formulas="formulas">
        <template #bars>
          <div v-if="bars" class="flex flex-col gap-3">
            <div
              v-for="side in ['revenue', 'cost'] as const"
              :key="side"
              class="flex flex-col gap-1.5"
            >
              <div class="flex items-baseline justify-between text-xs">
                <span class="font-medium text-primary-50/80">{{
                  t(`proposal.breakdown.${side}`)
                }}</span>
                <span class="font-semibold tabular-nums text-primary-50">
                  <span
                    v-if="bars.shareOfRoute[side] !== null && bars.shareOfRoute[side]! < 0.9995"
                    class="mr-2 text-[11px] font-normal text-primary-50/45"
                  >
                    {{
                      t('proposal.breakdown.shareOfRoute', {
                        share: formatShare(bars.shareOfRoute[side]),
                      })
                    }}
                  </span>
                  {{ formatEur(side === 'cost' ? bars.costTotal : bars.revenueTotal) }}
                </span>
              </div>
              <!-- Taller, with hairline separators between segments and the
                   shortfall drawn as a hatched continuation of the same track
                   rather than an outline floating beside it. -->
              <div
                :ref="
                  (el) => {
                    if (side === 'cost') trackEl = el as HTMLElement | null
                  }
                "
                class="relative h-8 overflow-hidden rounded-lg bg-primary-50/5"
              >
                <div
                  class="flex h-full"
                  :style="{
                    width: `${((side === 'cost' ? bars.costTotal : bars.revenueTotal) / bars.scale) * 100}%`,
                  }"
                >
                  <span
                    v-for="segment in side === 'cost' ? bars.cost : bars.revenue"
                    :key="segment.key"
                    class="flex h-full items-center justify-center overflow-hidden px-1 text-[10px] leading-none font-semibold whitespace-nowrap last:border-r-0"
                    :class="
                      side === 'cost'
                        ? 'border-r border-primary-50/35'
                        : 'border-r border-sapphire/40'
                    "
                    :style="{
                      width: `${(segment.value / (side === 'cost' ? bars.costTotal : bars.revenueTotal)) * 100}%`,
                      background: segment.color,
                      color: segmentInk(segment.color),
                    }"
                    :title="`${segment.label} · ${formatEur(segment.value)}`"
                  >
                    {{ insideText(side, segment.key) }}
                  </span>
                </div>
                <!-- COST SIDE, after the cost segments: the operator's
                     expected margin as a green-dashed block, and — when the
                     route earns more than cost + margin — the surplus
                     continuing in the same dash. Together they are the green
                     area: everything revenue brings in above the cost. A thin
                     divider marks where the margin ends and the surplus
                     begins. -->
                <template v-if="side === 'cost'">
                  <span
                    v-if="bars.margin > 0"
                    class="gap-surplus absolute top-0 flex h-full items-center justify-center text-[10px] leading-none font-semibold text-yellow-green"
                    :style="{
                      left: `${(bars.costTotal / bars.scale) * 100}%`,
                      width: `${(bars.margin / bars.scale) * 100}%`,
                    }"
                    :title="`${t('proposal.breakdown.segments.margin')} · ${formatEur(bars.margin)}`"
                  >
                    {{
                      (bars.margin / bars.scale) * trackWidth >= 30
                        ? t('proposal.breakdown.abbr.margin')
                        : ''
                    }}
                  </span>
                  <span
                    v-if="bars.net > 0"
                    class="gap-surplus absolute top-0 h-full border-l-2"
                    :style="{
                      left: `${(bars.required / bars.scale) * 100}%`,
                      width: `${(bars.net / bars.scale) * 100}%`,
                    }"
                    :title="
                      t('proposal.breakdown.surplusBeyondMargin', { value: formatEur(bars.net) })
                    "
                  />
                </template>

                <!-- REVENUE SIDE: the subsidy that would be needed to reach
                     cost + margin, and a negative catering contribution as
                     the deduction it is — hatched amber past the bar's end,
                     since the bar's own length is already the net total. -->
                <template v-else>
                  <span
                    v-if="bars.net < 0"
                    class="gap-subsidy absolute top-0 h-full"
                    :style="{
                      left: `${(bars.revenueTotal / bars.scale) * 100}%`,
                      width: `${(-bars.net / bars.scale) * 100}%`,
                    }"
                    :title="t('proposal.breakdown.gapSubsidy', { value: formatEur(-bars.net) })"
                  />
                  <span
                    v-if="bars.cateringDeduction > 0"
                    class="deduction absolute top-0 h-full"
                    :style="{
                      left: `${(bars.revenueTotal / bars.scale) * 100}%`,
                      width: `${(bars.cateringDeduction / bars.scale) * 100}%`,
                    }"
                    :title="
                      t('proposal.breakdown.cateringDeduction', {
                        value: formatEur(bars.cateringDeduction),
                      })
                    "
                  />
                </template>
              </div>

              <!-- Labels the bar could not hold: below it, each on a leader
                   from its own segment. An elbow joins a label that had to
                   move sideways back to where it came from. -->
              <div
                v-if="rowsNeeded(side) > 0"
                class="relative"
                :style="{ height: `${rowsNeeded(side) * LABEL_ROW_PX + 4}px` }"
              >
                <template v-for="label in outsideLabels(side)" :key="label.key">
                  <!-- drop from the segment centre to this label's row -->
                  <span
                    class="absolute top-0 w-px bg-primary-50/40"
                    :style="{
                      left: `${label.anchorX}px`,
                      height: `${label.row * LABEL_ROW_PX + 6}px`,
                    }"
                  />
                  <!-- elbow: only when the label was shifted off its anchor -->
                  <span
                    v-if="Math.abs(label.labelX + label.labelWidth / 2 - label.anchorX) > 1"
                    class="absolute h-px bg-primary-50/40"
                    :style="{
                      top: `${label.row * LABEL_ROW_PX + 6}px`,
                      left: `${Math.min(label.anchorX, label.labelX)}px`,
                      width: `${Math.abs(label.labelX - label.anchorX) + 1}px`,
                    }"
                  />
                  <span
                    class="absolute text-[10px] leading-none font-semibold whitespace-nowrap text-primary-50/80"
                    :style="{
                      top: `${label.row * LABEL_ROW_PX + 3}px`,
                      left: `${label.labelX}px`,
                    }"
                  >
                    {{ label.text }}
                  </span>
                </template>
              </div>
            </div>

            <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px]">
              <!-- Cost: the key, in BAR ORDER, with each segment's share.
                   This is where every segment is named, whether or not the
                   bar had room for its code: a sliver that cannot hold three
                   letters is still the fourth entry here, with its 0.1 %.
                   No swatch, because the bar has no colours to match. -->
              <span
                v-for="segment in bars.cost"
                :key="segment.key"
                class="flex items-center gap-1.5 text-primary-50/60"
              >
                <b class="font-semibold text-primary-50/85">{{ segment.abbr }}</b>
                {{ segment.label }}
                <span class="tabular-nums text-primary-50/40">
                  {{ formatShare(segment.value / bars.costTotal) }}
                </span>
              </span>
              <span class="flex items-center gap-1.5 text-primary-50/60">
                <span class="gap-surplus inline-block h-2.5 w-4" />
                {{ t('proposal.breakdown.keyMarginSurplus') }}
              </span>
              <span v-if="bars.net < 0" class="flex items-center gap-1.5 text-primary-50/60">
                <span class="gap-subsidy inline-block h-2.5 w-4" />
                {{ t('proposal.breakdown.keySubsidy') }}
              </span>
              <span
                v-if="bars.cateringDeduction > 0"
                class="flex items-center gap-1.5 text-primary-50/60"
              >
                <span class="deduction inline-block h-2.5 w-4" />
                {{ t('proposal.breakdown.keyCateringDeduction') }}
              </span>
              <span class="h-3 w-px bg-primary-50/15" />
              <!-- Revenue: the swatch, because here the colour is the key. -->
              <span
                v-for="segment in bars.revenue"
                :key="segment.key"
                class="flex items-center gap-1.5 text-primary-50/60"
              >
                <span
                  class="inline-block h-2.5 w-2.5 rounded-full"
                  :style="{ background: segment.color }"
                />
                {{ segment.label }}
              </span>
              <!-- The verdict, and where the margin sits in it. Surplus: the
                   green area is revenue minus cost, and the margin is its
                   first slice. Subsidy: the shortfall is measured against
                   cost PLUS margin — the subsidy has to be high enough for
                   the operator to earn its margin. -->
              <span
                class="ml-auto rounded-full px-2.5 py-1 text-[11px] font-semibold"
                :class="
                  bars.net < 0
                    ? 'bg-amber-400/15 text-amber-200'
                    : 'bg-yellow-green/15 text-yellow-green'
                "
              >
                {{
                  bars.net < 0
                    ? t('proposal.breakdown.verdictSubsidy', {
                        subsidy: formatEur(-bars.net),
                        margin: formatEur(bars.margin),
                      })
                    : t('proposal.breakdown.verdictSurplus', {
                        above: formatEur(bars.aboveCost),
                        margin: formatEur(bars.margin),
                        surplus: formatEur(bars.net),
                      })
                }}
              </span>
            </div>
          </div>
        </template>
      </CostBreakdownPanel>
      <div class="text-xs text-primary-50/40">
        {{ t('proposal.evaluation.calcVersion') }} {{ result.calc_version }}
      </div>
    </div>
  </details>
</template>

<style scoped>
/* The shortfall / excess: a hatched continuation of the bar's own track, so it
   reads as "this much is missing" rather than as a second object. */
.gap-subsidy,
.gap-surplus {
  border-radius: 0.5rem;
  border-width: 1px;
  border-style: dashed;
}
.gap-subsidy {
  background: repeating-linear-gradient(
    -45deg,
    color-mix(in srgb, #fbbf24 28%, transparent) 0 6px,
    transparent 6px 12px
  );
  border-color: color-mix(in srgb, #fbbf24 55%, transparent);
}
/* A negative catering contribution, drawn past the revenue bar's end: what
   the restaurant took off a total that is already net of it. */
.deduction {
  border-radius: 0 0.5rem 0.5rem 0;
  border: 1px dashed color-mix(in srgb, #d9a05b 60%, transparent);
  background: repeating-linear-gradient(
    45deg,
    color-mix(in srgb, #d9a05b 30%, transparent) 0 6px,
    transparent 6px 12px
  );
}
.gap-surplus {
  background: repeating-linear-gradient(
    -45deg,
    color-mix(in srgb, var(--color-yellow-green) 25%, transparent) 0 6px,
    transparent 6px 12px
  );
  border-color: color-mix(in srgb, var(--color-yellow-green) 55%, transparent);
}
</style>
