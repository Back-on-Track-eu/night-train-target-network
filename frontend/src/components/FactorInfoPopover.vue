<script setup lang="ts">
import { ref, computed } from 'vue'
import Popover from 'primevue/popover'
import AppIcon from '@/components/AppIcon.vue'
import { mdiOpenInNew } from '@mdi/js'
import { useI18n } from 'vue-i18n'
import { formulaKeyForNode, docsPathForFormula } from '@/lib/factorFeedback'
import type { FormulaMap } from '@/types/api'

// The info popover shared by the cost tree and the revenue panel: the row's
// label, a one-line summary of it, and a link to its documentation page.
//
// Shared rather than duplicated so the hover-intent timing and the overlay
// styling have one home.
//
// Parents render this once and drive it from their own info icons, passing
// the label they already render so the popover title cannot disagree with
// the row the user pointed at:
//   <FactorInfoPopover ref="info" :formulas="formulas" />
//   @mouseenter="info.open(row.key, row.label, $event)"
//   @mouseleave="info.scheduleClose"
const props = defineProps<{
  formulas: FormulaMap
}>()

const { t } = useI18n()

const popover = ref<InstanceType<typeof Popover> | null>(null)
const activeKey = ref<string | null>(null)
const activeLabel = ref('')
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
function open(nodeKey: string, label: string, event: Event) {
  cancelClose()
  activeLabel.value = label
  if (openKey.value === nodeKey) return
  activeKey.value = nodeKey
  popover.value?.show(event)
}

function scheduleClose() {
  cancelClose()
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
    // Handed over by the parent: the cost tree labels its four subtotal rows
    // and the margin row from proposal.evaluation.groups.*, its leaves from
    // .fields.*, so this component cannot derive the label from the key alone.
    title: activeLabel.value,
    // The backend's one-sentence form. formula.description is the long
    // version and belongs on the page the link opens.
    summary: formula.summary,
    docsPath: docsPathForFormula(formulaKeyForNode(key)),
  }
})
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
    <div v-if="activeFactor" class="flex w-96 flex-col gap-3">
      <div class="flex items-center gap-2">
        <h3 class="text-xl font-semibold text-primary-50">{{ activeFactor.title }}</h3>
        <!-- Leaves the SPA: the docs are a separate static site served at
             /docs/ on this origin, so a plain anchor, not a router link. -->
        <a
          :href="activeFactor.docsPath"
          target="_blank"
          rel="noopener"
          class="flex text-primary-300 transition hover:text-primary-50"
          :aria-label="t('proposal.evaluation.info.readMore')"
          :title="t('proposal.evaluation.info.readMore')"
        >
          <AppIcon :path="mdiOpenInNew" :size="16" />
        </a>
      </div>
      <!-- width:0 + min-width:100% so the sentence wraps to the column
           width rather than widening the popover with its max-content. -->
      <p class="w-0 min-w-full text-sm text-primary-50/70">
        {{ activeFactor.summary }}
      </p>
    </div>
  </Popover>
</template>

<style>
.cost-info-overlay {
  background: #23263d !important;
  border: 1px solid color-mix(in srgb, var(--p-primary-50) 20%, transparent) !important;
  /* One fixed-width column; the viewport is the only bound that still
     matters on a narrow screen. */
  max-width: calc(100vw - 2rem);
}
</style>
