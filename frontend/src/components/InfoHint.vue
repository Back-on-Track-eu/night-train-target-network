<script setup lang="ts">
import { ref } from 'vue'
import InfoPopover from '@/components/InfoPopover.vue'
import AppIcon from '@/components/AppIcon.vue'
import { mdiInformationOutline } from '@mdi/js'

// A single "ⓘ" with one sentence behind it — for a chip or a label that needs
// to explain itself without a paragraph competing with the controls it
// belongs to. Self-contained (icon + overlay in one element), unlike
// FactorInfoPopover, which one panel renders once and drives from many icons.
//
// Both sit on InfoPopover.vue, so hover-intent timing and overlay styling
// stay in one place. Not the browser's `title`: that waits a second, cannot
// be reached by keyboard, and renders in the OS style rather than ours.
defineProps<{ text: string }>()

const popover = ref<InstanceType<typeof InfoPopover> | null>(null)
</script>

<template>
  <span class="inline-flex items-center">
    <button
      type="button"
      class="flex cursor-help text-primary-50/55 transition hover:text-primary-50"
      :aria-label="text"
      @mouseenter="popover?.open($event)"
      @mouseleave="popover?.scheduleClose()"
      @focus="popover?.open($event)"
      @blur="popover?.scheduleClose()"
      @click="popover?.open($event)"
    >
      <AppIcon :path="mdiInformationOutline" :size="14" />
    </button>
    <InfoPopover ref="popover">
      <p class="w-0 min-w-full max-w-72 text-sm text-primary-50/75">{{ text }}</p>
    </InfoPopover>
  </span>
</template>
