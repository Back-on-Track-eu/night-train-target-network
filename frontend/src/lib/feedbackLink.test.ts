import { describe, it, expect } from 'vitest'
import {
  docsFeedbackUrl,
  FEEDBACK_TOPIC_MISSING_STOP,
  FEEDBACK_TOPIC_ROUTING,
  routingFeedbackContext,
  type RoutingReport,
} from './feedbackLink'

describe('docsFeedbackUrl', () => {
  it('links to the docs page with the topic alias', () => {
    expect(docsFeedbackUrl(FEEDBACK_TOPIC_MISSING_STOP)).toBe('/docs/feedback?topic=missing-stop')
  })

  it('carries the search text as q', () => {
    expect(docsFeedbackUrl(FEEDBACK_TOPIC_MISSING_STOP, 'Bad Ischl')).toBe(
      '/docs/feedback?topic=missing-stop&q=Bad+Ischl',
    )
  })

  it('escapes what a search box can legitimately hold', () => {
    // An & or a # in the query would otherwise end the parameter or start a
    // fragment — a station name with an ampersand is not exotic.
    expect(docsFeedbackUrl('t', 'A & B #1')).toBe('/docs/feedback?topic=t&q=A+%26+B+%231')
  })

  it('leaves q out when there is nothing to search for', () => {
    expect(docsFeedbackUrl('t', '   ')).toBe('/docs/feedback?topic=t')
    expect(docsFeedbackUrl('t', undefined)).toBe('/docs/feedback?topic=t')
  })

  it('trims and caps a pasted paragraph', () => {
    const url = docsFeedbackUrl('t', `  ${'x'.repeat(200)}  `)
    expect(new URLSearchParams(url.split('?')[1]).get('q')).toBe('x'.repeat(120))
  })
})

describe('docsFeedbackUrl with context', () => {
  it('carries a multi-line block as one parameter', () => {
    const url = docsFeedbackUrl(FEEDBACK_TOPIC_ROUTING, 'A → B', 'line one\nline two')
    const params = new URLSearchParams(url.split('?')[1])
    expect(params.get('topic')).toBe('routing')
    expect(params.get('q')).toBe('A → B')
    expect(params.get('context')).toBe('line one\nline two')
  })

  it('caps the block', () => {
    const url = docsFeedbackUrl('t', undefined, 'x'.repeat(3_000))
    expect(new URLSearchParams(url.split('?')[1]).get('context')).toHaveLength(1_500)
  })
})

describe('routingFeedbackContext', () => {
  const report: RoutingReport = {
    stops: [
      { name: 'Budapest-Déli', id: 'osm:n1' },
      { name: 'Bruxelles-Midi', id: 'osm:n2' },
    ],
    scenario: 'Infrastructure 2026',
    composition: 'NEW-BAL-7',
    expert: false,
    nightBetween: null,
    km: 1427.4,
    kmh: 101.6,
    countries: ['HU', 'AT', 'DE', 'BE'],
    proposalUrl: 'https://example.org/proposal/7',
    routeBuilderVersion: '0.9.40',
  }

  it('lists every input the route was computed from, one per line', () => {
    expect(routingFeedbackContext(report).split('\n')).toEqual([
      'Stops: Budapest-Déli (osm:n1) → Bruxelles-Midi (osm:n2)',
      'Scenario: Infrastructure 2026',
      'Train: NEW-BAL-7',
      'Timetable: automatic, centred on 02:30',
      'Result: 1427 km, 102 km/h average, through HU, AT, DE, BE',
      'Proposal: https://example.org/proposal/7',
      'Route builder: 0.9.40',
    ])
  })

  it('names the expert timetable and a fixed night', () => {
    const text = routingFeedbackContext({
      ...report,
      expert: true,
      nightBetween: ['Wien Hbf', 'München Ost'],
    })
    expect(text).toContain(
      'Timetable: expert (edited departures or leg minutes); night fixed between Wien Hbf and München Ost',
    )
  })

  it('leaves out what is not known rather than printing blanks', () => {
    const text = routingFeedbackContext({
      ...report,
      scenario: null,
      composition: null,
      km: null,
      kmh: null,
      countries: [],
      proposalUrl: null,
      routeBuilderVersion: null,
    })
    expect(text.split('\n')).toEqual([
      'Stops: Budapest-Déli (osm:n1) → Bruxelles-Midi (osm:n2)',
      'Timetable: automatic, centred on 02:30',
    ])
  })
})
