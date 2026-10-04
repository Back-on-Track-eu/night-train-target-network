<script setup lang="ts">
import { computed } from 'vue'
import { formatNumber } from '../lib/format'

// Europe, countries shaded by how many proposals touch them, stations as
// bubbles sized by use. Basemap and positions are pre-projected by
// backend/scripts/crowdsourcing_report.py (one Mercator in one place):
// the basemap is shared by every edition, the counts and bubbles are the
// edition's own. Every country and bubble links into the gallery, where
// "create proposal" seeds from that country or station — the report's
// "design a route where the map is still dark" promise.
export interface Basemap {
  width: number
  height: number
  names: Record<string, string>
  paths: Record<string, string>
}
export interface MapData {
  countries: Record<string, { value: number; href: string }>
  bubbles: { id: string; name: string; value: number; x: number; y: number; href: string }[]
  labelled: string[]
}

const props = defineProps<{
  basemap: Basemap
  data: MapData
  caption?: string
}>()

const top = computed(() => Math.max(...Object.values(props.data.countries).map((c) => c.value), 1))

const countries = computed(() =>
  Object.entries(props.basemap.paths).map(([iso, d]) => {
    const hit = props.data.countries[iso]
    const name = props.basemap.names[iso] ?? iso
    // Square root so the long tail of once-touched countries still reads.
    const t = hit ? Math.sqrt(hit.value / top.value) : 0
    return {
      iso,
      d,
      href: hit?.href,
      opacity: hit ? 0.18 + 0.72 * t : 0.045,
      shaded: Boolean(hit),
      title: hit
        ? `${name}: ${formatNumber(hit.value)} proposals — open in the gallery`
        : `${name}: no proposals yet`,
    }
  }),
)

const bubbles = computed(() =>
  props.data.bubbles.map((b) => ({
    ...b,
    r: 2.2 + 1.9 * Math.sqrt(b.value / 10),
    title: `${b.name}: ${formatNumber(b.value)} proposals — open in the gallery`,
  })),
)

const labels = computed(() => {
  const byId = new Map(props.data.bubbles.map((b) => [b.id, b]))
  return props.data.labelled.flatMap((id) => {
    const b = byId.get(id)
    return b ? [b] : []
  })
})
</script>

<template>
  <div class="report-map">
    <svg :viewBox="`0 0 ${basemap.width} ${basemap.height}`" class="report-map__svg" role="img">
      <rect :width="basemap.width" :height="basemap.height" class="report-map__sea" />
      <template v-for="c in countries" :key="c.iso">
        <a v-if="c.href" :href="c.href" target="_blank" rel="noopener noreferrer">
          <path
            :d="c.d"
            class="report-map__country report-map__country--shaded"
            :fill-opacity="c.opacity"
          >
            <title>{{ c.title }}</title>
          </path>
        </a>
        <path v-else :d="c.d" class="report-map__country" :fill-opacity="c.opacity">
          <title>{{ c.title }}</title>
        </path>
      </template>
      <a v-for="b in bubbles" :key="b.id" :href="b.href" target="_blank" rel="noopener noreferrer">
        <circle :cx="b.x" :cy="b.y" :r="b.r" class="report-map__bubble">
          <title>{{ b.title }}</title>
        </circle>
      </a>
      <a
        v-for="b in labels"
        :key="`label-${b.id}`"
        :href="b.href"
        target="_blank"
        rel="noopener noreferrer"
      >
        <text :x="b.x + 9" :y="b.y + 4" class="report-map__label">{{ b.name }}</text>
      </a>
    </svg>
    <p v-if="caption" class="report-caption" v-html="caption" />
  </div>
</template>

<style>
.report-map__svg {
  display: block;
  width: 100%;
  max-width: 760px;
  height: auto;
  margin: 0 auto;
  border: 1px solid var(--bot-hairline);
  border-radius: 12px;
}

/* Country, bubble and label links open the gallery in a new tab; the
   map's own hover states are the affordance, not an underline. */
.vp-doc .report-map a,
.report-map a {
  text-decoration: none;
}

.report-map__sea {
  fill: var(--bot-sapphire);
}

.report-map__country {
  fill: var(--bot-primary-50);
  stroke: var(--bot-sapphire);
  stroke-width: 0.6;
}

.report-map__country--shaded {
  fill: var(--bot-primary-500);
  cursor: pointer;
  transition: fill-opacity 0.15s;
}

.report-map a:hover .report-map__country--shaded {
  stroke: var(--bot-primary-200);
  stroke-width: 1.2;
}

.report-map__bubble {
  fill: var(--bot-primary-200);
  fill-opacity: 0.9;
  stroke: var(--bot-sapphire);
  stroke-width: 1;
  cursor: pointer;
}

.report-map a:hover .report-map__bubble {
  fill: var(--bot-primary-50);
}

/* A sapphire halo keeps the label legible over bubbles and borders. */
.report-map__label {
  fill: var(--bot-ink);
  font-size: 11px;
  font-weight: 700;
  paint-order: stroke;
  stroke: var(--bot-sapphire);
  stroke-width: 3px;
  cursor: pointer;
}

.report-map a:hover .report-map__label {
  fill: var(--bot-primary-200);
}

/* The map scales with the column; below phone width the labels would be
   unreadable, and every bubble still carries its name on hover. */
@media (max-width: 600px) {
  .report-map__label {
    display: none;
  }
}
</style>
