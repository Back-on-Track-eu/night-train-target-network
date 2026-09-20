// The sketch's follows(): what the schedule and the prices earn against a
// demand — passengers, place-km, utilisation and revenue per year. Pure
// arithmetic on the allocation and the OD spread, so the Supply tab's
// What-follows panel previews schedule and price edits live against the
// COMMITTED demand (D2), and the Demand tab's ladder previews demand edits
// against the committed schedule.

import {
  allocate,
  CLASS_ORDER,
  splitByGroup,
  type Allocation,
  type ClassMain,
} from '@/lib/demandAllocation'
import type { Tariff } from '@/lib/detailsScope'

export interface FollowsRow {
  classMain: ClassMain
  places: number
  served: number
  passengers: number
  placeKm: number
  ticketEur: number
  cateringEur: number
}

export interface Follows {
  allocation: Allocation
  departures: number
  rows: FollowsRow[]
  soldPerDeparture: number
  passengers: number
  placeKmSold: number
  ticketEur: number
  cateringEur: number
}

/**
 * passengersPerYear and sharesPct are the demand; departures the schedule's
 * departures a year (both directions); averageKm the share-weighted journey
 * length of the OD spread; the tariff the four maps as the fields have them.
 * Revenue is priced on the average journey — algebraically the same as
 * pricing every OD pair, which is what the backend does.
 */
export function follows(
  passengersPerYear: number,
  sharesPct: Record<string, number>,
  placesByClass: Record<string, number>,
  departures: number,
  averageKm: number,
  tariff: Tariff,
): Follows {
  const perTrip = splitByGroup(departures > 0 ? passengersPerYear / departures : 0, sharesPct)
  const allocation = allocate(placesByClass, perTrip)
  const rows = CLASS_ORDER.map((classMain) => {
    const served = allocation.byClass[classMain]
    const passengers = served * departures
    return {
      classMain,
      places: placesByClass[classMain] ?? 0,
      served,
      passengers,
      placeKm: passengers * averageKm,
      ticketEur:
        passengers *
        ((tariff.faresPerPax[classMain] ?? 0) +
          (tariff.faresPerKm[classMain] ?? 0) * averageKm +
          (tariff.servicesPerPax[classMain] ?? 0)),
      cateringEur: passengers * (tariff.cateringPerPax[classMain] ?? 0),
    }
  })
  const total = (key: keyof FollowsRow) => rows.reduce((s, r) => s + (r[key] as number), 0)
  return {
    allocation,
    departures,
    rows,
    soldPerDeparture: total('served'),
    passengers: total('passengers'),
    placeKmSold: total('placeKm'),
    ticketEur: total('ticketEur'),
    cateringEur: total('cateringEur'),
  }
}
