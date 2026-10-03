import { describe, expect, it } from 'vitest'
import { TYPICAL_NIGHT_TRAIN, typicalNightTrainFilter } from './typicalNightTrain'

describe('typicalNightTrainFilter', () => {
  it('carries the position paper bounds on the three range columns, scoped to proposals', () => {
    expect(typicalNightTrainFilter()).toEqual({
      total_distance_km: { min: 500, max: 2000, scope: 'proposal' },
      total_time_h: { min: 7, max: 21, scope: 'proposal' },
      avg_speed_kmh: { min: 50, scope: 'proposal' },
    })
  })

  it('hands out copies, so a caller cannot mutate the constant', () => {
    const filter = typicalNightTrainFilter()
    filter.total_distance_km!.min = 1
    expect(TYPICAL_NIGHT_TRAIN.distanceKm.min).toBe(500)
  })
})
