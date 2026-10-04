// Number formatting for the report pages. The report's JSON carries raw
// numbers (backend/scripts/crowdsourcing_report.py) and the page decides
// how they read, so one figure can appear as "1 297" in a sentence and as a
// bar length in the chart beside it without the script knowing either.
//
// Thousands are grouped with a narrow no-break space, the house style of
// the hand-written pages ("100 000 passengers" in demand.md), and the
// percent sign is set off the same way ("50 %").

const NNBSP = ' '

/** 1297 → "1 297"; with digits, 2.345 → "2.3". */
export function formatNumber(value: number, digits = 0): string {
  const fixed = Math.abs(value).toFixed(digits)
  const [whole, fraction] = fixed.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, NNBSP)
  const sign = value < 0 ? '−' : ''
  return sign + (fraction ? `${grouped}.${fraction}` : grouped)
}

/** 0.935 → "94 %". */
export function formatPercent(share: number, digits = 0): string {
  return `${formatNumber(share * 100, digits)}${NNBSP}%`
}

/** Large totals in words: 2 120 194 → "2.1 M", 124 402 361 949 → "124 bn". */
export function formatCompact(value: number, digits = 1): string {
  if (Math.abs(value) >= 1e9) return `${formatNumber(value / 1e9, digits)}${NNBSP}bn`
  if (Math.abs(value) >= 1e6) return `${formatNumber(value / 1e6, digits)}${NNBSP}M`
  return formatNumber(value)
}
