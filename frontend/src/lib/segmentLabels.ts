// Where each segment of a stacked bar gets its label.
//
// A proportional bar cannot hold a label in every segment: some parts are a
// tenth of a percent wide. So a label goes INSIDE its segment when the
// segment has room for it, and OUTSIDE — below the bar, on a leader that
// drops from the segment's centre — when it does not. Outside labels are laid
// out in rows so they never overlap each other, and a label that had to be
// shifted sideways to make room keeps an elbow back to its own segment, so it
// can never be read as belonging to the neighbour.
//
// Everything here is in PIXELS, measured from the real width of the track.
// The earlier attempt estimated widths as percentages of the bar and guessed
// at glyph sizes; on a narrow panel the estimates were wrong by enough that
// labels landed under the wrong segment. Pixels or nothing.

export interface SegmentInput {
  key: string
  /** Text to print — the abbreviation for cost, the class name for revenue. */
  text: string
  /** Left edge and width of the segment, in px from the track's left edge. */
  x: number
  width: number
}

export interface InsideLabel {
  key: string
  placement: 'inside'
  text: string
}

export interface OutsideLabel {
  key: string
  placement: 'outside'
  text: string
  /** Where the leader leaves the bar: the segment's centre. */
  anchorX: number
  /** Where the label starts, after collision avoidance. */
  labelX: number
  /** Which row below the bar, 0 nearest. */
  row: number
  /** Label width in px, so the elbow can be drawn to its edge. */
  labelWidth: number
}

export type SegmentLabel = InsideLabel | OutsideLabel

export interface LabelLayoutOptions {
  /** Track width in px. Labels are clamped inside it. */
  trackWidth: number
  /** Average glyph advance for the label face, px. 6.2 fits the 10 px
   *  semibold the bars use; measure before changing it. */
  charPx?: number
  /** Horizontal padding around a label inside its segment, px each side. */
  insidePad?: number
  /** Minimum gap between two outside labels in one row, px. */
  gapPx?: number
  /** How many rows below the bar may be used. Two is enough for six segments;
   *  anything that still does not fit is pushed right in the last row. */
  maxRows?: number
}

export function labelWidthPx(text: string, charPx: number): number {
  return text.length * charPx
}

/**
 * Lay out one bar's labels. Segments are given in bar order; outside labels
 * are assigned to rows in that same order, so reading a row left to right
 * follows the bar.
 */
export function layoutSegmentLabels(
  segments: SegmentInput[],
  opts: LabelLayoutOptions,
): SegmentLabel[] {
  const charPx = opts.charPx ?? 6.2
  const insidePad = opts.insidePad ?? 4
  const gapPx = opts.gapPx ?? 8
  const maxRows = Math.max(1, opts.maxRows ?? 2)
  const track = Math.max(0, opts.trackWidth)

  // Right edge of the last label placed in each row.
  const rowCursor: number[] = Array(maxRows).fill(-Infinity)

  return segments.map((segment) => {
    const width = labelWidthPx(segment.text, charPx)
    if (width + 2 * insidePad <= segment.width) {
      return { key: segment.key, placement: 'inside', text: segment.text }
    }

    const anchorX = segment.x + segment.width / 2
    // Centre the label on its anchor, then keep it on the track.
    const wanted = Math.min(Math.max(anchorX - width / 2, 0), Math.max(0, track - width))

    // First row where it fits at its wanted position; failing that, the row
    // whose cursor is furthest left, pushed right of that cursor. Labels are
    // laid in bar order, so a pushed label is always to the RIGHT of its
    // anchor, never left — the elbow only ever points back the one way.
    let row = rowCursor.findIndex((cursor) => wanted >= cursor + gapPx)
    let labelX = wanted
    if (row === -1) {
      row = rowCursor.indexOf(Math.min(...rowCursor))
      labelX = Math.min(rowCursor[row] + gapPx, Math.max(0, track - width))
    }
    rowCursor[row] = labelX + width

    return {
      key: segment.key,
      placement: 'outside',
      text: segment.text,
      anchorX,
      labelX,
      row,
      labelWidth: width,
    }
  })
}
