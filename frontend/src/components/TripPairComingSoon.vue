<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import InfoHint from '@/components/InfoHint.vue'
import { mdiSourceBranch } from '@mdi/js'

// Sits above the itinerary and announces the shape the builder is growing
// into: a proposal that carries more than one trip pair, so a route can branch
// off a shared section (Y) or cross another at an interchange (X) instead of
// being one line from A to B.
//
// Deliberately inert — a dashed outline and a disabled control, not a button
// that explains why it does nothing. The same "coming soon" chip and ⓘ as the
// scenario panel's held-back rows, so a visitor reads the two the same way.
const { t } = useI18n()
</script>

<template>
  <div
    class="mb-6 flex items-center gap-2.5 rounded-xl border border-dashed border-primary-50/15 px-3 py-2.5"
    aria-disabled="true"
  >
    <AppIcon :path="mdiSourceBranch" :size="16" class="shrink-0 text-primary-50/35" />
    <span class="text-sm text-primary-50/40">{{ t('proposal.tripPairs.addAnother') }}</span>
    <span
      class="ml-auto flex shrink-0 items-center gap-1 rounded-full border border-primary-50/20 px-2 py-0.5 text-[10px] leading-none text-primary-50/50"
    >
      {{ t('proposal.compare.comingSoon') }}
      <InfoHint :text="t('proposal.tripPairs.comingSoonHint')" />
    </span>
  </div>
</template>
