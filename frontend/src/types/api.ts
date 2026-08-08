export interface Stop {
  stop_id: string
  name: string
  country_code: string
  lat: number
  lon: number
  stop_charge_eur: { value: number; is_default: boolean }
}

export interface Composition {
  composition_id: string
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

// One candidate stop along the routed path, returned by POST
// /api/proposal/calc only when auto_stop_addition="suggest". added_time_min is
// the full trip-time increase (detour + dwell) the stop would cost if added.
export interface SuggestedStop {
  stop_id: string
  stop_name: string
  country_code: string
  lat: number
  lon: number
  added_time_min: number
}

// A scenario is a named snapshot of infrastructure parameters (track-access
// charges, energy prices, terrain, per-stop charges, hsr_allowed). It pins one
// version each of four DB tables; routing-relevant data lives in the two
// `track_*` versions, cost-only data in the `stop_*` versions.
export interface Scenario {
  scenario_id: number
  scenario_key: string
  scenario_name: string
  description: string | null
  change_log: string | null
  editor: string | null
  created_at: string
  is_current_base: boolean
  is_current_scenario: boolean
  track_infrastructures_version: number
  track_infrastructure_defaults_version: number
  stop_infrastructures_version: number
  stop_infrastructure_defaults_version: number
}

interface ScenarioGroup {
  count: number
  scenarios: Scenario[]
}

export interface ScenariosResponse {
  current_base: ScenarioGroup
  current_scenarios: ScenarioGroup
  historical_scenarios: ScenarioGroup
  total_count: number
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

// --- POST /api/proposal/calc : "evaluation" block ---------------------------
// Response shapes as produced by backend/api/helpers/evaluation_serialize.py,
// carried under the merged calc response's "evaluation" key (see
// ProposalCalcResponse below). The evaluation is a cube: view (grouping) ×
// filter selection (drill-down keys) × normalisation (unit) → one Breakdown
// per cell.

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
  composition_id: string
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

/** The subset of the route we read to scope rates to the entities the route
 *  actually uses (countries it runs through, composition per trip pair). The
 *  merged calc response carries the route once, as a top-level sibling of
 *  "evaluation" — ProposalViewport re-attaches it here when assembling the
 *  EvaluationResponse the panel renders. */
export interface EvaluationInputRoute {
  track_infrastructure: { country_code: string }[]
  trip_pairs: { composition_id: string }[]
}

export interface EvaluationInput {
  route: EvaluationInputRoute
  parameters: EvaluationParameters
}

// Panel-facing evaluation bundle. Not a wire shape: ProposalViewport assembles
// it from one ProposalCalcResponse (calc_version and route_id lifted from the
// top level / route, input.route re-attached from the response's route key).
export interface EvaluationResponse {
  calc_version: string
  route_id: string
  models: EvaluationModels
  input: EvaluationInput
  views: EvaluationViews
}

// --- POST /api/proposal/calc : full wire response ----------------------------
// The merged compute endpoint (route + evaluation in one stateless call,
// PROPOSALS_DESIGN.md §2.1). TRoute stays generic — the route shape is typed
// where it is consumed (ProposalViewport's BackendRoute), only the fields the
// frontend reads.
export interface ProposalCalcResponse<TRoute = unknown> {
  route_builder_version: string
  calc_version: string
  route_fingerprint: string
  // True when served from the server-side compute cache.
  cache_hit: boolean
  // Resolved request echo — defaults applied, scenario_id concrete.
  request: Record<string, unknown>
  // Only present when the request used auto_stop_addition="suggest".
  suggested_stops?: SuggestedStop[]
  // Gallery KPI summary — not consumed by the proposal builder.
  summary: Record<string, unknown>
  route: TRoute
  evaluation: {
    models: EvaluationModels
    input: { parameters: EvaluationParameters }
    views: EvaluationViews
  }
}

// The geographic scope currently selected in the evaluation panel — emitted so
// the map can highlight the matching part of the route and dim the rest.
// 'all' = whole route (nothing dimmed).
export type MapScope =
  | { kind: 'all' }
  | { kind: 'country'; country: string }
  | { kind: 'od'; originStopId: string; destinationStopId: string }
  | { kind: 'stop'; stopId: string }

// --- POST /api/auth/guest ---------------------------------------------------
// Backend: api/auth.py::guest(). Anonymous session — a real identity server-side
// (guest tokens expire after 30 days). We only keep the token to attach as a
// Bearer on the persist-on-calc endpoints; the other fields are informational.
export interface GuestSessionResponse {
  token: string
  user_id: number
  display_name: string
  is_guest: boolean
}

// --- POST /api/proposals ----------------------------------------------------
// Backend: api/proposals.py + api/helpers/proposal_serialize.py. Read-only list
// of saved proposals (every user sees every proposal). Filtering/sorting is done
// server-side; the four financial fields are null for proposals saved without an
// evaluation snapshot.

// One proposal, as produced by proposal_summary_to_dict(). snake_case mirrors
// the backend JSON verbatim.
export interface ProposalSummary {
  proposal_id: number
  proposal_version: number
  is_current: boolean
  user_id: number
  user_name: string | null
  change_log: string | null
  created_at: string
  name: string
  total_distance_km: number
  total_driving_time_h: number
  total_time_h: number
  countries: string[]
  stops: { stop_id: string; stop_name: string }[]
  total_revenue_eur: number | null
  total_cost_eur: number | null
  margin_eur: number | null
  margin_per: number | null
}

// Sortable keys accepted by the backend (SORT_KEYS in proposal_serialize.py).
// Note margin_per is deliberately NOT sortable server-side.
export const PROPOSAL_SORT_KEYS = [
  'created_at',
  'total_distance_km',
  'total_time_h',
  'total_revenue_eur',
  'total_cost_eur',
  'margin_eur',
] as const
export type ProposalSortKey = (typeof PROPOSAL_SORT_KEYS)[number]

export interface ProposalSort {
  by: ProposalSortKey
  dir: 'asc' | 'desc'
}

// All filter keys are OR / any-match server-side.
export interface ProposalsFilter {
  user_ids?: number[]
  countries?: string[]
  stop_ids?: string[]
}

export interface ProposalsRequest {
  filter?: ProposalsFilter
  sort?: ProposalSort[]
  limit?: number
  offset?: number
}

export interface ProposalsResponse {
  // Count after filtering, before pagination — what infinite scroll compares
  // loaded length against.
  total: number
  proposals: ProposalSummary[]
}

// --- GET /api/proposal/<id> -------------------------------------------------
// The full stored envelopes. The gallery map only needs the route geometry and
// the endpoint stops, so we type just those fields (the route object carries
// much more — see backend/api/route.py).
export interface ProposalRouteStopPoint {
  stop_id: string
  stop_name: string
  lat: number
  lon: number
}

export interface ProposalDetailResponse {
  route_body: {
    route: {
      geometries: { id: string; coords: [number, number][] }[]
      trip_pairs: {
        outbound: {
          segments: {
            from_stop: ProposalRouteStopPoint
            to_stop: ProposalRouteStopPoint
            // Country codes in the order the segment traverses them.
            country_distance_shares: Record<string, number>
          }[]
        }
      }[]
    }
  }
  evaluation_body: unknown | null
}

// A proposal reduced to what the gallery map draws: its routed line geometry
// (one entry per stored geometry leg) and endpoint stops for markers.
export interface GalleryMapRoute {
  key: string
  lines: [number, number][][]
  stops: { lat: number; lon: number; name: string }[]
}
