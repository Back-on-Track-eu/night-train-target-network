<script setup lang="ts">
/**
 * A failure the user can act on, shown next to the control that produced it.
 *
 * Deliberately NOT a toast: the toast surface carries systemic failures
 * ("something went wrong on our side"), which are about us and belong away
 * from the form. This carries the backend's own domain answer — an
 * impossible gauge pairing, a stop that will not snap, a rejected publish —
 * which is about what the user just asked for, and reads as an answer only
 * while it sits beside the thing they asked with. The split is enforced in
 * ProposalViewport.requestCalc(): verbatim text inline, everything else
 * reported to the toast store.
 *
 * The styling matches Toast.vue's error card so the two read as one system,
 * but muted: an inline panel sits in the page rather than over it, so it
 * takes a translucent background and a border instead of the toast's solid
 * fill and shadow.
 */
import AppIcon from '@/components/AppIcon.vue'
import { mdiAlertCircle } from '@mdi/js'

defineProps<{ message: string }>()
</script>

<template>
  <div
    class="flex w-full max-w-sm items-start gap-2.5 rounded-xl border border-red-400/30 bg-red-950/40 px-3.5 py-3 text-left"
    role="alert"
  >
    <AppIcon :path="mdiAlertCircle" :size="18" class="mt-px shrink-0 text-red-300" />
    <div class="flex min-w-0 flex-col gap-1.5">
      <p class="text-xs leading-relaxed break-words text-red-100">{{ message }}</p>
      <!-- Retry, or anything else the caller wants under the message. -->
      <slot />
    </div>
  </div>
</template>
