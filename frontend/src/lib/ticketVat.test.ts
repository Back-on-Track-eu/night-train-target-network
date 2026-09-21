import { describe, expect, it } from 'vitest'
import { gross, ticketVat, vatRatesByCountry, type VatLeg } from './ticketVat'
import type { TicketVatRate } from '@/types/api'

const rate = (cc: string, domestic: number, international: number): [string, TicketVatRate] => [
  cc,
  {
    country_code: cc,
    vat_domestic_per: domestic,
    vat_international_per: international,
    status: 'sourced',
    note: null,
    source_id: 1,
  },
]
const RATES = Object.fromEntries([
  rate('DE', 0.07, 0.07),
  rate('NL', 0.09, 0.09),
  rate('FR', 0.1, 0),
])

describe('ticketVat', () => {
  it("weights each country's international rate by its share of the distance", () => {
    // Two thirds Germany, one third Netherlands: 7 % × 2/3 + 9 % × 1/3.
    const legs: VatLeg[] = [
      { distanceM: 400_000, countryDistanceShares: { DE: 1 } },
      { distanceM: 200_000, countryDistanceShares: { DE: 0.5, NL: 0.5 } },
      { distanceM: 200_000, countryDistanceShares: { NL: 1 } },
    ]
    // DE = 400 + 100 = 500 km of 800 → 0.625; NL = 300 → 0.375
    const vat = ticketVat(legs, RATES)!
    expect(vat.international).toBe(true)
    expect(vat.ratePer).toBeCloseTo(0.07 * 0.625 + 0.09 * 0.375, 6)
    expect(vat.shares.map((s) => s.countryCode)).toEqual(['DE', 'NL'])
    expect(vat.shares[0].distanceShare).toBeCloseTo(0.625, 6)
    expect(vat.missing).toEqual([])
  })

  it('applies the international rate where the domestic one differs', () => {
    // France exempts the French leg of a cross-border ticket: 0 % on 3/4 of the
    // route, 7 % on the German quarter.
    const legs: VatLeg[] = [
      { distanceM: 300, countryDistanceShares: { FR: 1 } },
      { distanceM: 100, countryDistanceShares: { DE: 1 } },
    ]
    expect(ticketVat(legs, RATES)!.ratePer).toBeCloseTo(0.07 * 0.25, 6)
  })

  it('uses the domestic rate on a route inside one country', () => {
    const legs: VatLeg[] = [{ distanceM: 500, countryDistanceShares: { FR: 1 } }]
    const vat = ticketVat(legs, RATES)!
    expect(vat.international).toBe(false)
    expect(vat.ratePer).toBeCloseTo(0.1, 6)
  })

  it('reports a country the table does not know and counts its share at 0 %', () => {
    const legs: VatLeg[] = [
      { distanceM: 100, countryDistanceShares: { DE: 1 } },
      { distanceM: 100, countryDistanceShares: { XX: 1 } },
    ]
    const vat = ticketVat(legs, RATES)!
    expect(vat.missing).toEqual(['XX'])
    expect(vat.ratePer).toBeCloseTo(0.035, 6)
  })

  it('returns null without any distance', () => {
    expect(ticketVat([], RATES)).toBeNull()
    expect(ticketVat([{ distanceM: 0, countryDistanceShares: { DE: 1 } }], RATES)).toBeNull()
  })

  it('gross adds the rate on top of a net amount', () => {
    const vat = ticketVat([{ distanceM: 1, countryDistanceShares: { FR: 1 } }], RATES)!
    expect(gross(100, vat)).toBeCloseTo(110, 6)
  })

  it('lists each country with its applied rate, largest share first', () => {
    const legs: VatLeg[] = [
      { distanceM: 300, countryDistanceShares: { DE: 1 } },
      { distanceM: 100, countryDistanceShares: { FR: 1 } },
      { distanceM: 50, countryDistanceShares: { XX: 1 } },
    ]
    const vat = ticketVat(legs, RATES)!
    const pct = (v: number) => `${Math.round(v)} %`
    expect(vatRatesByCountry(vat, pct)).toBe('DE 7 %, FR 0 %, XX —')
  })
})
