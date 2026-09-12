<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { mdiChevronDown, mdiChevronRight, mdiInformationOutline } from '@mdi/js'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import type { LedgerRow } from '@/lib/ledgerRows'

// The one table shape both ledgers use: a collapsing tree with a chevron
// gutter, the label, its share of the panel total, and the euros — the same
// four columns as the Kassenzettel receipts in zone D, so a reader moving
// between them is reading one table, not two.
//
// Alignment is the point of having it. Cost and revenue had drifted into
// different gutters, and inside revenue the rows without a chevron sat at a
// hand-counted indent that did not line up with the rows that had one. Here
// EVERY row spends the same 20 px on the chevron column, whether it has one
// or not, so every label starts on the same pixel and depth is the only thing
// that moves it.

defineProps<{
  title: string
  total: number
  rows: LedgerRow[]
  /** Node keys that have a formula page behind the ⓘ. */
  hasInfo: (key: string) => boolean
}>()
const emit = defineEmits<{
  toggle: [key: string]
  info: [key: string, label: string, event: Event]
  infoClose: []
}>()

const { t } = useI18n()
const { formatEur, formatShare } = useEvaluationFormat()
</script>

<template>
  <div class="min-w-0 flex-1 rounded-xl bg-primary-50/5 p-4">
    <div class="mb-2 flex items-center gap-1 border-b border-primary-50/10 pb-2">
      <span class="w-5 shrink-0" />
      <span class="flex-1 font-semibold text-primary-50">{{ title }}</span>
      <span class="w-12 text-right text-xs tabular-nums text-primary-50/40">
        {{ formatShare(1) }}
      </span>
      <span class="w-24 text-right font-semibold tabular-nums text-primary-50">
        {{ formatEur(total) }}
      </span>
    </div>

    <div
      v-for="row in rows"
      :key="row.key"
      class="flex items-center gap-1 py-1"
      :style="{ paddingLeft: `${row.depth * 16}px` }"
    >
      <button
        v-if="row.hasChildren"
        type="button"
        class="flex w-5 shrink-0 cursor-pointer justify-center text-primary-50/40 transition hover:text-primary-50"
        :aria-expanded="row.isExpanded"
        @click="emit('toggle', row.key)"
      >
        <AppIcon :path="row.isExpanded ? mdiChevronDown : mdiChevronRight" :size="16" />
      </button>
      <!-- Same width whether or not there is a chevron: this is what keeps
           every label on one left edge. -->
      <span v-else class="flex w-5 shrink-0 justify-center">
        <i v-if="row.color" class="h-2.5 w-2.5 rounded-sm" :style="{ background: row.color }" />
      </span>

      <span
        class="flex flex-1 items-center gap-1 text-sm"
        :class="row.depth === 0 || row.hasChildren ? 'text-primary-50' : 'text-primary-50/70'"
      >
        {{ row.label }}
        <button
          v-if="hasInfo(row.key)"
          type="button"
          class="flex cursor-pointer text-primary-50/40 transition hover:text-primary-50"
          :aria-label="t('proposal.evaluation.info.iconLabel')"
          @mouseenter="emit('info', row.key, row.label, $event)"
          @mouseleave="emit('infoClose')"
          @click="emit('info', row.key, row.label, $event)"
        >
          <AppIcon :path="mdiInformationOutline" :size="14" />
        </button>
      </span>

      <span class="w-12 text-right text-xs tabular-nums text-primary-50/40">
        {{ formatShare(row.share) }}
      </span>
      <!-- No colour on a signed figure: every other row in both ledgers is
           plain, and one green line in a column of neutral ones reads as a
           status rather than as a sign. The leading + carries the sign. -->
      <span class="w-24 text-right text-sm tabular-nums text-primary-50">
        <template v-if="row.signed && row.value > 0">+ </template>{{ formatEur(row.value) }}
      </span>
    </div>
  </div>
</template>
