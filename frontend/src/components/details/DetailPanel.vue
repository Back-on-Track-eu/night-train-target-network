<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoHint from '@/components/InfoHint.vue'

// The one panel shape every box inside the Details card uses: a title row with
// EXACTLY ONE ⓘ carrying that panel's whole explanation, an optional
// right-aligned caption, the waiting badge, then content.
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
  // Reserved for the documentation deep link the ⓘ will carry once the
  // per-figure pages exist (docs/2026-09-09_supply_settings_plan.md). Passed
  // through so the panels can already name their page.
  docPath?: string | null
}>()

const { t } = useI18n()
const hint = computed(() => props.info)
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
        <InfoHint :text="hint" />
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
