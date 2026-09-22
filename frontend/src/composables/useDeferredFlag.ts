// A boolean for things that should not flash: it turns on only once the
// source has been on for `delayMs`, and once on stays on for at least
// `minVisibleMs`. A source that is on for less than the delay never shows at
// all — which is the point for a loading scrim over a request that comes back
// from a cache in a few hundred milliseconds.

import { getCurrentInstance, onBeforeUnmount, ref, watch, type Ref, type WatchSource } from 'vue'

export function useDeferredFlag(
  source: WatchSource<boolean>,
  { delayMs, minVisibleMs }: { delayMs: number; minVisibleMs: number },
): Ref<boolean> {
  const visible = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  let shownAt = 0

  function clear() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }

  watch(
    source,
    (on) => {
      clear()
      if (on) {
        if (visible.value) return
        timer = setTimeout(() => {
          visible.value = true
          shownAt = Date.now()
        }, delayMs)
        return
      }
      if (!visible.value) return
      const remaining = minVisibleMs - (Date.now() - shownAt)
      if (remaining <= 0) visible.value = false
      else timer = setTimeout(() => (visible.value = false), remaining)
    },
    // Sync: the flag is timing, not rendering, and must see every flip of the
    // source rather than the last one of a tick.
    { immediate: true, flush: 'sync' },
  )
  if (getCurrentInstance()) onBeforeUnmount(clear)

  return visible
}
