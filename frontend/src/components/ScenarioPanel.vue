<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import { useStore } from '@/stores/store'
import { selectPillPt } from '@/lib/selectPillPt'

// Scenario selector — its own golden box; the only control that changes
// EffectPanel below it (it triggers a full recompute), unlike ViewRow's cube
// dropdowns. Reads/writes the store directly since the selection is global
// app state, not something the parent needs to mediate.
const { t } = useI18n()
const store = useStore()

const selectedScenario = computed(
  () => store.scenarios.find((s) => s.scenario_id === store.selectedScenarioId) ?? null,
)
</script>

<template>
  <!-- Loading: keep the box and its footprint, so the panel doesn't pop into
       existence and shove everything below it down. -->
  <div v-if="store.scenariosStatus === 'loading'" class="scenario-gold-box rounded-xl p-4">
    <div class="flex justify-center">
      <Skeleton width="12rem" height="2.25rem" border-radius="9999px" />
    </div>
    <Skeleton width="70%" height="0.875rem" class="!mt-3" />
  </div>

  <!-- Failure has to be visible, not just an absent control: with no scenario
       loaded, selectedScenarioId stays null and the calc runs against the LIVE
       BASE instead of whatever the user assumes is selected. Silently omitting
       the panel would change the numbers without saying so. -->
  <div v-else-if="store.scenariosFailure" class="scenario-gold-box rounded-xl p-4" role="alert">
    <p class="text-sm leading-relaxed text-amber-200">{{ t('errors.scenariosUnavailable') }}</p>
    <button
      type="button"
      class="mt-2 cursor-pointer text-sm font-semibold text-primary-50 underline underline-offset-2"
      @click="store.fetchScenarios()"
    >
      {{ t('errors.retry') }}
    </button>
  </div>

  <!-- Loaded and genuinely empty stays hidden — an empty list is not an error. -->
  <div v-else-if="store.scenarios.length > 0" class="scenario-gold-box rounded-xl p-4">
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
    <p v-if="selectedScenario?.description" class="mt-3 text-sm leading-relaxed text-primary-50/70">
      {{ selectedScenario.description }}
    </p>
  </div>
</template>

<style scoped>
/* A soft golden wash + hairline gold border around the selector + its
   description. */
.scenario-gold-box {
  background: linear-gradient(
    135deg,
    color-mix(in srgb, #fcd34d 12%, transparent) 0%,
    color-mix(in srgb, #fbbf24 6%, transparent) 100%
  );
  border: 1px solid color-mix(in srgb, #fbbf24 25%, transparent);
}
</style>
