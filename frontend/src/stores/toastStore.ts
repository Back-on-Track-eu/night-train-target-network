import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  buildToast,
  mergeToast,
  toastKey,
  type ToastAction,
  type ToastItem,
  type ToastSeverity,
  type ToastSpec,
} from '@/lib/toastQueue'

// The queue arithmetic (sticky errors, dedupe, cap) lives in lib/toastQueue.ts
// so it can be unit-tested; this store owns only the reactive list and the
// dismissal timers.

export type { ToastSeverity, ToastAction }
/** Kept as `Toast` for the components that already import this name. */
export type Toast = ToastItem

export const useToastStore = defineStore('toast', () => {
  const toasts = ref<ToastItem[]>([])
  let nextId = 0
  const timers = new Map<number, ReturnType<typeof setTimeout>>()

  function clearTimer(id: number): void {
    const timer = timers.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.delete(id)
    }
  }

  function armTimer(toast: ToastItem): void {
    clearTimer(toast.id)
    // null = sticky (errors), so the user decides when it goes.
    if (toast.timeoutMs === null) return
    timers.set(
      toast.id,
      setTimeout(() => dismissToast(toast.id), toast.timeoutMs),
    )
  }

  /**
   * Raise a toast. Repeats of the same `key` (default `severity:message`) merge
   * into the existing one and bump its count rather than stacking — during an
   * outage the same failure can arrive dozens of times.
   */
  function addToast(
    severity: ToastSeverity,
    message: string,
    opts?: Omit<ToastSpec, 'severity' | 'message'>,
  ): number {
    const spec: ToastSpec = { severity, message, ...opts }
    const result = mergeToast(toasts.value, buildToast(spec, nextId++))
    for (const id of result.evicted) clearTimer(id)
    toasts.value = result.list
    armTimer(result.active)
    return result.active.id
  }

  function dismissToast(id: number): void {
    clearTimer(id)
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  /** Drop a toast by merge key — used to clear a stale failure once the same
   *  request succeeds, so a recovered error doesn't sit there indefinitely. */
  function dismissByKey(key: string): void {
    for (const toast of toasts.value) {
      if (toast.key === key) clearTimer(toast.id)
    }
    toasts.value = toasts.value.filter((toast) => toast.key !== key)
  }

  return { toasts, addToast, dismissToast, dismissByKey, toastKey }
})
