import { describe, expect, test } from 'vitest'
import { mapLimit } from './promisePool'

/** A task that records peak concurrency while it runs. */
function tracker() {
  let inFlight = 0
  let peak = 0
  return {
    get peak() {
      return peak
    },
    async run<T>(value: T): Promise<T> {
      inFlight += 1
      peak = Math.max(peak, inFlight)
      await new Promise((r) => setTimeout(r, 1))
      inFlight -= 1
      return value
    },
  }
}

describe('mapLimit', () => {
  test('never exceeds the limit in flight', async () => {
    const t = tracker()
    const items = Array.from({ length: 20 }, (_, i) => i)
    await mapLimit(items, 4, (i) => t.run(i))
    expect(t.peak).toBeLessThanOrEqual(4)
    expect(t.peak).toBe(4)
  })

  test('results come back in input order, not completion order', async () => {
    const items = [30, 10, 20]
    const results = await mapLimit(items, 3, async (ms) => {
      await new Promise((r) => setTimeout(r, ms))
      return ms
    })
    expect(results).toEqual([
      { ok: true, value: 30 },
      { ok: true, value: 10 },
      { ok: true, value: 20 },
    ])
  })

  test('the index is passed through', async () => {
    const results = await mapLimit(['a', 'b'], 2, async (item, index) => `${index}:${item}`)
    expect(results.map((r) => (r.ok ? r.value : null))).toEqual(['0:a', '1:b'])
  })

  // The gallery draws the routes it got and raises one toast; a single failing
  // proposal must not abandon the other nineteen.
  test('a rejecting item is settled, not thrown', async () => {
    const boom = new Error('nope')
    const results = await mapLimit([1, 2, 3], 2, async (i) => {
      if (i === 2) throw boom
      return i
    })
    expect(results).toEqual([
      { ok: true, value: 1 },
      { ok: false, error: boom },
      { ok: true, value: 3 },
    ])
  })

  test('every item runs even when the first one fails', async () => {
    const seen: number[] = []
    await mapLimit([1, 2, 3, 4], 1, async (i) => {
      seen.push(i)
      if (i === 1) throw new Error('first')
      return i
    })
    expect(seen).toEqual([1, 2, 3, 4])
  })

  test('an empty list resolves immediately', async () => {
    await expect(mapLimit([], 4, async () => 1)).resolves.toEqual([])
  })

  test('a limit above the item count, or below one, is clamped', async () => {
    await expect(mapLimit([1, 2], 99, async (i) => i)).resolves.toHaveLength(2)
    await expect(mapLimit([1, 2], 0, async (i) => i)).resolves.toHaveLength(2)
  })
})
