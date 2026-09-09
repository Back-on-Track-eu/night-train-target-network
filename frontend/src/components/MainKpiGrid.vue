<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ProposalCalcSummary } from '@/types/api'
import { COMPARE_KPIS, isImprovement, relativeDelta, subsidyDisplay } from '@/lib/compareKpis'
import { useCompareFormat } from '@/composables/useCompareFormat'

// Zone A's headline: the eight main KPIs of the member on screen, each with
// its change against the baseline member (base network, nothing switched on,
// same composition) once the family has delivered it. Values come from the
// summary of the member on screen; the baseline is a comparison only. Surplus rule (lib/compareKpis.ts subsidyDisplay): a
// profitable route reads "none · surplus X", never a negative subsidy.
const props = defineProps<{
  summary: ProposalCalcSummary
  baseline: ProposalCalcSummary | null
  isBaseline: boolean
}>()

const { t } = useI18n()
const fmt = useCompareFormat()

const net = computed(() => subsidyDisplay(props.summary))

const tiles = computed(() =>
  COMPARE_KPIS.map((kpi) => {
    const value = kpi.value(props.summary)
    const base = props.baseline ? kpi.value(props.baseline) : null
    const delta = props.isBaseline ? null : relativeDelta(value, base)
    return {
      kpi,
      value,
      label: value === null ? '—' : kpi.format(value, fmt),
      unit: kpi.unitKey ? t(`proposal.compare.units.${kpi.unitKey}`) : '',
      delta,
      better: delta === null ? null : isImprovement(kpi, delta),
    }
  }),
)
</script>

<template>
  <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
    <div
      v-for="tile in tiles"
      :key="tile.kpi.key"
      class="flex flex-col gap-0.5 rounded-lg border border-primary-50/10 bg-sapphire-100/60 p-3"
      :class="tile.kpi.key === 'subsidy' ? 'border-amber-400/40' : ''"
    >
      <span class="text-xs text-primary-50/60">{{
        t(`proposal.compare.kpis.${tile.kpi.labelKey}`)
      }}</span>

      <!-- Necessary subsidy: the one tile with its own wording for a surplus. -->
      <template v-if="tile.kpi.key === 'subsidy'">
        <span v-if="net.kind === 'subsidy'" class="text-xl font-semibold text-amber-300">
          {{ fmt.millionEur(net.millionEur) }}
          <small class="text-xs font-normal text-primary-50/60">{{ tile.unit }}</small>
        </span>
        <span v-else-if="net.kind === 'surplus'" class="text-xl font-semibold text-yellow-green">
          {{ t('proposal.compare.none') }}
          <small class="text-xs font-normal text-primary-50/60">
            {{ t('proposal.compare.surplus', { value: fmt.millionEur(net.millionEur) }) }}
            {{ tile.unit }}
          </small>
        </span>
        <span v-else class="text-xl font-semibold text-primary-50/50">—</span>
      </template>

      <!-- Subsidy per tonne reads "0 · no subsidy" on a surplus route. -->
      <template v-else-if="tile.kpi.key === 'subsidyPerT' && net.kind === 'surplus'">
        <span class="text-xl font-semibold text-yellow-green">
          0
          <small class="text-xs font-normal text-primary-50/60"
            >{{ tile.unit }} · {{ t('proposal.compare.noSubsidy') }}</small
          >
        </span>
      </template>

      <span v-else class="text-xl font-semibold text-primary-50">
        {{ tile.label }}
        <small v-if="tile.unit" class="text-xs font-normal text-primary-50/60">{{
          tile.unit
        }}</small>
      </span>

      <span
        class="text-[11px]"
        :class="
          tile.delta === null
            ? 'text-primary-50/40'
            : tile.better
              ? 'text-yellow-green'
              : 'text-amber-300'
        "
      >
        <template v-if="isBaseline">{{ t('proposal.compare.isBaseline') }}</template>
        <template v-else-if="tile.delta === null">{{
          t('proposal.compare.noBaselineYet')
        }}</template>
        <template v-else
          >{{ fmt.signedPercent(tile.delta) }} {{ t('proposal.compare.vsBaseline') }}</template
        >
      </span>
    </div>
  </div>
</template>
