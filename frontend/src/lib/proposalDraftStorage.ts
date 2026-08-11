// Persists an unpublished /proposal-builder draft (itinerary stop ids,
// composition id, and — if mid suggest-flow — the opted-in candidate stop
// ids) across reloads. Only bare ids are stored, never full Stop/Composition
// objects, so they're re-resolved against the loaded catalogue on read (same
// idiom as proposalPrefill.ts's seedToQuery/seedFromQuery). Cleared once the
// draft is published — see ProposalViewport.vue's doPublish().
export interface ProposalDraft {
  stopIds: string[]
  compositionId: string | null
  // null = not mid suggest-flow; an array (possibly empty) = was in suggest
  // mode with these candidate stop ids opted in.
  suggestSelectedIds: string[] | null
}

const STORAGE_KEY = 'nt_proposal_draft'

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string')
}

export function readDraft(): ProposalDraft | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return null
    const { stopIds, compositionId, suggestSelectedIds } = parsed as Record<string, unknown>
    if (!isStringArray(stopIds)) return null
    return {
      stopIds,
      compositionId: typeof compositionId === 'string' ? compositionId : null,
      suggestSelectedIds: isStringArray(suggestSelectedIds) ? suggestSelectedIds : null,
    }
  } catch {
    return null
  }
}

export function writeDraft(draft: ProposalDraft): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(draft))
}

export function clearDraft(): void {
  localStorage.removeItem(STORAGE_KEY)
}
