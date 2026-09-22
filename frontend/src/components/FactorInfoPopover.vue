<script setup lang="ts">
import { ref, computed } from 'vue'
import InfoPopover from '@/components/InfoPopover.vue'
import DocsReadMore from '@/components/DocsReadMore.vue'
import FeedbackLink from '@/components/FeedbackLink.vue'
import { formulaKeyForNode, docsPathForFormula } from '@/lib/factorFeedback'
import type { FormulaMap } from '@/types/api'

// The info popover shared by the cost tree and the revenue panel: the row's
// one-line summary, the hand-over to its documentation page and the
// feedback link — the same three parts, in the same look, as every InfoHint
// overlay in the builder, so a reader meets one kind of overlay everywhere.
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
    <!-- Same width and type as InfoHint's overlay (see the note there on why a
         definite width). The row's label leads the sentence: the overlay is
         shared, so it names what it is about. -->
    <div v-if="activeFactor" class="flex w-72 flex-col">
      <p class="text-sm text-primary-50/75">
        <b class="font-semibold text-primary-50">{{ activeFactor.title }}</b> —
        {{ activeFactor.summary }}
      </p>
      <DocsReadMore :href="activeFactor.docsPath" />
      <FeedbackLink topic="breakdown" :panel="activeFactor.title" />
    </div>
  </InfoPopover>
</template>
