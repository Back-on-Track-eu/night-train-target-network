// VAT on a ticket, distance-weighted over the countries a route runs
// through. Passenger transport is taxed where it takes place, in
// proportion to the distance covered in each country, and most countries
// exempt the domestic leg of an international journey while taxing a
// domestic ticket — so a route's effective rate is
//
//     Σ over countries of  distance share × rate
//
// with the country's international rate whenever the route crosses a
// border and its domestic rate otherwise. The rates come from
// GET /api/params/TicketVat (models/demand/calib/vat/VAT_CALIBRATION.md).
//
// Display only: the model prices net, so the gross figures this produces
// sit beside a net fare or a net ticket revenue and never enter a cost,
// revenue or subsidy figure.

import type { TicketVatRate } from '@/types/api'

/** One leg of a trip: its length and how it splits over countries. */
export interface VatLeg {
  distanceM: number
  countryDistanceShares: Record<string, number>
}

export interface TicketVatShare {
  countryCode: string
  /** Share of the route's distance in this country, 0–1. */
  distanceShare: number
  /** The rate applied to that share (international or domestic, see above). */
  ratePer: number
}

export interface TicketVat {
  /** The route's effective rate, 0–1. */
  ratePer: number
  /** Whether the route crosses a border, i.e. which rate column applied. */
  international: boolean
  /** Per country, in descending share, for the breakdown tooltip. */
  shares: TicketVatShare[]
  /** Countries on the route the rate table does not know — shown as a gap. */
  missing: string[]
}

/**
 * The effective VAT rate of a route from its legs and the rate table.
 * Returns null when there is no distance at all (nothing to weight).
 * A country the table does not list contributes its share at 0 % and is
 * reported in `missing`, so the figure stays a lower bound rather than
 * disappearing.
 */
export function ticketVat(legs: VatLeg[], rates: Record<string, TicketVatRate>): TicketVat | null {
  const metresByCountry = new Map<string, number>()
  let total = 0
  for (const leg of legs) {
    if (!(leg.distanceM > 0)) continue
    total += leg.distanceM
    for (const [cc, share] of Object.entries(leg.countryDistanceShares)) {
      metresByCountry.set(cc, (metresByCountry.get(cc) ?? 0) + leg.distanceM * share)
    }
  }
  if (total <= 0) return null

  const international = metresByCountry.size > 1
  const missing: string[] = []
  const shares: TicketVatShare[] = []
  let rate = 0
  for (const [cc, metres] of metresByCountry) {
    const distanceShare = metres / total
    const row = rates[cc]
    if (!row) {
      missing.push(cc)
      shares.push({ countryCode: cc, distanceShare, ratePer: 0 })
      continue
    }
    const ratePer = international ? row.vat_international_per : row.vat_domestic_per
    rate += distanceShare * ratePer
    shares.push({ countryCode: cc, distanceShare, ratePer })
  }
  shares.sort((a, b) => b.distanceShare - a.distanceShare)
  return { ratePer: rate, international, shares, missing: missing.sort() }
}

/**
 * The per-country breakdown as one line for a tooltip:
 * "DE 7 % on 62 % of the distance · NL 9 % on 38 %". `pct` formats a
 * 0–100 number the caller's way; the joiner is the caller's copy.
 */
export function vatBreakdown(
  vat: TicketVat,
  pct: (value: number) => string,
  onShare: (country: string, rate: string, share: string) => string,
): string {
  return vat.shares
    .map((s) => onShare(s.countryCode, pct(s.ratePer * 100), pct(s.distanceShare * 100)))
    .join(' · ')
}

/**
 * The rates by country as one short list for a visible label:
 * "DE 7 %, CH 0 %" — in descending distance share, so the country that
 * shapes the figure comes first. A country the table lacks shows a dash.
 */
export function vatRatesByCountry(
  vat: TicketVat,
  pct: (value: number) => string,
  missingMark = '—',
): string {
  return vat.shares
    .map(
      (s) =>
        `${s.countryCode} ${vat.missing.includes(s.countryCode) ? missingMark : pct(s.ratePer * 100)}`,
    )
    .join(', ')
}

/** A net amount with the route's VAT on top. */
export function gross(net: number, vat: TicketVat): number {
  return net * (1 + vat.ratePer)
}
