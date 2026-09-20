<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DemandInputs } from '@/lib/detailsScope'
import { GROUP_CLASS_PREFERENCES, GROUP_ORDER, RULE_SHARE } from '@/lib/demandAllocation'
import { classColor } from '@/lib/compositionFormation'
import { useCompareFormat } from '@/composables/useCompareFormat'
import DetailPanel from '@/components/details/DetailPanel.vue'
import PreviewChip from '@/components/details/PreviewChip.vue'

// Demand · Demand by traveller group (D14, D15): the five groups in
// allocation order, the share of the total each asks for (editable), what
// that is per year and per trip, and the classes each books in order of
// preference. A share sum other than 100 is allowed and shown in amber —
// the groups then ask for total × sum; nothing rebalances by itself.
const props = defineProps<{
  demand: DemandInputs
  departures: number
  previewing: boolean
}>()
const emit = defineEmits<{ 'update:demand': [demand: DemandInputs] }>()

const { t } = useI18n()
const fmt = useCompareFormat()

const sum = computed(() =>
  GROUP_ORDER.reduce((s, g) => s + (props.demand.groupSharesPct[g] ?? 0), 0),
)
const sumOff = computed(() => Math.abs(sum.value - 100) > 0.01)

const rows = computed(() =>
  GROUP_ORDER.map((g) => {
    const share = props.demand.groupSharesPct[g] ?? 0
    const perYear = (props.demand.passengersPerYear * share) / 100
    return {
      key: g,
      share,
      perYear,
      perTrip: props.departures > 0 ? perYear / props.departures : 0,
      classes: GROUP_CLASS_PREFERENCES[g],
    }
  }),
)

function setShare(group: string, event: Event) {
  const raw = parseFloat((event.target as HTMLInputElement).value.replace(',', '.'))
  const share = Math.max(0, Number.isFinite(raw) ? Math.round(raw * 10) / 10 : 0)
  emit('update:demand', {
    ...props.demand,
    groupSharesPct: { ...props.demand.groupSharesPct, [group]: share },
  })
}
</script>

<template>
  <DetailPanel
    :title="t('proposal.details.groupsPanel.title')"
    :info="t('proposal.details.groupsPanel.info')"
    :caption="t('proposal.details.groupsPanel.caption')"
  >
    <PreviewChip v-if="previewing" />
    <div class="overflow-x-auto">
      <table class="w-full border-collapse text-[11px] tabular-nums">
        <thead>
          <tr class="text-primary-50/50">
            <th class="py-1 pr-2 text-left font-normal">
              {{ t('proposal.details.groupsPanel.group') }}
            </th>
            <th class="px-1.5 py-1 text-right font-normal">
              {{ t('proposal.details.groupsPanel.share') }}
            </th>
            <th class="px-1.5 py-1 text-right font-normal">
              {{ t('proposal.details.groupsPanel.perYear') }}
            </th>
            <th class="px-1.5 py-1 text-right font-normal">
              {{ t('proposal.details.groupsPanel.perTrip') }}
            </th>
            <th class="pl-2 py-1 text-left font-normal">
              {{ t('proposal.details.groupsPanel.classes') }}
            </th>
          </tr>
        </thead>
        <tbody :class="previewing ? 'preview-value' : 'text-primary-50'">
          <tr v-for="row in rows" :key="row.key" class="border-t border-primary-50/8">
            <td class="py-0.5 pr-2 text-left">{{ t(`proposal.details.groups.${row.key}`) }}</td>
            <td class="px-1.5 py-0.5 text-right whitespace-nowrap">
              <input
                class="w-12 rounded border border-primary-50/15 bg-transparent px-1 py-px text-right text-[11px] text-primary-50 outline-none focus:border-sky-300"
                inputmode="decimal"
                :value="row.share"
                :aria-label="t(`proposal.details.groups.${row.key}`)"
                @change="setShare(row.key, $event)"
              />
              %
            </td>
            <td class="px-1.5 py-0.5 text-right">{{ fmt.int(row.perYear) }}</td>
            <td class="px-1.5 py-0.5 text-right">{{ fmt.int(row.perTrip) }}</td>
            <td class="pl-2 py-0.5 text-left whitespace-nowrap">
              <span class="inline-flex items-center gap-1">
                <i
                  v-for="(c, i) in row.classes"
                  :key="c"
                  class="h-2 w-2 rounded-sm"
                  :style="{ background: classColor(c), opacity: 1 - i * 0.3 }"
                  :title="t(`proposal.evaluation.classes.${c}`)"
                />
                <small class="text-primary-50/50">
                  {{ row.classes.map((c) => t(`proposal.evaluation.classes.${c}`)).join(' › ') }}
                </small>
              </span>
            </td>
          </tr>
          <tr class="border-t border-primary-50/20 font-semibold">
            <td class="py-0.5 pr-2 text-left">{{ t('proposal.details.groupsPanel.all') }}</td>
            <td class="px-1.5 py-0.5 text-right" :class="sumOff ? 'text-amber-300' : ''">
              {{ fmt.dec1(sum) }} %
            </td>
            <td class="px-1.5 py-0.5 text-right">
              {{ fmt.int((demand.passengersPerYear * sum) / 100) }}
            </td>
            <td class="px-1.5 py-0.5 text-right">
              {{
                fmt.int(departures > 0 ? (demand.passengersPerYear * sum) / 100 / departures : 0)
              }}
            </td>
            <td />
          </tr>
        </tbody>
      </table>
    </div>
    <p class="text-[11px] leading-snug text-primary-50/50">
      <span v-if="sumOff" class="text-amber-300">
        {{
          t('proposal.details.groupsPanel.sumOff', {
            sum: fmt.dec1(sum),
            n: fmt.int((demand.passengersPerYear * sum) / 100),
          })
        }}
      </span>
      {{
        t('proposal.details.groupsPanel.rule', {
          rule: Math.round(RULE_SHARE * 100),
          rest: Math.round((1 - RULE_SHARE) * 100),
        })
      }}
    </p>
  </DetailPanel>
</template>

<style scoped>
.preview-value {
  color: var(--color-amber-300);
  font-style: italic;
}
</style>
