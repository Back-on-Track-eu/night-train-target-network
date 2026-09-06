/**
 * factorFeedback.ts
 * =================
 * Three things the cost/revenue breakdown needs about one of its rows:
 * which backend formula documents it, where that formula is explained on
 * the documentation site, and what `sub_category` its feedback carries.
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

/**
 * Formula key → the full dotted Breakdown path POST /api/feedback expects
 * as `sub_category` (backend models/evaluation/views.py's Breakdown tree,
 * enumerated by GET /api/feedback/categories under "Evaluation —
 * calculation method").
 *
 * Now covers every row that shows an info icon, not just the cost leaves:
 * the four subtotals, the margin row (whose feedback button silently did
 * nothing before, because onSubmitFeedback bails on a null sub-category)
 * and ticket revenue.
 */
const FACTOR_SUB_CATEGORY: Record<string, string> = {
  driver_eur: 'cost.operator.variable.driver_eur',
  crew_eur: 'cost.operator.variable.crew_eur',
  coach_maintenance_eur: 'cost.operator.variable.coach_maintenance_eur',
  loco_eur: 'cost.operator.variable.loco_eur',
  svc_stockings_eur: 'cost.operator.variable.svc_stockings_eur',
  var_overhead_eur: 'cost.operator.variable.var_overhead_eur',
  coach_amortisation_eur: 'cost.operator.fixed.coach_amortisation_eur',
  financing_eur: 'cost.operator.fixed.financing_eur',
  fix_overhead_eur: 'cost.operator.fixed.fix_overhead_eur',
  cleaning_eur: 'cost.operator.fixed.cleaning_eur',
  shunting_eur: 'cost.operator.fixed.shunting_eur',
  tac_eur: 'cost.infrastructure.tac_eur',
  energy_eur: 'cost.infrastructure.energy_eur',
  station_charge_eur: 'cost.infrastructure.station_charge_eur',
  parking_eur: 'cost.infrastructure.parking_eur',
  operator_variable_total_eur: 'cost.operator.variable.total_eur',
  operator_fixed_total_eur: 'cost.operator.fixed.total_eur',
  operator_total_eur: 'cost.operator.total_eur',
  infrastructure_total_eur: 'cost.infrastructure.total_eur',
  ebit_margin_eur: 'margin.ebit_margin_eur',
  ticket_revenue_eur: 'revenue.ticket_revenue_eur',
}

/**
 * The `sub_category` POST /api/feedback wants for a factor. Returns null
 * for an unmapped key so the caller can withhold submission rather than
 * post something the working group cannot route.
 */
export function resolveFactorSubCategory(factorKey: string): string | null {
  return FACTOR_SUB_CATEGORY[factorKey] ?? null
}
