// Cost-factor → per-unit-rate resolution for the cost breakdown detail popover.
//
// The evaluation response carries every rate under input.parameters, but it
// does NOT say which rates feed which cost factor, nor in what order they
// appear in a factor's formula. FACTOR_RATES below is that missing link: for
// each cost-factor formula key (e.g. "driver_eur") it lists the rate ids in
// the order they appear left-to-right in the factor's LaTeX formula (see
// backend/models/evaluation/version.py::CALC_FORMULAS).
//
// This descriptor is the ONLY hardcoded piece — every value/unit/description/
// source is pulled live from input.parameters at resolve time. input.parameters
// lists all loaded entities (all countries/stops/compositions), so rates are
// scoped to the ones the route actually uses: countries from
// route.track_infrastructure, the composition per trip pair, and the ordered
// route stops passed in by the caller.

import type {
  CompositionParam,
  EvaluationInput,
  OperatorParam,
  ParamSource,
  TrackInfraParam,
} from '@/types/api'

/** One resolved rate row shown in the popover's rates table. */
export interface RateRow {
  /** Stable rate id → i18n label key `proposal.evaluation.rates.<id>`. */
  id: string
  /** Entity this value applies to (country code, stop, class, comp/operator);
   *  null when there is only one and the scope is unambiguous. */
  scope: string | null
  /** Raw numeric value from input.parameters (never transformed here). */
  value: number
  /** Unit token parsed from the backend description (e.g. "€/h"), "" if none. */
  unit: string
  /** Backend field description with the trailing "Unit: …" removed. */
  description: string
  /** True when the value fell back to a default (track/stop infra only). */
  isDefault: boolean
  /** Sources backing this value (backend-provided, shown as-is). */
  sources: ParamSource[]
}

// Rate ids per cost factor, in formula (left-to-right) order. Pure counts /
// multipliers in the formula (driver_factor, coach count, operating days) are
// omitted — only genuine per-unit rates and cost inputs are listed.
const FACTOR_RATES: Record<string, string[]> = {
  driver_eur: ['driver_rate'],
  crew_eur: ['crew_rate'],
  coach_maintenance_eur: ['coach_maint_km'],
  loco_eur: ['loco_lease_h'],
  svc_stockings_eur: ['svc_place'],
  var_overhead_eur: ['var_overhead_quota'],
  coach_amortisation_eur: ['coach_purchase', 'coach_amort_years'],
  financing_eur: ['coach_purchase', 'financing_quota'],
  fix_overhead_eur: ['fix_overhead_quota'],
  cleaning_eur: ['cleaning_day'],
  shunting_eur: ['shunting_event'],
  tac_eur: ['tac_km'],
  energy_eur: ['energy_kwh'],
  station_charge_eur: ['stop_charge'],
  parking_eur: ['parking_day'],
}

// Cost-factor formula key (e.g. "driver_eur") → the full dotted Breakdown
// path the feedback API expects as `sub_category` (see backend
// models/evaluation/views.py's Breakdown tree, enumerated by
// GET /api/feedback/categories under "Evaluation — calculation method").
// The cost tree's node keys are the short form ("driver"); append "_eur" to
// get the formula key used here, so the popover can tag feedback to the exact
// factor it is showing.
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
}

/**
 * The `sub_category` value POST /api/feedback wants for a cost factor — the
 * factor's full dotted Breakdown path. `factorKey` is the formula/field key
 * (e.g. "driver_eur"). Returns null for keys with no mapping (aggregates or
 * non-cost factors), so the caller can withhold submission.
 */
export function resolveFactorSubCategory(factorKey: string): string | null {
  return FACTOR_SUB_CATEGORY[factorKey] ?? null
}

/** Split "…text. Unit: €/h" into the description text and the unit token. */
function splitUnit(desc: string | undefined): { text: string; unit: string } {
  if (!desc) return { text: '', unit: '' }
  const m = desc.match(/\s*Unit:\s*(.+?)\.?\s*$/)
  if (!m) return { text: desc.trim(), unit: '' }
  return { text: desc.slice(0, m.index).trim(), unit: m[1].trim() }
}

/** Resolve distinct, in-order sources for a list of ids against a section map. */
function resolveSources(map: Record<string, ParamSource>, ids: (number | null)[]): ParamSource[] {
  const out: ParamSource[] = []
  const seen = new Set<number>()
  for (const id of ids) {
    if (id == null || seen.has(id)) continue
    seen.add(id)
    const s = map[String(id)]
    if (s) out.push(s)
  }
  return out
}

interface Ctx {
  input: EvaluationInput
  routeStops: { stop_id: string; name: string }[]
  usedCountries: string[]
  usedComps: CompositionParam[]
  usedOps: OperatorParam[]
}

function buildCtx(input: EvaluationInput, routeStops: { stop_id: string; name: string }[]): Ctx {
  const usedCountries = input.route.track_infrastructure.map((t) => t.country_code)
  const usedCompIds = new Set(input.route.trip_pairs.map((tp) => tp.composition_id))
  const usedComps = input.parameters.compositions.compositions.filter((c) =>
    usedCompIds.has(c.comp_id),
  )
  const usedOpIds = new Set(usedComps.map((c) => c.operator_id))
  const usedOps = input.parameters.compositions.operators.filter((o) =>
    usedOpIds.has(o.operator_id),
  )
  return { input, routeStops, usedCountries, usedComps, usedOps }
}

/** One row per used operator. */
function opRows(
  id: string,
  descKey: string,
  get: (o: OperatorParam) => number,
  ctx: Ctx,
): RateRow[] {
  const comp = ctx.input.parameters.compositions
  const { text, unit } = splitUnit(comp.descriptions.operators[descKey])
  return ctx.usedOps.map((op) => ({
    id,
    scope: ctx.usedOps.length > 1 ? op.operator_name : null,
    value: get(op),
    unit,
    description: text,
    isDefault: false,
    sources: resolveSources(comp.sources, op.source_ids),
  }))
}

/** One row per (used operator × class) for the per-class service cost. */
function svcRows(ctx: Ctx): RateRow[] {
  const comp = ctx.input.parameters.compositions
  const { text, unit } = splitUnit(comp.descriptions.operators['cost_per_class'])
  return ctx.usedOps.flatMap((op) =>
    Object.entries(op.cost_per_class).map(([cls, value]) => ({
      id: 'svc_place',
      scope: cls,
      value,
      unit,
      description: text,
      isDefault: false,
      sources: resolveSources(comp.sources, op.source_ids),
    })),
  )
}

/** One row per used composition. */
function compRows(
  id: string,
  section: 'fixed_costs' | 'variable_km',
  descKey: string,
  get: (c: CompositionParam) => number,
  ctx: Ctx,
): RateRow[] {
  const comp = ctx.input.parameters.compositions
  const { text, unit } = splitUnit(comp.descriptions.compositions[section]?.[descKey])
  return ctx.usedComps.map((c) => ({
    id,
    scope: ctx.usedComps.length > 1 ? c.comp_id : null,
    value: get(c),
    unit,
    description: text,
    isDefault: false,
    sources: resolveSources(comp.sources, c.source_ids),
  }))
}

/** One row per country the route runs through, in route order. */
function trackRows(
  id: string,
  fieldKey: keyof Pick<
    TrackInfraParam,
    'tac_eur_train_km' | 'parking_eur_day' | 'shunting_eur_event' | 'energy_price_eur_kwh'
  >,
  ctx: Ctx,
): RateRow[] {
  const track = ctx.input.parameters.track_infrastructures
  const { text, unit } = splitUnit(track.descriptions.fields[fieldKey])
  const rows: RateRow[] = []
  for (const cc of ctx.usedCountries) {
    const t = track.track_infrastructures.find((x) => x.country_code === cc)
    if (!t) continue
    const f = t[fieldKey]
    rows.push({
      id,
      scope: cc,
      value: f.value,
      unit,
      description: text,
      isDefault: f.is_default,
      sources: resolveSources(track.sources, [f.source_id]),
    })
  }
  return rows
}

/** One row per stop on the route, in route order. */
function stopRows(ctx: Ctx): RateRow[] {
  const stopSec = ctx.input.parameters.stop_infrastructures
  const { text, unit } = splitUnit(stopSec.descriptions.fields['stop_charge_eur'])
  const byId = new Map(stopSec.stops.map((s) => [s.stop_id, s]))
  const rows: RateRow[] = []
  for (const rs of ctx.routeStops) {
    const s = byId.get(rs.stop_id)
    if (!s) continue
    const f = s.stop_charge_eur
    rows.push({
      id: 'stop_charge',
      scope: s.name,
      value: f.value,
      unit,
      description: text,
      isDefault: f.is_default,
      sources: resolveSources(stopSec.sources, [f.source_id]),
    })
  }
  return rows
}

function resolveRate(rateId: string, ctx: Ctx): RateRow[] {
  switch (rateId) {
    case 'driver_rate':
      return opRows('driver_rate', 'driver_costs_eur_h', (o) => o.driver_costs_eur_h, ctx)
    case 'crew_rate':
      return opRows('crew_rate', 'crew_costs_eur_h', (o) => o.crew_costs_eur_h, ctx)
    case 'loco_lease_h':
      return opRows(
        'loco_lease_h',
        'loco_full_service_lease_eur_h',
        (o) => o.loco_full_service_lease_eur_h,
        ctx,
      )
    case 'var_overhead_quota':
      return opRows('var_overhead_quota', 'var_overhead_per', (o) => o.var_overhead_per, ctx)
    case 'financing_quota':
      return opRows('financing_quota', 'financing_quota_per', (o) => o.financing_quota_per, ctx)
    case 'fix_overhead_quota':
      return opRows(
        'fix_overhead_quota',
        'fix_overhead_quota_per',
        (o) => o.fix_overhead_quota_per,
        ctx,
      )
    case 'svc_place':
      return svcRows(ctx)
    case 'coach_maint_km':
      return compRows(
        'coach_maint_km',
        'variable_km',
        'coach_maint_eur_km',
        (c) => c.variable_km.coach_maint_eur_km,
        ctx,
      )
    case 'coach_purchase':
      return compRows(
        'coach_purchase',
        'fixed_costs',
        'purchase_coach_eur',
        (c) => c.fixed_costs.purchase_coach_eur,
        ctx,
      )
    case 'coach_amort_years':
      return compRows(
        'coach_amort_years',
        'fixed_costs',
        'coach_amort_years',
        (c) => c.fixed_costs.coach_amort_years,
        ctx,
      )
    case 'cleaning_day':
      return compRows(
        'cleaning_day',
        'fixed_costs',
        'cleaning_services_eur_day',
        (c) => c.fixed_costs.cleaning_services_eur_day,
        ctx,
      )
    case 'tac_km':
      return trackRows('tac_km', 'tac_eur_train_km', ctx)
    case 'energy_kwh':
      return trackRows('energy_kwh', 'energy_price_eur_kwh', ctx)
    case 'parking_day':
      return trackRows('parking_day', 'parking_eur_day', ctx)
    case 'shunting_event':
      return trackRows('shunting_event', 'shunting_eur_event', ctx)
    case 'stop_charge':
      return stopRows(ctx)
    default:
      return []
  }
}

/**
 * Ordered per-unit rates for a cost factor, as they appear in its formula.
 * `factorKey` is the formula/field key (e.g. "driver_eur"). Returns [] for
 * factors with no associated rates (aggregates/totals) — the popover then
 * shows just the title, explanation and formula.
 */
export function resolveFactorRates(
  factorKey: string,
  input: EvaluationInput,
  routeStops: { stop_id: string; name: string }[],
): RateRow[] {
  const rateIds = FACTOR_RATES[factorKey]
  if (!rateIds) return []
  const ctx = buildCtx(input, routeStops)
  return rateIds.flatMap((id) => resolveRate(id, ctx))
}
