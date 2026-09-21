// One place decides what a currency figure looks like. Every panel that prints
// euros — the KPI strip, the bars, both ledgers, the compare tiles, every
// receipt and strip in the Details card — goes through here, so a change
// lands everywhere at once. Before this module three formatters disagreed on
// one screen ("7.19M €", "7.19 M €", "565,148.02 €" for the same kind of
// figure).
//
// THE RULE, and it is the whole rule:
//
//   ≥ 1,000,000   →  "1.23 M €"
//   ≥ 1,000       →  "5.40 k €"
//   otherwise     →  "443.70 €"
//
// Two decimals at every scale, the unit on every figure, a space before the
// suffix and before the €. No compact notation ("7.19M€"), no grouped
// six-figure sums, no role-dependent exceptions: a receipt line and a KPI
// tile print the same number the same way. The one carve-out lives in
// useEvaluationFormat — a rate below one euro keeps significant digits so
// a 0.004 €/place-km leaf does not read as "0.00 €".

const MILLION = 1_000_000
const THOUSAND = 1_000

function two(locale: string): Intl.NumberFormat {
  return new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function formatEur(value: number, locale: string): string {
  const abs = Math.abs(value)
  if (abs >= MILLION) return `${two(locale).format(value / MILLION)} M €`
  if (abs >= THOUSAND) return `${two(locale).format(value / THOUSAND)} k €`
  return `${two(locale).format(value)} €`
}

/** A figure already expressed in millions (the compare KPI helpers carry
 *  these). Same look as formatEur would give the full amount. */
export function formatMillionEur(millions: number, locale: string): string {
  return formatEur(millions * MILLION, locale)
}

/** Plain counts — passengers, place-km, hours — on the same thresholds and
 *  suffixes as money, minus the unit, so "1.20 M" and "1.20 M €" read as the
 *  same order of magnitude rather than two conventions. */
export function formatCount(value: number, locale: string): string {
  const abs = Math.abs(value)
  if (abs >= MILLION) return `${two(locale).format(value / MILLION)} M`
  if (abs >= 10 * THOUSAND) {
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value / THOUSAND)} k`
  }
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value)
}

/** Tonnes on the same thresholds, with the unit folded into the prefix —
 *  "43.66 kt", "1.20 Mt", "850 t" — because a bare "k" in front of a
 *  separate "t" reads as a typo, and a million prefix in front of "kt"
 *  (which is how the CO₂ tile once read) is off by a factor of a million. */
export function formatTonnes(value: number, locale: string): string {
  const abs = Math.abs(value)
  if (abs >= MILLION) return `${two(locale).format(value / MILLION)} Mt`
  if (abs >= THOUSAND) return `${two(locale).format(value / THOUSAND)} kt`
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value)} t`
}

export function formatInt(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value)
}
