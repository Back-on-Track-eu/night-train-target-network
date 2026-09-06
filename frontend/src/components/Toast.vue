<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { Toast, ToastSeverity } from '@/stores/toastStore'
import { mdiCheckCircle, mdiAlertCircle, mdiInformation, mdiAlert, mdiClose } from '@mdi/js'

const props = defineProps<{ toast: Toast }>()
const emit = defineEmits<{ dismiss: [id: number] }>()

const { t } = useI18n()

// Failures interrupt (role="alert" implies aria-live="assertive"); successes and
// hints do not. Bearable only because repeats merge instead of stacking.
const isUrgent = computed(() => props.toast.severity === 'error' || props.toast.severity === 'warn')

const ICONS: Record<ToastSeverity, string> = {
  success: mdiCheckCircle,
  error: mdiAlertCircle,
  info: mdiInformation,
  warn: mdiAlert,
}
</script>

<template>
  <div
    class="toast-item flex items-center gap-3 rounded-xl px-4 py-3 shadow-xl"
    :class="`toast-${toast.severity}`"
    :role="isUrgent ? 'alert' : 'status'"
    aria-atomic="true"
  >
    <AppIcon :path="ICONS[toast.severity]" :size="22" class="shrink-0" />
    <p class="flex-1 text-sm font-medium">
      {{ toast.message }}
      <!-- Repeats merge rather than stack, so the count is the only signal that
           this failure happened more than once. -->
      <span v-if="toast.count > 1" class="ml-1 text-xs opacity-70">×{{ toast.count }}</span>
    </p>
    <button
      v-if="toast.action"
      type="button"
      class="shrink-0 cursor-pointer rounded-lg bg-white/15 px-2.5 py-1 text-xs font-semibold transition hover:bg-white/25"
      @click="toast.action.run()"
    >
      {{ t(toast.action.labelKey) }}
    </button>
    <button
      type="button"
      class="shrink-0 cursor-pointer opacity-70 transition hover:opacity-100"
      :aria-label="t('toast.dismiss')"
      @click="emit('dismiss', toast.id)"
    >
      <AppIcon :path="mdiClose" :size="16" />
    </button>
  </div>
</template>

<style scoped>
.toast-success {
  background: color-mix(in srgb, var(--color-pure-green) 92%, black);
  color: white;
}
.toast-error {
  background: #7f1d1d;
  color: #fecaca;
}
.toast-info {
  background: var(--p-primary-800);
  color: var(--p-primary-50);
}
.toast-warn {
  background: #78350f;
  color: #fde68a;
}
</style>
