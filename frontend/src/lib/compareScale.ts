// When a bar chart may stop starting at zero — and when it may not.
//
// Zone B's scenarios differ by a percent or two. On a zero-based axis that is
// four identical rectangles: the comparison the panel exists for is the one it
// hides. Zooming the axis fixes that and introduces a worse risk, because the
// eye reads bar LENGTH as quantity, so a zoomed chart overstates differences
// to anyone who does not notice the axis.
//
// The rule below is the compromise, and it is deliberately conservative: zoom
// only when the differences would otherwise be invisible AND nothing about the
// sign of the values is at stake. The component that uses this draws a marked
// baseline, a labelled axis and a torn edge on every bar whenever `zoomed` is
// true — the arithmetic here is only half the honesty.

/** Zoom only if the spread is under this share of the distance to zero. At a
 *  third, a chart whose bars differ by 30 % still starts at zero — that
 *  difference is already plain to see. */
export const ZOOM_WHEN_SPREAD_BELOW = 1 / 3

export interface AxisScale {
  /** Value at the bottom of the plot: zero on a normal axis. */
  baseline: number
  /** Value at the top of the plot. */
  top: number
  /** top - baseline, never zero. */
  range: number
  zoomed: boolean
}

/**
 * The axis for a set of bar values. Nulls (pending or failed cells) are the
 * caller's to filter out first.
 *
 * Not zoomed when:
 *   · there is nothing to draw, or every bar is identical — a zoom would
 *     magnify rounding noise into a story;
 *   · the values straddle zero. "One scenario needs a subsidy and another
 *     runs a surplus" is exactly the comparison a floating baseline flattens,
 *     and the zero line is the whole point of that chart;
 *   · the spread is already a visible fraction of the bars' own height.
 */
export function chooseScale(values: number[]): AxisScale {
  if (values.length === 0) return { baseline: 0, top: 1, range: 1, zoomed: false }

  const hi = Math.max(...values)
  const lo = Math.min(...values)
  const spread = hi - lo
  const sameSign = lo > 0 || hi < 0
  const toZero = Math.max(Math.abs(hi), Math.abs(lo))

  if (!sameSign || spread === 0 || spread >= toZero * ZOOM_WHEN_SPREAD_BELOW) {
    const top = Math.max(0, hi)
    const baseline = Math.min(0, lo)
    return { baseline, top, range: top - baseline || 1, zoomed: false }
  }

  // An eighth of the spread of air at each end, so the tallest bar does not
  // touch the top of the plot and the shortest is still visibly a bar rather
  // than a line.
  const pad = spread / 8
  const baseline = lo - pad
  const top = hi + pad
  return { baseline, top, range: top - baseline, zoomed: true }
}
