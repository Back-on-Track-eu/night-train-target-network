// Pure helpers for the two-handle route-section slider (RouteSectionSlider.vue).
// Extracted so the index arithmetic is unit-testable without mounting the
// component (see the frontend test note in AGENTS.md).

/**
 * Which handle a click on stop `index` should move: 0 = origin, 1 = destination.
 *
 * A click names one position but the slider has two handles, so the nearer one
 * moves — matching how dragging already behaves, with no click-order mode for
 * the user to track.
 *
 * Clicks at or beyond a handle always move THAT handle. Without those two
 * guards a click exactly on the destination could be assigned to the origin,
 * which the one-leg-apart clamp would then push to `dest - 1` — moving a handle
 * the user never aimed at. Interior ties go to the origin, arbitrarily but
 * deterministically.
 */
export function nearestHandle(index: number, origin: number, dest: number): 0 | 1 {
  if (index <= origin) return 0
  if (index >= dest) return 1
  return index - origin <= dest - index ? 0 : 1
}
