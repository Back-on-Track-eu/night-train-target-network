// When a family-served switch in the builder is worth saving, and how long
// to wait before it is. The rule lives here rather than inside
// ProposalViewport so it can be reasoned about — and tested — without a
// component: the frontend test setup never mounts one.
//
// WHY THIS EXISTS. Switching composition on an owned proposal used to be a
// look, not an edit: `applyMemberFromFamily()` put the member on screen and
// nothing was stored, so a creator who arrowed through the catalogue and
// left had a proposal on the composition of their last RECALCULATE, not
// their last selection. Every figure the gallery then showed — and, since
// the per-scenario projections, every figure it shows on every scenario —
// described a train they had moved on from.
//
// WHY A DEBOUNCE. Each publish recomputes server-side and rewrites the
// proposal's rows. Arrowing through twelve compositions must cost one
// publish, not twelve, so the save waits until the selection has stopped
// moving. The delay is long enough to cover a fast reader stepping through
// the catalogue and short enough that leaving the page right after a
// deliberate pick still saves it.

/** Milliseconds of quiet before a changed selection is saved. */
export const SELECTION_SAVE_DELAY_MS = 1500

export interface SelectionSaveState {
  /** Whether the proposal on screen is this user's own. Someone else's is
   *  never overwritten — recomputing it to look at another composition is a
   *  private what-if (the backend refuses the write anyway). */
  ownsProposal: boolean
  /** The stored proposal's id, or null while nothing has been published —
   *  a first publish is the Evaluate button's job, never an auto-save. */
  proposalId: number | null
  /** Composition currently on screen. */
  selectedCompositionId: string | null
  /** Composition the stored proposal was last published with. */
  savedCompositionId: string | null
  /** An edited itinerary: the results describe a route that no longer
   *  exists, and saving would store the old one under the new stops. */
  dirty: boolean
  /** A compute or a load is in flight — its own path decides what to save. */
  busy: boolean
}

/**
 * Whether the current state is a selection worth persisting. Deliberately
 * only the composition: prices, demand, schedule and expert edits already
 * reach the store through the Recalculate that computes them, and the
 * scenario is not stored at all (a published proposal always represents the
 * current base — the gallery's scenario panel is what shows the others).
 */
export function selectionSaveNeeded(state: SelectionSaveState): boolean {
  if (!state.ownsProposal || state.proposalId === null) return false
  if (state.dirty || state.busy) return false
  if (state.selectedCompositionId === null) return false
  return state.selectedCompositionId !== state.savedCompositionId
}
