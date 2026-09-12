// The proposal family on the client (backend/adapters/family/README.md):
// pure helpers over one FamilyDocument. No fetching — that is
// composables/useProposalFamily.ts — and no Vue.
//
//   memberKey(sv, comp)            the map key every member lookup uses
//   inflateRoute(document, route)  the document's compact route back into
//                                  the full shape ProposalViewport reads
//   alternativeRoutes(...)         the corridors the other members take,
//                                  reduced to what diverges from the one
//                                  on screen — the map's faded lines
//   memberFailure(member)          an error member as the ApiFailure the
//                                  builder's copy paths already handle
//
// Why inflate rather than teach the viewport the compact shape: the compact
// route drops each intermediate stop's second copy and moves geometry into a
// shared pool, and about forty places in ProposalViewport (adaptRoute, the
// map, the itinerary, the expert reconciliation) read `from_stop`/`to_stop`
// and `geometries[]`. One 40-line function here keeps all of them as they
// are; the data is the same, only its layout differs.

import type { ApiFailure } from '@/lib/apiError'
import type {
  CompactRoute,
  CompactSegment,
  CompactStop,
  CompactTrip,
  FamilyDocument,
  FamilyMember,
  FamilyMemberError,
  FamilyMemberOk,
} from '@/types/api'

export function memberKey(scenarioVariantId: number, compositionId: string): string {
  return `${scenarioVariantId}:${compositionId}`
}

/** A full-shape segment: the compact segment's own fields, plus the two
 *  stops it refers to by index, inlined the way route_serialize.route_to_dict()
 *  emits them. `from`/`to` stay on the object — harmless, and dropping them
 *  would cost a spread per segment for nothing. */
export interface InflatedSegment extends CompactSegment {
  from_stop: CompactStop
  to_stop: CompactStop
}

export interface InflatedTrip extends Omit<CompactTrip, 'segments'> {
  segments: InflatedSegment[]
}

export interface InflatedTripPair {
  composition_id: string
  outbound: InflatedTrip
  return_trip: InflatedTrip
}

/** The full route shape (route_serialize.route_to_dict() minus the catalog,
 *  demand and provenance blocks the document deliberately does not carry:
 *  `composition`, `od_pairs`, `track_infrastructure`). `geometries` is
 *  rebuilt from the pool with one entry per DISTINCT geometry the route
 *  references, ids unchanged, so segment.geometry_id resolves as before. */
export interface InflatedRoute extends Omit<CompactRoute, 'trip_pairs'> {
  trip_pairs: InflatedTripPair[]
  geometries: { id: string; coords: number[][] }[]
}

function inflateTrip(trip: CompactTrip): InflatedTrip {
  const segments = trip.segments.map((seg) => ({
    ...seg,
    from_stop: trip.stops[seg.from],
    to_stop: trip.stops[seg.to],
  }))
  return { ...trip, segments }
}

export function inflateRoute(document: FamilyDocument, route: CompactRoute): InflatedRoute {
  const trip_pairs = route.trip_pairs.map((pair) => ({
    composition_id: pair.composition_id,
    outbound: inflateTrip(pair.outbound),
    return_trip: inflateTrip(pair.return_trip),
  }))
  const ids = new Set<string>()
  for (const pair of trip_pairs) {
    for (const trip of [pair.outbound, pair.return_trip]) {
      for (const seg of trip.segments) ids.add(seg.geometry_id)
    }
  }
  const geometries = [...ids].map((id) => ({ id, coords: document.geometries[id] ?? [] }))
  return { ...route, trip_pairs, geometries }
}

/** The document's route for an ok member. */
export function routeFor(document: FamilyDocument, member: FamilyMemberOk): CompactRoute {
  return document.routes[member.route_ref]
}

/** Every geometry id a compact route draws, both directions of every pair. */
export function geometryIdsOf(route: CompactRoute): Set<string> {
  const ids = new Set<string>()
  for (const pair of route.trip_pairs) {
    for (const trip of [pair.outbound, pair.return_trip]) {
      for (const seg of trip.segments) ids.add(seg.geometry_id)
    }
  }
  return ids
}

/** One corridor the family found that the route on screen does not take. */
export interface AlternativeRoute {
  /** `${scenarioId}:${compositionId}` — stable identity for hover state. */
  key: string
  scenarioId: number
  compositionId: string
  /** Only the geometry the shown route does NOT draw: what actually diverges. */
  geometryIds: string[]
}

/** The corridors of every OTHER member of `document`, ready to draw underneath
 *  the one on screen.
 *
 *  Two reductions, both of which matter on a 72-member family. Each route is
 *  reduced to the geometry the current one does not already draw, so a variant
 *  that only differs over one border shows as that one branch rather than as a
 *  second copy of the whole line; and routes left with the same geometry are
 *  one alternative, not one per member — the family's ~12 routes share about
 *  eight geometries, so most of them are the same corridor twice over.
 *
 *  `preferCompositionId` decides which member represents a shared corridor:
 *  the one whose composition already matches means clicking it changes the
 *  scenario only. Insertion order is the document's route order. */
export function alternativeRoutes(
  document: FamilyDocument,
  currentRouteRef: string,
  preferCompositionId: string | null = null,
): AlternativeRoute[] {
  const current = document.routes[currentRouteRef]
  if (!current) return []
  const shown = geometryIdsOf(current)

  const byCorridor = new Map<string, AlternativeRoute>()
  for (const [ref, route] of Object.entries(document.routes)) {
    if (ref === currentRouteRef) continue
    const compositionId = route.trip_pairs[0]?.composition_id
    if (compositionId === undefined) continue
    const geometryIds = [...geometryIdsOf(route)].filter((id) => !shown.has(id)).sort()
    if (geometryIds.length === 0) continue

    const corridor = geometryIds.join('|')
    const existing = byCorridor.get(corridor)
    if (existing && existing.compositionId === preferCompositionId) continue
    if (existing && compositionId !== preferCompositionId) continue
    byCorridor.set(corridor, {
      // Scenario id, not variant id: the same key the comparison grid's
      // cells use, and what the viewport's selection is expressed in.
      key: `${route.scenario_id}:${compositionId}`,
      scenarioId: route.scenario_id,
      compositionId,
      geometryIds,
    })
  }
  return [...byCorridor.values()]
}

export function isOk(member: FamilyMember | undefined): member is FamilyMemberOk {
  return member?.status === 'ok'
}

// Backend error codes → the ApiFailure kind the builder's copy already
// distinguishes (lib/apiError.ts). A failed member is a 200 on the wire, so
// the classification the response status used to give is done here: the
// gauge/routing/domain cases are the user's input, the missing routing graph
// is the deployment's. classify_compute_error()'s statuses, kept as they were
// on /calc so the messages that key off them stay right.
const STATUS_BY_CODE: Record<string, number> = {
  gauge_mismatch: 422,
  routing_error: 422,
  domain_error: 422,
  routing_graph_not_configured: 503,
}

export function memberFailure(member: FamilyMemberError): ApiFailure {
  const status = STATUS_BY_CODE[member.error] ?? 500
  if (status === 503) return { kind: 'unavailable', status, slug: member.error }
  if (status === 422)
    return { kind: 'bad_input', status, slug: member.error, message: member.message }
  return { kind: 'server', status, slug: member.error }
}
