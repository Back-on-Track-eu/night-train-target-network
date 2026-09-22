import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import { follows } from './whatFollows'

const fixture = JSON.parse(
  readFileSync(
    new URL('../../../backend/tests/fixtures/demand_reference.json', import.meta.url),
    'utf8',
  ),
)

describe('what follows from the schedule and the prices', () => {
  const tariff = {
    faresPerKm: fixture.tariff.fares_eur_per_km,
    faresPerPax: fixture.tariff.fares_eur_per_pax,
    servicesPerPax: fixture.tariff.services_eur_per_pax,
    cateringPerPax: fixture.tariff.catering_eur_per_pax,
  }

  it("reproduces the guide's per-year reference for NEW-BAL-7 to the cent", () => {
    const f = follows(
      fixture.passengers_per_year,
      fixture.group_shares_pct,
      fixture.compositions['NEW-BAL-7'],
      fixture.departures_per_year,
      fixture.average_distance_km,
      tariff,
    )
    expect(f.soldPerDeparture).toBeCloseTo(260, 9)
    expect(f.passengers).toBeCloseTo(fixture.new_bal_7_per_year.passengers, 6)
    expect(f.placeKmSold).toBeCloseTo(fixture.new_bal_7_per_year.place_km_sold, 3)
    expect(f.ticketEur).toBeCloseTo(fixture.new_bal_7_per_year.ticket_revenue_eur, 2)
    expect(f.cateringEur).toBeCloseTo(fixture.new_bal_7_per_year.catering_eur, 2)
  })

  it('earns nothing without departures', () => {
    const f = follows(
      200000,
      fixture.group_shares_pct,
      fixture.compositions['NEW-BAL-7'],
      0,
      500,
      tariff,
    )
    expect(f.passengers).toBe(0)
    expect(f.ticketEur).toBe(0)
  })
})
