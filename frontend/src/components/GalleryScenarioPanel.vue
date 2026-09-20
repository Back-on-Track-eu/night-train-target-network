<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { mdiChevronDown, mdiTuneVariant } from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import ScenarioSwitches from '@/components/ScenarioSwitches.vue'
import { buildScenarioAxes, conditionLabelKey } from '@/lib/scenarioAxes'
import type { Scenario } from '@/types/api'

// The gallery's scenario picker: the same switches the builder uses
// (ScenarioSwitches.vue, driven by lib/scenarioAxes.ts), collapsed to one
// line until someone opens it.
//
// Collapsed by default, and that is a layout decision as much as an
// editorial one: the gallery's results row is sized to the viewport minus
// everything above it (Gallery.vue's measureRow), so an always-open panel
// would cost the map its height for a control most readers never touch.
// The summary line states the current scenario, so "which figures am I
// looking at?" is answered without opening anything.
//
// What it changes is where the FIGURES come from, never which routes are
// listed: every proposal is stored once per scenario variant (backend
// §5.4a) and the request joins that variant's figures onto the same rows
// the base returns — the same filter, the same cards, other numbers. A card
// the scenario has no figures for says so instead of disappearing.
// Existing (ONTD) trains are scenario-independent and unaffected.
const props = defineProps<{
  scenarios: Scenario[]
  /** Selected scenario id; null while the scenarios are still loading. */
  modelValue: number | null
  /** Loaded rows the chosen scenario has no figures for (not evaluable on
   *  that network, or not yet backfilled). They stay listed — the count is
   *  the header's way of saying why some cards carry a note instead. */
  withoutFigures?: number
  /** The list shows existing trains only: nothing here applies to them, so
   *  the panel is shown greyed and closed rather than hidden — a control
   *  that vanishes with the source switch is a control nobody can find. */
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [scenarioId: number] }>()

const { t } = useI18n()
const open = ref(false)
// Closing when the source switch moves to existing-only keeps a greyed panel
// from sitting open on controls that would do nothing.
watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) open.value = false
  },
)

const axes = computed(() => buildScenarioAxes(props.scenarios))
const state = computed(() =>
  props.modelValue === null ? null : axes.value.stateOf(props.modelValue),
)

// "Infra 2026 · Base" — network and the two operating levers, in the same
// words the builder's comparison axis uses.
const summary = computed(() => {
  if (!state.value) return null
  const network = t('proposal.compare.axes.infra', { network: state.value.network })
  const condition = t(`proposal.compare.conditionsShort.${conditionLabelKey(state.value)}`)
  return `${network} · ${condition}`
})

const isBase = computed(() => {
  if (props.modelValue === null) return true
  return props.scenarios.find((s) => s.scenario_id === props.modelValue)?.is_current_base ?? false
})
</script>

<template>
  <div
    class="w-full rounded-xl border border-primary-50/10 bg-primary-50/[0.03] transition-opacity"
    :class="disabled ? 'opacity-40' : ''"
    :aria-disabled="disabled"
  >
    <button
      type="button"
      class="flex w-full items-center gap-2 px-4 py-2 text-sm text-primary-50/70 transition"
      :class="disabled ? 'cursor-not-allowed' : 'cursor-pointer hover:text-primary-50'"
      :aria-expanded="open"
      :disabled="disabled"
      :title="disabled ? t('gallery.scenario.disabledHint') : undefined"
      @click="open = !open"
    >
      <AppIcon :path="mdiTuneVariant" :size="16" class="shrink-0 text-primary-50/40" />
      <span class="text-primary-50/50">{{ t('gallery.scenario.label') }}</span>
      <span v-if="summary" class="font-semibold text-primary-50">{{ summary }}</span>
      <!-- Always on: which rows a scenario reaches is the one thing a reader
           can get wrong here, and the existing-only case greys the whole
           panel to say the same thing louder. -->
      <span
        class="rounded-full border border-primary-50/15 px-2 py-0.5 text-[0.65rem] uppercase tracking-wider text-primary-50/45"
      >
        {{ t('gallery.scenario.proposalsOnly') }}
      </span>
      <!-- Only when it is NOT the base: on the base the figures are the ones
           every other surface shows, and saying so would be noise. -->
      <span v-if="!isBase" class="text-xs text-primary-50/50">
        {{ t('gallery.scenario.applied') }}
      </span>
      <span v-if="withoutFigures" class="text-xs text-amber-300/80">
        {{ t('gallery.scenario.withoutFigures', withoutFigures) }}
      </span>
      <AppIcon
        :path="mdiChevronDown"
        :size="18"
        class="ml-auto shrink-0 text-primary-50/40 transition-transform"
        :class="open ? 'rotate-180' : ''"
      />
    </button>

    <div v-if="open" class="border-t border-primary-50/10 px-4 py-4">
      <p class="mb-4 text-xs leading-relaxed text-primary-50/50">
        {{ t('gallery.scenario.hint') }}
      </p>
      <ScenarioSwitches
        :scenarios="scenarios"
        :model-value="modelValue"
        @update:model-value="emit('update:modelValue', $event)"
      />
    </div>
  </div>
</template>
