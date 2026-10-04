import type { Router } from 'vue-router'
import { liveEntryBundle, runningEntryBundle } from '@/lib/freshBuild'

// Keeps a tab on the build the server serves, so a deploy reaches people
// who already have the app open — and a browser that served a stale
// index.html (seen on staging 2026-10-04) corrects itself instead of
// running last week's bundle until someone presses reload.
//
// Checked shortly after boot, whenever the tab becomes visible again, and
// every ten minutes; at most once a minute. The moment the live entry
// bundle differs from the running one the tab is STALE, and the only
// question is when to reload:
//
//   * on the gallery, right away — everything it shows is in the URL, so a
//     reload costs nothing (unless the reader is typing in a field, then it
//     waits for the next navigation);
//   * elsewhere, right after the next navigation TO the gallery, as a full
//     page load of that URL. Never inside the builder or a proposal page:
//     those hand state across routes in memory (the prefill seed, the
//     scenario hand-over), and a forced reload there would lose work.
//
// Off on the dev server, where no hashed entry exists to compare.

const STARTUP_DELAY_MS = 3_000
const PERIOD_MS = 10 * 60_000
const MIN_GAP_MS = 60_000

export function startFreshBuildWatch(router: Router): void {
  const running = runningEntryBundle(document)
  if (!running) return

  let stale = false
  let lastCheck = 0

  const typing = (): boolean =>
    document.activeElement instanceof HTMLInputElement ||
    document.activeElement instanceof HTMLTextAreaElement

  function reloadIfHarmless(): void {
    if (
      router.currentRoute.value.name === 'gallery' &&
      document.visibilityState === 'visible' &&
      !typing()
    ) {
      window.location.reload()
    }
  }

  async function check(): Promise<void> {
    if (stale || Date.now() - lastCheck < MIN_GAP_MS) return
    lastCheck = Date.now()
    try {
      const live = await liveEntryBundle()
      if (live && live !== running) {
        stale = true
        reloadIfHarmless()
      }
    } catch {
      // Offline or a hiccup: the next check will say.
    }
  }

  // After, not before, the navigation: the URL already names the gallery
  // route, so a plain reload lands on the new build at the right place —
  // for a click and for a back/forward step alike (cancelling a popstate
  // navigation in a guard would have the router revert the URL instead).
  router.afterEach((to) => {
    if (stale && to.name === 'gallery') window.location.reload()
  })

  window.setTimeout(check, STARTUP_DELAY_MS)
  window.setInterval(check, PERIOD_MS)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') check()
  })
}
