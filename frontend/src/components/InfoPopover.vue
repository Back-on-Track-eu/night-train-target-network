<script setup lang="ts">
import { ref } from 'vue'
import Popover from 'primevue/popover'

// The hover-intent info overlay every "ⓘ" in the app opens: the timing (open
// on hover, stay open while the cursor is inside it, close on a short delay
// once it has left both) and the overlay styling live here and nowhere else.
//
// Content is a slot, so the two users differ only in what they show:
//   FactorInfoPopover — a cost/revenue factor: title, docs link, summary,
//                       driven by many icons in one panel, hence the key
//                       argument on open()
//   InfoHint          — one sentence next to a single icon
//
// Parents drive it from their own icon:
//   <InfoPopover ref="info"><p>…</p></InfoPopover>
//   @mouseenter="info.open($event)"  @mouseleave="info.scheduleClose"
//
// `key` exists so a parent with several icons can skip a redundant show()
// (and the flicker it causes) when the cursor re-enters the icon that is
// already open; a single-icon parent passes nothing.
const emit = defineEmits<{ show: []; hide: [] }>()

const popover = ref<InstanceType<typeof Popover> | null>(null)
const pendingKey = ref<string | null>(null)
const openKey = ref<string | null>(null)
let closeTimer: ReturnType<typeof setTimeout> | null = null

function cancelClose() {
  if (closeTimer !== null) {
    clearTimeout(closeTimer)
    closeTimer = null
  }
}

function open(event: Event, key: string | null = null) {
  cancelClose()
  if (key !== null && openKey.value === key) return
  pendingKey.value = key
  popover.value?.show(event)
}

function scheduleClose() {
  cancelClose()
  closeTimer = setTimeout(() => popover.value?.hide(), 150)
}

function onShow() {
  openKey.value = pendingKey.value
  emit('show')
}

function onHide() {
  openKey.value = null
  emit('hide')
}

defineExpose({ open, scheduleClose, cancelClose })
</script>

<template>
  <Popover
    ref="popover"
    :pt="{
      root: {
        class: 'info-overlay !rounded-xl !shadow-2xl',
        onMouseenter: cancelClose,
        onMouseleave: scheduleClose,
      },
      content: { class: '!p-6 !bg-transparent' },
    }"
    @show="onShow"
    @hide="onHide"
  >
    <slot />
  </Popover>
</template>

<style>
.info-overlay {
  background: #23263d !important;
  border: 1px solid color-mix(in srgb, var(--p-primary-50) 20%, transparent) !important;
  /* One fixed-width column; the viewport is the only bound that still
     matters on a narrow screen. */
  max-width: calc(100vw - 2rem);
}
</style>
