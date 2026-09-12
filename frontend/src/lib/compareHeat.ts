// The colour a comparison cell gets, in the brand palette. Split out of
// ScenarioCompositionGrid so it can be reasoned about — and tested — on its
// own, because one ramp was being asked to carry two unrelated meanings.
//
// The rule: BRIGHTNESS is quality, HUE is sign.
//
// A sequential KPI (CO2 saved, passenger trips, journey time) has no sign, so
// it runs on one ramp from deep sapphire to yellow-green — dark is worse,
// bright is better, exactly as before.
//
// The subsidy KPI does have a sign, and that is what the single ramp could not
// say. A route needing 2 M€ and a route earning 2 M€ sat next to each other on
// the scale, a few percent apart in colour, distinguished only by the word
// "surplus" in 9px type. It now diverges at break-even:
//
//   worst subsidy  ...  break-even  ...  best surplus
//   dark amber     →   mid amber  |  mint  →  yellow-green
//
// Hue flips at zero, so "does this route pay for itself" is legible at a
// glance across the whole grid. Brightness still rises toward better within
// each side, and the amber side deliberately tops out dimmer than the green
// side does, so the brightest cell in the grid is always the best one and
// never a large subsidy.

import type { CompareKpi } from '@/lib/compareKpis'
import { goodness } from '@/lib/compareKpis'

type Rgb = [number, number, number]

// Sequential: sapphire → sky-blue → yellow-green.
const SEQ_WORST: Rgb = [32, 53, 90]
const SEQ_MID: Rgb = [34, 113, 179]
const SEQ_BEST: Rgb = [146, 208, 81]

// Diverging, subsidy side. The near-zero end stops well short of the green
// side's brightness on purpose — see the note above.
const SUBSIDY_WORST: Rgb = [58, 42, 20]
const SUBSIDY_ZERO: Rgb = [124, 91, 33]

// Diverging, surplus side. The two near-zero constants are matched in
// brightness (luma ~93 either side) so the ramp is monotonic ACROSS the
// boundary as well as within each half: a 0.1 M€ subsidy must not look
// brighter than a 2 M€ surplus just because it sits closer to break-even.
const SURPLUS_ZERO: Rgb = [38, 112, 66]
const SURPLUS_BEST: Rgb = [146, 208, 81]

function lerp(a: Rgb, b: Rgb, t: number): Rgb {
  return a.map((c, i) => Math.round(c + (b[i] - c) * t)) as Rgb
}

function css(c: Rgb): string {
  return `rgb(${c.join(',')})`
}

export interface HeatScale {
  /** Whether the scale breaks at zero — true only when a signed KPI's values
   *  actually straddle it, so an all-subsidy grid keeps one continuous ramp. */
  diverging: boolean
  /** Fill for one cell. */
  color(value: number): string
  /** CSS gradient for the legend, worst on the left. Carries a hard stop at
   *  break-even when diverging, so the legend shows the boundary too. */
  gradient: string
  /** Where break-even sits along the legend, 0..1, or null when not diverging. */
  zeroAt: number | null
  /** The best value present, for marking the cell that holds it. */
  best: number | null
  worst: number | null
}

const EMPTY: HeatScale = {
  diverging: false,
  color: () => css(SEQ_MID),
  gradient: `linear-gradient(90deg, ${css(SEQ_WORST)}, ${css(SEQ_BEST)})`,
  zeroAt: null,
  best: null,
  worst: null,
}

export function buildHeatScale(kpi: CompareKpi, values: number[]): HeatScale {
  if (values.length === 0) return EMPTY
  const min = Math.min(...values)
  const max = Math.max(...values)
  const best = kpi.lowerIsBetter ? min : max
  const worst = kpi.lowerIsBetter ? max : min

  // Signed only for `subsidy`, and only when both signs are on screen: a grid
  // where every route needs a subsidy has no boundary to draw.
  if (kpi.key === 'subsidy' && min < 0 && max > 0) {
    return {
      diverging: true,
      color: (value) =>
        css(
          value >= 0
            ? lerp(SUBSIDY_ZERO, SUBSIDY_WORST, max === 0 ? 0 : value / max)
            : lerp(SURPLUS_ZERO, SURPLUS_BEST, min === 0 ? 0 : value / min),
        ),
      // Left to right is worst to best, and for subsidy worse is HIGHER, so
      // the gradient runs max → 0 → min.
      gradient:
        `linear-gradient(90deg, ${css(SUBSIDY_WORST)}, ` +
        `${css(SUBSIDY_ZERO)} ${((max / (max - min)) * 100).toFixed(1)}%, ` +
        `${css(SURPLUS_ZERO)} ${((max / (max - min)) * 100).toFixed(1)}%, ` +
        `${css(SURPLUS_BEST)})`,
      zeroAt: max / (max - min),
      best,
      worst,
    }
  }

  return {
    diverging: false,
    color: (value) => {
      const t = goodness(kpi, value, min, max)
      return css(t < 0.5 ? lerp(SEQ_WORST, SEQ_MID, t * 2) : lerp(SEQ_MID, SEQ_BEST, (t - 0.5) * 2))
    },
    gradient: `linear-gradient(90deg, ${css(SEQ_WORST)}, ${css(SEQ_MID)}, ${css(SEQ_BEST)})`,
    zeroAt: null,
    best,
    worst,
  }
}
