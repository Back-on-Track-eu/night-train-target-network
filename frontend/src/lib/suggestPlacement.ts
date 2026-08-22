// Timeline placement for auto_stop_addition="suggest": interleave the stops
// the route was actually run with (confirmed) and the candidate stops the
// backend proposed along the way (suggested) into one ordered list.
//
// Extracted from ProposalViewport.vue so the ordering rule is testable on its
// own — it is pure geometry plus the backend's ordering, no Vue involved.

import type { SuggestedStop } from '@/types/api'

// The subset of a routed trip's stop_times this placement needs.
export interface ConfirmedStop {
  stop_id: string
  stop_name: string
  lat: number
  lon: number
}

export interface SuggestRow {
  kind: 'confirmed' | 'suggested'
  stopId: string
  name: string
  lat: number
  lon: number
  selected: boolean
  addedMin: number | null
}

function dist(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const dLat = a.lat - b.lat
  const dLon = a.lon - b.lon
  return Math.sqrt(dLat * dLat + dLon * dLon)
}

// Detour a point adds to the leg a→b: the classic triangle delta, ~0 for a
// point sitting on the leg and growing the further off it lies.
function detour(
  a: { lat: number; lon: number },
  p: { lat: number; lon: number },
  b: { lat: number; lon: number },
): number {
  return dist(a, p) + dist(p, b) - dist(a, b)
}

// Which confirmed stop each suggestion follows, as an index into `confirmed`.
//
// The backend hands suggestions over already ordered along the route — sorted
// by (leg_index, along_leg_fraction) in timetable.suggest_auto_stops() — so
// their leg assignment can only ever move forward. Walking a pointer through
// the legs enforces exactly that: geometry picks *which* leg a suggestion sits
// on, but never lets it fall behind a suggestion that came before it, and
// never outside the caller's own endpoints (a suggestion is by definition a
// stop *along the way*, so it can neither precede the origin nor follow the
// destination).
function assignLegs(confirmed: ConfirmedStop[], suggestions: SuggestedStop[]): number[] {
  const lastLeg = confirmed.length - 2
  let leg = 0
  return suggestions.map((s) => {
    let best = leg
    let bestCost = Infinity
    for (let i = leg; i <= lastLeg; i++) {
      const cost = detour(confirmed[i], s, confirmed[i + 1])
      if (cost < bestCost) {
        bestCost = cost
        best = i
      }
    }
    leg = best
    return leg
  })
}

// Confirmed stops (in order) interleaved with the proposed stops, each placed
// on the leg it belongs to while keeping the backend's along-route order.
export function buildSuggestRows(
  confirmed: ConfirmedStop[],
  suggestions: SuggestedStop[],
  selected: ReadonlySet<string>,
): SuggestRow[] {
  const suggestedRow = (s: SuggestedStop): SuggestRow => ({
    kind: 'suggested',
    stopId: s.stop_id,
    name: s.stop_name,
    lat: s.lat,
    lon: s.lon,
    selected: selected.has(s.stop_id),
    addedMin: s.added_time_min,
  })
  // No leg to place anything on — show the suggestions as they came.
  if (confirmed.length === 0) return suggestions.map(suggestedRow)

  const legOf = assignLegs(confirmed, suggestions)
  const rows: SuggestRow[] = []
  confirmed.forEach((st, i) => {
    rows.push({
      kind: 'confirmed',
      stopId: st.stop_id,
      name: st.stop_name,
      lat: st.lat,
      lon: st.lon,
      selected: true,
      addedMin: null,
    })
    suggestions.forEach((s, k) => {
      if (legOf[k] === i) rows.push(suggestedRow(s))
    })
  })
  return rows
}
