// The temporary route on the map while the user is still choosing stops in
// suggest mode. The base "suggest" response routed exactly the user's own
// stops; when one of them is taken off the route, its two legs are gone and
// nothing has been routed between the neighbours yet. Rather than recompute
// per click, the map bridges the gap with a straight line — a beeline the
// map draws dimmed, so it reads as "not routed yet" — and the real routing
// happens once, on Continue.
//
// Pure geometry, no Vue: ProposalViewport maps the backend's segments into
// `LegGeometry` and hands the result to MapView.

export interface LegEnd {
  stopId: string
  lon: number
  lat: number
}

export interface LegGeometry {
  from: LegEnd
  to: LegEnd
  coords: [number, number][]
}

export interface BridgedShape {
  /** The routed legs that survive, stitched in order — one run per stretch
   *  between two bridges, so the polyline never crosses a removed stop. */
  routed: [number, number][][]
  /** One straight line per gap where a removed stop used to be. */
  bridges: [number, number][][]
}

export function bridgeRemovedStops(
  legs: LegGeometry[],
  removed: ReadonlySet<string>,
): BridgedShape {
  const routed: [number, number][][] = []
  const bridges: [number, number][][] = []
  let run: [number, number][] = []
  // The last stop still on the route, once one has been passed; null while the
  // route has not started yet (a removed origin drops its leading legs).
  let lastActive: LegEnd | null = null
  let gap = false

  const flush = () => {
    if (run.length > 0) routed.push(run)
    run = []
  }

  legs.forEach((leg, i) => {
    if (i === 0) {
      if (removed.has(leg.from.stopId)) gap = true
      else lastActive = leg.from
    }
    if (removed.has(leg.to.stopId)) {
      gap = true
      return
    }
    if (gap) {
      flush()
      if (lastActive) {
        bridges.push([
          [lastActive.lon, lastActive.lat],
          [leg.to.lon, leg.to.lat],
        ])
      }
      gap = false
    } else {
      run.push(...leg.coords)
    }
    lastActive = leg.to
  })
  flush()
  return { routed, bridges }
}
