<script setup lang="ts">
import { computed } from 'vue'
import { useStore } from '@/stores/store'
import type { Composition, DemandBlock } from '@/types/api'
import { type DemandInputs } from '@/lib/detailsScope'
import PotentialDemandPanel from '@/components/details/PotentialDemandPanel.vue'
import TravellerGroupsPanel from '@/components/details/TravellerGroupsPanel.vue'
import UtilisationLadder from '@/components/details/UtilisationLadder.vue'
import OdMatrixPanel from '@/components/details/OdMatrixPanel.vue'

// Demand — the four panels of D3, top to bottom: Potential demand and Demand
// by traveller group side by side, then Utilisation by composition, then
// Demand by OD pair. This tab OWNS the demand scope: every panel previews
// the demand as it is edited (the client-side ports of the allocation and
// the OD spread) and says so; nothing here waits. The demand lives in the
// store because it is posted with every family request and saved with the
// proposal; the panels hand back whole DemandInputs, which keeps each edit
// one immutable replacement.
const props = defineProps<{
  compositions: Composition[]
  selectedCompositionId: string | null
  /** The backend's demand block for the selected composition — the OD
   *  structure (which pairs sell, names, journeys) comes from it. */
  committedBlock: DemandBlock | null
  daysPerWeek: number
  departures: number
  previewing: boolean
}>()
const emit = defineEmits<{ selectComposition: [id: string]; goToSupply: [] }>()

const store = useStore()

const demand = computed<DemandInputs | null>(() => store.demand)
const levels = computed(() => store.demandDefaults?.levels ?? {})
const selected = computed(
  () => props.compositions.find((c) => c.composition_id === props.selectedCompositionId) ?? null,
)

function apply(next: DemandInputs) {
  store.demand = next
}
</script>

<template>
  <div v-if="demand" class="flex flex-col gap-3">
    <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <PotentialDemandPanel
        :demand="demand"
        :levels="levels"
        :previewing="previewing"
        :departures="departures"
        :days-per-week="daysPerWeek"
        :selected-composition-id="selectedCompositionId"
        :selected-places="selected?.capacity.total_places ?? 0"
        @update:demand="apply"
      />
      <TravellerGroupsPanel
        :demand="demand"
        :departures="departures"
        :previewing="previewing"
        @update:demand="apply"
      />
    </div>
    <UtilisationLadder
      :compositions="compositions"
      :demand="demand"
      :departures="departures"
      :days-per-week="daysPerWeek"
      :selected-composition-id="selectedCompositionId"
      :previewing="previewing"
      @select-composition="(id) => emit('selectComposition', id)"
      @go-to-supply="emit('goToSupply')"
    />
    <OdMatrixPanel
      :demand="demand"
      :block="committedBlock"
      :previewing="previewing"
      @update:demand="apply"
    />
  </div>
</template>
