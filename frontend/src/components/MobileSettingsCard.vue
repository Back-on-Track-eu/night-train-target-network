<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// ≤ 640 px replacement for Zones D and E (and the grid view): a short card
// saying what the figures were evaluated with, instead of tables that need
// a wider screen.
defineProps<{ composition: string | null; frequency: string | null }>()
const { t } = useI18n()
</script>

<template>
  <div class="rounded-xl border border-primary-50/10 p-4 text-sm text-primary-50/70">
    {{
      t('proposal.settings.mobileCard', {
        composition: composition ?? '—',
        frequency: frequency ?? '—',
      })
    }}
  </div>
</template>
