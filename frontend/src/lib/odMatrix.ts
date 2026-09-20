// The OD spread of DEMAND 0.1.0 (docs/2026-09-18_manual_demand_guide.md
// D25–D30), ported one-to-one from the sketch's odShares(), pinPair() and
// presetWeights() and mirrored by the backend's models/demand/od_matrix.py.
// Shares are fractions summing to 1 over the SELLABLE pairs — a stop the
// trip boards at before a stop it alights at; night stops sell nothing —
// keyed by stop id, never by name. Pins are posted and shown in percent.

export interface SellablePair {
  originStopId: string
  destinationStopId: string
  distanceKm: number
}

export type PinMap = Record<string, Record<string, number>>

export const OD_PRESETS = ['even', 'long', 'mid', 'short'] as const
export type OdPreset = (typeof OD_PRESETS)[number]

/** A preset maps a stop's position factor f (0 first … 1 last of its list)
 *  to OD_WEIGHT_MIN + OD_WEIGHT_SPAN × f, one decimal; even is 1. */
export const OD_WEIGHT_MIN = 0.3
export const OD_WEIGHT_SPAN = 2.7
export const DEFAULT_OD_WEIGHT = 1

const PRESET_FACTORS: Record<OdPreset, [(x: number) => number, (x: number) => number]> = {
  even: [() => 1, () => 1],
  long: [(x) => 1 - x, (x) => x],
  mid: [(x) => 1 - Math.abs(2 * x - 1), (x) => 1 - Math.abs(2 * x - 1)],
  short: [(x) => x, (x) => 1 - x],
}

/** The sellable pairs of a compact trip in route order: origins outer,
 *  destinations inner. stops carry their stop_type as the backend classifies
 *  them; km are cumulative from the trip's segments. */
export function sellablePairs(
  stops: { stop_id: string; stop_type: string }[],
  segmentKm: number[],
): SellablePair[] {
  const km = [0]
  for (const d of segmentKm) km.push(km[km.length - 1] + d)
  const boards = (t: string) => t === 'BOARDING' || t === 'BOTH'
  const alights = (t: string) => t === 'ALIGHTING' || t === 'BOTH'
  const out: SellablePair[] = []
  for (let i = 0; i < stops.length; i++) {
    if (!boards(stops[i].stop_type)) continue
    for (let j = i + 1; j < stops.length; j++) {
      if (!alights(stops[j].stop_type)) continue
      out.push({
        originStopId: stops[i].stop_id,
        destinationStopId: stops[j].stop_id,
        distanceKm: km[j] - km[i],
      })
    }
  }
  return out
}

export function boardingStopIds(stops: { stop_id: string; stop_type: string }[]): string[] {
  return stops
    .filter((s) => s.stop_type === 'BOARDING' || s.stop_type === 'BOTH')
    .map((s) => s.stop_id)
}

export function alightingStopIds(stops: { stop_id: string; stop_type: string }[]): string[] {
  return stops
    .filter((s) => s.stop_type === 'ALIGHTING' || s.stop_type === 'BOTH')
    .map((s) => s.stop_id)
}

/** The stop weights a preset writes. */
export function presetWeights(
  boardIds: string[],
  alightIds: string[],
  preset: OdPreset,
): { board: Record<string, number>; alight: Record<string, number> } {
  const [boardF, alightF] = PRESET_FACTORS[preset]
  const pos = (ids: string[], i: number) => (ids.length > 1 ? i / (ids.length - 1) : 0.5)
  // toFixed(1) as the sketch does; the backend rounds to one decimal too, and
  // both round 1.6500000000000001 up.
  const weight = (f: number) =>
    preset === 'even' ? 1 : +(OD_WEIGHT_MIN + OD_WEIGHT_SPAN * f).toFixed(1)
  const board: Record<string, number> = {}
  const alight: Record<string, number> = {}
  boardIds.forEach((s, i) => (board[s] = weight(boardF(pos(boardIds, i)))))
  alightIds.forEach((s, i) => (alight[s] = weight(alightF(pos(alightIds, i)))))
  return { board, alight }
}

/** One weight per stop of the list: the given one where it names the stop,
 *  DEFAULT_OD_WEIGHT elsewhere. */
export function resolveWeights(
  ids: string[],
  weights: Record<string, number> | undefined,
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const s of ids) out[s] = weights?.[s] ?? DEFAULT_OD_WEIGHT
  return out
}

export const pinKey = (o: string, d: string) => `${o}\u0000${d}`

function pinOf(pins: PinMap, p: SellablePair): number | undefined {
  return pins[p.originStopId]?.[p.destinationStopId]
}

/** Share per sellable pair, fractions summing to 1: board × alight weight,
 *  normalised over the unpinned pairs onto whatever the pins leave; a pinned
 *  pair keeps its value. Returned in the pairs' order. */
export function odShares(
  pairs: SellablePair[],
  board: Record<string, number>,
  alight: Record<string, number>,
  pins: PinMap = {},
): number[] {
  const base = pairs.map((p) => (board[p.originStopId] ?? 0) * (alight[p.destinationStopId] ?? 0))
  const pinned = pairs.reduce((t, p) => t + (pinOf(pins, p) ?? 0), 0)
  const free = pairs.reduce((t, p, i) => t + (pinOf(pins, p) === undefined ? base[i] : 0), 0)
  const rest = Math.max(0, 100 - pinned)
  return pairs.map((p, i) => {
    const pin = pinOf(pins, p)
    return (pin !== undefined ? pin : free ? (base[i] / free) * rest : 0) / 100
  })
}

/** Pin one pair at valuePct; the other pins rescale by (100 − v) / (100 − old)
 *  and the unpinned pairs through the remainder, so the total stays 100. */
export function pinPair(
  pairs: SellablePair[],
  board: Record<string, number>,
  alight: Record<string, number>,
  pins: PinMap,
  origin: string,
  destination: string,
  valuePct: number,
): PinMap {
  const current = odShares(pairs, board, alight, pins)
  const index = pairs.findIndex(
    (p) => p.originStopId === origin && p.destinationStopId === destination,
  )
  const old = index >= 0 ? current[index] * 100 : 0
  const value = Math.min(100, Math.max(0, valuePct))
  const k = old < 100 ? (100 - value) / (100 - old) : 0
  const next: PinMap = {}
  for (const [o, row] of Object.entries(pins)) {
    for (const [d, v] of Object.entries(row)) {
      if (o === origin && d === destination) continue
      ;(next[o] ??= {})[d] = +(v * k).toFixed(2)
    }
  }
  ;(next[origin] ??= {})[destination] = +value.toFixed(2)
  return next
}

/** Drop a pin — the pair rejoins the unpinned remainder. */
export function unpinPair(pins: PinMap, origin: string, destination: string): PinMap {
  const next: PinMap = {}
  for (const [o, row] of Object.entries(pins)) {
    const kept = Object.fromEntries(
      Object.entries(row).filter(([d]) => !(o === origin && d === destination)),
    )
    if (Object.keys(kept).length) next[o] = kept
  }
  return next
}

/** The share-weighted journey length. */
export function averageDistanceKm(pairs: SellablePair[], shares: number[]): number {
  return pairs.reduce((s, p, i) => s + p.distanceKm * (shares[i] ?? 0), 0)
}
