import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useDeferredFlag } from './useDeferredFlag'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('useDeferredFlag', () => {
  const opts = { delayMs: 500, minVisibleMs: 700 }

  it('never shows for a source that is on less than the delay', () => {
    const source = ref(false)
    const visible = useDeferredFlag(source, opts)
    source.value = true
    vi.advanceTimersByTime(400)
    source.value = false
    vi.advanceTimersByTime(5_000)
    expect(visible.value).toBe(false)
  })

  it('shows after the delay and stays for the minimum', () => {
    const source = ref(false)
    const visible = useDeferredFlag(source, opts)
    source.value = true
    vi.advanceTimersByTime(500)
    expect(visible.value).toBe(true)
    vi.advanceTimersByTime(100)
    source.value = false
    expect(visible.value).toBe(true)
    vi.advanceTimersByTime(599)
    expect(visible.value).toBe(true)
    vi.advanceTimersByTime(1)
    expect(visible.value).toBe(false)
  })

  it('hides at once when it has already been shown long enough', () => {
    const source = ref(false)
    const visible = useDeferredFlag(source, opts)
    source.value = true
    vi.advanceTimersByTime(3_000)
    source.value = false
    expect(visible.value).toBe(false)
  })

  it('stays up when the source comes back during the minimum', () => {
    const source = ref(false)
    const visible = useDeferredFlag(source, opts)
    source.value = true
    vi.advanceTimersByTime(600)
    source.value = false
    source.value = true
    vi.advanceTimersByTime(5_000)
    expect(visible.value).toBe(true)
  })
})
