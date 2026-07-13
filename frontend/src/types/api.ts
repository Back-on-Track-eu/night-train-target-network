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
  routing: { max_speed_kmh: number; total_weight_t: number; hsr_allowed: boolean }
  capacity: Record<string, { places: number; density: number }>
}

export interface StopsResponse {
  stops: Stop[]
}

export interface CompositionsResponse {
  compositions: Composition[]
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

export const NORM_KEYS = [
  'per_year',
  'per_operating_day',
  'per_trip_km',
  'per_available_place_km',
  'per_sold_place_km',
] as const
export type NormKey = (typeof NORM_KEYS)[number]

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

/** All five normalisations of one Breakdown. */
export type Normalisations = Record<NormKey, Breakdown>

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
  per_trip_per_stop: EvaluationView<Record<string, Record<string, FilteredCell>>>
}

export interface EvaluationResponse {
  calc_version: string
  route_id: string
  // Not rendered by the panel yet — kept loosely typed until they are.
  models: Record<string, unknown>
  input: Record<string, unknown>
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
