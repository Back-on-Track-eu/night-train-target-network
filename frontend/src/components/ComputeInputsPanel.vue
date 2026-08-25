<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import CompositionPanel from '@/components/CompositionPanel.vue'
import { useStore } from '@/stores/store'
import { selectPillPt } from '@/lib/selectPillPt'
import type { Composition } from '@/types/api'

// The two inputs a computed route was produced from: the scenario (which
// version of every parameter table) and the composition (which train). Both
// trigger a recompute, unlike ViewRow's cube dropdowns which only re-slice
// results that already exist — which is why they sit together here, in the
// workspace that owns recompute, rather than inside EvaluationPanel.
//
// Scenario is global app state and read straight from the store; the
// composition belongs to the proposal on screen and is mediated by the parent.
defineProps<{
  compositions: Composition[]
  selectedCompositionId: string | null
}>()
const emit = defineEmits<{ selectComposition: [compId: string] }>()

const { t } = useI18n()
const store = useStore()

const selectedScenario = computed(
  () => store.scenarios.find((s) => s.scenario_id === store.selectedScenarioId) ?? null,
)
</script>

<template>
  <!-- One box each, side by side: they are peers, and the scenario's
       description would otherwise stretch a shared box around a one-line
       composition card. items-stretch keeps the two the same height. -->
  <div class="grid grid-cols-1 items-stretch gap-4 sm:grid-cols-2">
    <!-- display:contents so the state chain stays one grid cell, not three. -->
    <div class="contents">
      <!-- Loading: hold the box and its footprint, so the panel doesn't pop
           into existence and shove everything below it down. -->
      <div
        v-if="store.scenariosStatus === 'loading'"
        class="scenario-gold-box flex flex-col justify-center gap-3 rounded-xl p-4"
      >
        <div class="flex justify-center">
          <Skeleton width="12rem" height="2.25rem" border-radius="9999px" />
        </div>
        <Skeleton width="70%" height="0.875rem" />
      </div>

      <!-- Failure has to be visible, not just an absent control: with no
           scenario loaded, selectedScenarioId stays null and the calc runs
           against the LIVE BASE instead of whatever the user assumes is
           selected. Silently omitting the box would change the numbers
           without saying so. -->
      <div
        v-else-if="store.scenariosFailure"
        class="scenario-gold-box flex flex-col justify-center gap-2 rounded-xl p-4"
        role="alert"
      >
        <p class="text-sm leading-relaxed text-amber-200">{{ t('errors.scenariosUnavailable') }}</p>
        <button
          type="button"
          class="cursor-pointer text-sm font-semibold text-primary-50 underline underline-offset-2"
          @click="store.fetchScenarios()"
        >
          {{ t('errors.retry') }}
        </button>
      </div>

      <!-- Loaded and genuinely empty stays hidden — an empty list is not an
           error. -->
      <div
        v-else-if="store.scenarios.length > 0"
        class="scenario-gold-box flex flex-col justify-center gap-3 rounded-xl p-4"
      >
        <div class="flex justify-center">
          <Select
            v-model="store.selectedScenarioId"
            :options="store.scenarios"
            option-value="scenario_id"
            option-label="scenario_name"
            :aria-label="t('proposal.evaluation.scenario')"
            :unstyled="true"
            :pt="selectPillPt"
          />
        </div>
        <p v-if="selectedScenario?.description" class="text-sm leading-relaxed text-primary-50/70">
          {{ selectedScenario.description }}
        </p>
      </div>
    </div>

    <CompositionPanel
      v-if="compositions.length > 0"
      :compositions="compositions"
      :selected-id="selectedCompositionId"
      @select="(id) => emit('selectComposition', id)"
    />
  </div>
</template>

<style scoped>
/* A soft golden wash + hairline gold border around the selectors + the
   scenario description. */
.scenario-gold-box {
  background: linear-gradient(
    135deg,
    color-mix(in srgb, #fcd34d 12%, transparent) 0%,
    color-mix(in srgb, #fbbf24 6%, transparent) 100%
  );
  border: 1px solid color-mix(in srgb, #fbbf24 25%, transparent);
}
</style>
