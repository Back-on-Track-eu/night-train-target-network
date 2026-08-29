<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import Popover from 'primevue/popover'
import Textarea from 'primevue/textarea'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import AppIcon from '@/components/AppIcon.vue'
import { mdiChevronDown, mdiChevronRight, mdiInformationOutline } from '@mdi/js'
import { resolveFactorRates, resolveFactorSubCategory } from '@/lib/costFactorRates'
import { submitFeedback, FeedbackError } from '@/lib/feedbackApi'
import { useStore } from '@/stores/store'
import { useEvaluationFormat } from '@/composables/useEvaluationFormat'
import type { Breakdown, EvaluationInput, FormulaMap } from '@/types/api'

// Cost tree (left column of the cost/revenue split) plus its cost-factor
// detail popover — title, explanation, formula, resolved rates, and a
// feedback form scoped to the factor the popover is showing.
const props = defineProps<{
  breakdown: Breakdown
  formulas: FormulaMap
  input: EvaluationInput
  // Ordered stops (outbound) — costFactorRates scopes rates to the route.
  stops: { stop_id: string; name: string }[]
}>()

const { t } = useI18n()
const store = useStore()
const { formatEur, formatShare, formatRateValue } = useEvaluationFormat()

// --- Cost tree: hierarchical node spec, flattened for rendering ------------
interface CostNode {
  key: string
  label: string
  value: number
  children?: CostNode[]
}

const costTree = computed<CostNode[]>(() => {
  const b = props.breakdown
  const f = (k: string) => t(`proposal.evaluation.fields.${k}`)
  const g = (k: string) => t(`proposal.evaluation.groups.${k}`)
  const v = b.cost.operator.variable
  const x = b.cost.operator.fixed
  const i = b.cost.infrastructure
  return [
    {
      key: 'operator',
      label: g('operator'),
      value: b.cost.operator.total_eur,
      children: [
        {
          key: 'variable',
          label: g('variable'),
          value: v.total_eur,
          children: [
            { key: 'driver', label: f('driver'), value: v.driver_eur },
            { key: 'crew', label: f('crew'), value: v.crew_eur },
            {
              key: 'coach_maintenance',
              label: f('coach_maintenance'),
              value: v.coach_maintenance_eur,
            },
            { key: 'loco', label: f('loco'), value: v.loco_eur },
            { key: 'svc_stockings', label: f('svc_stockings'), value: v.svc_stockings_eur },
            { key: 'var_overhead', label: f('var_overhead'), value: v.var_overhead_eur },
          ],
        },
        {
          key: 'fixed',
          label: g('fixed'),
          value: x.total_eur,
          children: [
            {
              key: 'coach_amortisation',
              label: f('coach_amortisation'),
              value: x.coach_amortisation_eur,
            },
            { key: 'financing', label: f('financing'), value: x.financing_eur },
            { key: 'fix_overhead', label: f('fix_overhead'), value: x.fix_overhead_eur },
            { key: 'cleaning', label: f('cleaning'), value: x.cleaning_eur },
            { key: 'shunting', label: f('shunting'), value: x.shunting_eur },
          ],
        },
        // Target EBIT margin — shown as a point under Operator (the profit the
        // fare must cover on top of operator costs), not a cost line itself.
        { key: 'ebit_margin', label: f('ebit_margin'), value: b.margin.ebit_margin_eur },
      ],
    },
    {
      key: 'infrastructure',
      label: g('infrastructure'),
      value: i.total_eur,
      children: [
        { key: 'tac', label: f('tac'), value: i.tac_eur },
        { key: 'energy', label: f('energy'), value: i.energy_eur },
        { key: 'station_charge', label: f('station_charge'), value: i.station_charge_eur },
        { key: 'parking', label: f('parking'), value: i.parking_eur },
      ],
    },
  ]
})

const expanded = ref(new Set<string>(['operator', 'infrastructure']))

function toggleExpand(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

interface CostRow {
  key: string
  label: string
  value: number
  depth: number
  hasChildren: boolean
  isExpanded: boolean
  share: number | null
}

const costRows = computed<CostRow[]>(() => {
  const total = props.breakdown.cost.total_eur
  const rows: CostRow[] = []
  const visit = (nodes: CostNode[], depth: number) => {
    for (const n of nodes) {
      const isExpanded = expanded.value.has(n.key)
      rows.push({
        key: n.key,
        label: n.label,
        value: n.value,
        depth,
        hasChildren: (n.children?.length ?? 0) > 0,
        isExpanded,
        share: total !== 0 ? n.value / total : null,
      })
      if (n.children && isExpanded) visit(n.children, depth + 1)
    }
  }
  visit(costTree.value, 0)
  return rows
})

// --- Cost-factor detail popover --------------------------------------------
// A tree node's key maps to its formula/field key by appending "_eur"
// (driver → driver_eur); the info icon shows only where a formula exists.
const formulaKey = (nodeKey: string) => `${nodeKey}_eur`
function hasInfo(nodeKey: string): boolean {
  return formulaKey(nodeKey) in props.formulas
}

const infoPopover = ref<InstanceType<typeof Popover> | null>(null)
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
function openInfo(nodeKey: string, event: Event) {
  cancelClose()
  if (openKey.value === nodeKey) return
  activeKey.value = nodeKey
  infoPopover.value?.show(event)
}

function scheduleClose() {
  cancelClose()
  // Sticky when the form has content: don't yank a half-typed draft away on
  // unhover. PrimeVue's outside-click dismiss still closes the popover.
  if (isFeedbackDirty.value) return
  closeTimer = setTimeout(() => infoPopover.value?.hide(), 150)
}

function onInfoShow() {
  openKey.value = activeKey.value
}
function onInfoHide() {
  openKey.value = null
}

const activeFactor = computed(() => {
  const key = activeKey.value
  if (!key) return null
  const formula = props.formulas[formulaKey(key)]
  if (!formula) return null
  return {
    title: t(`proposal.evaluation.fields.${key}`),
    description: formula.description,
    // Inline layout + \displaystyle so the box hugs the formula's natural
    // width (displayMode would stretch it to full width and centre it).
    latexHtml: katex.renderToString(`\\displaystyle ${formula.latex}`, {
      throwOnError: false,
      displayMode: false,
    }),
    rates: resolveFactorRates(formulaKey(key), props.input, props.stops),
  }
})

// --- Cost-factor feedback form (right column of the detail popover) ----------
// Posts to the existing POST /api/feedback via the anonymous email path,
// tagged to the factor the popover is showing (its dotted Breakdown path).
// These are protocol values sent verbatim in the body, not i18n.
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
  const subCategory = resolveFactorSubCategory(formulaKey(key))
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
    feedbackErrorMsg.value =
      err instanceof FeedbackError && err.message
        ? err.message
        : t('proposal.evaluation.feedback.error')
  }
}
</script>

<template>
  <div class="w-1/2 rounded-xl bg-primary-50/5 p-4">
    <div class="mb-2 flex items-center gap-1 border-b border-primary-50/10 pb-2">
      <span class="w-5 shrink-0" />
      <span class="flex-1 font-semibold text-primary-50">
        {{ t('proposal.evaluation.groups.cost') }}
      </span>
      <span class="w-12 text-right text-xs text-primary-50/40 tabular-nums">
        {{ formatShare(1) }}
      </span>
      <span class="w-24 text-right font-semibold text-primary-50 tabular-nums">
        {{ formatEur(breakdown.cost.total_eur) }}
      </span>
    </div>
    <div
      v-for="row in costRows"
      :key="row.key"
      class="flex items-center gap-1 py-1"
      :style="{ paddingLeft: `${row.depth * 16}px` }"
    >
      <button
        v-if="row.hasChildren"
        class="flex w-5 shrink-0 cursor-pointer justify-center text-primary-50/40 transition hover:text-primary-50"
        @click="toggleExpand(row.key)"
      >
        <AppIcon :path="row.isExpanded ? mdiChevronDown : mdiChevronRight" :size="16" />
      </button>
      <span v-else class="w-5 shrink-0" />
      <span
        class="flex flex-1 items-center gap-1 text-sm"
        :class="row.hasChildren ? 'text-primary-50' : 'text-primary-50/70'"
      >
        {{ row.label }}
        <button
          v-if="hasInfo(row.key)"
          type="button"
          class="flex cursor-pointer text-primary-50/40 transition hover:text-primary-50"
          :aria-label="t('proposal.evaluation.info.iconLabel')"
          @mouseenter="openInfo(row.key, $event)"
          @mouseleave="scheduleClose"
          @click="openInfo(row.key, $event)"
        >
          <AppIcon :path="mdiInformationOutline" :size="14" />
        </button>
      </span>
      <span class="w-12 text-right text-xs text-primary-50/40 tabular-nums">
        {{ formatShare(row.share) }}
      </span>
      <span class="w-24 text-right text-sm text-primary-50 tabular-nums">
        {{ formatEur(row.value) }}
      </span>
    </div>

    <!-- Cost-factor detail popover: title · explanation · formula · rates -->
    <Popover
      ref="infoPopover"
      :pt="{
        root: {
          class: 'cost-info-overlay !rounded-xl !shadow-2xl',
          onMouseenter: cancelClose,
          onMouseleave: scheduleClose,
        },
        content: { class: '!p-6 !bg-transparent' },
      }"
      @show="onInfoShow"
      @hide="onInfoHide"
    >
      <div v-if="activeFactor" class="flex items-stretch gap-6">
        <!-- Left column: title · explanation · formula · rates -->
        <div class="flex min-w-0 max-w-2xl flex-col gap-6">
          <h3 class="text-xl font-semibold text-primary-50">{{ activeFactor.title }}</h3>
          <!-- width:0 + min-width:100% so the paragraph fills (and wraps to) the
               width set by the formula box / table, without its own single-line
               max-content widening the column. -->
          <p class="w-0 min-w-full text-justify text-sm text-primary-50/70">
            {{ activeFactor.description }}
          </p>
          <!-- Rendered LaTeX; formula is backend-controlled, so v-html is safe. -->
          <!-- eslint-disable vue/no-v-html -->
          <div
            class="cost-info-formula max-w-full self-center overflow-x-auto rounded-lg bg-black/20 px-8 py-5 text-primary-50"
            v-html="activeFactor.latexHtml"
          />
          <!-- eslint-enable vue/no-v-html -->
          <template v-if="activeFactor.rates.length">
            <table class="w-full text-left text-sm">
              <thead>
                <tr class="text-xs text-primary-50/40">
                  <th class="pr-6 pb-1 font-medium">
                    {{ t('proposal.evaluation.info.rateCol') }}
                  </th>
                  <th class="pr-6 pb-1 text-right font-medium">
                    {{ t('proposal.evaluation.info.valueCol') }}
                  </th>
                  <th class="pb-1 font-medium">
                    {{ t('proposal.evaluation.info.sourceCol') }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(rate, idx) in activeFactor.rates"
                  :key="idx"
                  class="border-t border-primary-50/10 align-top"
                >
                  <td class="py-1.5 pr-6">
                    <div class="text-primary-50">
                      {{ t(`proposal.evaluation.rates.${rate.id}`) }}
                      <span v-if="rate.scope" class="text-primary-50/50">· {{ rate.scope }}</span>
                    </div>
                    <!-- width:0 + min-width:100% so the title drives the column
                       width and the description wraps beneath it rather than
                       widening the row (same pattern as the main description). -->
                    <div v-if="rate.description" class="w-0 min-w-full text-xs text-primary-50/40">
                      {{ rate.description }}
                    </div>
                  </td>
                  <td class="py-1.5 pr-6 text-right whitespace-nowrap text-primary-50 tabular-nums">
                    {{ formatRateValue(rate) }}
                    <span v-if="rate.unit" class="text-primary-50/50">{{ rate.unit }}</span>
                  </td>
                  <td class="py-1.5 text-xs text-primary-50/60">
                    <span
                      v-if="rate.isDefault"
                      class="mr-1 mb-1 inline-block rounded-full bg-primary-50/10 px-1.5 py-0.5 text-primary-50/50"
                    >
                      {{ t('proposal.evaluation.info.defaultBadge') }}
                    </span>
                    <span v-for="(src, i) in rate.sources" :key="i" class="block">
                      <a
                        v-if="src.source_url"
                        :href="src.source_url"
                        target="_blank"
                        rel="noopener"
                        class="underline hover:text-primary-50"
                      >
                        {{ src.source_description || src.source_url }}
                      </a>
                      <span v-else>{{ src.source_description }}</span>
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </template>
        </div>

        <!-- Vertical separator between the content and the feedback form -->
        <div class="w-px shrink-0 self-stretch bg-primary-50/10" aria-hidden="true" />

        <!-- Right column: report a mistake / suggestion about this cost factor -->
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
            <Button
              type="button"
              :label="
                feedbackStatus === 'submitting'
                  ? t('proposal.evaluation.feedback.submitting')
                  : t('proposal.evaluation.feedback.submit')
              "
              :disabled="!canSubmitFeedback"
              :unstyled="true"
              class="cursor-pointer self-start rounded-lg bg-primary-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-600 active:bg-primary-700 disabled:cursor-not-allowed disabled:bg-primary-500/40 disabled:text-white/60 disabled:shadow-none"
              @click="onSubmitFeedback"
            />
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
  </div>
</template>

<style>
.cost-info-overlay {
  background: #23263d !important;
  border: 1px solid color-mix(in srgb, var(--p-primary-50) 20%, transparent) !important;
  /* Grow to fit a wide formula; only the viewport bounds the width. */
  max-width: calc(100vw - 2rem);
}
/* KaTeX inherits the box's text colour; keep the formula on one baseline. */
.cost-info-formula .katex {
  font-size: 1.05em;
}
</style>
