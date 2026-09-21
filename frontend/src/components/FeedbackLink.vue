<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { mdiMessageTextOutline } from '@mdi/js'
import { docsFeedbackUrl, type ReportPanel } from '@/lib/feedbackLink'
import { useReportContext } from '@/composables/useReportContext'

// The "Provide feedback" line at the foot of a result panel's info overlay
// (InfoHint), beside the docs hand-over. It opens the documentation site's
// feedback page in a new tab with the panel's topic preselected, the
// route's ends in the subject and its input parameters in the message — the
// same mechanics as the map pill's feedback menu, so a reader gives
// feedback on exactly what they were looking at. In the overlay rather than
// as a second icon beside the ⓘ: two small icons in a row read as one
// control that does two things.
//
// `panel` names the box inside a tab (a Details tab holds several); it goes
// into the subject after the topic so the working group sees which one.
// Renders nothing until the builder has a calculated route to give feedback on.
const props = defineProps<{ topic: ReportPanel; panel?: string }>()

const { t } = useI18n()
const report = useReportContext()

const href = computed(() => {
  const ctx = report?.value
  if (!ctx) return null
  const subject = props.panel ? `${props.panel} · ${ctx.ends}` : ctx.ends
  return docsFeedbackUrl(props.topic, subject, ctx.context)
})
</script>

<template>
  <a
    v-if="href"
    :href="href"
    target="_blank"
    rel="noopener noreferrer"
    class="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-primary-300 transition hover:text-primary-50"
    @click.stop
  >
    {{ t('proposal.feedback.panel') }}
    <AppIcon :path="mdiMessageTextOutline" :size="14" />
  </a>
</template>
