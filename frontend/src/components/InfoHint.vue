<script setup lang="ts">
import { ref } from 'vue'
import InfoPopover from '@/components/InfoPopover.vue'
import AppIcon from '@/components/AppIcon.vue'
import DocsReadMore from '@/components/DocsReadMore.vue'
import { mdiInformationOutline } from '@mdi/js'

// A single "ⓘ" with a short explanation behind it — for a chip or a label
// that needs to explain itself without a paragraph competing with the
// controls it belongs to. Self-contained (icon + overlay in one element), unlike
// FactorInfoPopover, which one panel renders once and drives from many icons.
//
// Both sit on InfoPopover.vue, so hover-intent timing and overlay styling
// stay in one place. Not the browser's `title`: that waits a second, cannot
// be reached by keyboard, and renders in the OS style rather than ours.
//
// `docsHref` adds the hand-over to the documentation below the sentence; the
// overlay stays open while the cursor is inside it, so the link is reachable.
defineProps<{ text: string; docsHref?: string }>()

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
      <!-- A definite width, not `w-0 min-w-full`: the overlay is shrink-to-fit,
           so a percentage min-width resolves against a containing block that is
           itself sized by this element, collapses to zero, and leaves the text
           wrapping at its longest word. The overlay's own max-width keeps this
           inside a narrow viewport. -->
      <div class="flex w-72 flex-col">
        <p class="text-sm text-primary-50/75">{{ text }}</p>
        <DocsReadMore v-if="docsHref" :href="docsHref" />
      </div>
    </InfoPopover>
  </span>
</template>
