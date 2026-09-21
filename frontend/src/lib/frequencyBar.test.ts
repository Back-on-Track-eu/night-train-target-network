import { describe, it, expect } from 'vitest'
import {
  FREQUENCY_TICKS,
  frequencyFromKey,
  frequencyFromPointer,
  frequencyPosition,
  frequencyQualifier,
} from './frequencyBar'

describe('the frequency bar', () => {
  it('has a tick for every whole day of the week', () => {
    expect(FREQUENCY_TICKS).toEqual([1, 2, 3, 4, 5, 6, 7])
    expect(frequencyPosition(1)).toBe(0)
    expect(frequencyPosition(4)).toBe(0.5)
    expect(frequencyPosition(7)).toBe(1)
  })

  it('snaps a pointer to the nearest tick and never leaves the range', () => {
    expect(frequencyFromPointer(0, 600)).toBe(1)
    expect(frequencyFromPointer(600, 600)).toBe(7)
    expect(frequencyFromPointer(300, 600)).toBe(4)
    expect(frequencyFromPointer(240, 600)).toBe(3) // 3.4 rounds down
    expect(frequencyFromPointer(-50, 600)).toBe(1)
    expect(frequencyFromPointer(900, 600)).toBe(7)
    expect(frequencyFromPointer(10, 0)).toBe(1)
  })

  it('steps by one on the arrow keys and jumps on Home/End', () => {
    expect(frequencyFromKey('ArrowRight', 3)).toBe(4)
    expect(frequencyFromKey('ArrowUp', 7)).toBe(7)
    expect(frequencyFromKey('ArrowLeft', 1)).toBe(1)
    expect(frequencyFromKey('ArrowDown', 5)).toBe(4)
    expect(frequencyFromKey('Home', 5)).toBe(1)
    expect(frequencyFromKey('End', 5)).toBe(7)
    expect(frequencyFromKey('a', 5)).toBeNull()
  })

  it('qualifies the two ends of the range in words', () => {
    expect(frequencyQualifier(7)).toBe('everyDay')
    expect(frequencyQualifier(1)).toBe('onceAWeek')
    expect(frequencyQualifier(3)).toBeNull()
  })
})
