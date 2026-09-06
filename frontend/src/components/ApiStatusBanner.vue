<script setup lang="ts">
// One app-wide statement when several requests in a row have failed, so a user
// whose every action is failing gets a coherent explanation instead of N
// unrelated messages.
//
// Passive: nothing here polls. The signal is the failures the app was already
// making (lib/apiHealth.ts), so a struggling backend pays nothing to be
// reported. role="status"/polite rather than alert — this describes a standing
// condition, and the error toast for the same event has already interrupted.
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { useApiHealth } from '@/composables/useApiHealth'
import { mdiAlert, mdiClose } from '@mdi/js'

const { t } = useI18n()
const { state, dismiss } = useApiHealth()

// A reload is the only honest recovery action: there is no single request to
// retry, and the app's reference data is loaded once at boot.
function reload(): void {
  window.location.reload()
}
</script>

<template>
  <!-- In normal flow, NOT fixed: both the proposal workspace's and the
       gallery's sticky maps use `top-6`, and would slide under a fixed bar. -->
  <div
    v-if="state.visible"
    class="api-degraded flex w-full items-center gap-3 px-8 py-3"
    role="status"
    aria-live="polite"
  >
    <AppIcon :path="mdiAlert" :size="20" class="shrink-0" />
    <div class="flex-1 text-sm">
      <span class="font-semibold">{{ t('errors.degraded.title') }}</span>
      <span class="ml-2 opacity-90">{{ t('errors.degraded.body') }}</span>
    </div>
    <button
      type="button"
      class="shrink-0 cursor-pointer rounded-lg bg-black/15 px-3 py-1 text-xs font-semibold transition hover:bg-black/25"
      @click="reload"
    >
      {{ t('errors.reload') }}
    </button>
    <button
      type="button"
      class="shrink-0 cursor-pointer opacity-70 transition hover:opacity-100"
      :aria-label="t('toast.dismiss')"
      @click="dismiss"
    >
      <AppIcon :path="mdiClose" :size="16" />
    </button>
  </div>
</template>

<style scoped>
/* Same palette as the warn toast (Toast.vue), so the two read as one voice. */
.api-degraded {
  background: #78350f;
  color: #fde68a;
}
</style>
