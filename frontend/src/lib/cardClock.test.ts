import { describe, expect, it } from 'vitest'
import { clockMinutes, endpointClocks } from './cardClock'

describe('clockMinutes', () => {
  it('reads hours past 24', () => {
    expect(clockMinutes('30:43')).toBe(30 * 60 + 43)
  })

  it('is null for a missing or malformed time', () => {
    expect(clockMinutes(null)).toBeNull()
    expect(clockMinutes('6.43')).toBeNull()
  })
})

describe('endpointClocks', () => {
  it('shows an overnight arrival on the 24-hour clock, one day later', () => {
    expect(endpointClocks('21:14', '30:43')).toEqual({
      departure: { time: '21:14', dayOffset: 0 },
      arrival: { time: '06:43', dayOffset: 1 },
    })
  })

  it('counts the arrival day from the departure day', () => {
    expect(endpointClocks('25:10', '31:00')).toEqual({
      departure: { time: '01:10', dayOffset: 0 },
      arrival: { time: '07:00', dayOffset: 0 },
    })
  })

  it('reads an arrival before the departure as the next day (times wrapped at 24:00)', () => {
    expect(endpointClocks('18:00', '14:30')).toEqual({
      departure: { time: '18:00', dayOffset: 0 },
      arrival: { time: '14:30', dayOffset: 1 },
    })
  })

  it('leaves out whichever end has no time', () => {
    expect(endpointClocks(null, '08:05')).toEqual({
      departure: null,
      arrival: { time: '08:05', dayOffset: 0 },
    })
  })
})
