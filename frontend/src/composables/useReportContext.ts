// What a "report a problem" link on a result panel needs from the builder:
// the route's two ends for the subject line and the parameter block for the
// message (lib/feedbackLink.ts routingFeedbackContext). Only ProposalViewport
// knows the committed state that block is built from, so it provides it once
// and every panel below — the KPI grid, the comparison, the breakdown, each
// Details panel — injects it, however deep it sits.
//
// Null while there is no calculated route: the panels then render no report
// link, because there is nothing to report on yet.

import { inject, provide, type ComputedRef } from 'vue'

export interface ReportContext {
  /** "Budapest-Déli → Bruxelles-Midi" */
  ends: string
  /** The route's input parameters, one labelled line each. */
  context: string
}

const KEY = Symbol('report-context')

export function provideReportContext(value: ComputedRef<ReportContext | null>): void {
  provide(KEY, value)
}

export function useReportContext(): ComputedRef<ReportContext | null> | undefined {
  return inject<ComputedRef<ReportContext | null>>(KEY, undefined)
}
