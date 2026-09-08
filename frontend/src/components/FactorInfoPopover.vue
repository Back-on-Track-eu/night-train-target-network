<script setup lang="ts">
import { ref, computed } from 'vue'
import InfoPopover from '@/components/InfoPopover.vue'
import AppIcon from '@/components/AppIcon.vue'
import { mdiOpenInNew } from '@mdi/js'
import { useI18n } from 'vue-i18n'
import { formulaKeyForNode, docsPathForFormula } from '@/lib/factorFeedback'
import type { FormulaMap } from '@/types/api'

// The info popover shared by the cost tree and the revenue panel: the row's
// label, a one-line summary of it, and a link to its documentation page.
//
// The overlay itself — hover-intent timing, styling — is InfoPopover.vue,
// which InfoHint.vue also uses; this component is only the factor content
// and the key → formula lookup behind it.
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

const popover = ref<InstanceType<typeof InfoPopover> | null>(null)
const activeKey = ref<string | null>(null)
const activeLabel = ref('')

// The label comes from the icon the cursor is on, so it is refreshed even
// when the overlay is already open on that key (InfoPopover skips the
// redundant show()).
function open(nodeKey: string, label: string, event: Event) {
  activeLabel.value = label
  activeKey.value = nodeKey
  popover.value?.open(event, nodeKey)
}

function scheduleClose() {
  popover.value?.scheduleClose()
}

function cancelClose() {
  popover.value?.cancelClose()
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
  <InfoPopover ref="popover">
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
  </InfoPopover>
</template>
