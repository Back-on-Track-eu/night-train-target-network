// Queue arithmetic for the toast stack, split out of stores/toastStore.ts so it
// can be unit-tested (the store keeps only the ref and the timer map).
//
// Three rules the old store lacked, all of which matter during an outage:
//   - errors are STICKY. A 4-second auto-dismiss on the most important message
//     in the app was backwards.
//   - identical toasts MERGE. Without this, 20 failed map fetches meant 20
//     stacked toasts, and making errors role="alert" would be unbearable.
//   - the stack is CAPPED, and a success can never evict a sticky error.

export type ToastSeverity = 'success' | 'error' | 'info' | 'warn'

export interface ToastAction {
  /** i18n key, resolved by the component — nothing here imports vue-i18n. */
  labelKey: string
  run: () => void
}

export interface ToastSpec {
  severity: ToastSeverity
  message: string
  /** Merge identity. Defaults to `${severity}:${message}`; API failures use
   *  `api:${kind}` so differently-worded instances of one outage still merge. */
  key?: string
  /** null = sticky. Omit to take the severity default. */
  timeoutMs?: number | null
  action?: ToastAction
}

export interface ToastItem {
  id: number
  severity: ToastSeverity
  message: string
  key: string
  timeoutMs: number | null
  /** How many times this toast has been raised. Rendered as ×N when > 1. */
  count: number
  action?: ToastAction
}

export const AUTO_DISMISS_MS = 4000
export const MAX_TOASTS = 4

/** Errors persist until dismissed; everything else fades. */
export function defaultTimeoutFor(severity: ToastSeverity): number | null {
  return severity === 'error' ? null : AUTO_DISMISS_MS
}

export function toastKey(spec: ToastSpec): string {
  return spec.key ?? `${spec.severity}:${spec.message}`
}

export function buildToast(spec: ToastSpec, id: number): ToastItem {
  return {
    id,
    severity: spec.severity,
    message: spec.message,
    key: toastKey(spec),
    timeoutMs: spec.timeoutMs === undefined ? defaultTimeoutFor(spec.severity) : spec.timeoutMs,
    count: 1,
    ...(spec.action ? { action: spec.action } : {}),
  }
}

export interface MergeResult {
  list: ToastItem[]
  /** The item the caller should (re)arm a timer for — the merged one when a
   *  merge happened, otherwise the new one. */
  active: ToastItem
  merged: boolean
  /** Ids dropped by the cap; the caller clears their timers. */
  evicted: number[]
}

/**
 * Insert `incoming` at the head of `list`, merging into an existing toast with
 * the same key, then enforce MAX_TOASTS by evicting the oldest NON-error first
 * (a success must never push out a sticky error the user hasn't seen).
 */
export function mergeToast(list: readonly ToastItem[], incoming: ToastItem): MergeResult {
  const existing = list.find((t) => t.key === incoming.key)
  if (existing) {
    const merged: ToastItem = {
      ...existing,
      count: existing.count + 1,
      // Take the newest message and action — same key, possibly fresher detail.
      message: incoming.message,
      timeoutMs: incoming.timeoutMs,
      ...(incoming.action ? { action: incoming.action } : {}),
    }
    return {
      list: [merged, ...list.filter((t) => t.key !== incoming.key)],
      active: merged,
      merged: true,
      evicted: [],
    }
  }

  let next = [incoming, ...list]
  const evicted: number[] = []
  while (next.length > MAX_TOASTS) {
    // Oldest first within the least-important class we're willing to drop.
    const victim = [...next].reverse().find((t) => t.severity !== 'error') ?? next[next.length - 1]
    evicted.push(victim.id)
    next = next.filter((t) => t.id !== victim.id)
  }
  return { list: next, active: incoming, merged: false, evicted }
}
