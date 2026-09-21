import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import { allocate, GROUP_ORDER, splitByGroup, CLASS_ORDER } from './demandAllocation'

// Parity with the backend: tests/test_83_demand_units.py writes this fixture
// from models/demand/groups.py, so the two ports of the sketch's allocate()
// are pinned to the same reference values — the guide's §3 table.
const fixture = JSON.parse(
  readFileSync(
    new URL('../../../backend/tests/fixtures/demand_reference.json', import.meta.url),
    'utf8',
  ),
)

describe('the allocation rule (parity with models/demand/groups.py)', () => {
  const groups = splitByGroup(
    fixture.passengers_per_year / fixture.departures_per_year,
    fixture.group_shares_pct,
  )

  it('splits the departure demand as the backend does', () => {
    for (const g of GROUP_ORDER) expect(groups[g]).toBeCloseTo(fixture.per_trip_by_group[g], 9)
  })

  for (const [comp, places] of Object.entries(fixture.compositions) as [
    string,
    Record<string, number>,
  ][]) {
    it(`seats ${comp} exactly as the backend`, () => {
      const a = allocate(places, groups)
      const expected = fixture.allocations[comp]
      for (const c of CLASS_ORDER) expect(a.byClass[c]).toBeCloseTo(expected.by_class[c], 9)
      for (const g of GROUP_ORDER) {
        expect(a.notServedByGroup[g]).toBeCloseTo(expected.not_served_by_group[g], 9)
        for (const c of CLASS_ORDER)
          expect(a.byGroupByClass[g][c]).toBeCloseTo(expected.by_group_by_class[g][c], 9)
      }
      expect(a.served).toBeCloseTo(expected.served, 9)
      expect(a.notServed).toBeCloseTo(expected.not_served, 9)
    })
  }

  it("reproduces the guide's reference table", () => {
    const a = allocate(fixture.compositions['NEW-BAL-7'], groups)
    expect(a.served).toBeCloseTo(260, 9)
    expect(a.notServed).toBeCloseTo(377.52, 2)
    expect(a.byGroupByClass.comfort.Couchette).toBeCloseTo(35.38, 2)
    expect(a.byGroupByClass.group.Seat).toBeCloseTo(75.07, 2)
    expect(a.notServedByGroup.business).toBeCloseTo(31.88, 2)
    const pod = allocate(fixture.compositions['REF-POD-14'], groups)
    expect(pod.served).toBeCloseTo(382.51, 2)
    expect(pod.notServed).toBeCloseTo(255.01, 2)
  })

  it('never reports a negative remainder', () => {
    const a = allocate(fixture.compositions['REF-POD-14'], groups)
    expect(a.notServedByGroup.comfort).toBe(0)
  })

  it('reflects a share sum other than 100 rather than rebalancing', () => {
    const g = splitByGroup(1000, { comfort: 50, group: 25, senior: 10, budget: 10, business: 10 })
    expect(GROUP_ORDER.reduce((s, k) => s + g[k], 0)).toBeCloseTo(1050, 9)
  })
})
