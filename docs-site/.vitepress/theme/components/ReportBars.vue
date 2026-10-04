<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { formatNumber, formatPercent } from '../lib/format'

// Bar charts as inline SVG — no chart library on this site. Horizontal
// (`rows`: label | bar | value, a row may link into the gallery) or
// vertical (`values` + `labels`, one column per day or bucket). Thin bars,
// 2 px gaps, rounded data ends, recessive axis text, a value label on the
// top bar only (on every bar when there are four or fewer), and a hover
// <title> on every mark.
//
// The viewBox is one unit per CSS pixel: it is re-measured from the
// container after mount, so text stays 12 px on a phone instead of being
// scaled down with the drawing. Server-side the chart renders at the
// default width and settles on the client — a one-off reflow, no mismatch.
export interface BarRow {
  label: string
  value: number
  href?: string
}

const props = withDefaults(
  defineProps<{
    rows?: BarRow[]
    values?: number[]
    labels?: string[]
    direction?: 'h' | 'v'
    /** Column index or indices drawn in the accent colour; the rest recede. */
    highlight?: number | number[]
    unit?: string
    /** Horizontal rows show their value as a share of this total. */
    percentOf?: number
    /** Space for row labels, in px; shrinks to 40 % of a narrow chart. */
    labelWidth?: number
    rowHeight?: number
    height?: number
    caption?: string
  }>(),
  {
    direction: 'h',
    unit: '',
    labelWidth: 170,
    rowHeight: 26,
    height: 180,
  },
)

const DEFAULT_WIDTH = 560
const MIN_WIDTH = 280
// Below this width the horizontal layout stacks: label above its bar,
// nothing truncated. Above it, label | bar | value on one line.
const STACK_BELOW = 440
// Approximate advance of the 12 px row label font, for truncation.
const PX_PER_CHAR = 7

const host = ref<HTMLElement | null>(null)
const width = ref(DEFAULT_WIDTH)
let observer: ResizeObserver | null = null

onMounted(() => {
  if (!host.value || typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(([entry]) => {
    width.value = Math.max(MIN_WIDTH, Math.round(entry.contentRect.width))
  })
  observer.observe(host.value)
})
onBeforeUnmount(() => observer?.disconnect())

function fmt(value: number): string {
  const digits = Number.isInteger(value) || value >= 100 ? 0 : 1
  return formatNumber(value, digits) + props.unit
}

function truncate(label: string, maxPx: number): string {
  const max = Math.floor(maxPx / PX_PER_CHAR)
  return label.length > max ? label.slice(0, Math.max(1, max - 1)).trimEnd() + '…' : label
}

const stacked = computed(() => width.value < STACK_BELOW)
const labelWidth = computed(() => (stacked.value ? 0 : props.labelWidth))
const rowStep = computed(() => (stacked.value ? props.rowHeight + 16 : props.rowHeight))

const hRows = computed(() => {
  const rows = props.rows ?? []
  const top = Math.max(...rows.map((r) => r.value), 1)
  const barWidth = width.value - labelWidth.value - 70
  return rows.map((row, i) => {
    const w = Math.max(3, (barWidth * row.value) / top)
    const value = props.percentOf ? formatPercent(row.value / props.percentOf) : fmt(row.value)
    const y = i * rowStep.value
    return {
      ...row,
      y,
      // Bar and value share one line; the label sits beside it or above it.
      barY: stacked.value ? y + 16 : y,
      labelY: stacked.value ? y + 12 : y + props.rowHeight / 2 + 4,
      w,
      shortLabel: stacked.value ? row.label : truncate(row.label, labelWidth.value - 10),
      text: value,
      title: `${row.label}: ${fmt(row.value)}${row.href ? ' — open in the gallery' : ''}`,
    }
  })
})

const vCols = computed(() => {
  const values = props.values ?? []
  const labels = props.labels ?? []
  const n = values.length || 1
  const top = Math.max(...values, 1)
  const padBottom = 26
  const padTop = 22
  const padX = 18
  const gap = 2
  const barWidth = (width.value - 2 * padX - gap * (n - 1)) / n
  const plotHeight = props.height - padBottom - padTop
  const lit = new Set(
    props.highlight === undefined
      ? []
      : Array.isArray(props.highlight)
        ? props.highlight
        : [props.highlight],
  )
  const single = typeof props.highlight === 'number'
  return values.map((v, i) => {
    const h = Math.max(2, (plotHeight * v) / top)
    const x = padX + i * (barWidth + gap)
    const y = padTop + plotHeight - h
    const highlighted = props.highlight === undefined || lit.has(i)
    return {
      x,
      y,
      w: barWidth,
      h,
      label: labels[i] ?? '',
      dim: !highlighted,
      labelled: n <= 4 || v === top || (single && lit.has(i)),
      value: fmt(v),
      title: `${labels[i] ?? ''}: ${fmt(v)}`,
    }
  })
})

const hHeight = computed(() => (props.rows?.length ?? 0) * rowStep.value)
</script>

<template>
  <div ref="host" class="report-bars">
    <svg
      v-if="direction === 'h'"
      :viewBox="`0 0 ${width} ${hHeight}`"
      class="report-chart"
      role="img"
    >
      <template v-for="row in hRows" :key="row.label">
        <component
          :is="row.href ? 'a' : 'g'"
          :href="row.href"
          :target="row.href ? '_blank' : undefined"
          :rel="row.href ? 'noopener noreferrer' : undefined"
          :class="{ 'report-bars__link': row.href }"
        >
          <rect
            v-if="row.href"
            x="0"
            :y="row.y"
            :width="width"
            :height="rowStep"
            fill="transparent"
          />
          <text
            :x="stacked ? 0 : labelWidth - 10"
            :y="row.labelY"
            class="report-chart__row"
            :text-anchor="stacked ? 'start' : 'end'"
          >
            {{ row.shortLabel }}
          </text>
          <rect
            :x="labelWidth"
            :y="row.barY + 6"
            :width="row.w"
            :height="rowHeight - 12"
            rx="3"
            class="report-chart__bar"
          >
            <title>{{ row.title }}</title>
          </rect>
          <text
            :x="labelWidth + row.w + 8"
            :y="row.barY + rowHeight / 2 + 4"
            class="report-chart__value"
          >
            {{ row.text }}
          </text>
        </component>
      </template>
    </svg>

    <svg v-else :viewBox="`0 0 ${width} ${height}`" class="report-chart" role="img">
      <template v-for="(col, i) in vCols" :key="i">
        <rect
          :x="col.x"
          :y="col.y"
          :width="col.w"
          :height="col.h"
          rx="3"
          class="report-chart__bar"
          :class="{ 'report-chart__bar--dim': col.dim }"
        >
          <title>{{ col.title }}</title>
        </rect>
        <text
          v-if="col.labelled"
          :x="col.x + col.w / 2"
          :y="col.y - 6"
          class="report-chart__value"
          text-anchor="middle"
        >
          {{ col.value }}
        </text>
        <text
          :x="col.x + col.w / 2"
          :y="height - 8"
          class="report-chart__axis"
          text-anchor="middle"
        >
          {{ col.label }}
        </text>
      </template>
    </svg>

    <p v-if="caption" class="report-caption" v-html="caption" />
  </div>
</template>

<style>
.report-chart {
  display: block;
  width: 100%;
  height: auto;
}

.report-chart__bar {
  fill: var(--bot-primary-300);
}

.report-chart__bar--dim {
  fill: var(--bot-primary-600);
}

.report-chart__value {
  fill: var(--bot-ink);
  font-size: 12px;
  font-weight: 700;
}

.report-chart__axis {
  fill: var(--bot-ink-50);
  font-size: 11px;
}

.report-chart__row {
  fill: var(--bot-ink-70);
  font-size: 12px;
}

/* Links into the gallery open a new tab (the docs stay put); the row
   itself is the affordance, so no underline — .vp-doc a would add one. */
.vp-doc .report-bars__link,
.report-bars__link {
  cursor: pointer;
  text-decoration: none;
}

.report-bars__link:hover .report-chart__bar {
  fill: var(--bot-primary-200);
}

.report-bars__link:hover .report-chart__row {
  fill: var(--bot-ink);
}
</style>
