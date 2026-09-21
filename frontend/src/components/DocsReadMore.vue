<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { mdiOpenInNew } from '@mdi/js'

// The "read more" line at the foot of an info overlay: one wording, one look,
// wherever an explanation hands over to the documentation. A plain anchor in a
// new tab — the docs are a separate static site at /docs/ on this origin, and
// the builder's state is not saved by leaving it.
defineProps<{ href: string }>()

const { t } = useI18n()
</script>

<template>
  <a
    :href="href"
    target="_blank"
    rel="noopener"
    class="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-primary-300 transition hover:text-primary-50"
  >
    {{ t('proposal.docsReadMore') }}
    <AppIcon :path="mdiOpenInNew" :size="14" />
  </a>
</template>
