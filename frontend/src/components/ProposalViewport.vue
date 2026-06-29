<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { Stop } from '@/types/api'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Select from 'primevue/select'
import AppIcon from '@/components/AppIcon.vue'
import { mdiMagnify, mdiPencil, mdiTrashCan } from '@mdi/js'

defineProps<{ mode: 'edit' | 'display' }>()

const { t } = useI18n()
const store = useStore()

interface ItineraryStop {
  id: number
  name: string
  selectedStop: Stop | null
  filterQuery: string
}

const itinerary = ref<ItineraryStop[]>([])

let _nextId = 1

// Plain array, not ref([]). Mutating a reactive ref inside a template-ref callback
// re-triggers Vue's reactivity on every render → infinite loop inside DataTable.
const selectRefs: Array<InstanceType<typeof Select> | null> = []

function onRowReorder(event: { value: ItineraryStop[] }) {
  itinerary.value = event.value
}

function onStopSelect(stop: ItineraryStop, selected: Stop) {
  stop.name = selected.name
  stop.selectedStop = selected
  stop.filterQuery = ''
}

// We own the search input (no PrimeVue `filter` prop), so we re-derive the same
// filter expression here rather than reading PrimeVue's internal filtered list.
function onSearchEnter(stop: ItineraryStop, index: number) {
  const filtered = store.stops.filter(
    (s) => !stop.filterQuery || s.name.toLowerCase().includes(stop.filterQuery.toLowerCase()),
  )
  if (!filtered.length) return
  onStopSelect(stop, filtered[0])
  selectRefs[index]?.hide()
}

function removeStop(index: number) {
  itinerary.value.splice(index, 1)
  selectRefs.splice(index, 1)
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
      { id: _nextId++, name: shuffled[0].name, selectedStop: shuffled[0], filterQuery: '' },
      { id: _nextId++, name: shuffled[1].name, selectedStop: shuffled[1], filterQuery: '' },
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
                    <!-- append-to="body" teleports the overlay out of the table so it
                         isn't clipped by the table's overflow / stacking context. -->
                    <Select
                      :ref="
                        (el: any) => {
                          selectRefs[index] = el
                        }
                      "
                      v-model="stop.selectedStop"
                      :options="
                        store.stops.filter(
                          (s) =>
                            !stop.filterQuery ||
                            s.name.toLowerCase().includes(stop.filterQuery.toLowerCase()),
                        )
                      "
                      option-label="name"
                      append-to="body"
                      :pt="{
                        root: { class: '!bg-transparent !border-0 !shadow-none !outline-none' },
                        label: { class: '!hidden' },
                        dropdown: { class: '!bg-transparent !border-0 !shadow-none !outline-none' },
                        overlay: {
                          class: 'itinerary-select-overlay !rounded-xl !shadow-2xl min-w-[260px]',
                        },
                        listContainer: { class: '!max-h-80' },
                        list: { class: '!bg-transparent !p-1.5' },
                        option: {
                          class:
                            '!rounded-lg !px-4 !py-3 !text-base !text-primary-50 !cursor-pointer',
                        },
                        optionLabel: { class: '!text-primary-50 !text-base' },
                        emptyMessage: { class: '!text-primary-50 !px-4 !py-3 !text-base' },
                      }"
                      @update:model-value="(val: Stop) => onStopSelect(stop, val)"
                    >
                      <template #dropdownicon>
                        <AppIcon :path="mdiPencil" :size="20" color="var(--p-primary-50)" />
                      </template>
                      <template #header>
                        <div
                          class="flex items-center gap-2.5 px-3 py-3"
                          style="border-bottom: 1px solid var(--p-primary-50)"
                        >
                          <AppIcon
                            :path="mdiMagnify"
                            :size="13"
                            color="color-mix(in srgb, var(--p-primary-50) 70%, transparent)"
                            class="shrink-0"
                          />
                          <input
                            v-model="stop.filterQuery"
                            type="text"
                            :placeholder="t('proposal.searchPlaceholder')"
                            @keydown.enter.prevent="onSearchEnter(stop, index)"
                            style="
                              flex: 1;
                              background: transparent;
                              border: none;
                              outline: none;
                              box-shadow: none;
                              color: var(--p-primary-50);
                              font-size: 1rem;
                              padding: 0;
                              font-family: inherit;
                            "
                          />
                        </div>
                      </template>
                    </Select>

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
:deep(.p-select) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}
/* PrimeVue dims the dropdown trigger in its Aura theme; force full opacity so
   the chevron stays visible against our dark background at all times. */
:deep(.p-select-dropdown) {
  color: var(--p-primary-50) !important;
  opacity: 1 !important;
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

<style>
/* ── Select overlay (teleports to <body>) ── */
/* ── Overlay shell ── */
.itinerary-select-overlay {
  border: 1px solid var(--p-primary-50) !important;
}

/* ── Scrollbar ── */
.itinerary-select-overlay * {
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--p-primary-50) 50%, transparent) transparent;
}
.itinerary-select-overlay *::-webkit-scrollbar {
  width: 5px !important;
}
.itinerary-select-overlay *::-webkit-scrollbar-track {
  background: transparent !important;
}
.itinerary-select-overlay *::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--p-primary-50) 50%, transparent) !important;
  border-radius: 99px !important;
}
.itinerary-select-overlay *::-webkit-scrollbar-button {
  display: none !important;
}

/* ── Option states (background fallbacks; colours come from definePreset tokens) ── */
.itinerary-select-overlay [data-pc-section='option'][data-p-focused='true'] {
  background: #2b2e4a !important;
}
.itinerary-select-overlay [data-pc-section='option'][data-p-selected='true'] {
  background: #363a58 !important;
}
.itinerary-select-overlay
  [data-pc-section='option'][data-p-selected='true'][data-p-focused='true'] {
  background: #41466e !important;
}
</style>
