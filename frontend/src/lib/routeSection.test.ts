import { describe, it, expect } from 'vitest'
import { nearestHandle } from './routeSection'

describe('nearestHandle', () => {
  it('moves the origin for clicks at or before it', () => {
    expect(nearestHandle(0, 2, 7)).toBe(0)
    expect(nearestHandle(2, 2, 7)).toBe(0)
  })

  it('moves the destination for clicks at or after it', () => {
    expect(nearestHandle(7, 2, 7)).toBe(1)
    expect(nearestHandle(9, 2, 7)).toBe(1)
  })

  it('picks the nearer handle for interior clicks', () => {
    expect(nearestHandle(3, 2, 7)).toBe(0)
    expect(nearestHandle(6, 2, 7)).toBe(1)
  })

  it('breaks interior ties toward the origin', () => {
    // equidistant: 4 - 2 === 6 - 4
    expect(nearestHandle(4, 2, 6)).toBe(0)
  })

  it('never picks a handle the one-leg-apart clamp would drag off target', () => {
    // Adjacent handles: a click on either endpoint must move that endpoint, so
    // the clamp (min(n, dest-1) / max(n, origin+1)) leaves it where it landed.
    expect(nearestHandle(3, 3, 4)).toBe(0)
    expect(nearestHandle(4, 3, 4)).toBe(1)
  })
})
