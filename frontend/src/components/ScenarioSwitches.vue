<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Scenario } from '@/types/api'
import { buildScenarioAxes, type ScenarioSwitchState } from '@/lib/scenarioAxes'
import InfoHint from '@/components/InfoHint.vue'

// Zone A's controls: the scenario as three switches instead of a dropdown of
// six names. Every switch state maps to one scenario (lib/scenarioAxes.ts);
// a switch is disabled when no scenario exists for the state it would
// produce. The value is the scenario_id, so the store's selectedScenarioId
// stays the single source of truth.
//
// The third row — price & regulatory measures (VAT exemption, energy-tax
// exemption, track access at direct cost) — is rendered disabled with a
// "coming soon" hint: those are evaluation-only parameters the backend does
// not model yet (docs/PARKED_WORK.md §3, WP17). VITE_FEATURE_MEASURES hides
// the row entirely for deployments that prefer not to show it.
//
// A network can carry the same "coming soon" treatment while its
// infrastructure data is still being worked on (lib/scenarioAxes.ts
// PREVIEW_NETWORKS — Infra 2032 today): the routing instance runs and the
// backend would evaluate against it, but we do not put figures on screen we
// would not stand behind.
const props = defineProps<{
  scenarios: Scenario[]
  modelValue: number | null
}>()
const emit = defineEmits<{ 'update:modelValue': [scenarioId: number] }>()

const { t } = useI18n()

const axes = computed(() => buildScenarioAxes(props.scenarios))
const state = computed<ScenarioSwitchState | null>(() =>
  props.modelValue === null ? null : axes.value.stateOf(props.modelValue),
)

const showMeasures = import.meta.env.VITE_FEATURE_MEASURES !== 'off'
const MEASURES = ['vat', 'energyTax', 'tac'] as const

function select(next: ScenarioSwitchState) {
  const scenario = axes.value.scenarioFor(next)
  if (scenario) emit('update:modelValue', scenario.scenario_id)
}

function setNetwork(network: string) {
  if (!state.value) return
  select({ ...state.value, network })
}

function toggle(key: 'hsr' | 'optTt') {
  if (!state.value) return
  const next = { ...state.value, [key]: !state.value[key] }
  // Turning HSR off takes optimised timetables with it — it does not exist
  // without HSR in the offered grid (scenarioAxes decides, this only tidies).
  if (key === 'hsr' && !next.hsr && next.optTt) next.optTt = false
  select(next)
}

const previewNetwork = computed(() => axes.value.networks.find((n) => n.preview) ?? null)

const toggleClass = (on: boolean, disabled: boolean) =>
  [
    'relative inline-flex h-5 w-9 shrink-0 rounded-full border transition',
    on ? 'border-amber-400 bg-amber-400' : 'border-primary-50/15 bg-sapphire-200',
    disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
  ].join(' ')

const knobClass = (on: boolean) =>
  [
    'absolute top-0.5 h-3.5 w-3.5 rounded-full transition',
    on ? 'left-[1.15rem] bg-sapphire' : 'left-0.5 bg-primary-50',
  ].join(' ')
</script>

<template>
  <div v-if="state" class="grid gap-x-10 gap-y-6 sm:grid-cols-3">
    <!-- Rail network -->
    <fieldset class="flex flex-col gap-3">
      <legend class="mb-3 text-xs tracking-wide text-primary-50/50 uppercase">
        {{ t('proposal.compare.axes.network') }}
      </legend>
      <div class="flex flex-wrap items-center gap-2">
        <div
          class="inline-flex rounded-full border border-primary-50/15 bg-sapphire-100 p-0.5"
          role="group"
        >
          <button
            v-for="option in axes.networks"
            :key="option.network"
            type="button"
            class="rounded-full px-3.5 py-1 text-sm transition"
            :class="[
              state.network === option.network
                ? 'bg-amber-400 font-semibold text-sapphire'
                : 'text-primary-50/70 hover:text-primary-50',
              axes.canSelectNetwork(state, option.network)
                ? 'cursor-pointer'
                : 'cursor-not-allowed opacity-40',
            ]"
            :aria-pressed="state.network === option.network"
            :disabled="!axes.canSelectNetwork(state, option.network)"
            @click="setNetwork(option.network)"
          >
            {{ t('proposal.compare.axes.infra', { network: option.network }) }}
          </button>
        </div>
        <!-- Outside the control, so the segmented bar stays the width of its
             two labels. The ⓘ carries the "why" on hover. -->
        <span
          v-if="previewNetwork"
          class="flex items-center gap-1 rounded-full border border-primary-50/20 px-2 py-0.5 text-[10px] text-primary-50/50"
        >
          {{ t('proposal.compare.comingSoon') }}
          <InfoHint :text="t('proposal.compare.axes.networkPreviewHint')" />
        </span>
      </div>
    </fieldset>

    <!-- Operating conditions -->
    <fieldset class="flex flex-col gap-3">
      <legend class="mb-3 text-xs tracking-wide text-primary-50/50 uppercase">
        {{ t('proposal.compare.axes.conditions') }}
      </legend>
      <label class="flex cursor-pointer items-center gap-2.5 text-sm text-primary-50/85">
        <button
          type="button"
          role="switch"
          :aria-checked="state.hsr"
          :class="toggleClass(state.hsr, !axes.canToggle(state, 'hsr'))"
          :disabled="!axes.canToggle(state, 'hsr')"
          @click="toggle('hsr')"
        >
          <span :class="knobClass(state.hsr)" />
        </button>
        {{ t('proposal.compare.axes.hsr') }}
      </label>
      <label
        class="flex items-center gap-2.5 text-sm"
        :class="
          axes.canToggle(state, 'optTt')
            ? 'cursor-pointer text-primary-50/85'
            : 'text-primary-50/40'
        "
        :title="
          axes.canToggle(state, 'optTt') ? undefined : t('proposal.compare.axes.optTtNeedsHsr')
        "
      >
        <button
          type="button"
          role="switch"
          :aria-checked="state.optTt"
          :class="toggleClass(state.optTt, !axes.canToggle(state, 'optTt'))"
          :disabled="!axes.canToggle(state, 'optTt')"
          @click="toggle('optTt')"
        >
          <span :class="knobClass(state.optTt)" />
        </button>
        {{ t('proposal.compare.axes.optTt') }}
      </label>
    </fieldset>

    <!-- Price & regulatory measures — not modelled yet (WP17). -->
    <fieldset v-if="showMeasures" class="flex flex-col gap-3" aria-disabled="true">
      <legend
        class="mb-3 flex items-center gap-2 text-xs tracking-wide text-primary-50/50 uppercase"
      >
        {{ t('proposal.compare.axes.measures') }}
        <span
          class="flex items-center gap-1 rounded-full border border-primary-50/20 px-2 py-0.5 text-[10px] normal-case tracking-normal"
        >
          {{ t('proposal.compare.comingSoon') }}
          <InfoHint :text="t('proposal.compare.axes.measuresHint')" />
        </span>
      </legend>
      <span
        v-for="measure in MEASURES"
        :key="measure"
        class="flex items-center gap-2.5 text-sm text-primary-50/40"
      >
        <span :class="toggleClass(false, true)" aria-hidden="true">
          <span :class="knobClass(false)" />
        </span>
        {{ t(`proposal.compare.axes.measure.${measure}`) }}
      </span>
    </fieldset>
  </div>
</template>
