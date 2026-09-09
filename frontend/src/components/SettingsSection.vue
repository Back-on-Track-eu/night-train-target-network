<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { Composition, MatrixCell, ProposalCalcSummary } from '@/types/api'
import { buildFormation } from '@/lib/compositionFormation'
import CompositionFormation from '@/components/CompositionFormation.vue'
import SupplyTable from '@/components/SupplyTable.vue'
import SupplySidebar from '@/components/SupplySidebar.vue'
import AppIcon from '@/components/AppIcon.vue'
import { mdiChevronDown } from '@mdi/js'

// Zone D — collapsible "Detail settings", tabs Supply / Demand. Supply is
// where a composition is compared and chosen (SupplyTable over the family's
// members for the current scenario, the formation drawing of the selected one,
// the frequency & supply sidebar). Demand explains what the demand figures
// rest on rather than shipping empty — the model is a stopgap.
const props = defineProps<{
  compositions: Composition[]
  cellsByComposition: Map<string, MatrixCell>
  selectedCompositionId: string | null
  summary: ProposalCalcSummary | null
  scheduleMode: string | null
}>()
const emit = defineEmits<{ selectComposition: [compositionId: string] }>()

const { t } = useI18n()
const store = useStore()
const open = ref(false)
const tab = ref<'supply' | 'demand'>('supply')

const selected = computed(
  () => props.compositions.find((c) => c.composition_id === props.selectedCompositionId) ?? null,
)
const formation = computed(() =>
  selected.value
    ? buildFormation(
        selected.value,
        store.compositionCatalog.coach_types,
        store.compositionCatalog.classes,
      )
    : null,
)
</script>

<template>
  <details
    class="group rounded-xl border border-primary-50/10"
    :open="open"
    @toggle="open = ($event.target as HTMLDetailsElement).open"
  >
    <summary class="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3">
      <span class="flex flex-col">
        <span class="text-base font-semibold text-primary-50">{{
          t('proposal.settings.title')
        }}</span>
        <span class="text-xs text-primary-50/60">{{ t('proposal.settings.body') }}</span>
      </span>
      <AppIcon
        :path="mdiChevronDown"
        :size="20"
        class="text-primary-50/60 transition group-open:rotate-180"
      />
    </summary>
    <div class="flex flex-col gap-3 border-t border-primary-50/10 px-4 py-3">
      <div class="inline-flex w-fit rounded-full border border-primary-50/15 p-0.5" role="tablist">
        <button
          v-for="key in ['supply', 'demand'] as const"
          :key="key"
          type="button"
          role="tab"
          class="cursor-pointer rounded-full px-3 py-1 text-xs transition"
          :class="tab === key ? 'bg-primary-50/15 text-primary-50' : 'text-primary-50/60'"
          :aria-selected="tab === key"
          @click="tab = key"
        >
          {{ t(`proposal.settings.tabs.${key}`) }}
        </button>
      </div>

      <div v-if="tab === 'supply'" class="grid gap-4 lg:grid-cols-[1fr_16rem]">
        <div class="flex flex-col gap-3">
          <div v-if="formation && selected" class="rounded-lg border border-primary-50/10 p-3">
            <p class="mb-1 text-xs text-primary-50/60">
              {{ t('proposal.settings.selectedFormation', { composition: selected.description }) }}
            </p>
            <CompositionFormation :formation="formation" :selected="null" />
          </div>
          <SupplyTable
            :compositions="compositions"
            :cells="cellsByComposition"
            :selected-composition-id="selectedCompositionId"
            @select="(id) => emit('selectComposition', id)"
          />
        </div>
        <SupplySidebar
          v-if="summary"
          :summary="summary"
          :composition-places="selected?.capacity.total_places ?? null"
          :schedule-mode="scheduleMode"
        />
      </div>

      <div v-else class="flex flex-col gap-2 text-sm text-primary-50/70">
        <p>{{ t('proposal.settings.demand.intro') }}</p>
        <ul class="list-disc pl-5 text-xs">
          <li>{{ t('proposal.settings.demand.source') }}</li>
          <li>{{ t('proposal.settings.demand.prices') }}</li>
          <li>{{ t('proposal.settings.demand.modes') }}</li>
        </ul>
        <p class="text-xs text-primary-50/50">{{ t('proposal.settings.demand.placeholder') }}</p>
      </div>
    </div>
  </details>
</template>
