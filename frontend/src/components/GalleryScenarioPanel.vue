<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Popover from 'primevue/popover'
import { mdiChevronDown, mdiChevronRight } from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import ScenarioSwitches from '@/components/ScenarioSwitches.vue'
import { buildScenarioAxes, conditionLabelKey } from '@/lib/scenarioAxes'
import type { Scenario } from '@/types/api'

// The gallery's scenario picker: the same switches the builder uses
// (ScenarioSwitches.vue, driven by lib/scenarioAxes.ts) in a popover behind
// one pill — "Figures for Infra 2026 · Base" — at the head of the results,
// beside the sort, because that is what it changes. The pill states the
// current scenario, so "which figures am I looking at?" is answered without
// opening anything. On a phone the Filters sheet shows it as a full-width
// row instead (`row`), which asks the sheet to open its own scenario screen
// rather than a popover.
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
  /** The Filters sheet's row: emits `open` instead of opening the popover. */
  row?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [scenarioId: number]; open: [] }>()

const { t } = useI18n()
const popover = ref<InstanceType<typeof Popover> | null>(null)
// Closing when the source switch moves to existing-only keeps a greyed panel
// from sitting open on controls that would do nothing.
watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) popover.value?.hide()
  },
)

// Same look as the card's stat popover (ProposalCard.vue).
const popoverPt = {
  root: {
    class:
      'z-50 !rounded-xl !border !border-primary-50/20 !bg-sapphire-100 !shadow-xl before:!hidden after:!hidden',
  },
  content: { class: '!p-4 !bg-transparent' },
}

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
</script>

<template>
  <button
    v-if="row"
    type="button"
    class="flex min-h-13 w-full items-center justify-between gap-3 rounded-xl bg-primary-50/[0.06] px-4 text-left text-[15px] text-primary-50 transition"
    :class="disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer hover:bg-primary-50/10'"
    :disabled="disabled"
    @click="emit('open')"
  >
    <span class="flex flex-col">
      {{ summary }}
      <span v-if="withoutFigures" class="text-xs text-amber-300/80">
        {{ t('gallery.scenario.withoutFigures', withoutFigures) }}
      </span>
    </span>
    <AppIcon :path="mdiChevronRight" :size="18" class="shrink-0 text-primary-50/60" />
  </button>
  <button
    v-else
    type="button"
    class="flex items-center gap-2 rounded-full bg-primary-50/[0.06] px-3 py-1.5 text-sm leading-none whitespace-nowrap text-primary-50/85 transition"
    :class="disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer hover:bg-primary-50/10'"
    aria-haspopup="dialog"
    :disabled="disabled"
    :title="disabled ? t('gallery.scenario.disabledHint') : undefined"
    @click="popover?.toggle($event)"
  >
    <span class="text-primary-50/55">{{ t('gallery.scenario.label') }}</span>
    <span v-if="summary">{{ summary }}</span>
    <span v-if="withoutFigures" class="text-xs text-amber-300/80">
      {{ t('gallery.scenario.withoutFigures', withoutFigures) }}
    </span>
    <AppIcon :path="mdiChevronDown" :size="16" class="text-primary-50/50" />
  </button>
  <Popover v-if="!row" ref="popover" :pt="popoverPt">
    <div class="flex w-[min(64rem,calc(100vw-3rem))] flex-col gap-4">
      <p class="text-xs leading-relaxed text-primary-50/60">
        {{ t('gallery.scenario.hint') }}
      </p>
      <ScenarioSwitches
        :scenarios="scenarios"
        :model-value="modelValue"
        @update:model-value="emit('update:modelValue', $event)"
      />
    </div>
  </Popover>
</template>
