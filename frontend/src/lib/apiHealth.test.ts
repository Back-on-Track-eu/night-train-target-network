import { describe, expect, test, vi } from 'vitest'
import { createApiHealth } from './apiHealth'

describe('createApiHealth', () => {
  test('one outage is not enough; two consecutive ones are', () => {
    const health = createApiHealth()
    health.record('outage')
    expect(health.snapshot()).toEqual({ consecutiveFailures: 1, degraded: false, visible: false })
    health.record('outage')
    expect(health.snapshot()).toEqual({ consecutiveFailures: 2, degraded: true, visible: true })
  })

  test('failures are consecutive, not cumulative', () => {
    const health = createApiHealth()
    health.record('outage')
    health.record('ok')
    health.record('outage')
    expect(health.snapshot().degraded).toBe(false)
  })

  test('a success clears the episode', () => {
    const health = createApiHealth()
    health.record('outage')
    health.record('outage')
    health.record('ok')
    expect(health.snapshot()).toEqual({ consecutiveFailures: 0, degraded: false, visible: false })
  })

  test("'ignore' never moves the counter", () => {
    const health = createApiHealth()
    health.record('ignore')
    health.record('ignore')
    health.record('ignore')
    expect(health.snapshot().consecutiveFailures).toBe(0)
  })

  test('dismiss hides the banner but keeps the degraded fact', () => {
    const health = createApiHealth()
    health.record('outage')
    health.record('outage')
    health.dismiss()
    expect(health.snapshot()).toEqual({ consecutiveFailures: 2, degraded: true, visible: false })
  })

  // Without this rule the banner reappears on the very next failed request of
  // the outage the user just dismissed.
  test('a further outage does not re-show a dismissed banner', () => {
    const health = createApiHealth()
    health.record('outage')
    health.record('outage')
    health.dismiss()
    health.record('outage')
    health.record('outage')
    expect(health.snapshot().visible).toBe(false)
  })

  test('recovery re-arms it, so a later outage shows again', () => {
    const health = createApiHealth()
    health.record('outage')
    health.record('outage')
    health.dismiss()
    health.record('ok')
    health.record('outage')
    health.record('outage')
    expect(health.snapshot().visible).toBe(true)
  })

  test('threshold is configurable', () => {
    const health = createApiHealth({ threshold: 3 })
    health.record('outage')
    health.record('outage')
    expect(health.snapshot().degraded).toBe(false)
    health.record('outage')
    expect(health.snapshot().degraded).toBe(true)
  })

  test('subscribers see changes, not no-ops, and can detach', () => {
    const health = createApiHealth()
    const seen = vi.fn()
    const unsubscribe = health.subscribe(seen)

    health.record('ignore')
    expect(seen).not.toHaveBeenCalled()

    health.record('outage')
    expect(seen).toHaveBeenCalledTimes(1)
    expect(seen).toHaveBeenLastCalledWith({
      consecutiveFailures: 1,
      degraded: false,
      visible: false,
    })

    health.record('outage')
    expect(seen).toHaveBeenLastCalledWith({ consecutiveFailures: 2, degraded: true, visible: true })

    unsubscribe()
    health.record('ok')
    expect(seen).toHaveBeenCalledTimes(2)
  })

  test('a redundant dismiss does not notify', () => {
    const health = createApiHealth()
    health.record('outage')
    health.record('outage')
    const seen = vi.fn()
    health.subscribe(seen)
    health.dismiss()
    health.dismiss()
    expect(seen).toHaveBeenCalledTimes(1)
  })

  test('instances are independent (no module-level state)', () => {
    const a = createApiHealth()
    const b = createApiHealth()
    a.record('outage')
    a.record('outage')
    expect(a.snapshot().degraded).toBe(true)
    expect(b.snapshot().degraded).toBe(false)
  })
})
