import { describe, expect, test } from 'vitest'
import {
  SELECTION_SAVE_DELAY_MS,
  selectionSaveNeeded,
  type SelectionSaveState,
} from './selectionSave'

function state(over: Partial<SelectionSaveState> = {}): SelectionSaveState {
  return {
    ownsProposal: true,
    proposalId: 7,
    selectedCompositionId: 'NEW-BAL-14',
    savedCompositionId: 'NEW-BAL-7',
    dirty: false,
    busy: false,
    ...over,
  }
}

describe('selectionSaveNeeded', () => {
  test('saves a changed composition on the user own stored proposal', () => {
    expect(selectionSaveNeeded(state())).toBe(true)
  })

  // The whole point of comparing against the stored value: arrowing away
  // and back is not an edit, and must not cost a publish.
  test('is false once the selection is back where it was saved', () => {
    expect(selectionSaveNeeded(state({ selectedCompositionId: 'NEW-BAL-7' }))).toBe(false)
  })

  // Recomputing someone else's proposal to look at another composition is a
  // private what-if; the backend refuses the write, and asking for it would
  // be a 403 the user never provoked.
  test('never saves someone else proposal', () => {
    expect(selectionSaveNeeded(state({ ownsProposal: false }))).toBe(false)
  })

  // A first publish carries the name, the identity gate and the "published"
  // event — the Evaluate path owns it.
  test('never creates a proposal', () => {
    expect(selectionSaveNeeded(state({ proposalId: null }))).toBe(false)
  })

  // A dirty itinerary means the figures describe a route that no longer
  // exists; a busy state means another path is already deciding what to
  // store.
  test('waits while the itinerary is edited or something is in flight', () => {
    expect(selectionSaveNeeded(state({ dirty: true }))).toBe(false)
    expect(selectionSaveNeeded(state({ busy: true }))).toBe(false)
  })

  test('needs a composition to save', () => {
    expect(selectionSaveNeeded(state({ selectedCompositionId: null }))).toBe(false)
  })
})

describe('SELECTION_SAVE_DELAY_MS', () => {
  // Long enough that stepping through the catalogue is one publish, short
  // enough that a deliberate pick survives leaving the page.
  test('is a debounce, not a delay the user would notice as lag', () => {
    expect(SELECTION_SAVE_DELAY_MS).toBeGreaterThanOrEqual(1000)
    expect(SELECTION_SAVE_DELAY_MS).toBeLessThanOrEqual(3000)
  })
})
