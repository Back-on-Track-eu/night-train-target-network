<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppSpinner from '@/components/AppSpinner.vue'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { LG_MEDIA_QUERY, useMediaQuery } from '@/composables/useMediaQuery'
import { CORRIDOR_COLORS } from '@/lib/galleryMap'
import type { Bounds, GalleryMeasure } from '@/lib/galleryRanges'
import type { DistributionBin, DistributionMeasure } from '@/types/api'

// One measure of the gallery's range filters (GalleryDistribution.vue shows
// all four at once): its histogram, the range set by dragging the two
// handles or by typing a bound.
//
// The histogram is the backend's `distributions` section, counted on the
// filter MINUS the measure's own range: a bar is what this one range keeps
// or drops of the set the other filters leave. Existing trains are never
// filtered (every range is scoped to proposals), so their part of a bar
// stays whatever the handles do.
//
// Only committed edits leave this component: a drag updates a local draft
// until the pointer is released, and `update:bounds` fires once — one
// reload of cards, corridors and histograms per gesture, not per pixel.
const props = defineProps<{
  measure: GalleryMeasure
  /** The committed range of this measure; {} for none. */
  bounds: Bounds
  data: DistributionMeasure | null
  status: 'idle' | 'loading' | 'failed'
}>()
const emit = defineEmits<{
  (e: 'update:bounds', bounds: Bounds): void
  (e: 'retry'): void
}>()

const { t } = useI18n()
const { formatInt } = useLocaleFormat()

const unit = computed(() => t(`gallery.distribution.unit.${props.measure}`))

// What the handles show: the drag in progress, else the committed range.
const draft = ref<Bounds | null>(null)
const bounds = computed<Bounds>(() => draft.value ?? props.bounds)

// A bound typed or dragged to the axis edge is no bound at all: the handle
// sits at the edge, the input empties, and the request carries nothing.
function withBound(side: 'min' | 'max', value: number | undefined): Bounds {
  const current = { ...bounds.value }
  const axis = props.data
  if (
    value === undefined ||
    (axis && (side === 'min' ? value <= axis.origin : value >= axis.top))
  ) {
    delete current[side]
    return current
  }
  if (side === 'min') current.min = current.max !== undefined ? Math.min(value, current.max) : value
  else current.max = current.min !== undefined ? Math.max(value, current.min) : value
  return current
}

function onInput(side: 'min' | 'max', event: Event): void {
  const raw = (event.target as HTMLInputElement).value
  const value = raw === '' ? undefined : Number(raw)
  if (value !== undefined && !Number.isFinite(value)) return
  emit('update:bounds', withBound(side, value))
}

// The value in words beside the measure's name: "500–2,000 km", "≥ 50 km/h",
// or "any" when no bound is set.
const summary = computed(() => {
  const b = bounds.value
  if (b.min !== undefined && b.max !== undefined) {
    return `${formatInt(b.min)}–${formatInt(b.max)} ${unit.value}`
  }
  if (b.min !== undefined) return `≥ ${formatInt(b.min)} ${unit.value}`
  if (b.max !== undefined) return `≤ ${formatInt(b.max)} ${unit.value}`
  return t('gallery.distribution.any')
})

// --- the chart -----------------------------------------------------------------
// A viewBox scaled to the chart's width; the geometry below is in viewBox
// units, so the viewBox width sets the chart's proportions: a phone's sheet
// draws it larger — readable ticks, handles a thumb can take — and the two
// columns of a desktop keep it from towering over the map it pushes down.
// Room above the plot for the grips and labels.
const lg = useMediaQuery(LG_MEDIA_QUERY)
const W = computed(() => (lg.value ? 640 : 460))
const H = 170
const PAD = { left: 34, right: 14, top: 30, bottom: 24 }
const plotW = computed(() => W.value - PAD.left - PAD.right)
const plotH = H - PAD.top - PAD.bottom

const axis = computed(() => {
  const d = props.data
  if (!d) return null
  // The open last bin draws at one bin width past the top.
  const span = d.top + d.bin_width - d.origin
  const x = (v: number) => PAD.left + ((v - d.origin) / span) * plotW.value
  const peak = Math.max(1, ...d.bins.map((b) => b.n_proposals + b.n_existing))
  const y = (count: number) => PAD.top + plotH - (count / peak) * plotH
  return { ...d, span, x, y, peak }
})

// Value → axis position, with the handle for an absent bound at the edge.
const lo = computed(() => bounds.value.min ?? axis.value?.origin ?? 0)
const hi = computed(() => bounds.value.max ?? axis.value?.top ?? 0)

const bars = computed(() => {
  const a = axis.value
  if (!a) return []
  const bw = plotW.value / a.bins.length
  return a.bins.map((b, i) => {
    const binEnd = b.to ?? b.from + a.bin_width
    const inside = binEnd > lo.value && b.from < hi.value
    const x0 = PAD.left + i * bw + 1
    const w = Math.max(1, bw - 2)
    const yExisting = a.y(b.n_proposals + b.n_existing)
    const yProposal = a.y(b.n_proposals)
    return {
      bin: b,
      inside,
      hitX: PAD.left + i * bw,
      hitW: bw,
      x: x0,
      w,
      proposal: { y: yProposal, h: PAD.top + plotH - yProposal },
      // 2 px of panel between the two stacks when both are drawn.
      existing: { y: yExisting, h: Math.max(0, yProposal - yExisting - (b.n_proposals ? 2 : 0)) },
    }
  })
})

// Tick labels at round values; the open bin's label says "top+".
const ticks = computed(() => {
  const a = axis.value
  if (!a) return []
  const n = 4
  const labels = []
  for (let i = 0; i < n; i++) {
    const v = a.origin + ((a.top - a.origin) * i) / n
    labels.push({ x: a.x(v), text: formatInt(v), anchor: i === 0 ? 'start' : 'middle' })
  }
  labels.push({ x: a.x(a.top), text: `${formatInt(a.top)}+`, anchor: 'middle' })
  return labels
})
const gridLines = computed(() => {
  const a = axis.value
  if (!a) return []
  return [0.5, 1].map((f) => {
    const count = Math.round(a.peak * f)
    return { y: a.y(count), text: formatInt(count) }
  })
})

// --- handles -------------------------------------------------------------------
const svg = ref<SVGSVGElement | null>(null)

function snap(value: number): number {
  const a = axis.value!
  const stepped = a.origin + Math.round((value - a.origin) / a.bin_width) * a.bin_width
  return Math.min(a.top, Math.max(a.origin, stepped))
}

function startDrag(event: PointerEvent, side: 'min' | 'max'): void {
  const el = svg.value
  if (!el || !axis.value) return
  event.preventDefault()
  const target = event.currentTarget as SVGGElement
  target.setPointerCapture(event.pointerId)
  const move = (e: PointerEvent) => {
    const rect = el.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W.value
    const value = axis.value!.origin + ((px - PAD.left) / plotW.value) * axis.value!.span
    draft.value = withBound(side, snap(value))
  }
  const up = () => {
    target.removeEventListener('pointermove', move)
    target.removeEventListener('pointerup', up)
    target.removeEventListener('pointercancel', up)
    if (draft.value) emit('update:bounds', draft.value)
    draft.value = null
  }
  target.addEventListener('pointermove', move)
  target.addEventListener('pointerup', up)
  target.addEventListener('pointercancel', up)
}

function nudge(side: 'min' | 'max', direction: -1 | 1): void {
  const a = axis.value
  if (!a) return
  const current = side === 'min' ? lo.value : hi.value
  emit('update:bounds', withBound(side, snap(current + direction * a.bin_width)))
}

const handles = computed(() => {
  const a = axis.value
  if (!a) return []
  return (['min', 'max'] as const).map((side) => {
    const value = side === 'min' ? lo.value : hi.value
    const open = bounds.value[side] === undefined
    return { side, x: a.x(value), open, label: open ? '' : formatInt(value) }
  })
})
// The bar across the top of the plot between the two handles.
const rangeBar = computed(() => {
  const a = axis.value
  if (!a) return { x: 0, w: 0 }
  return { x: a.x(lo.value), w: Math.max(0, a.x(hi.value) - a.x(lo.value)) }
})

// --- hover -----------------------------------------------------------------------
const hovered = ref<{ bin: DistributionBin; x: number; y: number } | null>(null)
function binLabel(b: DistributionBin): string {
  const from = formatInt(b.from)
  if (b.to === null) return t('gallery.distribution.binOpen', { from, unit: unit.value })
  // Integer measures: a one-wide bin is one value, not a range.
  if (b.to - b.from === 1 && props.measure === 'n_stops') return `${from} ${unit.value}`
  return t('gallery.distribution.bin', { from, to: formatInt(b.to), unit: unit.value })
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5">
    <!-- The measure, its range in words, and the typed bounds. -->
    <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <span class="text-sm text-primary-50/70">
        {{ t(`gallery.distribution.measure.${measure}`) }}
        <b
          class="ml-1 font-semibold tabular-nums"
          :class="
            bounds.min === undefined && bounds.max === undefined
              ? 'text-primary-50/60'
              : 'text-primary-50'
          "
          >{{ summary }}</b
        >
      </span>
      <!-- Typed bounds. Empty means no bound on that side. -->
      <span class="flex items-center gap-1.5 text-sm text-primary-50/60">
        <input
          type="number"
          inputmode="decimal"
          class="w-16 rounded-lg border border-primary-50/20 bg-sapphire px-2 py-1 text-right text-sm text-primary-50 tabular-nums placeholder:text-primary-50/30"
          :value="bounds.min ?? ''"
          :placeholder="axis ? formatInt(axis.origin) : ''"
          :aria-label="`${t(`gallery.distribution.measure.${measure}`)} — ${t('gallery.distribution.min')}`"
          @change="onInput('min', $event)"
        />
        <span aria-hidden="true">–</span>
        <input
          type="number"
          inputmode="decimal"
          class="w-16 rounded-lg border border-primary-50/20 bg-sapphire px-2 py-1 text-right text-sm text-primary-50 tabular-nums placeholder:text-primary-50/30"
          :value="bounds.max ?? ''"
          :placeholder="t('gallery.distribution.any')"
          :aria-label="`${t(`gallery.distribution.measure.${measure}`)} — ${t('gallery.distribution.max')}`"
          @change="onInput('max', $event)"
        />
        <span class="min-w-8">{{ unit }}</span>
      </span>
    </div>

    <div class="relative">
      <svg
        ref="svg"
        :viewBox="`0 0 ${W} ${H}`"
        class="block h-auto w-full select-none"
        role="img"
        :aria-label="t('gallery.distribution.measure.' + measure)"
      >
        <template v-if="axis">
          <!-- Two faint count lines and the baseline; the axis is recessive. -->
          <g class="text-primary-50/60" fill="currentColor" font-size="11">
            <template v-for="line in gridLines" :key="line.text">
              <line
                :x1="PAD.left"
                :x2="W - PAD.right"
                :y1="line.y"
                :y2="line.y"
                stroke="currentColor"
                stroke-opacity="0.25"
                stroke-dasharray="2 4"
              />
              <text :x="PAD.left - 6" :y="line.y + 4" text-anchor="end">{{ line.text }}</text>
            </template>
            <line
              :x1="PAD.left"
              :x2="W - PAD.right"
              :y1="PAD.top + plotH"
              :y2="PAD.top + plotH"
              stroke="currentColor"
              stroke-opacity="0.35"
            />
            <text
              v-for="tick in ticks"
              :key="tick.text"
              :x="tick.x"
              :y="H - 8"
              :text-anchor="tick.anchor"
            >
              {{ tick.text }}
            </text>
          </g>

          <!-- Bars: proposals, existing stacked on top, dimmed outside the range. -->
          <g
            v-for="bar in bars"
            :key="bar.bin.from"
            class="transition-opacity motion-reduce:transition-none"
            :opacity="bar.inside ? 1 : 0.28"
          >
            <rect
              v-if="bar.bin.n_proposals"
              :x="bar.x"
              :width="bar.w"
              :y="bar.proposal.y"
              :height="bar.proposal.h"
              :fill="CORRIDOR_COLORS.proposed"
              rx="1.5"
            />
            <rect
              v-if="bar.bin.n_existing"
              :x="bar.x"
              :width="bar.w"
              :y="bar.existing.y"
              :height="bar.existing.h"
              :fill="CORRIDOR_COLORS.existing"
              rx="1.5"
            />
            <rect
              :x="bar.hitX"
              :width="bar.hitW"
              :y="PAD.top"
              :height="plotH"
              fill="transparent"
              @pointerenter="
                hovered = { bin: bar.bin, x: bar.hitX + bar.hitW / 2, y: bar.existing.y }
              "
              @pointerleave="hovered = null"
            />
          </g>

          <!-- The range: a bar across the top between the handles, a grip and
               a guide line per handle, the bound's value above the grip. -->
          <g class="text-primary-300">
            <rect
              :x="rangeBar.x"
              :width="rangeBar.w"
              :y="PAD.top - 8"
              height="3"
              fill="currentColor"
              rx="1.5"
            />
            <g
              v-for="h in handles"
              :key="h.side"
              class="cursor-ew-resize focus:outline-none"
              :opacity="h.open ? 0.5 : 1"
              tabindex="0"
              role="slider"
              :aria-label="
                t(
                  h.side === 'min'
                    ? 'gallery.distribution.lowerHandle'
                    : 'gallery.distribution.upperHandle',
                )
              "
              :aria-valuenow="h.side === 'min' ? lo : hi"
              :aria-valuemin="axis.origin"
              :aria-valuemax="axis.top"
              @pointerdown="startDrag($event, h.side)"
              @keydown.left.prevent="nudge(h.side, -1)"
              @keydown.right.prevent="nudge(h.side, 1)"
            >
              <line
                :x1="h.x"
                :x2="h.x"
                :y1="PAD.top - 8"
                :y2="PAD.top + plotH"
                stroke="currentColor"
                stroke-width="1.5"
              />
              <rect
                :x="h.x - 7"
                :y="PAD.top - 14"
                width="14"
                height="14"
                rx="3"
                class="fill-primary-50"
              />
              <text
                v-if="h.label"
                :x="h.x + (h.side === 'min' ? -10 : 10)"
                :y="PAD.top - 15"
                :text-anchor="h.side === 'min' ? 'end' : 'start'"
                class="fill-primary-50"
                font-size="12"
                font-weight="600"
              >
                {{ h.label }}
              </text>
            </g>
          </g>
        </template>
      </svg>

      <!-- Hover: the bin and its two counts. -->
      <div
        v-if="hovered"
        class="pointer-events-none absolute -translate-x-1/2 -translate-y-full rounded-lg border border-primary-50/20 bg-sapphire px-2 py-1 text-xs whitespace-nowrap text-primary-50 tabular-nums shadow-md"
        :style="{
          left: `${(hovered.x / W) * 100}%`,
          top: `${(Math.max(hovered.y - 4, PAD.top + 34) / H) * 100}%`,
        }"
      >
        <b class="font-semibold">{{ binLabel(hovered.bin) }}</b
        ><br />
        {{
          t('gallery.distribution.binCounts', {
            proposals: formatInt(hovered.bin.n_proposals),
            existing: formatInt(hovered.bin.n_existing),
          })
        }}
      </div>

      <!-- No data yet, or none at all: say so in the chart's own space. -->
      <div
        v-if="!axis || status !== 'idle'"
        class="absolute inset-x-0 top-0 flex justify-center pt-2"
        role="status"
      >
        <span
          class="flex items-center gap-2 rounded-lg bg-sapphire/80 px-3 py-1 text-xs text-primary-50/70"
        >
          <template v-if="status === 'failed'">
            {{ t('gallery.distribution.failed') }}
            <button
              type="button"
              class="cursor-pointer font-semibold text-primary-50 underline underline-offset-2"
              @click="emit('retry')"
            >
              {{ t('errors.retry') }}
            </button>
          </template>
          <template v-else-if="!axis || status === 'loading'">
            <AppSpinner :size="12" />
            {{ t('gallery.distribution.loading') }}
          </template>
        </span>
      </div>
    </div>
  </div>
</template>
