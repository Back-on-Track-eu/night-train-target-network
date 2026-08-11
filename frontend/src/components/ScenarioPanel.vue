<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Select from 'primevue/select'
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
  <div v-if="store.scenarios.length > 0" class="scenario-gold-box rounded-xl p-4">
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
