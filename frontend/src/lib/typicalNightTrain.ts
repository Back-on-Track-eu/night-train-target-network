// The "typical night train" yardstick of the general position paper, as the
// gallery applies it: one way, 500–2 000 km, 7–16 hours, at least 50 km/h on
// average. The launch report counted with these bounds (at 60 km/h then —
// lowered to 50 on 2026-10-03 after looking at the existing catalogue, where
// the median real night train runs right around 60), so the gallery's
// default view is the set the report meant.
//
// Expressed as POST /api/proposals range filters on three summary columns,
// each with scope "proposal" (adapters/proposal/filter_builder.py): the
// bounds are asked of PROPOSALS ONLY and every existing (ONTD) train stays
// listed — the real trains are the comparison, whether or not they meet the
// paper's envelope (126 of production's 205 did not, 2026-10-03).

import type { ProposalsFilter, ProposalsRange } from '@/types/api'

export const TYPICAL_NIGHT_TRAIN = {
  distanceKm: { min: 500, max: 2000 },
  timeH: { min: 7, max: 16 },
  avgSpeedKmh: { min: 50 },
} as const satisfies Record<string, Pick<ProposalsRange, 'min' | 'max'>>

/** The filter keys the sieve sets — what a caller merges into its own. */
export function typicalNightTrainFilter(): Pick<
  ProposalsFilter,
  'total_distance_km' | 'total_time_h' | 'avg_speed_kmh'
> {
  return {
    total_distance_km: { ...TYPICAL_NIGHT_TRAIN.distanceKm, scope: 'proposal' },
    total_time_h: { ...TYPICAL_NIGHT_TRAIN.timeH, scope: 'proposal' },
    avg_speed_kmh: { ...TYPICAL_NIGHT_TRAIN.avgSpeedKmh, scope: 'proposal' },
  }
}
