import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMediaQuery } from './useMediaQuery'

// A stand-in for window.matchMedia that remembers its 'change' listeners so
// a test can flip the answer the way a real resize would.
function fakeMatchMedia(initial: boolean) {
  const listeners = new Set<(e: { matches: boolean }) => void>()
  const list = {
    matches: initial,
    addEventListener: (_: 'change', fn: (e: { matches: boolean }) => void) => listeners.add(fn),
    removeEventListener: (_: 'change', fn: (e: { matches: boolean }) => void) =>
      listeners.delete(fn),
  }
  const flip = (matches: boolean) => {
    list.matches = matches
    for (const fn of listeners) fn({ matches })
  }
  return { list, flip, listeners }
}

afterEach(() => vi.unstubAllGlobals())

describe('useMediaQuery', () => {
  it('answers false where there is no window (SSR, node tests)', () => {
    expect(useMediaQuery('(min-width: 64rem)').value).toBe(false)
  })

  it('starts from the current answer and follows changes', () => {
    const { list, flip } = fakeMatchMedia(true)
    vi.stubGlobal('window', { matchMedia: () => list })
    const wide = useMediaQuery('(min-width: 64rem)')
    expect(wide.value).toBe(true)
    flip(false)
    expect(wide.value).toBe(false)
    flip(true)
    expect(wide.value).toBe(true)
  })

  it('asks matchMedia for the query it was given', () => {
    const matchMedia = vi.fn(() => fakeMatchMedia(false).list)
    vi.stubGlobal('window', { matchMedia })
    useMediaQuery('(min-width: 40rem)')
    expect(matchMedia).toHaveBeenCalledWith('(min-width: 40rem)')
  })
})
