export interface Stop {
  stop_id: string
  name: string
  country_code: string
  lat: number
  lon: number
  stop_charge_eur: { value: number; is_default: boolean }
}

export interface Composition {
  comp_id: string
  description: string
  operator_id: string
  routing: {
    max_speed_kmh: number
    total_weight_t: number
    total_length_m: number
    n_locos: number
    hsr_allowed: boolean
  }
  // Redesigned 2026-07-22: totals + full-composition average densities
  // (service areas included) + per-class_main entries with derived
  // densities from real section geometry.
  capacity: {
    total_places: number
    avg_density_length_m_per_place: number
    avg_density_weight_t_per_place: number
    by_class: Record<
      string,
      {
        places: number
        density_length_m_per_place: number
        density_weight_t_per_place: number
      }
    >
  }
}

export interface StopsResponse {
  stops: Stop[]
}

export interface CompositionsResponse {
  compositions: Composition[]
  operators: unknown[]
  // All service classes grouped by class_main; class_id =
  // "<coach_type_id> - <section label>".
  classes: Record<string, { class_id: string; coach_type_id: string; places: number }[]>
  // All coach types keyed by coach_type_id, referenced from
  // compositions' coaches.list and carrying class_ids into "classes".
  coach_types: Record<
    string,
    {
      length_m: number
      length_wo_service_m: number
      weight_gross_t: number
      weight_wo_service_t: number
      crew_factor: number
      places_total: number
      equipment: Record<string, boolean>
      class_ids: string[]
      remarks: string
    }
  >
}

// --- POST /api/evaluation/calc ----------------------------------------------
// Response shapes as produced by backend/api/helpers/evaluation_serialize.py.
// The response is a cube: view (grouping) × filter selection (drill-down keys)
// × normalisation (unit) → one Breakdown per cell.

export const VIEW_KEYS = [
  'route',
  'per_trip_pair',
  'per_trip_pair_per_country',
  'per_trip_pair_per_od',
  'per_trip_per_stop',
] as const
export type ViewKey = (typeof VIEW_KEYS)[number]

// Normalisations (CALC 0.9.9): class_main is an orthogonal axis on EVERY
// normalisation — each norm maps to {"all" | class_main: Breakdown}.
// "all" is the whole cell; class cells are its allocation split. The former
// by_class_main norm is retired (identical to per_year's class cells).
export const NORM_KEYS = [
  'per_year',
  'per_operating_day',
  'per_train_km', // renamed from per_trip_km (CALC 0.9.4)
  'per_available_place_km',
  'per_sold_place_km',
] as const
export type NormKey = (typeof NORM_KEYS)[number]

export type ClassKeyedBreakdowns = Record<string, Breakdown>

export interface BreakdownOperatorVariable {
  driver_eur: number
  crew_eur: number
  coach_maintenance_eur: number
  loco_eur: number
  svc_stockings_eur: number
  var_overhead_eur: number
  total_eur: number
}

export interface BreakdownOperatorFixed {
  coach_amortisation_eur: number
  financing_eur: number
  fix_overhead_eur: number
  cleaning_eur: number
  shunting_eur: number
  total_eur: number
}

export interface BreakdownInfrastructure {
  tac_eur: number
  energy_eur: number
  station_charge_eur: number
  parking_eur: number
  total_eur: number
}

export interface Breakdown {
  cost: {
    operator: {
      variable: BreakdownOperatorVariable
      fixed: BreakdownOperatorFixed
      total_eur: number
    }
    infrastructure: BreakdownInfrastructure
    total_eur: number
  }
  revenue: { ticket_revenue_eur: number; total_eur: number }
  margin: { ebit_margin_eur: number; total_eur: number }
  total_cost_eur: number
  total_revenue_eur: number
  net_eur: number
}

/** All normalisations of one cell (CALC 0.9.9): each norm is a dict keyed
 *  by class_main plus "all". "all" = the whole cell; class cells = its
 *  allocation split. Classes without capacity (available) or sales (sold)
 *  are omitted from the two place-km norms; "all" is omitted from
 *  per_sold when the cell has no sold place-km at all. */
export type Normalisations = Record<NormKey, ClassKeyedBreakdowns>

/** One filtered data point: human-readable filter labels (one entry per
 *  dimension, backend-provided) alongside the values. */
export interface FilteredCell {
  filter: Record<string, string>
  values: Normalisations
}

export interface NormalisationDoc {
  description: string
  processing_sequence: string[]
}

export interface EvaluationView<TData> {
  description: string
  normalisations: Record<string, NormalisationDoc>
  data: TData
}

export interface EvaluationViews {
  route: EvaluationView<Normalisations>
  per_trip_pair: EvaluationView<Record<string, FilteredCell>>
  per_trip_pair_per_country: EvaluationView<Record<string, Record<string, FilteredCell>>>
  per_trip_pair_per_od: EvaluationView<Record<string, Record<string, FilteredCell>>>
  per_trip_pair_per_section: EvaluationView<Record<string, Record<string, FilteredCell>>>
  per_trip_per_stop: EvaluationView<Record<string, Record<string, FilteredCell>>>
}

// --- models.* : per-model version + LaTeX formula registry ------------------
// Backend: api/helpers/evaluation_serialize.py::models_to_dict(). We only read
// models.evaluation.formulas (keyed by the cost-factor field name, e.g.
// "driver_eur") for the cost-factor detail popover; the other sections are
// typed for completeness but unused.

/** One cost-factor formula: a KaTeX-compatible LaTeX string plus a
 *  plain-English description. Both are backend-provided and shown as-is. */
export interface Formula {
  latex: string
  description: string
}

/** Formula registry keyed by cost-factor field name (e.g. "driver_eur"). */
export type FormulaMap = Record<string, Formula>

export interface EvaluationModelSection {
  version: string
  description: string
  formulas: FormulaMap
}

export interface EvaluationModels {
  route_builder: EvaluationModelSection
  energy: EvaluationModelSection
  evaluation: EvaluationModelSection
}

// --- input.parameters : the per-unit rates actually loaded to cost this route
// Backend: api/helpers/params_serialize.py (reused by input_to_dict()). Each
// section lists EVERY loaded entity (all countries/stops/compositions), so the
// popover scopes rates to the entities the route actually uses — see
// src/lib/costFactorRates.ts.

/** A referenced data source, keyed by source_id inside each section's
 *  `sources` map. */
export interface ParamSource {
  source_id: number
  source_description: string | null
  source_url: string | null
  source_date: string | null
}

/** A versioned, sourced scalar parameter (track/stop infrastructure fields). */
export interface ParamField<T = number> {
  value: T
  is_default: boolean
  version: number | null
  source_id: number | null
}

/** track_infrastructures[] — one per country. Only the rate fields the
 *  popover reads are typed. */
export interface TrackInfraParam {
  country_code: string
  tac_eur_train_km: ParamField
  parking_eur_day: ParamField
  shunting_eur_event: ParamField
  energy_price_eur_kwh: ParamField
}

/** stops[] — one per stop. */
export interface StopInfraParam {
  stop_id: string
  name: string
  country_code: string
  stop_charge_eur: ParamField
}

/** compositions[] — composition-level rates are plain numbers (sourced at the
 *  entity level via source_ids, not per field). */
export interface CompositionParam {
  comp_id: string
  operator_id: string
  fixed_costs: {
    purchase_coach_eur: number
    coach_amort_years: number
    cleaning_services_eur_day: number
  }
  variable_km: {
    coach_maint_eur_km: number
  }
  source_ids: number[]
}

/** operators[] — operator-level rates, sourced at the entity level. */
export interface OperatorParam {
  operator_id: string
  operator_name: string
  driver_costs_eur_h: number
  crew_costs_eur_h: number
  var_overhead_per: number
  financing_quota_per: number
  fix_overhead_quota_per: number
  loco_full_service_lease_eur_h: number
  cost_per_class: Record<string, number>
  source_ids: number[]
}

/** Flat {field: description} documentation carried by track/stop sections.
 *  Each description embeds a trailing "Unit: …" the popover parses out. */
export interface FieldDescriptions {
  table?: string
  fields: Record<string, string>
}

export interface TrackInfraSection {
  descriptions: FieldDescriptions
  sources: Record<string, ParamSource>
  track_infrastructures: TrackInfraParam[]
}

export interface StopInfraSection {
  descriptions: FieldDescriptions
  sources: Record<string, ParamSource>
  stops: StopInfraParam[]
}

export interface CompositionsSection {
  // Nested documentation: descriptions.compositions[section][field] and
  // descriptions.operators[field].
  descriptions: {
    compositions: Record<string, Record<string, string>>
    operators: Record<string, string>
  }
  sources: Record<string, ParamSource>
  compositions: CompositionParam[]
  operators: OperatorParam[]
}

export interface EvaluationParameters {
  track_infrastructures: TrackInfraSection
  stop_infrastructures: StopInfraSection
  compositions: CompositionsSection
}

/** The subset of the posted route we read to scope rates to the entities the
 *  route actually uses (countries it runs through, composition per trip pair). */
export interface EvaluationInputRoute {
  track_infrastructure: { country_code: string }[]
  trip_pairs: { composition_id: string }[]
}

export interface EvaluationInput {
  route: EvaluationInputRoute
  parameters: EvaluationParameters
}

export interface EvaluationResponse {
  calc_version: string
  route_id: string
  models: EvaluationModels
  input: EvaluationInput
  views: EvaluationViews
}

// The geographic scope currently selected in the evaluation panel — emitted so
// the map can highlight the matching part of the route and dim the rest.
// 'all' = whole route (nothing dimmed).
export type MapScope =
  | { kind: 'all' }
  | { kind: 'country'; country: string }
  | { kind: 'od'; originStopId: string; destinationStopId: string }
  | { kind: 'stop'; stopId: string }
