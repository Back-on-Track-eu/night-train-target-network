<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// One chip, one sentence: these figures were worked out here on the page, not
// by the model. It appears only on a panel that OWNS a changed input — the
// panels that merely depend on one carry the waiting badge instead, and hold
// the figures they have.
const { t } = useI18n()
</script>

<template>
  <span
    class="w-fit rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-px text-[10px] text-amber-200"
  >
    {{ t('proposal.details.previewChip') }}
  </span>
</template>
