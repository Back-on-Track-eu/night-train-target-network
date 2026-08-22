import { describe, expect, test } from 'vitest'
import { buildSuggestRows, type ConfirmedStop } from './suggestPlacement'
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
