<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DemandBlock } from '@/types/api'
import type { DemandInputs } from '@/lib/detailsScope'
import {
  averageDistanceKm,
  OD_PRESETS,
  odShares,
  pinPair,
  presetWeights,
  resolveWeights,
  type OdPreset,
  type SellablePair,
} from '@/lib/odMatrix'
import { useCompareFormat } from '@/composables/useCompareFormat'
import DetailPanel from '@/components/details/DetailPanel.vue'
import PreviewChip from '@/components/details/PreviewChip.vue'

// Demand · Demand by OD pair (D25–D30): an origin × destination matrix of
// shares over the sellable pairs, filled from one weight per stop in the
// margins (share ∝ board × alight, normalised). Presets write the weights by
// position along the route; any weight can be typed. Clicking a cell and
// typing a share pins it — the rest rescales so the total stays 100. The
// structure of the matrix (which pairs sell, their names and journeys) is the
// backend's, from the committed demand block; the shares are the page's
// arithmetic on the fields, so they preview live.
const props = defineProps<{
  demand: DemandInputs
  /** The committed block for the selected composition — its OD structure
   *  is the route's, the same for every composition. */
  block: DemandBlock | null
  previewing: boolean
}>()
const emit = defineEmits<{ 'update:demand': [demand: DemandInputs] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

const boardIds = computed(() => props.block?.od.boarding_stop_ids ?? [])
const alightIds = computed(() => props.block?.od.alighting_stop_ids ?? [])
const names = computed(() => {
  const out: Record<string, string> = {}
  for (const p of props.block?.od.pairs ?? []) {
    out[p.origin_stop_id] = p.origin_stop_name
    out[p.destination_stop_id] = p.destination_stop_name
  }
  return out
})
const pairs = computed<SellablePair[]>(() =>
  (props.block?.od.pairs ?? []).map((p) => ({
    originStopId: p.origin_stop_id,
    destinationStopId: p.destination_stop_id,
    distanceKm: p.distance_km,
  })),
)

const board = computed(() => resolveWeights(boardIds.value, props.demand.od.stopWeights.board))
const alight = computed(() => resolveWeights(alightIds.value, props.demand.od.stopWeights.alight))
const pins = computed(() => props.demand.od.pinnedSharesPct)
const shares = computed(() => odShares(pairs.value, board.value, alight.value, pins.value))
const maxShare = computed(() => Math.max(0, ...shares.value))
const index = computed(() => {
  const out = new Map<string, number>()
  pairs.value.forEach((p, i) => out.set(`${p.originStopId}\u0000${p.destinationStopId}`, i))
  return out
})
const cellIndex = (o: string, d: string) => index.value.get(`${o}\u0000${d}`) ?? -1
const isPinned = (o: string, d: string) => pins.value[o]?.[d] !== undefined

const rowSum = (o: string) =>
  pairs.value.reduce((s, p, i) => s + (p.originStopId === o ? shares.value[i] : 0), 0)
const colSum = (d: string) =>
  pairs.value.reduce((s, p, i) => s + (p.destinationStopId === d ? shares.value[i] : 0), 0)

const sameWeights = (a: Record<string, number>, b: Record<string, number>) =>
  Object.keys(b).every((k) => a[k] === b[k])
/** Which preset the margins currently spell, or none. */
const activePreset = computed<OdPreset | null>(() => {
  for (const preset of OD_PRESETS) {
    const w = presetWeights(boardIds.value, alightIds.value, preset)
    if (sameWeights(board.value, w.board) && sameWeights(alight.value, w.alight)) return preset
  }
  return null
})

function update(od: Partial<DemandInputs['od']>) {
  emit('update:demand', { ...props.demand, od: { ...props.demand.od, ...od } })
}

function applyPreset(preset: OdPreset) {
  const w = presetWeights(boardIds.value, alightIds.value, preset)
  update({ preset, stopWeights: { board: w.board, alight: w.alight } })
}

function setWeight(side: 'board' | 'alight', stopId: string, event: Event) {
  const raw = parseFloat((event.target as HTMLInputElement).value.replace(',', '.'))
  const value = Math.max(0, Number.isFinite(raw) ? Math.round(raw * 10000) / 10000 : 0)
  update({
    preset: 'custom',
    stopWeights: {
      ...props.demand.od.stopWeights,
      [side]: { ...props.demand.od.stopWeights[side], [stopId]: value },
    },
  })
}

// One cell is edited at a time: click opens a field with the share as it is.
const editing = ref<{ o: string; d: string } | null>(null)
const draft = ref('')
function startEdit(o: string, d: string) {
  const i = cellIndex(o, d)
  if (i < 0) return
  editing.value = { o, d }
  draft.value = (shares.value[i] * 100).toFixed(1)
  nextTick(() => {
    const field = root.value?.querySelector<HTMLInputElement>('input.cell-edit')
    field?.focus()
    field?.select()
  })
}
const root = ref<HTMLElement | null>(null)
function commitEdit() {
  const cell = editing.value
  editing.value = null
  if (!cell) return
  const value = parseFloat(draft.value.replace(',', '.'))
  if (!Number.isFinite(value)) return
  update({
    pinnedSharesPct: pinPair(
      pairs.value,
      board.value,
      alight.value,
      pins.value,
      cell.o,
      cell.d,
      value,
    ),
  })
}
function cancelEdit() {
  editing.value = null
}
function unpinAll() {
  update({ pinnedSharesPct: {} })
}

const pinnedCount = computed(() =>
  Object.values(pins.value).reduce((s, row) => s + Object.keys(row).length, 0),
)
const averageKm = computed(() => averageDistanceKm(pairs.value, shares.value))
const longest = computed(() => {
  let best = -1
  pairs.value.forEach((p, i) => {
    if (best < 0 || p.distanceKm > pairs.value[best].distanceKm) best = i
  })
  return best
})
const shortest = computed(() => {
  let best = -1
  pairs.value.forEach((p, i) => {
    if (best < 0 || p.distanceKm < pairs.value[best].distanceKm) best = i
  })
  return best
})
const busiestBoard = computed(
  () => boardIds.value.map((o) => [o, rowSum(o)] as const).sort((a, b) => b[1] - a[1])[0] ?? null,
)
const busiestAlight = computed(
  () => alightIds.value.map((d) => [d, colSum(d)] as const).sort((a, b) => b[1] - a[1])[0] ?? null,
)
const pairName = (i: number) =>
  i < 0
    ? ''
    : `${names.value[pairs.value[i].originStopId]} – ${names.value[pairs.value[i].destinationStopId]}`
const droppedPins = computed(() => props.block?.od.dropped_pins ?? [])
</script>

<template>
  <DetailPanel
    :title="t('proposal.details.od.title')"
    :info="t('proposal.details.od.info')"
    :caption="t('proposal.details.od.caption')"
  >
    <p v-if="!block" class="text-xs text-primary-50/50">{{ t('proposal.details.od.noRoute') }}</p>
    <div v-else class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_17rem]">
      <div class="flex min-w-0 flex-col gap-2">
        <div class="flex flex-wrap items-center gap-1 text-[11px]">
          <span class="text-primary-50/40">{{ t('proposal.details.od.stopWeights') }}</span>
          <button
            v-for="preset in OD_PRESETS"
            :key="preset"
            type="button"
            class="cursor-pointer rounded-full px-2.5 py-0.5 transition"
            :class="
              activePreset === preset
                ? 'bg-primary-50/15 text-primary-50'
                : 'text-primary-50/55 hover:text-primary-50'
            "
            :aria-pressed="activePreset === preset"
            @click="applyPreset(preset)"
          >
            {{ t(`proposal.details.od.presets.${preset}`) }}
          </button>
          <span class="mx-1 h-3 w-px bg-primary-50/15" />
          <button
            type="button"
            class="cursor-pointer rounded-full px-2.5 py-0.5 text-primary-50/55 transition hover:text-primary-50 disabled:cursor-default disabled:opacity-40"
            :disabled="pinnedCount === 0"
            :title="t('proposal.details.od.unpinAllHint')"
            @click="unpinAll"
          >
            {{ t('proposal.details.od.unpinAll') }}
          </button>
        </div>

        <div ref="root" class="max-h-[32rem] overflow-auto">
          <table class="odm text-[11px] tabular-nums">
            <thead>
              <tr>
                <th class="text-right text-primary-50/50">{{ t('proposal.details.od.corner') }}</th>
                <th v-for="d in alightIds" :key="d" class="text-center text-primary-50/70">
                  {{ names[d] ?? d }}
                  <span class="block text-[9px] font-normal text-primary-50/40">
                    {{ t('proposal.details.od.weight') }}
                    <input
                      class="w-9 rounded border border-primary-50/15 bg-transparent px-1 text-right text-[10px] text-primary-50 outline-none focus:border-sky-300"
                      inputmode="decimal"
                      :value="alight[d]"
                      :aria-label="`${names[d] ?? d} · ${t('proposal.details.od.weight')}`"
                      @change="setWeight('alight', d, $event)"
                    />
                  </span>
                </th>
                <th class="text-center text-primary-50/50">
                  {{ t('proposal.details.od.boards') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in boardIds" :key="o">
                <th class="text-right text-primary-50/70">
                  {{ names[o] ?? o }}
                  <span class="block text-[9px] font-normal text-primary-50/40">
                    {{ t('proposal.details.od.weight') }}
                    <input
                      class="w-9 rounded border border-primary-50/15 bg-transparent px-1 text-right text-[10px] text-primary-50 outline-none focus:border-sky-300"
                      inputmode="decimal"
                      :value="board[o]"
                      :aria-label="`${names[o] ?? o} · ${t('proposal.details.od.weight')}`"
                      @change="setWeight('board', o, $event)"
                    />
                  </span>
                </th>
                <td
                  v-for="d in alightIds"
                  :key="d"
                  :class="cellIndex(o, d) < 0 ? 'x' : 'c'"
                  :style="
                    cellIndex(o, d) >= 0
                      ? { '--a': maxShare ? shares[cellIndex(o, d)] / maxShare : 0 }
                      : undefined
                  "
                  :title="
                    cellIndex(o, d) >= 0
                      ? `${pairName(cellIndex(o, d))} · ${fmt.int(pairs[cellIndex(o, d)].distanceKm)} km${isPinned(o, d) ? ' · ' + t('proposal.details.od.pinned') : ''}`
                      : undefined
                  "
                  @click="
                    cellIndex(o, d) >= 0 &&
                    !(editing?.o === o && editing?.d === d) &&
                    startEdit(o, d)
                  "
                >
                  <template v-if="cellIndex(o, d) < 0">–</template>
                  <input
                    v-else-if="editing?.o === o && editing?.d === d"
                    v-model="draft"
                    class="cell-edit w-11 rounded border border-sky-300 bg-primary-900 px-1 text-right text-[12px] text-primary-50 outline-none"
                    inputmode="decimal"
                    @blur="commitEdit"
                    @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
                    @keydown.esc.prevent="cancelEdit"
                  />
                  <template v-else>
                    <b
                      class="block text-[12px]"
                      :class="previewing ? 'preview-value' : 'text-primary-50'"
                    >
                      {{ fmt.dec1(shares[cellIndex(o, d)] * 100) }} %
                    </b>
                    <small class="block text-[9px] text-primary-50/60"
                      >{{ fmt.int(pairs[cellIndex(o, d)].distanceKm) }} km</small
                    >
                    <i v-if="isPinned(o, d)" class="pin" />
                  </template>
                </td>
                <td class="t text-primary-50/70">{{ fmt.percent(rowSum(o) * 100) }}</td>
              </tr>
              <tr>
                <th class="text-right text-primary-50/50">
                  {{ t('proposal.details.od.alights') }}
                </th>
                <td v-for="d in alightIds" :key="d" class="t text-primary-50/70">
                  {{ fmt.percent(colSum(d) * 100) }}
                </td>
                <td class="t text-primary-50/70">100 %</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="text-[11px] leading-snug text-primary-50/50">
          {{ t('proposal.details.od.hint') }}
        </p>
        <p v-if="droppedPins.length" class="text-[11px] leading-snug text-amber-300">
          {{
            t('proposal.details.od.droppedPins', {
              pairs: droppedPins
                .map(
                  (p) =>
                    `${names[p.origin_stop_id] ?? p.origin_stop_id} – ${names[p.destination_stop_id] ?? p.destination_stop_id}`,
                )
                .join(', '),
            })
          }}
        </p>
      </div>

      <div class="flex flex-col gap-2 border-primary-50/10 xl:border-l xl:pl-4">
        <PreviewChip v-if="previewing" />
        <dl class="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-xs">
          <dt class="text-primary-50/65">{{ t('proposal.details.od.sellablePairs') }}</dt>
          <dd class="text-right tabular-nums text-primary-50">{{ pairs.length }}</dd>
          <dt class="text-primary-50/65">{{ t('proposal.details.od.pinnedPairs') }}</dt>
          <dd
            class="text-right tabular-nums"
            :class="previewing ? 'preview-value' : 'text-primary-50'"
          >
            {{ pinnedCount }}
          </dd>
          <dt class="text-primary-50/65">{{ t('proposal.details.od.averageJourney') }}</dt>
          <dd
            class="text-right tabular-nums"
            :class="previewing ? 'preview-value' : 'text-primary-50'"
          >
            {{ fmt.int(averageKm) }} km
          </dd>
          <template v-if="longest >= 0">
            <dt class="text-primary-50/65">
              {{ t('proposal.details.od.longestPair', { name: pairName(longest) }) }}
            </dt>
            <dd
              class="text-right tabular-nums"
              :class="previewing ? 'preview-value' : 'text-primary-50'"
            >
              {{ fmt.dec1(shares[longest] * 100) }} %
            </dd>
          </template>
          <template v-if="shortest >= 0">
            <dt class="text-primary-50/65">
              {{ t('proposal.details.od.shortestPair', { name: pairName(shortest) }) }}
            </dt>
            <dd
              class="text-right tabular-nums"
              :class="previewing ? 'preview-value' : 'text-primary-50'"
            >
              {{ fmt.dec1(shares[shortest] * 100) }} %
            </dd>
          </template>
          <template v-if="busiestBoard">
            <dt class="text-primary-50/65">{{ t('proposal.details.od.busiestBoarding') }}</dt>
            <dd
              class="text-right tabular-nums"
              :class="previewing ? 'preview-value' : 'text-primary-50'"
            >
              {{ names[busiestBoard[0]] ?? busiestBoard[0] }} ·
              {{ fmt.percent(busiestBoard[1] * 100) }}
            </dd>
          </template>
          <template v-if="busiestAlight">
            <dt class="text-primary-50/65">{{ t('proposal.details.od.busiestAlighting') }}</dt>
            <dd
              class="text-right tabular-nums"
              :class="previewing ? 'preview-value' : 'text-primary-50'"
            >
              {{ names[busiestAlight[0]] ?? busiestAlight[0] }} ·
              {{ fmt.percent(busiestAlight[1] * 100) }}
            </dd>
          </template>
        </dl>
        <p class="text-[11px] leading-snug text-primary-50/45">
          {{ t('proposal.details.od.figuresNote') }}
        </p>
      </div>
    </div>
  </DetailPanel>
</template>

<style scoped>
.odm {
  border-collapse: separate;
  border-spacing: 3px;
}
.odm th {
  font-weight: 400;
  padding: 2px 4px;
  white-space: nowrap;
  vertical-align: bottom;
}
.odm td {
  width: 58px;
  height: 34px;
  border-radius: 5px;
  text-align: center;
  vertical-align: middle;
  padding: 0;
  position: relative;
}
.odm td.c {
  background: rgba(34, 113, 179, calc(0.08 + 0.8 * var(--a)));
  cursor: text;
}
.odm td.x {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.25);
}
.odm td.t {
  font-size: 10px;
}
.odm .pin::after {
  content: '●';
  position: absolute;
  top: 2px;
  right: 4px;
  font-size: 7px;
  color: var(--color-amber-300);
}
.preview-value {
  color: var(--color-amber-300);
  font-style: italic;
}
</style>
