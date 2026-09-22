<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoPopover from '@/components/InfoPopover.vue'
import DocsReadMore from '@/components/DocsReadMore.vue'
import FeedbackLink from '@/components/FeedbackLink.vue'
import { DOCS_PRICE_BASIS } from '@/lib/docsLinks'
import type { ReportPanel } from '@/lib/feedbackLink'

// The "2032 prices" sticker on a headline that puts euros on screen. Every
// cost and fare is in 2032 money, escalated from its source's own price year
// — except the purchase price of the rolling stock, which stays at the 2026
// contract basis. That is easy to miss and changes how a figure compares with
// anything a reader knows from today, so it is said on the headline itself,
// not only in an overlay: the sticker is the statement, the overlay behind
// it (hover or focus) is the explanation, the docs page the full account.
//
// Amber like the other "mind this" chips (stale results, coming soon), so it
// reads as a caveat rather than a decoration.
defineProps<{
  /** Which feedback topic a reader's remark lands under. */
  feedbackTopic: ReportPanel
}>()

const { t } = useI18n()
const popover = ref<InstanceType<typeof InfoPopover> | null>(null)
</script>

<template>
  <span class="inline-flex items-center" @click.stop>
    <button
      type="button"
      class="cursor-help rounded-full border border-amber-400/40 bg-amber-400/10 px-2 py-px text-[10px] leading-4 font-normal whitespace-nowrap text-amber-200 transition hover:bg-amber-400/20"
      :aria-label="t('proposal.priceBasis.hint')"
      @mouseenter="popover?.open($event)"
      @mouseleave="popover?.scheduleClose()"
      @focus="popover?.open($event)"
      @blur="popover?.scheduleClose()"
      @click="popover?.open($event)"
    >
      {{ t('proposal.priceBasis.badge') }}
    </button>
    <InfoPopover ref="popover">
      <div class="flex w-72 flex-col">
        <p class="text-sm text-primary-50/75">{{ t('proposal.priceBasis.hint') }}</p>
        <DocsReadMore :href="DOCS_PRICE_BASIS" />
        <FeedbackLink :topic="feedbackTopic" :panel="t('proposal.priceBasis.badge')" />
      </div>
    </InfoPopover>
  </span>
</template>
