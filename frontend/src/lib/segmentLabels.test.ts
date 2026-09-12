import { describe, it, expect } from 'vitest'
import { layoutSegmentLabels, type OutsideLabel } from './segmentLabels'

const seg = (key: string, x: number, width: number, text = key) => ({ key, text, x, width })

describe('segment labels', () => {
  it('goes inside when the segment has room', () => {
    const [label] = layoutSegmentLabels([seg('OP-VAR', 0, 200)], { trackWidth: 600 })
    expect(label.placement).toBe('inside')
  })

  it('goes outside when the segment does not', () => {
    // 'STN' at 6.2 px/char is ~19 px plus padding; a 3 px sliver cannot hold it.
    const [label] = layoutSegmentLabels([seg('STN', 300, 3)], { trackWidth: 600 })
    expect(label.placement).toBe('outside')
    expect((label as OutsideLabel).anchorX).toBeCloseTo(301.5, 3)
  })

  it('centres an outside label on its own segment', () => {
    const [label] = layoutSegmentLabels([seg('STN', 300, 3)], {
      trackWidth: 600,
    }) as OutsideLabel[]
    expect(label.labelX + label.labelWidth / 2).toBeCloseTo(label.anchorX, 3)
    expect(label.row).toBe(0)
  })

  it('never lets two outside labels overlap', () => {
    // Three slivers next to each other — the case that broke the old callouts.
    const labels = layoutSegmentLabels(
      [seg('STN', 300, 2), seg('NRG', 302, 2), seg('MRG', 304, 2)],
      { trackWidth: 600 },
    ) as OutsideLabel[]
    for (const row of [0, 1]) {
      const inRow = labels.filter((l) => l.row === row).sort((a, b) => a.labelX - b.labelX)
      for (let i = 1; i < inRow.length; i++) {
        expect(inRow[i].labelX).toBeGreaterThanOrEqual(
          inRow[i - 1].labelX + inRow[i - 1].labelWidth,
        )
      }
    }
  })

  it('uses the second row before pushing a label away from its segment', () => {
    const labels = layoutSegmentLabels([seg('STN', 300, 2), seg('NRG', 302, 2)], {
      trackWidth: 600,
    }) as OutsideLabel[]
    expect(labels[0].row).toBe(0)
    expect(labels[1].row).toBe(1)
    // Both still centred on their anchors — no sideways shove was needed.
    expect(labels[1].labelX + labels[1].labelWidth / 2).toBeCloseTo(labels[1].anchorX, 3)
  })

  it('only ever pushes a label to the right of its anchor', () => {
    // Four slivers, two rows: the third and fourth must shove, and they
    // shove right, so the elbow always points back the same way.
    const labels = layoutSegmentLabels(
      [seg('A-1', 300, 1), seg('B-2', 301, 1), seg('C-3', 302, 1), seg('D-4', 303, 1)],
      { trackWidth: 600 },
    ) as OutsideLabel[]
    for (const label of labels) {
      expect(label.labelX + label.labelWidth / 2).toBeGreaterThanOrEqual(label.anchorX - 0.001)
    }
  })

  it('keeps every label on the track', () => {
    const labels = layoutSegmentLabels([seg('OP-FIX', 590, 4)], {
      trackWidth: 600,
    }) as OutsideLabel[]
    expect(labels[0].labelX + labels[0].labelWidth).toBeLessThanOrEqual(600)
    expect(labels[0].labelX).toBeGreaterThanOrEqual(0)
  })
})
