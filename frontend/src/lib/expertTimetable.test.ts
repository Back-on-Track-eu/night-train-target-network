import { describe, it, expect } from 'vitest'
import {
  addonFor,
  clockToServiceMinute,
  addonsForDirection,
  droppedAddons,
  emptyExpert,
  fromRequest,
  fromRouteSegments,
  isEmptyExpert,
  materialiseSlack,
  mirrorDeparture,
  mirrorDirection,
  pruneExpertToStops,
  pruneToStops,
  resolveDeparture,
  resolveTimetable,
  setAddon,
  setDeparture,
  swapDirections,
  toRequest,
  toggleDepartureMode,
  type SegmentAddon,
} from './expertTimetable'

const A = 'osm:a'
const B = 'osm:b'
const C = 'osm:c'
const X = 'osm:x'

const addon = (from: string, to: string, min: number): SegmentAddon => ({
  fromStopId: from,
  toStopId: to,
  addMin: min,
})

// Automatic departures of the two directions — outbound 21:00, return 21:10
// (asymmetric on purpose, so a mirrored pin cannot pass by coincidence).
const AUTOS = { own: 1260, other: 1270 }
const AUTOS_FLIPPED = { own: AUTOS.other, other: AUTOS.own }

describe('setAddon', () => {
  it('never stores a negative value — a leg can only be padded', () => {
    expect(setAddon([], A, B, -10)).toEqual([])
    expect(setAddon([addon(A, B, 5)], A, B, -1)).toEqual([])
  })

  it('removes the entry at zero rather than sending add_min: 0', () => {
    expect(setAddon([addon(A, B, 5)], A, B, 0)).toEqual([])
  })

  it('rounds to whole minutes and replaces in place', () => {
    expect(setAddon([addon(A, B, 5)], A, B, 7.4)).toEqual([addon(A, B, 7)])
  })

  it('leaves other legs alone', () => {
    const result = setAddon([addon(A, B, 5)], B, C, 3)
    expect(result).toHaveLength(2)
    expect(addonFor(result, A, B)).toBe(5)
    expect(addonFor(result, B, C)).toBe(3)
  })

  it('treats a NaN from an emptied number input as zero', () => {
    expect(setAddon([addon(A, B, 5)], A, B, Number.NaN)).toEqual([])
  })
})

describe('pruneToStops', () => {
  it('keeps add-ons whose pair is still a leg', () => {
    expect(pruneToStops([addon(A, B, 5)], [A, B, C])).toEqual([addon(A, B, 5)])
  })

  it('drops an add-on whose pair a new stop split — never redistributes it', () => {
    expect(pruneToStops([addon(A, B, 5)], [A, X, B, C])).toEqual([])
  })

  it('drops an add-on whose stop was removed', () => {
    expect(pruneToStops([addon(B, C, 5)], [A, C])).toEqual([])
  })

  it('is direction-sensitive: the reversed pair is a different leg', () => {
    expect(pruneToStops([addon(B, A, 5)], [A, B, C])).toEqual([])
  })

  it('prunes an unlinked return against the reversed itinerary', () => {
    const state = {
      outbound: { departure: null, addons: [addon(A, B, 4)] },
      returnTrip: { departure: null, addons: [addon(C, B, 6), addon(B, A, 2)] },
    }
    const pruned = pruneExpertToStops(state, [A, X, B, C])
    expect(pruned.outbound.addons).toEqual([])
    // C→B survives the insertion of X between A and B; B→A does not.
    expect(pruned.returnTrip?.addons).toEqual([addon(C, B, 6)])
  })
})

describe('mirroring', () => {
  it('reverses each pair and displaces the departure the other way', () => {
    const mirrored = mirrorDirection(
      { departure: { mode: 'shift', minutes: -60 }, addons: [addon(A, B, 8)] },
      AUTOS,
    )
    expect(mirrored.departure).toEqual({ mode: 'shift', minutes: 60 })
    expect(mirrored.addons).toEqual([addon(B, A, 8)])
  })

  it('mirrors a pinned departure as a pin, by its distance from the automatic value', () => {
    // 20:00 against an automatic 21:00 is an hour early; the other
    // direction leaves an hour late against ITS automatic value.
    const pinned = { mode: 'absolute' as const, minutes: 1200 }
    expect(mirrorDeparture(pinned, AUTOS)).toEqual({ mode: 'absolute', minutes: 1330 })
    expect(mirrorDeparture(null, AUTOS)).toBeNull()
  })

  it('is an involution once the autos change places', () => {
    for (const departure of [
      { mode: 'absolute' as const, minutes: 1200 },
      { mode: 'shift' as const, minutes: 25 },
    ]) {
      expect(mirrorDeparture(mirrorDeparture(departure, AUTOS), AUTOS_FLIPPED)).toEqual(departure)
    }
  })

  it('gives the return outbound’s mirrored add-ons until the link is broken', () => {
    const state = { outbound: { departure: null, addons: [addon(A, B, 8)] }, returnTrip: null }
    expect(addonsForDirection(state, 1)).toEqual([addon(B, A, 8)])

    const unlinked = { ...state, returnTrip: { departure: null, addons: [addon(C, B, 3)] } }
    expect(addonsForDirection(unlinked, 1)).toEqual([addon(C, B, 3)])
  })
})

describe('swapDirections', () => {
  it('leaves an untouched timetable untouched', () => {
    expect(swapDirections(emptyExpert(), AUTOS)).toEqual(emptyExpert())
  })

  it('keeps a mirroring return mirroring, minutes staying on the same physical legs', () => {
    const state = { outbound: { departure: null, addons: [addon(A, B, 8)] }, returnTrip: null }
    const swapped = swapDirections(state, AUTOS)
    expect(swapped.returnTrip).toBeNull()
    expect(swapped.outbound.addons).toEqual([addon(B, A, 8)])
    // Mirroring is symmetric, so flipping twice is where you started.
    expect(swapDirections(swapped, AUTOS_FLIPPED)).toEqual(state)
  })

  it('shows the mirrored pin on the direction now on screen, and gets it back on the way home', () => {
    const state = {
      outbound: {
        departure: { mode: 'absolute' as const, minutes: 1200 },
        addons: [addon(A, B, 8)],
      },
      returnTrip: null,
    }
    const swapped = swapDirections(state, AUTOS)
    expect(swapped.returnTrip).toBeNull()
    expect(swapped.outbound).toEqual({
      departure: { mode: 'absolute', minutes: 1330 },
      addons: [addon(B, A, 8)],
    })
    expect(swapDirections(swapped, AUTOS_FLIPPED)).toEqual(state)
  })

  it('exchanges two unlinked directions as they are', () => {
    const state = {
      outbound: { departure: null, addons: [addon(A, B, 8)] },
      returnTrip: {
        departure: { mode: 'shift' as const, minutes: -20 },
        addons: [addon(C, B, 4)],
      },
    }
    const swapped = swapDirections(state, AUTOS)
    expect(swapped.outbound).toEqual(state.returnTrip)
    expect(swapped.returnTrip).toEqual(state.outbound)
    expect(swapDirections(swapped, AUTOS_FLIPPED)).toEqual(state)
  })

  it('survives the prune that follows a direction flip — the wipe this prevents', () => {
    // Flipping direction in the builder reverses the itinerary, so the next
    // request posts the reversed stop list. Without the swap, every add-on is
    // checked against the opposite direction's legs and dropped.
    const stops = [A, B, C]
    const state = {
      outbound: { departure: null, addons: [addon(A, B, 8)] },
      returnTrip: { departure: null, addons: [addon(C, B, 4)] },
    }
    const pruned = pruneExpertToStops(swapDirections(state, AUTOS), [...stops].reverse())
    expect(pruned.outbound.addons).toEqual([addon(C, B, 4)])
    expect(pruned.returnTrip?.addons).toEqual([addon(A, B, 8)])

    const withoutTheSwap = pruneExpertToStops(state, [...stops].reverse())
    expect(withoutTheSwap.outbound.addons).toEqual([])
    expect(withoutTheSwap.returnTrip?.addons).toEqual([])
  })
})

describe('departure override', () => {
  const auto = 1300

  it('pins to the automatic value when the lock is turned on with nothing set', () => {
    expect(toggleDepartureMode(null, auto)).toEqual({ mode: 'absolute', minutes: auto })
  })

  it('converts between modes without moving the departure', () => {
    const pinned = { mode: 'absolute' as const, minutes: auto + 40 }
    const following = toggleDepartureMode(pinned, auto)
    expect(following).toEqual({ mode: 'shift', minutes: 40 })
    expect(resolveDeparture(following, auto)).toBe(resolveDeparture(pinned, auto))
    expect(toggleDepartureMode(following, auto)).toEqual(pinned)
  })

  it('is the whole difference between the modes: only a shift follows a new auto value', () => {
    const pinned = { mode: 'absolute' as const, minutes: auto + 40 }
    const following = { mode: 'shift' as const, minutes: 40 }
    const newAuto = auto - 25 // a reroute re-centred the mirror
    expect(resolveDeparture(pinned, newAuto)).toBe(auto + 40)
    expect(resolveDeparture(following, newAuto)).toBe(newAuto + 40)
  })

  it('keeps a following departure following when a time is typed in', () => {
    expect(setDeparture({ mode: 'shift', minutes: 10 }, auto, auto + 30)).toEqual({
      mode: 'shift',
      minutes: 30,
    })
    expect(setDeparture(null, auto, auto + 30)).toEqual({
      mode: 'absolute',
      minutes: auto + 30,
    })
  })
})

describe('fromRouteSegments / droppedAddons', () => {
  const segments = [
    { from_stop: { stop_id: A }, to_stop: { stop_id: X }, addon_time_min: 0 },
    { from_stop: { stop_id: X }, to_stop: { stop_id: B }, addon_time_min: 0 },
    { from_stop: { stop_id: B }, to_stop: { stop_id: C }, addon_time_min: 6 },
  ]

  it('reads back only the legs that actually carry minutes', () => {
    expect(fromRouteSegments(segments)).toEqual([addon(B, C, 6)])
  })

  it('tolerates a payload predating the field', () => {
    expect(fromRouteSegments([{ from_stop: { stop_id: A }, to_stop: { stop_id: B } }])).toEqual([])
  })

  it('names the add-on the backend dropped when a stop was auto-inserted', () => {
    const sent = [addon(A, B, 9), addon(B, C, 6)]
    expect(droppedAddons(sent, fromRouteSegments(segments))).toEqual([addon(A, B, 9)])
  })
})

describe('toRequest', () => {
  it('is null while nothing is overridden, so the key can be omitted', () => {
    expect(isEmptyExpert(emptyExpert())).toBe(true)
    expect(toRequest(emptyExpert())).toBeNull()
  })

  it('sorts add-ons so two equal states produce one cache entry', () => {
    const one = {
      outbound: { departure: null, addons: [addon(B, C, 6), addon(A, B, 3)] },
      returnTrip: null,
    }
    const other = {
      outbound: { departure: null, addons: [addon(A, B, 3), addon(B, C, 6)] },
      returnTrip: null,
    }
    expect(toRequest(one)).toEqual(toRequest(other))
    expect(toRequest(one)).toEqual({
      outbound: {
        departure: null,
        segment_addons: [
          { from_stop_id: A, to_stop_id: B, add_min: 3 },
          { from_stop_id: B, to_stop_id: C, add_min: 6 },
        ],
      },
      return: { mirror_outbound: true },
    })
  })

  it('spells the two departure modes the way the API takes them', () => {
    expect(
      toRequest({
        outbound: { departure: { mode: 'absolute', minutes: 1290 }, addons: [] },
        returnTrip: null,
      })?.outbound,
    ).toEqual({ departure: { mode: 'absolute', time_min: 1290 }, segment_addons: [] })

    expect(
      toRequest({
        outbound: { departure: { mode: 'shift', minutes: -25 }, addons: [] },
        returnTrip: null,
      })?.outbound,
    ).toEqual({ departure: { mode: 'shift', shift_min: -25 }, segment_addons: [] })
  })

  it('mirrors the return unless it carries overrides of its own', () => {
    const linked = toRequest({
      outbound: { departure: null, addons: [addon(A, B, 3)] },
      returnTrip: null,
    })
    expect(linked?.return).toEqual({ mirror_outbound: true })

    const unlinked = toRequest({
      outbound: { departure: null, addons: [addon(A, B, 3)] },
      returnTrip: { departure: null, addons: [addon(C, B, 4)] },
    })
    expect(unlinked?.return).toEqual({
      departure: null,
      segment_addons: [{ from_stop_id: C, to_stop_id: B, add_min: 4 }],
    })
  })

  it('round-trips through fromRequest — what a stored proposal replays', () => {
    const state = {
      outbound: {
        departure: { mode: 'absolute' as const, minutes: 1290 },
        addons: [addon(A, B, 3), addon(B, C, 6)],
      },
      returnTrip: { departure: { mode: 'shift' as const, minutes: -20 }, addons: [addon(C, B, 4)] },
    }
    expect(toRequest(fromRequest(toRequest(state)))).toEqual(toRequest(state))
  })

  it('reads a mirroring return back as a linked one, not an empty override', () => {
    const hydrated = fromRequest({
      outbound: {
        departure: null,
        segment_addons: [{ from_stop_id: A, to_stop_id: B, add_min: 3 }],
      },
      return: { mirror_outbound: true },
    })
    expect(hydrated.returnTrip).toBeNull()
    expect(addonsForDirection(hydrated, 1)).toEqual([addon(B, A, 3)])
  })

  it('hydrates nothing from an absent block', () => {
    expect(fromRequest(null)).toEqual(emptyExpert())
    expect(fromRequest(undefined)).toEqual(emptyExpert())
  })

  it('falls back to mirroring when the return was unlinked but left empty', () => {
    const state = {
      outbound: { departure: null, addons: [addon(A, B, 3)] },
      returnTrip: { departure: null, addons: [] },
    }
    expect(toRequest(state)?.return).toEqual({ mirror_outbound: true })
  })
})

describe('clockToServiceMinute', () => {
  it('lands on the day nearest the current departure', () => {
    expect(clockToServiceMinute('23:55', 1260)).toBe(1435) // same evening
    expect(clockToServiceMinute('00:10', 1435)).toBe(1450) // just past midnight
    expect(clockToServiceMinute('23:55', -5)).toBe(-5) // a mirrored return, day −1
  })

  it('rejects anything that is not a clock time', () => {
    expect(clockToServiceMinute('', 1260)).toBeNull()
    expect(clockToServiceMinute('later', 1260)).toBeNull()
  })
})

describe('resolveTimetable', () => {
  const same = (
    a: Parameters<typeof resolveTimetable>[0],
    b: Parameters<typeof resolveTimetable>[0],
  ) => JSON.stringify(resolveTimetable(a, AUTOS)) === JSON.stringify(resolveTimetable(b, AUTOS))

  it('reads an untouched state as the automatic timetable', () => {
    expect(resolveTimetable(emptyExpert(), AUTOS)).toEqual([
      { departureMin: AUTOS.own, addons: [] },
      { departureMin: AUTOS.other, addons: [] },
    ])
  })

  it('does not call a pin at the automatic value, or a pin↔shift toggle, a change', () => {
    const pinnedAtAuto = {
      outbound: { departure: { mode: 'absolute' as const, minutes: AUTOS.own }, addons: [] },
      returnTrip: null,
    }
    expect(same(emptyExpert(), pinnedAtAuto)).toBe(true)
    const pinned = {
      outbound: { departure: { mode: 'absolute' as const, minutes: 1200 }, addons: [] },
      returnTrip: null,
    }
    const following = {
      outbound: {
        departure: toggleDepartureMode(pinned.outbound.departure, AUTOS.own),
        addons: [],
      },
      returnTrip: null,
    }
    expect(same(pinned, following)).toBe(true)
  })

  it('does not call breaking the mirror link a change, but moving a mirrored time is one', () => {
    const mirrored = {
      outbound: { departure: { mode: 'shift' as const, minutes: -60 }, addons: [addon(A, B, 8)] },
      returnTrip: null,
    }
    const copied = { ...mirrored, returnTrip: mirrorDirection(mirrored.outbound, AUTOS) }
    expect(same(mirrored, copied)).toBe(true)
    const moved = {
      ...copied,
      returnTrip: { ...copied.returnTrip, departure: { mode: 'shift' as const, minutes: 30 } },
    }
    expect(same(mirrored, moved)).toBe(false)
  })

  it('resolves the mirrored return as the opposite shift', () => {
    const state = {
      outbound: { departure: { mode: 'absolute' as const, minutes: 1200 }, addons: [] },
      returnTrip: null,
    }
    expect(resolveTimetable(state, AUTOS)[1].departureMin).toBe(AUTOS.other + 60)
  })
})

describe('materialiseSlack', () => {
  it('turns the stretch into add-ons on the same legs and pins the departure where it is', () => {
    const direction = { departure: null, addons: [addon(A, B, 5)] }
    const legs = [
      { fromStopId: A, toStopId: B, slackMin: 40 },
      { fromStopId: B, toStopId: C, slackMin: 120 },
      { fromStopId: C, toStopId: X, slackMin: 0 },
    ]
    const result = materialiseSlack(direction, legs, 1260)
    expect(result.departure).toEqual({ mode: 'absolute', minutes: 1260 })
    expect(addonFor(result.addons, A, B)).toBe(45)
    expect(addonFor(result.addons, B, C)).toBe(120)
    expect(addonFor(result.addons, C, X)).toBe(0)
  })

  it('replaces a following departure with a pin, so the automatic re-centring cannot move the trip', () => {
    const direction = { departure: { mode: 'shift' as const, minutes: -30 }, addons: [] }
    expect(materialiseSlack(direction, [], 1230).departure).toEqual({
      mode: 'absolute',
      minutes: 1230,
    })
  })
})
