import { describe, it, expect } from 'vitest'
import { docsFeedbackUrl, FEEDBACK_TOPIC_MISSING_STOP } from './feedbackLink'

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
