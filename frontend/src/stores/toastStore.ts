import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastSeverity = 'success' | 'error' | 'info' | 'warn'

export interface Toast {
  id: number
  severity: ToastSeverity
  message: string
}

const AUTO_DISMISS_MS = 4000

export const useToastStore = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])
  let nextId = 0
  const timers = new Map<number, ReturnType<typeof setTimeout>>()

  function addToast(severity: ToastSeverity, message: string): number {
    const id = nextId++
    toasts.value = [{ id, severity, message }, ...toasts.value]
    timers.set(
      id,
      setTimeout(() => dismissToast(id), AUTO_DISMISS_MS),
    )
    return id
  }

  function dismissToast(id: number): void {
    const timer = timers.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.delete(id)
    }
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  return { toasts, addToast, dismissToast }
})
