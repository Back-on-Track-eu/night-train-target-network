<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Popover from 'primevue/popover'
import Textarea from 'primevue/textarea'
import InputText from 'primevue/inputtext'
import AppIcon from '@/components/AppIcon.vue'
import AppSpinner from '@/components/AppSpinner.vue'
import { mdiOpenInNew } from '@mdi/js'
import {
  formulaKeyForNode,
  docsPathForFormula,
  resolveFactorSubCategory,
} from '@/lib/factorFeedback'
import { submitFeedback } from '@/lib/feedbackApi'
import { useApiFailure } from '@/composables/useApiFailure'
import { useStore } from '@/stores/store'
import type { FormulaMap } from '@/types/api'

// The info popover shared by the cost tree and the revenue panel: a
// one-line summary of a breakdown row, a link to its documentation page,
// and a feedback form tagged to that exact row.
//
// Shared rather than duplicated because the feedback form is the bulk of
// it — two copies would mean two places to fix a submit bug.
//
// Parents render this once and drive it from their own info icons:
//   <FactorInfoPopover ref="info" :formulas="formulas" />
//   @mouseenter="info.open(row.key, $event)" @mouseleave="info.scheduleClose"
const props = defineProps<{
  formulas: FormulaMap
}>()

const { t } = useI18n()
const store = useStore()
const { describe } = useApiFailure()

const popover = ref<InstanceType<typeof Popover> | null>(null)
const activeKey = ref<string | null>(null)
// Key whose popover is currently shown — lets us skip a redundant show()
// (and the flicker it causes) when the cursor re-enters the same icon.
const openKey = ref<string | null>(null)
let closeTimer: ReturnType<typeof setTimeout> | null = null

function cancelClose() {
  if (closeTimer !== null) {
    clearTimeout(closeTimer)
    closeTimer = null
  }
}

// Hover-intent: open on icon hover, keep open while the cursor is over the
// popover, and close only after a short delay once it has left both — so
// moving from the icon into the popover doesn't flicker-close it.
function open(nodeKey: string, event: Event) {
  cancelClose()
  if (openKey.value === nodeKey) return
  activeKey.value = nodeKey
  popover.value?.show(event)
}

function scheduleClose() {
  cancelClose()
  // Sticky when the form has content: don't yank a half-typed draft away on
  // unhover. PrimeVue's outside-click dismiss still closes the popover.
  if (isFeedbackDirty.value) return
  closeTimer = setTimeout(() => popover.value?.hide(), 150)
}

function onShow() {
  openKey.value = activeKey.value
}
function onHide() {
  openKey.value = null
}

defineExpose({ open, scheduleClose, cancelClose })

const activeFactor = computed(() => {
  const key = activeKey.value
  if (!key) return null
  const formula = props.formulas[formulaKeyForNode(key)]
  if (!formula) return null
  return {
    title: t(`proposal.evaluation.fields.${key}`),
    // The backend's one-sentence form. formula.description is the long
    // version and belongs on the page the link below opens.
    summary: formula.summary,
    docsPath: docsPathForFormula(formulaKeyForNode(key)),
  }
})

// --- Feedback form ---------------------------------------------------------
// Posts to POST /api/feedback via the anonymous email path, tagged to the
// row the popover is showing (its dotted Breakdown path). These are
// protocol values sent verbatim in the body, not i18n.
const FEEDBACK_CATEGORY = 'Evaluation — calculation method'

type FeedbackStatus = 'idle' | 'submitting' | 'success' | 'error'

// Per-factor drafts so a half-typed message/email survives closing and
// reopening the popover; keyed by factor node key, cleared on a 201.
interface FeedbackDraft {
  message: string
  email: string
}
const feedbackDrafts = reactive<Record<string, FeedbackDraft>>({})
function draftFor(key: string): FeedbackDraft {
  if (!feedbackDrafts[key]) feedbackDrafts[key] = { message: '', email: '' }
  return feedbackDrafts[key]
}

// Bind v-model to the active factor's draft so the fields always show (and
// mutate) the right factor's stored content.
const feedbackMessage = computed<string>({
  get: () => (activeKey.value ? draftFor(activeKey.value).message : ''),
  set: (v) => {
    if (activeKey.value) draftFor(activeKey.value).message = v
  },
})
const feedbackEmail = computed<string>({
  get: () => (activeKey.value ? draftFor(activeKey.value).email : ''),
  set: (v) => {
    if (activeKey.value) draftFor(activeKey.value).email = v
  },
})

const feedbackStatus = ref<FeedbackStatus>('idle')
const feedbackErrorMsg = ref('')

// Plausible-email gate for the submit button — the backend regex-validates too;
// this is just the client-side check. Logged-in users don't enter an email at
// all — the backend derives it from their account, so the field (and this
// check) only applies to the anonymous/guest path.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const requiresEmail = computed(() => store.authChoice !== 'user')
const emailValid = computed(() => !requiresEmail.value || EMAIL_RE.test(feedbackEmail.value.trim()))
const messageValid = computed(() => feedbackMessage.value.trim().length > 0)
const canSubmitFeedback = computed(
  () => emailValid.value && messageValid.value && feedbackStatus.value !== 'submitting',
)

// "Dirty" = either field has content. Drives the sticky-popover behavior:
// while dirty the popover stays open on unhover and closes only on outside-click.
const isFeedbackDirty = computed(
  () => feedbackMessage.value.length > 0 || feedbackEmail.value.length > 0,
)

// Switching to another factor only resets the transient status/error — each
// factor keeps its own draft, which is restored when its popover reopens.
watch(activeKey, () => {
  feedbackStatus.value = 'idle'
  feedbackErrorMsg.value = ''
})

async function onSubmitFeedback() {
  const key = activeKey.value
  if (!key || !canSubmitFeedback.value) return
  const subCategory = resolveFactorSubCategory(formulaKeyForNode(key))
  if (!subCategory) return
  feedbackStatus.value = 'submitting'
  feedbackErrorMsg.value = ''
  try {
    await submitFeedback(
      {
        ...(requiresEmail.value ? { email: feedbackEmail.value.trim() } : {}),
        subject: `Cost factor feedback: ${t(`proposal.evaluation.fields.${key}`)}`,
        category: FEEDBACK_CATEGORY,
        sub_category: subCategory,
        message: feedbackMessage.value.trim(),
      },
      requiresEmail.value ? {} : store.authHeaders(),
    )
    feedbackStatus.value = 'success'
    // Clear this factor's draft on a successful submit.
    const draft = draftFor(key)
    draft.message = ''
    draft.email = ''
  } catch (err) {
    feedbackStatus.value = 'error'
    // describe() keeps the backend's validation text (written for users) and
    // drops a 500's, which for a failed INSERT is a psycopg2 message naming
    // tables and constraints.
    feedbackErrorMsg.value = describe(err, 'errors.feedbackFailed')
  }
}
</script>

<template>
  <Popover
    ref="popover"
    :pt="{
      root: {
        class: 'cost-info-overlay !rounded-xl !shadow-2xl',
        onMouseenter: cancelClose,
        onMouseleave: scheduleClose,
      },
      content: { class: '!p-6 !bg-transparent' },
    }"
    @show="onShow"
    @hide="onHide"
  >
    <div v-if="activeFactor" class="flex items-stretch gap-6">
      <!-- Left column: title · one-line summary · link to the full page -->
      <div class="flex w-96 shrink-0 flex-col gap-3">
        <h3 class="text-xl font-semibold text-primary-50">{{ activeFactor.title }}</h3>
        <!-- width:0 + min-width:100% so the sentence wraps to the column
             width rather than widening the popover with its max-content. -->
        <p class="w-0 min-w-full text-sm text-primary-50/70">
          {{ activeFactor.summary }}
        </p>
        <!-- Leaves the SPA: the docs are a separate static site served at
             /docs/ on this origin, so a plain anchor, not a router link. -->
        <a
          :href="activeFactor.docsPath"
          target="_blank"
          rel="noopener"
          class="flex items-center gap-1.5 self-start text-sm font-medium text-primary-300 underline transition hover:text-primary-50"
        >
          {{ t('proposal.evaluation.info.readMore') }}
          <AppIcon :path="mdiOpenInNew" :size="14" />
        </a>
      </div>

      <!-- Vertical separator between the content and the feedback form -->
      <div class="w-px shrink-0 self-stretch bg-primary-50/10" aria-hidden="true" />

      <!-- Right column: report a mistake / suggestion about this factor -->
      <div class="flex w-80 shrink-0 flex-col gap-3">
        <h4 class="text-base font-semibold text-primary-50">
          {{ t('proposal.evaluation.feedback.title') }}
        </h4>
        <!-- width:0 + min-width:100% so the paragraph wraps to the popover
             width rather than widening it (same pattern as above). -->
        <p class="w-0 min-w-full text-sm text-primary-50/70">
          {{ t('proposal.evaluation.feedback.description') }}
        </p>
        <Textarea
          v-model="feedbackMessage"
          :placeholder="t('proposal.evaluation.feedback.messagePlaceholder')"
          :disabled="feedbackStatus === 'submitting'"
          rows="3"
          auto-resize
          class="w-full resize-y rounded-lg border border-primary-50/20 bg-primary-50/5 px-3 py-2 text-sm text-primary-50 placeholder:text-primary-50/40"
        />
        <InputText
          v-if="requiresEmail"
          v-model="feedbackEmail"
          type="email"
          :placeholder="t('proposal.evaluation.feedback.emailPlaceholder')"
          :aria-label="t('proposal.evaluation.feedback.emailLabel')"
          :disabled="feedbackStatus === 'submitting'"
          class="w-full rounded-lg border border-primary-50/20 bg-primary-50/5 px-3 py-2 text-sm text-primary-50 placeholder:text-primary-50/40"
        />
        <div class="flex flex-wrap items-center gap-3">
          <button
            type="button"
            :disabled="!canSubmitFeedback"
            class="flex cursor-pointer items-center gap-2 self-start rounded-lg bg-primary-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-600 active:bg-primary-700 disabled:cursor-not-allowed disabled:bg-primary-500/40 disabled:text-white/60 disabled:shadow-none"
            @click="onSubmitFeedback"
          >
            <AppSpinner v-if="feedbackStatus === 'submitting'" />
            {{
              feedbackStatus === 'submitting'
                ? t('proposal.evaluation.feedback.submitting')
                : t('proposal.evaluation.feedback.submit')
            }}
          </button>
          <span v-if="feedbackStatus === 'success'" class="text-sm text-green-400" role="status">
            {{ t('proposal.evaluation.feedback.success') }}
          </span>
          <span v-else-if="feedbackStatus === 'error'" class="text-sm text-red-400" role="alert">
            {{ feedbackErrorMsg }}
          </span>
        </div>
      </div>
    </div>
  </Popover>
</template>

<style>
.cost-info-overlay {
  background: #23263d !important;
  border: 1px solid color-mix(in srgb, var(--p-primary-50) 20%, transparent) !important;
  /* Two fixed columns (summary | feedback); the viewport is the only bound
     that still matters on a narrow screen. */
  max-width: calc(100vw - 2rem);
}
</style>
