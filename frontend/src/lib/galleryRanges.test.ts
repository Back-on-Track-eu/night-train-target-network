import { describe, expect, it } from 'vitest'
import {
  isTypicalNightTrain,
  rangesFromQuery,
  rangesToFilter,
  rangesToQuery,
  sameRanges,
  typicalNightTrainRanges,
} from './galleryRanges'
import { TYPICAL_NIGHT_TRAIN } from './typicalNightTrain'

describe('typicalNightTrainRanges', () => {
  it('is the position paper envelope on three measures and no stops range', () => {
    expect(typicalNightTrainRanges()).toEqual({
      total_distance_km: { min: 500, max: 2000 },
      total_time_h: { min: 7, max: 21 },
      avg_speed_kmh: { min: 50 },
    })
  })

  it('hands out copies, so a caller cannot mutate the constant', () => {
    const ranges = typicalNightTrainRanges()
    ranges.total_distance_km!.min = 1
    expect(TYPICAL_NIGHT_TRAIN.distanceKm.min).toBe(500)
  })
})

describe('rangesToFilter', () => {
  it('scopes every bounded measure to proposals and drops empty pairs', () => {
    expect(rangesToFilter({ ...typicalNightTrainRanges(), n_stops: {} })).toEqual({
      total_distance_km: { min: 500, max: 2000, scope: 'proposal' },
      total_time_h: { min: 7, max: 21, scope: 'proposal' },
      avg_speed_kmh: { min: 50, scope: 'proposal' },
    })
  })
})

describe('sameRanges', () => {
  it('ignores empty pairs and undefined bounds', () => {
    expect(
      sameRanges(
        { n_stops: {}, total_time_h: { min: 7, max: undefined } },
        { total_time_h: { min: 7 } },
      ),
    ).toBe(true)
    expect(isTypicalNightTrain({ ...typicalNightTrainRanges(), n_stops: { min: 3 } })).toBe(false)
  })
})

describe('URL round trip', () => {
  it('writes nothing for the preset', () => {
    expect(rangesToQuery(typicalNightTrainRanges())).toEqual({})
    expect(rangesFromQuery({})).toEqual(typicalNightTrainRanges())
  })

  it('writes typical=0 for no ranges at all, and reads the old toggle links', () => {
    expect(rangesToQuery({})).toEqual({ typical: '0' })
    expect(rangesFromQuery({ typical: '0' })).toEqual({})
  })

  it('writes each bounded measure with an empty open side', () => {
    const ranges = {
      total_distance_km: { min: 500, max: 2000 },
      avg_speed_kmh: { min: 50 },
      n_stops: { max: 8 },
    }
    expect(rangesToQuery(ranges)).toEqual({ km: '500-2000', kmh: '50-', stops: '-8' })
    expect(rangesFromQuery({ km: '500-2000', kmh: '50-', stops: '-8' })).toEqual(ranges)
  })

  it('an explicit range key means no preset, even when malformed', () => {
    expect(rangesFromQuery({ km: 'abc' })).toEqual({})
    expect(rangesFromQuery({ km: ['100-200', '300-400'] })).toEqual({
      total_distance_km: { min: 100, max: 200 },
    })
  })
})
