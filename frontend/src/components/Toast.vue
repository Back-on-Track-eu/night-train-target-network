<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { Toast, ToastSeverity } from '@/stores/toastStore'
import { mdiCheckCircle, mdiAlertCircle, mdiInformation, mdiAlert, mdiClose } from '@mdi/js'

defineProps<{ toast: Toast }>()
const emit = defineEmits<{ dismiss: [id: number] }>()

const { t } = useI18n()

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
    role="status"
  >
    <AppIcon :path="ICONS[toast.severity]" :size="22" class="shrink-0" />
    <p class="flex-1 text-sm font-medium">{{ toast.message }}</p>
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
