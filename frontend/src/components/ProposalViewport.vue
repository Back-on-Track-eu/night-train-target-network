<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { Stop } from '@/types/api'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import AppIcon from '@/components/AppIcon.vue'
import StopSelect from '@/components/StopSelect.vue'
import { mdiPencil, mdiPlus, mdiTrashCan } from '@mdi/js'

defineProps<{ mode: 'edit' | 'display' }>()

const { t } = useI18n()
const store = useStore()

interface ItineraryStop {
  id: number
  name: string
  selectedStop: Stop | null
}

const itinerary = ref<ItineraryStop[]>([])

let _nextId = 1

function onRowReorder(event: { value: ItineraryStop[] }) {
  itinerary.value = event.value
}

function onStopSelect(stop: ItineraryStop, selected: Stop) {
  stop.name = selected.name
  stop.selectedStop = selected
}

function removeStop(index: number) {
  itinerary.value.splice(index, 1)
}

function dist(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const dLat = a.lat - b.lat
  const dLon = a.lon - b.lon
  return Math.sqrt(dLat * dLat + dLon * dLon)
}

function optimalInsertIndex(stop: Stop): number {
  const items = itinerary.value
  const n = items.length
  if (n === 0) return 0

  const coords = (item: ItineraryStop) => item.selectedStop ?? { lat: 0, lon: 0 }

  let bestIndex = n
  let bestExtra = Infinity

  for (let i = 0; i <= n; i++) {
    let extra: number
    if (i === 0) {
      extra = dist(stop, coords(items[0]))
    } else if (i === n) {
      extra = dist(coords(items[n - 1]), stop)
    } else {
      const prev = coords(items[i - 1])
      const next = coords(items[i])
      extra = dist(prev, stop) + dist(stop, next) - dist(prev, next)
    }
    if (extra < bestExtra) {
      bestExtra = extra
      bestIndex = i
    }
  }

  return bestIndex
}

function addStop(stop: Stop) {
  const index = optimalInsertIndex(stop)
  itinerary.value.splice(index, 0, {
    id: _nextId++,
    name: stop.name,
    selectedStop: stop,
  })
}

// PrimeVue's row-reorder only activates when the user mousedowns its own hidden
// handle element. We forward a synthetic event from the whole row so any drag
// gesture moves the row. The [data-row-actions] guard prevents the forward when
// the user is clicking the dropdown or remove button.
function onRowMouseDown(event: MouseEvent) {
  if ((event.target as HTMLElement).closest('[data-row-actions]')) return
  const row = (event.currentTarget as HTMLElement).closest('tr')
  const handle = row?.querySelector('[data-pc-section="reorderableRowHandle"]')
  if (handle) {
    handle.dispatchEvent(
      new MouseEvent('mousedown', {
        bubbles: true,
        cancelable: true,
        clientX: event.clientX,
        clientY: event.clientY,
      }),
    )
  }
}

onMounted(async () => {
  await store.fetchStops()
  if (store.stops.length >= 2) {
    const shuffled = [...store.stops].sort(() => Math.random() - 0.5)
    itinerary.value = [
      { id: _nextId++, name: shuffled[0].name, selectedStop: shuffled[0] },
      { id: _nextId++, name: shuffled[1].name, selectedStop: shuffled[1] },
    ]
  }
  store.fetchCompositions()
})
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="flex gap-6">
      <!-- Left panel -->
      <div class="flex w-2/5 flex-col gap-4">
        <div class="itinerary-table px-4">
          <!-- Add Stop button — top-right, edit mode only -->
          <div v-if="mode === 'edit'" class="flex justify-end">
            <StopSelect :stops="store.stops" @select="addStop">
              <button
                class="flex cursor-pointer items-center gap-1.5 rounded-full px-3 py-1.5 text-sm text-primary-50 transition hover:bg-primary-50/10"
              >
                <AppIcon :path="mdiPlus" :size="16" />
                {{ t('proposal.addStop') }}
              </button>
            </StopSelect>
          </div>
          <!-- border-collapse (set in pt.table) removes default cell spacing so
               the timeline line segments in consecutive rows connect seamlessly. -->
          <DataTable
            :value="itinerary"
            :reorderable-rows="mode === 'edit'"
            data-key="id"
            :pt="{
              table: { class: 'w-full border-collapse' },
              thead: { class: 'hidden' },
              row: { class: '!bg-transparent border-0' },
              bodyCell: { class: '!bg-transparent border-0 !p-0' },
            }"
            @row-reorder="onRowReorder"
          >
            <Column
              v-if="mode === 'edit'"
              row-reorder
              style="width: 2rem"
              :pt="{
                bodyCell: { class: 'reorder-col !p-0' },
                reorderableRowHandle: { style: { color: 'var(--p-primary-50)' } },
              }"
            />
            <Column style="width: 2.5rem" :pt="{ bodyCell: { class: 'timeline-col !p-0' } }">
              <template #body="{ index }">
                <div class="absolute inset-0 flex items-center justify-center">
                  <div
                    class="absolute left-1/2 w-0.5 -translate-x-1/2 bg-primary-50/30"
                    :class="[
                      index === 0 ? 'top-1/2' : 'top-0',
                      index === itinerary.length - 1 ? 'bottom-1/2' : 'bottom-0',
                    ]"
                  />
                  <div
                    class="relative z-10 rounded-full bg-primary-50"
                    :class="index === 0 || index === itinerary.length - 1 ? 'h-4 w-4' : 'h-3 w-3'"
                  />
                </div>
              </template>
            </Column>
            <Column field="name">
              <template #body="{ data: stop, index }">
                <div
                  class="group flex cursor-default select-none items-center gap-2 rounded-lg px-3 py-2"
                  @mousedown="onRowMouseDown"
                >
                  <span
                    :class="[
                      'text-primary-50 leading-tight',
                      index === 0 || index === itinerary.length - 1
                        ? 'text-2xl font-bold'
                        : 'text-lg font-semibold',
                    ]"
                  >
                    {{ stop.name }}
                  </span>

                  <div v-if="mode === 'edit'" data-row-actions class="flex items-center">
                    <StopSelect :stops="store.stops" @select="(s) => onStopSelect(stop, s)">
                      <AppIcon :path="mdiPencil" :size="20" color="var(--p-primary-50)" />
                    </StopSelect>

                    <span
                      class="inline-flex"
                      :title="itinerary.length <= 2 ? t('proposal.minStopsTooltip') : undefined"
                    >
                      <button
                        class="flex items-center justify-center text-primary-50 opacity-0 translate-x-[-8px] transition-all duration-200 ease-out group-hover:translate-x-0"
                        :class="
                          itinerary.length <= 2
                            ? 'cursor-not-allowed pointer-events-none group-hover:opacity-30'
                            : 'cursor-pointer group-hover:opacity-100'
                        "
                        :disabled="itinerary.length <= 2"
                        @click.stop="removeStop(index)"
                      >
                        <AppIcon :path="mdiTrashCan" :size="20" />
                      </button>
                    </span>
                  </div>
                </div>
              </template>
            </Column>
          </DataTable>
        </div>

        <!-- Train card placeholder -->
        <div
          class="flex h-32 items-center justify-center rounded-xl bg-primary-50/5 text-sm text-primary-50/40"
        >
          {{ t('proposal.trainCardPlaceholder') }}
        </div>

        <!-- JSON preview -->
        <div
          v-if="store.stopsStatus === 'success' || store.compositionsStatus === 'success'"
          class="rounded-xl bg-primary-50/5 p-4 text-xs text-primary-50/60"
        >
          <p v-if="store.stopsStatus === 'success'" class="mb-1 font-bold text-primary-50/80">
            {{ t('proposal.debugStopsPreview') }}
          </p>
          <pre v-if="store.stopsStatus === 'success'" class="mb-4 overflow-auto">{{
            JSON.stringify(store.stops.slice(0, 2), null, 2)
          }}</pre>
          <p
            v-if="store.compositionsStatus === 'success'"
            class="mb-1 font-bold text-primary-50/80"
          >
            {{ t('proposal.debugCompositionsPreview') }}
          </p>
          <pre v-if="store.compositionsStatus === 'success'" class="overflow-auto">{{
            JSON.stringify(store.compositions.slice(0, 2), null, 2)
          }}</pre>
        </div>

        <div
          v-if="store.stopsStatus === 'loading' || store.compositionsStatus === 'loading'"
          class="text-xs text-primary-50/40"
        >
          {{ t('proposal.loading') }}
        </div>
        <div v-if="store.stopsError || store.compositionsError" class="text-xs text-red-400">
          {{ store.stopsError ?? store.compositionsError }}
        </div>
      </div>

      <!-- Right panel: map placeholder -->
      <div
        class="flex flex-1 items-center justify-center rounded-xl bg-primary-50/5 text-sm text-primary-50/40"
        style="min-height: 480px"
      >
        {{ t('proposal.mapPlaceholder') }}
      </div>
    </div>

    <!-- Evaluate button (edit mode only) -->
    <div v-if="mode === 'edit'" class="flex justify-center">
      <button
        class="flex items-center gap-2 rounded-full bg-primary-50/10 px-6 py-2 text-sm text-primary-50 transition hover:bg-primary-50/20"
      >
        {{ t('proposal.evaluate') }} <span>→</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
:deep(.p-datatable-table) {
  background: transparent;
}
:deep(.p-datatable-tbody > tr),
:deep(.p-datatable-tbody > tr > td) {
  background: transparent !important;
  border: none !important;
  font-size: inherit !important;
  user-select: none;
}
/* Timeline column: must be position:relative so absolute children span full cell height */
:deep(.timeline-col) {
  position: relative !important;
}
/* Drag handle: hover-only */
:deep(.reorder-col > *) {
  opacity: 0;
  transition: opacity 0.2s ease;
}
:deep(tr:hover .reorder-col > *) {
  opacity: 1;
}
</style>
