/**
 * factorFeedback.ts
 * =================
 * Two things the cost/revenue breakdown needs about one of its rows: which
 * backend formula documents it, and where that formula is explained on the
 * documentation site.
 *
 * Replaces the mapping that lived in costFactorRates.ts, which existed to
 * feed the popover's rates table. That table moved to the docs site, so
 * only this part survives.
 */

/**
 * Tree node key → backend formula key.
 *
 * Leaves are just the key plus "_eur" (driver → driver_eur), but the four
 * subtotal rows are not: the tree calls them operator/variable/fixed/
 * infrastructure while the backend calls them *_total_eur. Appending
 * "_eur" to those yields "operator_eur", which is in no registry — which
 * is why the subtotal rows silently had no info icon before this map
 * existed.
 */
const NODE_FORMULA_OVERRIDES: Record<string, string> = {
  operator: 'operator_total_eur',
  variable: 'operator_variable_total_eur',
  fixed: 'operator_fixed_total_eur',
  infrastructure: 'infrastructure_total_eur',
}

/** The formula key documenting a breakdown row. */
export function formulaKeyForNode(nodeKey: string): string {
  return NODE_FORMULA_OVERRIDES[nodeKey] ?? `${nodeKey}_eur`
}

/**
 * Documentation page for a formula.
 *
 * The contract, shared with the emitter's cost_slug() in
 * backend/scripts/model_docs/render_site.py: drop a trailing "_eur", then
 * underscores become hyphens. tac_eur → /docs/cost/tac,
 * operator_variable_total_eur → /docs/cost/operator-variable-total.
 *
 * Absolute, and deliberately not a vue-router link: the docs are a
 * separate static site served by nginx at /docs/ on this same origin, not
 * a route this SPA owns.
 */
export function docsPathForFormula(formulaKey: string): string {
  return `/docs/cost/${formulaKey.replace(/_eur$/, '').replace(/_/g, '-')}`
}
