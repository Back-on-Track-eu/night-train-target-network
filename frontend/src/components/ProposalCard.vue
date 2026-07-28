<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ProposalSummary } from '@/types/api'

const props = defineProps<{ proposal: ProposalSummary; flash?: boolean }>()

const { t } = useI18n()

// Route metrics as label/value rows — "just print the info" per the summary.
const rows = computed(() => [
  {
    label: t('gallery.card.distance'),
    value: t('gallery.card.km', { value: props.proposal.total_distance_km }),
  },
  {
    label: t('gallery.card.countries'),
    value: props.proposal.countries.join(', ') || '—',
  },
  {
    label: t('gallery.card.stops'),
    value: String(props.proposal.stops.length),
  },
])
</script>

<template>
  <article
    class="flex flex-col gap-3 rounded-xl p-4 transition-colors duration-500"
    :class="flash ? 'bg-primary-50/20' : 'bg-primary-50/5'"
  >
    <h3 class="text-base font-bold text-primary-50" :title="proposal.name">
      {{ proposal.name }}
    </h3>

    <dl class="flex flex-col gap-1 text-sm">
      <div v-for="row in rows" :key="row.label" class="flex justify-between gap-2">
        <dt class="text-primary-50/50">{{ row.label }}</dt>
        <dd class="text-right text-primary-50">{{ row.value }}</dd>
      </div>
    </dl>

    <footer class="text-xs text-primary-50/40">
      {{ t('gallery.card.savedBy') }}: {{ proposal.user_name ?? `#${proposal.user_id}` }}
    </footer>
  </article>
</template>
