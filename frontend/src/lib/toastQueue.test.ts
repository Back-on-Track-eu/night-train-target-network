import { describe, expect, test } from 'vitest'
import {
  AUTO_DISMISS_MS,
  MAX_TOASTS,
  buildToast,
  defaultTimeoutFor,
  mergeToast,
  type ToastItem,
} from './toastQueue'

let nextId = 0
function item(severity: ToastItem['severity'], message: string, key?: string): ToastItem {
  return buildToast({ severity, message, ...(key ? { key } : {}) }, nextId++)
}

describe('defaultTimeoutFor', () => {
  test('errors stick until dismissed; everything else fades', () => {
    expect(defaultTimeoutFor('error')).toBeNull()
    expect(defaultTimeoutFor('success')).toBe(AUTO_DISMISS_MS)
    expect(defaultTimeoutFor('info')).toBe(AUTO_DISMISS_MS)
    expect(defaultTimeoutFor('warn')).toBe(AUTO_DISMISS_MS)
  })

  test('an explicit timeout still wins, including an explicit null', () => {
    expect(
      buildToast({ severity: 'success', message: 'x', timeoutMs: null }, 1).timeoutMs,
    ).toBeNull()
    expect(buildToast({ severity: 'error', message: 'x', timeoutMs: 500 }, 1).timeoutMs).toBe(500)
  })
})

describe('mergeToast — dedupe', () => {
  test('the same message twice is one toast with a count', () => {
    const first = item('error', 'Server trouble.')
    const second = item('error', 'Server trouble.')

    const once = mergeToast([], first)
    expect(once.merged).toBe(false)
    expect(once.list).toHaveLength(1)

    const twice = mergeToast(once.list, second)
    expect(twice.merged).toBe(true)
    expect(twice.list).toHaveLength(1)
    expect(twice.list[0].count).toBe(2)
    expect(twice.list[0].id).toBe(first.id)
    expect(twice.active.id).toBe(first.id)
  })

  // The gallery fans out one request per card; during an outage that is 20
  // failures of one kind. They must collapse, or role="alert" is unusable.
  test('an explicit key merges differently-worded instances of one failure', () => {
    let list: ToastItem[] = []
    for (let i = 0; i < 20; i++) {
      list = mergeToast(list, item('error', `Route ${i} failed.`, 'api:server')).list
    }
    expect(list).toHaveLength(1)
    expect(list[0].count).toBe(20)
    // The newest wording is kept.
    expect(list[0].message).toBe('Route 19 failed.')
  })

  test('different keys stay separate', () => {
    const a = mergeToast([], item('error', 'A', 'api:server'))
    const b = mergeToast(a.list, item('error', 'B', 'api:offline'))
    expect(b.list).toHaveLength(2)
    expect(b.merged).toBe(false)
  })

  test('a merged toast moves back to the head of the stack', () => {
    const older = item('error', 'Older', 'api:server')
    const newer = item('info', 'Newer', 'info:x')
    const list = mergeToast(mergeToast([], older).list, newer).list
    expect(list[0].key).toBe('info:x')

    const merged = mergeToast(list, item('error', 'Older again', 'api:server'))
    expect(merged.list[0].key).toBe('api:server')
  })
})

describe('mergeToast — cap', () => {
  test('newest first, oldest dropped past the cap', () => {
    let list: ToastItem[] = []
    const ids: number[] = []
    for (let i = 0; i < MAX_TOASTS + 1; i++) {
      const next = item('info', `msg ${i}`, `info:${i}`)
      ids.push(next.id)
      list = mergeToast(list, next).list
    }
    expect(list).toHaveLength(MAX_TOASTS)
    expect(list.map((t) => t.id)).not.toContain(ids[0])
  })

  test('a success never evicts a sticky error', () => {
    let list: ToastItem[] = []
    const error = item('error', 'Something broke.', 'api:server')
    list = mergeToast(list, error).list
    for (let i = 0; i < MAX_TOASTS + 2; i++) {
      list = mergeToast(list, item('success', `ok ${i}`, `success:${i}`)).list
    }
    expect(list).toHaveLength(MAX_TOASTS)
    expect(list.some((t) => t.id === error.id)).toBe(true)
  })

  test('evicted ids are reported so the caller can clear their timers', () => {
    let list: ToastItem[] = []
    const first = item('info', 'first', 'info:first')
    list = mergeToast(list, first).list
    for (let i = 0; i < MAX_TOASTS - 1; i++) {
      list = mergeToast(list, item('info', `fill ${i}`, `info:fill${i}`)).list
    }
    const result = mergeToast(list, item('info', 'overflow', 'info:overflow'))
    expect(result.evicted).toEqual([first.id])
  })

  test('past the cap with nothing but errors, the oldest error goes', () => {
    let list: ToastItem[] = []
    const oldest = item('error', 'oldest', 'api:a')
    list = mergeToast(list, oldest).list
    for (let i = 0; i < MAX_TOASTS; i++) {
      list = mergeToast(list, item('error', `e${i}`, `api:e${i}`)).list
    }
    expect(list).toHaveLength(MAX_TOASTS)
    expect(list.some((t) => t.id === oldest.id)).toBe(false)
  })
})
