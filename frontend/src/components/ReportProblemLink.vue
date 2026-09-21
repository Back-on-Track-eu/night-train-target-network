<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { mdiMessageAlertOutline } from '@mdi/js'
import { docsFeedbackUrl, type ReportPanel } from '@/lib/feedbackLink'
import { useReportContext } from '@/composables/useReportContext'

// The small "report a problem" icon a result panel carries in its header. It
// opens the documentation site's feedback page in a new tab with the panel's
// topic preselected, the route's ends in the subject and its input
// parameters in the message — the same mechanics as the map pill's report
// menu, one icon per panel so a reader reports what they were looking at.
//
// `panel` names the box inside a tab (a Details tab holds several); it goes
// into the subject after the topic so the working group sees which one.
// Renders nothing until the builder has a calculated route to report on.
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
    class="flex cursor-pointer text-primary-50/40 transition hover:text-primary-50"
    :aria-label="t('proposal.report.panel')"
    :title="t('proposal.report.panel')"
    @click.stop
  >
    <AppIcon :path="mdiMessageAlertOutline" :size="14" />
  </a>
</template>
