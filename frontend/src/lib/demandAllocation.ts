// The traveller-group allocation rule of DEMAND 0.1.0 (docs/2026-09-18_
// manual_demand_guide.md D14–D19), ported one-to-one from the sketch's
// allocate() and mirrored by the backend's models/demand/groups.py. The
// Details card previews it live between recalculations; the backend's
// figures are the ones that count, and the parity test
// (demandAllocation.test.ts) pins both ports to the same reference values.
//
// Four rounds release a share of every group's demand; in each round the
// groups are walked in order and seat what they released: RULE_SHARE along
// the preference list, first class until full, then the next; the rest is
// spread evenly over the group's OTHER listed classes first, and whatever of
// it cannot be seated rejoins the rule-followers. A group sits only in the
// classes it lists — demand no listed class can seat is not served. Expected
// values, never random draws.

export const CLASS_ORDER = ['Seat', 'Couchette', 'Sleeper', 'Capsule'] as const
export type ClassMain = (typeof CLASS_ORDER)[number]

export const GROUP_ORDER = ['comfort', 'group', 'senior', 'budget', 'business'] as const
export type GroupKey = (typeof GROUP_ORDER)[number]

/** The classes each group books, first preference first — and ONLY those. */
export const GROUP_CLASS_PREFERENCES: Record<GroupKey, readonly ClassMain[]> = {
  comfort: ['Sleeper', 'Capsule', 'Couchette'],
  group: ['Couchette', 'Seat'],
  senior: ['Couchette', 'Sleeper'],
  budget: ['Seat'],
  business: ['Sleeper', 'Capsule'],
}

/** Share of each group's demand released in each round (percent). */
export const ROUNDS_PCT = [50, 20, 20, 10] as const

/** Within a round, the share of a group's released demand that follows the
 *  rule; the rest spreads over the group's other listed classes. */
export const RULE_SHARE = 0.8

export interface Allocation {
  byGroupByClass: Record<GroupKey, Record<ClassMain, number>>
  byClass: Record<ClassMain, number>
  served: number
  notServedByGroup: Record<GroupKey, number>
  notServed: number
  demandByGroup: Record<GroupKey, number>
}

/** Passengers per group from a total and the shares as entered — in floats,
 *  never rounded per group; a share sum other than 100 is reflected, not
 *  rebalanced (D15). */
export function splitByGroup(
  total: number,
  sharesPct: Record<string, number>,
): Record<GroupKey, number> {
  const out = {} as Record<GroupKey, number>
  for (const g of GROUP_ORDER) out[g] = (total * (sharesPct[g] ?? 0)) / 100
  return out
}

/** Seat one departure's group demand onto a train with these places. */
export function allocate(
  placesByClass: Record<string, number>,
  demandByGroup: Record<string, number>,
): Allocation {
  const room = {} as Record<ClassMain, number>
  for (const c of CLASS_ORDER) room[c] = placesByClass[c] ?? 0
  const demand = {} as Record<GroupKey, number>
  const left = {} as Record<GroupKey, number>
  const pending = {} as Record<GroupKey, number>
  const alloc = {} as Record<GroupKey, Record<ClassMain, number>>
  for (const g of GROUP_ORDER) {
    demand[g] = demandByGroup[g] ?? 0
    left[g] = demand[g]
    pending[g] = 0
    alloc[g] = {} as Record<ClassMain, number>
    for (const c of CLASS_ORDER) alloc[g][c] = 0
  }

  const seat = (g: GroupKey, c: ClassMain, amount: number): number => {
    const take = Math.min(amount, room[c])
    if (take > 0) {
      alloc[g][c] += take
      room[c] -= take
      left[g] -= take
    }
    return take
  }

  for (const share of ROUNDS_PCT) {
    for (const g of GROUP_ORDER) {
      const prefs = GROUP_CLASS_PREFERENCES[g]
      const others = prefs.slice(1)
      const released = (demand[g] * share) / 100
      const stray = others.length ? released * (1 - RULE_SHARE) : 0
      pending[g] += released - stray
      for (const c of others) {
        const each = stray / others.length
        pending[g] += each - seat(g, c, each)
      }
      for (const c of prefs) pending[g] -= seat(g, c, pending[g])
    }
  }

  const byClass = {} as Record<ClassMain, number>
  for (const c of CLASS_ORDER) byClass[c] = GROUP_ORDER.reduce((s, g) => s + alloc[g][c], 0)
  const notServedByGroup = {} as Record<GroupKey, number>
  for (const g of GROUP_ORDER) notServedByGroup[g] = Math.max(0, left[g])
  return {
    byGroupByClass: alloc,
    byClass,
    served: CLASS_ORDER.reduce((s, c) => s + byClass[c], 0),
    notServedByGroup,
    notServed: GROUP_ORDER.reduce((s, g) => s + notServedByGroup[g], 0),
    demandByGroup: demand,
  }
}
