<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoHint from '@/components/InfoHint.vue'
import ReportProblemLink from '@/components/ReportProblemLink.vue'
import { useDetailsTabReport } from '@/composables/useDetailsTabReport'

// The one panel shape every box inside the Details card uses: a title row with
// EXACTLY ONE ⓘ carrying that panel's whole explanation, the report icon,
// an optional right-aligned caption, the waiting badge, then content.
//
// The report icon needs no prop: DetailsSection provides the active tab's
// report topic (useDetailsTabReport), and since tabs render with v-if, every
// panel on screen belongs to that tab. The panel's own title goes into the
// report's subject.
//
// overflow-hidden is load-bearing, not decoration: the card is available from
// the lg breakpoint up, and at the narrow end of that range a receipt table
// would otherwise run out of its box. Tables go in the `scroll` slot wrapper
// (or their own overflow-x-auto) so they scroll inside the panel instead.
const props = defineProps<{
  title: string
  info: string
  caption?: string | null
  awaiting?: boolean
  /** The documentation page the ⓘ hands over to, when the panel has one. */
  docPath?: string | null
}>()

const { t } = useI18n()
const hint = computed(() => props.info)
const reportTopic = useDetailsTabReport()
</script>

<template>
  <section
    class="detail-panel flex flex-col gap-2 overflow-hidden rounded-lg border border-primary-50/10 p-3 transition-opacity duration-200"
    :class="awaiting ? 'awaiting opacity-45' : ''"
    :data-awaiting="awaiting ? 'true' : undefined"
  >
    <header class="flex flex-wrap items-center gap-x-2 gap-y-1">
      <h4 class="flex items-center gap-1.5 text-sm font-semibold text-primary-50">
        {{ title }}
        <InfoHint :text="hint" :docs-href="docPath ?? undefined" />
        <ReportProblemLink v-if="reportTopic" :topic="reportTopic" :panel="title" />
      </h4>
      <span
        v-if="awaiting"
        class="rounded-full bg-amber-400/20 px-2 py-px text-[10px] whitespace-nowrap text-amber-200"
      >
        {{ t('proposal.details.awaiting') }}
      </span>
      <span v-if="caption" class="ml-auto truncate text-[11px] text-primary-50/50">
        {{ caption }}
      </span>
    </header>
    <slot />
  </section>
</template>
