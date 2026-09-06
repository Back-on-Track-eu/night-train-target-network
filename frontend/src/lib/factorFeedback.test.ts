import { describe, it, expect } from 'vitest'
import { formulaKeyForNode, docsPathForFormula, resolveFactorSubCategory } from './factorFeedback'

// The cost tree's node keys, exactly as CostPanel.vue builds them, plus the
// revenue row. If a row is added there without a mapping here, these fail.
const LEAF_NODES = [
  'driver',
  'crew',
  'coach_maintenance',
  'loco',
  'svc_stockings',
  'var_overhead',
  'coach_amortisation',
  'financing',
  'fix_overhead',
  'cleaning',
  'shunting',
  'tac',
  'energy',
  'station_charge',
  'parking',
  'ebit_margin',
]
const GROUP_NODES = ['operator', 'variable', 'fixed', 'infrastructure']

describe('formulaKeyForNode', () => {
  it('appends _eur for leaf rows', () => {
    expect(formulaKeyForNode('driver')).toBe('driver_eur')
    expect(formulaKeyForNode('tac')).toBe('tac_eur')
    expect(formulaKeyForNode('ebit_margin')).toBe('ebit_margin_eur')
  })

  // The bug this map exists for: "operator" + "_eur" is in no registry, so
  // the four subtotal rows used to resolve to nothing and lose their icon.
  it('maps the four subtotal rows to their *_total_eur keys', () => {
    expect(formulaKeyForNode('operator')).toBe('operator_total_eur')
    expect(formulaKeyForNode('variable')).toBe('operator_variable_total_eur')
    expect(formulaKeyForNode('fixed')).toBe('operator_fixed_total_eur')
    expect(formulaKeyForNode('infrastructure')).toBe('infrastructure_total_eur')
  })

  it('never yields a bare *_eur for a subtotal row', () => {
    for (const node of GROUP_NODES) {
      expect(formulaKeyForNode(node)).not.toBe(`${node}_eur`)
      expect(formulaKeyForNode(node)).toMatch(/_total_eur$/)
    }
  })
})

describe('docsPathForFormula', () => {
  // Shared with cost_slug() in backend/scripts/model_docs/render_site.py.
  // These are the emitted page names; a change here without a change there
  // is a 404 on every info popover.
  it.each([
    ['tac_eur', '/docs/cost/tac'],
    ['driver_eur', '/docs/cost/driver'],
    ['coach_maintenance_eur', '/docs/cost/coach-maintenance'],
    ['operator_variable_total_eur', '/docs/cost/operator-variable-total'],
    ['infrastructure_total_eur', '/docs/cost/infrastructure-total'],
    ['ebit_margin_eur', '/docs/cost/ebit-margin'],
    ['ticket_revenue_eur', '/docs/cost/ticket-revenue'],
    ['net_eur', '/docs/cost/net'],
  ])('%s → %s', (key, path) => {
    expect(docsPathForFormula(key)).toBe(path)
  })

  it('strips only a trailing _eur, not one inside the key', () => {
    expect(docsPathForFormula('total_eur_thing_eur')).toBe('/docs/cost/total-eur-thing')
  })

  it('leaves a key without the suffix alone apart from hyphenation', () => {
    expect(docsPathForFormula('tac_night_share')).toBe('/docs/cost/tac-night-share')
  })
})

describe('resolveFactorSubCategory', () => {
  it('maps every row that shows an info icon', () => {
    for (const node of [...LEAF_NODES, ...GROUP_NODES]) {
      const sub = resolveFactorSubCategory(formulaKeyForNode(node))
      expect(sub, `no sub_category for node "${node}"`).not.toBeNull()
    }
  })

  // Regression: ebit_margin had no entry, so its feedback button submitted
  // nothing at all — onSubmitFeedback returns early on a null sub-category.
  it('covers the margin row', () => {
    expect(resolveFactorSubCategory('ebit_margin_eur')).toBe('margin.ebit_margin_eur')
  })

  it('covers ticket revenue, which had no icon at all before', () => {
    expect(resolveFactorSubCategory('ticket_revenue_eur')).toBe('revenue.ticket_revenue_eur')
  })

  it('returns null for an unmapped key so the caller can withhold', () => {
    expect(resolveFactorSubCategory('not_a_factor_eur')).toBeNull()
  })

  it('emits dotted Breakdown paths, matching the backend tree', () => {
    expect(resolveFactorSubCategory('driver_eur')).toBe('cost.operator.variable.driver_eur')
    expect(resolveFactorSubCategory('operator_total_eur')).toBe('cost.operator.total_eur')
  })
})
