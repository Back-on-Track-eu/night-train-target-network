// Which feedback topic the panels of the Details card carry — the active
// tab's. DetailsSection provides it; DetailPanel injects it. A panel rendered
// outside the card (none today) gets undefined and shows no feedback link.

import { inject, provide, type ComputedRef } from 'vue'
import type { ReportPanel } from '@/lib/feedbackLink'

const KEY = Symbol('details-tab-report')

export function provideDetailsTabReport(topic: ComputedRef<ReportPanel>): void {
  provide(KEY, topic)
}

export function useDetailsTabReport(): ComputedRef<ReportPanel> | undefined {
  return inject<ComputedRef<ReportPanel>>(KEY, undefined)
}
