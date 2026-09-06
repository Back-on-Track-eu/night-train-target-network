// Tracks whether the backend as a whole looks unwell, so the app can say
// "we're experiencing high demand" once instead of failing N times in silence.
//
// Deliberately NOT a Pinia store: this is plain observable state so it can be
// unit-tested in the node-env vitest config, and so apiClient can feed it
// without importing vue. The Vue side is composables/useApiHealth.ts.
//
// Passive by design — nothing here polls. The signal is the failures the app
// was already making, so an unwell server pays nothing to be detected.

export interface ApiHealthState {
  /** Consecutive outage-class failures with no intervening success. */
  consecutiveFailures: number
  /** Counter has reached the threshold. */
  degraded: boolean
  /** degraded AND the user hasn't dismissed this episode. */
  visible: boolean
}

/** What a settled request tells us. 'ignore' is for failures that say nothing
 *  about the server's health (rate limits, bad input) — see apiError.outcome. */
export type HealthSignal = 'ok' | 'outage' | 'ignore'

export interface ApiHealth {
  record(signal: HealthSignal): void
  /** Hide the banner for this episode. Re-arming requires an intervening 'ok' —
   *  without that rule the banner would reappear on the next failed request of
   *  the same outage, which is exactly what the user just dismissed. */
  dismiss(): void
  snapshot(): ApiHealthState
  subscribe(fn: (state: ApiHealthState) => void): () => void
}

const DEFAULT_THRESHOLD = 2

export function createApiHealth(opts?: { threshold?: number }): ApiHealth {
  const threshold = opts?.threshold ?? DEFAULT_THRESHOLD
  let failures = 0
  let dismissed = false
  const listeners = new Set<(state: ApiHealthState) => void>()

  function snapshot(): ApiHealthState {
    const degraded = failures >= threshold
    return { consecutiveFailures: failures, degraded, visible: degraded && !dismissed }
  }

  function emit(before: ApiHealthState): void {
    const after = snapshot()
    if (
      before.consecutiveFailures === after.consecutiveFailures &&
      before.degraded === after.degraded &&
      before.visible === after.visible
    ) {
      return
    }
    for (const fn of listeners) fn(after)
  }

  return {
    record(signal) {
      if (signal === 'ignore') return
      const before = snapshot()
      if (signal === 'ok') {
        failures = 0
        dismissed = false
      } else {
        failures += 1
      }
      emit(before)
    },
    dismiss() {
      if (dismissed) return
      const before = snapshot()
      dismissed = true
      emit(before)
    },
    snapshot,
    subscribe(fn) {
      listeners.add(fn)
      return () => {
        listeners.delete(fn)
      }
    },
  }
}

/** The instance apiClient feeds and the banner reads. */
export const apiHealth: ApiHealth = createApiHealth()
