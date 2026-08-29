import { describe, expect, test } from 'vitest'
import { buildSuggestRows, settledRows, type ConfirmedStop } from './suggestPlacement'
import type { SuggestedStop } from '@/types/api'

// Real station coordinates, so the expected orders below are the geography of
// an actual corridor rather than anything re-derived from the code.
const ODENSE = { stop_id: 'odense', stop_name: 'Odense', lat: 55.4028, lon: 10.3868 }
const PRAHA = { stop_id: 'praha', stop_name: 'Praha hl.n.', lat: 50.083, lon: 14.4356 }
const HAMBURG = { stop_id: 'hamburg', stop_name: 'Hamburg Hbf', lat: 53.5528, lon: 10.0067 }

function suggestion(
  stop_id: string,
  stop_name: string,
  lat: number,
  lon: number,
  added_time_min = 5,
): SuggestedStop {
  return { stop_id, stop_name, country_code: 'XX', lat, lon, added_time_min }
}

// Odense → Praha, the reported case. The backend routes exactly the caller's
// two stops in "suggest" mode and returns the candidates already ordered along
// the route (timetable.suggest_auto_stops sorts by leg_index, then
// along_leg_fraction), so this list is in true travel order.
const ODENSE_PRAHA_SUGGESTIONS: SuggestedStop[] = [
  suggestion('kolding', 'Kolding', 55.49, 9.475),
  suggestion('padborg', 'Padborg', 54.8244, 9.3617),
  suggestion('flensburg', 'Flensburg', 54.783, 9.4408),
  suggestion('hamburg', 'Hamburg Hbf', 53.5528, 10.0067),
  suggestion('berlin', 'Berlin Hbf', 52.525, 13.3694),
  suggestion('dresden', 'Dresden Hbf', 51.04, 13.7322),
]

describe('buildSuggestRows', () => {
  test('lists suggested stops between the origin and destination, in travel order', () => {
    const confirmed: ConfirmedStop[] = [ODENSE, PRAHA]

    const rows = buildSuggestRows(confirmed, ODENSE_PRAHA_SUGGESTIONS, new Set())

    expect(rows.map((r) => r.name)).toEqual([
      'Odense',
      'Kolding',
      'Padborg',
      'Flensburg',
      'Hamburg Hbf',
      'Berlin Hbf',
      'Dresden Hbf',
      'Praha hl.n.',
    ])
  })

  test('puts each suggestion on the leg it belongs to when the route already has an intermediate stop', () => {
    const confirmed: ConfirmedStop[] = [ODENSE, HAMBURG, PRAHA]

    const rows = buildSuggestRows(
      confirmed,
      ODENSE_PRAHA_SUGGESTIONS.filter((s) => s.stop_id !== 'hamburg'),
      new Set(),
    )

    expect(rows.map((r) => r.name)).toEqual([
      'Odense',
      'Kolding',
      'Padborg',
      'Flensburg',
      'Hamburg Hbf',
      'Berlin Hbf',
      'Dresden Hbf',
      'Praha hl.n.',
    ])
  })

  test('marks every confirmed stop as selected and carries each suggestion’s opt-in and added time', () => {
    const rows = buildSuggestRows(
      [ODENSE, PRAHA],
      [suggestion('kolding', 'Kolding', 55.49, 9.475, 12.4)],
      new Set(['kolding']),
    )

    expect(rows).toEqual([
      {
        kind: 'confirmed',
        stopId: 'odense',
        name: 'Odense',
        lat: 55.4028,
        lon: 10.3868,
        selected: true,
        addedMin: null,
      },
      {
        kind: 'suggested',
        stopId: 'kolding',
        name: 'Kolding',
        lat: 55.49,
        lon: 9.475,
        selected: true,
        addedMin: 12.4,
      },
      {
        kind: 'confirmed',
        stopId: 'praha',
        name: 'Praha hl.n.',
        lat: 50.083,
        lon: 14.4356,
        selected: true,
        addedMin: null,
      },
    ])
  })

  test('leaves an unsuggested route as its confirmed stops alone', () => {
    const rows = buildSuggestRows([ODENSE, PRAHA], [], new Set())

    expect(rows.map((r) => r.name)).toEqual(['Odense', 'Praha hl.n.'])
  })
})

// Stockholm-Zagreb, the reported case: the timeline listed these correctly, but
// the itinerary the follow-up calc then ran with was re-derived from lat/lon
// one stop at a time, which sent Køge, København Syd and the airport back
// *after* Hamburg Hbf. Real coordinates and real backend ordering, straight
// from POST /api/proposal/calc with auto_stop_addition="suggest".
const STOCKHOLM = {
  stop_id: 'stockholm',
  stop_name: 'Stockholm Central',
  lat: 59.329875,
  lon: 18.057501,
}
const ZAGREB = {
  stop_id: 'zagreb',
  stop_name: 'Zagreb Glavni kolodvor',
  lat: 45.804446,
  lon: 15.978833,
}
const STOCKHOLM_ZAGREB_SUGGESTIONS: SuggestedStop[] = [
  suggestion('kastrup', 'Københavns Lufthavn Kastrup', 55.629555, 12.649417),
  suggestion('kobenhavn-h', 'Københavns Hovedbanegård', 55.672453, 12.565374),
  suggestion('kobenhavn-syd', 'København Syd', 55.652631, 12.516191),
  suggestion('hoje-taastrup', 'Høje Taastrup', 55.648655, 12.268851),
  suggestion('koge', 'Køge', 55.457979, 12.186467),
  suggestion('slagelse', 'Slagelse', 55.407501, 11.348556),
  suggestion('flensburg', 'Flensburg / Flensborg', 54.774112, 9.436527),
  suggestion('hamburg-hbf', 'Hamburg Hauptbahnhof', 53.552696, 10.007564),
]

describe('settledRows', () => {
  test('keeps every adopted stop in the backend’s route order', () => {
    const rows = settledRows(
      [STOCKHOLM, ZAGREB],
      STOCKHOLM_ZAGREB_SUGGESTIONS,
      new Set(STOCKHOLM_ZAGREB_SUGGESTIONS.map((s) => s.stop_id)),
    )

    expect(rows.map((r) => r.name)).toEqual([
      'Stockholm Central',
      'Københavns Lufthavn Kastrup',
      'Københavns Hovedbanegård',
      'København Syd',
      'Høje Taastrup',
      'Køge',
      'Slagelse',
      'Flensburg / Flensborg',
      'Hamburg Hauptbahnhof',
      'Zagreb Glavni kolodvor',
    ])
  })

  // Two stations 3 km apart, both far from the origin: the tightest case where
  // proximity-based placement flipped a pair, since inserting Westbahnhof
  // before Hauptbahnhof splits the long Stockholm leg fractionally cheaper.
  test('keeps the order of two stops that all but share a location', () => {
    const rows = settledRows(
      [STOCKHOLM, ZAGREB],
      [
        suggestion('wien-hbf', 'Wien Hauptbahnhof', 48.18506, 16.377799),
        suggestion('wien-west', 'Wien Westbahnhof', 48.196545, 16.336282),
      ],
      new Set(['wien-hbf', 'wien-west']),
    )

    expect(rows.map((r) => r.name)).toEqual([
      'Stockholm Central',
      'Wien Hauptbahnhof',
      'Wien Westbahnhof',
      'Zagreb Glavni kolodvor',
    ])
  })

  test('drops the candidates the caller did not opt in, keeping every confirmed stop', () => {
    const rows = settledRows(
      [STOCKHOLM, ZAGREB],
      STOCKHOLM_ZAGREB_SUGGESTIONS,
      new Set(['hoje-taastrup', 'hamburg-hbf']),
    )

    expect(rows.map((r) => r.name)).toEqual([
      'Stockholm Central',
      'Høje Taastrup',
      'Hamburg Hauptbahnhof',
      'Zagreb Glavni kolodvor',
    ])
  })
})
