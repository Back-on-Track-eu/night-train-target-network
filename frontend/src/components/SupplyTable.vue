<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Composition, FamilyMember } from '@/types/api'
import { subsidyDisplay } from '@/lib/compareKpis'
import { CLASS_ICONS, classColor } from '@/lib/compositionFormation'
import { useCompareFormat } from '@/composables/useCompareFormat'

// Zone D, Train operation tab: the catalog as a table to compare and choose
// from —
// every composition evaluated on the current route under the selected
// scenario (the matrix row byComposition(scenarioId)). Filters by fleet
// kind, sortable columns, the selected row highlighted in place. The
// selected one's own figures are the panel below it, not an overlay: the
// overlay is gone, and with it the ⓘ column that opened it.
//
// Trainsets lead, because that is the first question a reader has about a
// composition on THIS route rather than in the catalog; the two density
// columns (m and t per place) replace the catalog's indicative unit costs,
// which said the same thing about every route.
//
// "Fit to demand" is in the header but not selectable (a "coming soon"
// chip) until the Demand tab's utilisation ladder lands (manual demand
// inputs, phase D): DEMAND 0.1.0 does tell the compositions apart, and the
// ladder is where that comparison is drawn.
const props = defineProps<{
  compositions: Composition[]
  cells: Map<string, FamilyMember>
  selectedCompositionId: string | null
}>()
const emit = defineEmits<{ select: [compositionId: string] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

type Filter = 'all' | 'new' | 'refurbished' | 'hsr'
type SortKey =
  | 'subsidy'
  | 'eurTrainKm'
  | 'eurPlaceKm'
  | 'places'
  | 'trainsets'
  | 'densityLength'
  | 'densityWeight'
const filter = ref<Filter>('all')
const sortKey = ref<SortKey>('subsidy')
const sortDir = ref<1 | -1>(1)

const rows = computed(() =>
  props.compositions
    .filter((c) => {
      if (filter.value === 'new') return c.material_strategy === 'new'
      if (filter.value === 'refurbished') return c.material_strategy === 'refurbished'
      if (filter.value === 'hsr') return c.routing.hsr_allowed
      return true
    })
    .map((composition) => {
      const cell = props.cells.get(`${composition.composition_id}`)
      const summary = cell?.status === 'ok' ? cell.summary : null
      const placeKm = summary?.available_place_km_per_year ?? null
      const cost = summary?.cost_eur_per_train_km ?? null
      const trainKm = summary?.train_km_per_year ?? null
      const net = summary ? subsidyDisplay(summary) : null
      return {
        composition,
        summary,
        error: cell?.status === 'error' ? cell.error : null,
        pending: cell === undefined,
        places: composition.capacity.total_places,
        // This route's own fleet under the current schedule — the summary's,
        // not a catalog figure.
        trainsets: summary?.trainsets_physical ?? null,
        densityLength: composition.capacity.avg_density_length_m_per_place,
        densityWeight: composition.capacity.avg_density_weight_t_per_place,
        eurTrainKm: cost,
        // €/place-km from the annual totals, in cents: cost per train-km ×
        // train-km / available place-km.
        ctPlaceKm: cost !== null && trainKm && placeKm ? (cost * trainKm * 100) / placeKm : null,
        net,
        subsidySort:
          net === null ? Infinity : net.kind === 'subsidy' ? net.millionEur : -net.millionEur,
        classMix: CLASS_ICONS.map(([classMain]) => ({
          classMain,
          color: classColor(classMain),
          share:
            composition.capacity.total_places > 0
              ? (composition.capacity.by_class[classMain]?.places ?? 0) /
                composition.capacity.total_places
              : 0,
        })).filter((m) => m.share > 0),
      }
    }),
)

const sorted = computed(() => {
  const key = sortKey.value
  const dir = sortDir.value
  const value = (r: (typeof rows.value)[number]) =>
    key === 'subsidy'
      ? r.subsidySort
      : key === 'eurTrainKm'
        ? (r.eurTrainKm ?? Infinity)
        : key === 'eurPlaceKm'
          ? (r.ctPlaceKm ?? Infinity)
          : key === 'trainsets'
            ? (r.trainsets ?? Infinity)
            : key === 'densityLength'
              ? r.densityLength
              : key === 'densityWeight'
                ? r.densityWeight
                : r.places
  // The selected row keeps its place in the order. It used to be lifted to the
  // top, which made "where does my train rank" — the question this table is
  // for — unanswerable at a glance; the highlight is what marks it.
  return [...rows.value].sort((a, b) => (value(a) - value(b)) * dir)
})

function sortBy(key: SortKey) {
  if (sortKey.value === key) sortDir.value = sortDir.value === 1 ? -1 : 1
  else {
    sortKey.value = key
    sortDir.value = key === 'places' ? -1 : 1
  }
}

const FILTERS: Filter[] = ['all', 'new', 'refurbished', 'hsr']
const headerClass =
  'cursor-pointer select-none px-2 py-1.5 text-left text-[11px] font-normal text-primary-50/60 hover:text-primary-50'
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex flex-wrap items-center gap-1">
      <button
        v-for="f in FILTERS"
        :key="f"
        type="button"
        class="cursor-pointer rounded-full px-2.5 py-0.5 text-xs transition"
        :class="
          filter === f
            ? 'bg-primary-50/15 text-primary-50'
            : 'text-primary-50/60 hover:text-primary-50'
        "
        :aria-pressed="filter === f"
        @click="filter = f"
      >
        {{ t(`proposal.supply.filters.${f}`) }}
      </button>
    </div>

    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="sticky top-0 bg-sapphire">
          <tr class="align-bottom">
            <th :class="headerClass" @click="sortBy('trainsets')">
              {{ t('proposal.supply.columns.trainsets')
              }}<span v-if="sortKey === 'trainsets'">{{ sortDir === 1 ? ' ↑' : ' ↓' }}</span>
            </th>
            <th :class="headerClass">{{ t('proposal.supply.columns.composition') }}</th>
            <th :class="headerClass" @click="sortBy('places')">
              {{ t('proposal.supply.columns.places')
              }}<span v-if="sortKey === 'places'">{{ sortDir === 1 ? ' ↑' : ' ↓' }}</span>
            </th>
            <th :class="headerClass" @click="sortBy('eurTrainKm')">
              {{ t('proposal.supply.columns.eurTrainKm')
              }}<span v-if="sortKey === 'eurTrainKm'">{{ sortDir === 1 ? ' ↑' : ' ↓' }}</span>
              <span class="block text-[9px] text-primary-50/40">
                {{ t('proposal.supply.units.eurPerTrainKm') }}
              </span>
            </th>
            <th :class="headerClass" @click="sortBy('densityLength')">
              {{ t('proposal.supply.columns.densityLength')
              }}<span v-if="sortKey === 'densityLength'">{{ sortDir === 1 ? ' ↑' : ' ↓' }}</span>
              <span class="block text-[9px] text-primary-50/40">
                {{ t('proposal.supply.units.metresPerPlace') }}
              </span>
            </th>
            <th :class="headerClass" @click="sortBy('densityWeight')">
              {{ t('proposal.supply.columns.densityWeight')
              }}<span v-if="sortKey === 'densityWeight'">{{ sortDir === 1 ? ' ↑' : ' ↓' }}</span>
              <span class="block text-[9px] text-primary-50/40">
                {{ t('proposal.supply.units.tonnesPerPlace') }}
              </span>
            </th>
            <th :class="headerClass" @click="sortBy('eurPlaceKm')">
              {{ t('proposal.supply.columns.ctPlaceKm')
              }}<span v-if="sortKey === 'eurPlaceKm'">{{ sortDir === 1 ? ' ↑' : ' ↓' }}</span>
              <span class="block text-[9px] text-primary-50/40">
                {{ t('proposal.supply.units.centPerPlaceKm') }}
              </span>
            </th>
            <!-- Not selectable until the utilisation ladder (Demand tab) carries it. -->
            <th
              class="cursor-not-allowed px-2 py-1.5 text-left text-[11px] font-normal text-primary-50/35"
              :title="t('proposal.supply.fitHint')"
              aria-disabled="true"
            >
              {{ t('proposal.supply.columns.fit') }}
              <span class="ml-1 rounded-full border border-primary-50/20 px-1.5 py-px text-[9px]">
                {{ t('proposal.compare.comingSoon') }}
              </span>
            </th>
            <th :class="headerClass" @click="sortBy('subsidy')">
              {{ t('proposal.supply.columns.subsidy')
              }}<span v-if="sortKey === 'subsidy'">{{ sortDir === 1 ? ' ↑' : ' ↓' }}</span>
              <span class="block text-[9px] text-primary-50/40">
                {{ t('proposal.supply.units.perYear') }}
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in sorted"
            :key="row.composition.composition_id"
            class="cursor-pointer border-t border-primary-50/10 transition hover:bg-primary-50/5"
            :class="
              row.composition.composition_id === selectedCompositionId ? 'bg-amber-400/10' : ''
            "
            @click="emit('select', row.composition.composition_id)"
          >
            <td class="px-2 py-1.5 font-semibold tabular-nums text-primary-50">
              {{ row.trainsets === null ? '…' : fmt.int(row.trainsets) }}
            </td>
            <td class="px-2 py-1.5">
              <div class="flex flex-col gap-1">
                <span class="font-semibold text-primary-50">{{
                  row.composition.composition_id
                }}</span>
                <span class="max-w-52 truncate text-[11px] text-primary-50/60">{{
                  row.composition.description
                }}</span>
                <span class="flex h-1 w-40 overflow-hidden rounded">
                  <span
                    v-for="m in row.classMix"
                    :key="m.classMain"
                    :style="{ width: `${m.share * 100}%`, background: m.color }"
                    :title="`${t(`proposal.evaluation.classes.${m.classMain}`)} ${fmt.percent(m.share * 100)}`"
                  />
                </span>
              </div>
            </td>
            <td class="px-2 py-1.5 text-primary-50/85">{{ fmt.int(row.places) }}</td>
            <td class="px-2 py-1.5 text-primary-50/85">
              <template v-if="row.eurTrainKm !== null">{{ fmt.eur2(row.eurTrainKm) }}</template>
              <span
                v-else-if="row.error"
                class="text-red-300"
                :title="t(`proposal.compare.cellErrors.${row.error}`, row.error)"
                >✕</span
              >
              <span v-else class="text-primary-50/30">…</span>
            </td>
            <td class="px-2 py-1.5 tabular-nums text-primary-50/70">
              {{ fmt.dec2(row.densityLength) }}
            </td>
            <td class="px-2 py-1.5 tabular-nums text-primary-50/70">
              {{ fmt.dec2(row.densityWeight) }}
            </td>
            <td class="px-2 py-1.5 text-primary-50/85">
              <template v-if="row.ctPlaceKm !== null">
                {{ fmt.dec2(row.ctPlaceKm) }}
              </template>
              <span v-else class="text-primary-50/30">…</span>
            </td>
            <td class="px-2 py-1.5 text-primary-50/30">—</td>
            <td class="px-2 py-1.5">
              <template v-if="row.net">
                <span v-if="row.net.kind === 'subsidy'" class="text-amber-300">{{
                  fmt.millionEur(row.net.millionEur)
                }}</span>
                <span v-else-if="row.net.kind === 'surplus'" class="text-yellow-green">
                  {{ t('proposal.compare.none') }} ·
                  {{ t('proposal.compare.surplus', { value: fmt.millionEur(row.net.millionEur) }) }}
                </span>
                <span v-else class="text-primary-50/30">—</span>
              </template>
              <span v-else class="text-primary-50/30">…</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
