// Turns a classified ApiFailure into user-facing copy and, when appropriate, a
// toast. The decision of WHICH surface a failure belongs on is made once, in
// lib/apiError.ts; this is only the Vue-side plumbing (i18n + the toast store).
//
// Inline rendering stays the caller's job — a component owns its own layout and
// knows where the error belongs relative to its controls.

import { useI18n } from 'vue-i18n'
import { ApiError, asApiFailure, messageKey, treatment } from '@/lib/apiError'
import { useToastStore } from '@/stores/toastStore'
import type { ToastAction } from '@/lib/toastQueue'

export function useApiFailure() {
  const { t } = useI18n()
  const toasts = useToastStore()

  // Kinds where naming what failed adds nothing: the classified sentence
  // already says it ("You don't have access to that", "We couldn't find that"),
  // or the backend's own text is doing the work.
  const NO_CONTEXT_PREFIX = new Set(['validation', 'bad_input', 'auth', 'not_found'])

  /**
   * The sentence to show a user.
   *
   * Order of preference: the backend's own text where it is written for users
   * (validation details, bad input), then reviewed copy chosen by
   * classification. `contextKey` names what was being attempted and is
   * PREPENDED rather than substituted — "Proposals couldn't be loaded." on its
   * own hides whose fault it is, and the classified sentence is what carries
   * the fault attribution and the "try again in a moment".
   */
  function describe(err: unknown, contextKey?: string): string {
    if (err instanceof ApiError) {
      if (err.verbatim) return err.verbatim
      const classified = t(messageKey(err.failure))
      if (!contextKey || NO_CONTEXT_PREFIX.has(err.failure.kind)) return classified
      const context = t(contextKey)
      // A caller whose context key resolves to the same copy as the classified
      // message must not print it twice — cheap insurance, since the two keys
      // are chosen independently and can legitimately coincide.
      if (context === classified) return classified
      return `${context} ${classified}`
    }
    // Not one of ours — an unexpected client-side throw. Blaming the server
    // would be a guess, so lead with the context and keep the copy generic.
    return contextKey ? `${t(contextKey)} ${t('errors.server')}` : t('errors.server')
  }

  /**
   * Surface a failure on whichever channel its classification calls for.
   * Returns true when it was toasted, so a caller can skip its own inline copy.
   * Cancellations return false and produce nothing.
   */
  function report(
    err: unknown,
    opts?: { fallbackKey?: string; force?: 'toast' | 'inline'; action?: ToastAction },
  ): boolean {
    const failure = asApiFailure(err)
    if (failure?.kind === 'canceled') return false

    const where = opts?.force ?? (failure ? treatment(failure) : 'toast')
    if (where !== 'toast') return false

    toasts.addToast('error', describe(err, opts?.fallbackKey), {
      // Merge by failure kind, so twenty instances of one outage are one toast.
      key: failure ? `api:${failure.kind}` : 'api:unknown',
      ...(opts?.action ? { action: opts.action } : {}),
    })
    return true
  }

  return { describe, report }
}
