/** Localized names keyed by language code (en/de/fr/nl/it/es/pl —
 *  backend db/schema.py STOP_NAME_LANGS). */
export type LocalizedNames = Record<string, string>

export interface StopCity {
  name: string
  osm_id: number | null
  names: LocalizedNames
}

export interface Stop {
  stop_id: string
  name: string
  country_code: string
  lat: number
  lon: number
  stop_charge_eur: { value: number; is_default: boolean }
  /** Catalog provenance category, e.g. "existing night train stop". */
  provenance: string
  name_latin: string
  name_ascii: string
  uic_ref: string | null
  /** null for rural halts beyond any city/town radius. */
  city: StopCity | null
  country_names: LocalizedNames
  /** Night-train-capable gauges (>= 1435 mm); null = unknown. */
  gauges_mm: number[] | null
  gauge_evidence: string | null
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
  // "By route section" — backed by the backend's physical-section view
  // (per_trip_pair_per_section), NOT the OD ticket-relation view. The section
  // cells are pre-aggregated and normalised against their own section physics,
  // so the panel reads them straight (no client-side summing). The OD view is
  // still served (per_trip_pair_per_od on EvaluationViews) but no longer shown
  // as a tab.
  'per_trip_pair_per_section',
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

/** A trip filter value — a single direction of a trip pair. The frontend
 *  composes "origin → destination (localised direction)". */
export interface TripFilterValue {
  origin: string
  destination: string
  direction: 'outbound' | 'return'
}

/** An OD / section filter value — origin, destination and the accommodation
 *  class (class_main may be "all"). The frontend composes
 *  "origin → destination (localised class)". */
export interface ClassFilterValue {
  origin: string
  destination: string
  class_main: string
}

/** One filter dimension value. Proper-noun dimensions (trip_pair, stop,
 *  country code, class_main code) stay plain strings — the frontend localises
 *  country codes / class codes itself; the translatable ones (trip direction,
 *  OD/section class) arrive structured so the frontend can compose + translate.
 *  "all" wildcard cells send the literal string "all". */
export type FilterValue = string | TripFilterValue | ClassFilterValue

/** One filtered data point: per-dimension filter values (backend-provided)
 *  alongside the values. See FilterValue for why some are structured. */
export interface FilteredCell {
  filter: Record<string, FilterValue>
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

/** stops[] — one per stop. Enrichment fields are plain values (no
 *  ParamField wrapper — nothing resolves against defaults). */
export interface StopInfraParam {
  stop_id: string
  name: string
  country_code: string
  stop_charge_eur: ParamField
  provenance: string
  name_latin: string
  name_ascii: string
  uic_ref: string | null
  city: StopCity | null
  country_names: LocalizedNames
  gauges_mm: number[] | null
  gauge_evidence: string | null
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
// Gallery KPI summary block of the calc response. Only co2_savings_t_per_year
// is read by the builder (the auth gate); the rest passes through untyped.
export interface ProposalCalcSummary {
  co2_savings_t_per_year: number | null
  // Demand & modal-shift KPIs — route-level, annual. PLACEHOLDER values
  // (deterministic fakes derived from route metrics) until models/demand/
  // lands; demand_kpis_placeholder stays true, so the UI must present these as
  // estimates. Source: backend models/evaluation/summary.py.
  demand_trips_per_year?: number
  shift_air_trips_per_year?: number
  shift_air_trip_km_per_year?: number
  shift_car_trips_per_year?: number
  shift_car_trip_km_per_year?: number
  subsidy_eur_per_t_co2?: number | null
  co2_g_per_pax_km?: number
  demand_kpis_placeholder?: boolean
  [key: string]: unknown
}

export interface ProposalCalcResponse<TRoute = unknown> {
  route_builder_version: string
  calc_version: string
  route_fingerprint: string
  // True when served from the server-side compute cache. Only present on a
  // fresh calc — a proposal hydrated from GET /api/proposal/<id> (same shape,
  // reused by ProposalViewport's applyPlan()) has no cache concept.
  cache_hit?: boolean
  // Resolved request echo — defaults applied, scenario_id concrete.
  request: Record<string, unknown>
  // Only present when the request used auto_stop_addition="suggest".
  suggested_stops?: SuggestedStop[]
  // Gallery KPI summary — read by the auth gate (co2_savings_t_per_year) and
  // the EvaluationPanel's demand/modal-shift box. Also returned by GET
  // /api/proposal/<id> (see ProposalDetailResponse), so a loaded proposal
  // populates the same box.
  summary?: ProposalCalcSummary
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

// --- POST /api/auth/verify --------------------------------------------------
// Backend: api/auth.py::verify(). OTP -> JWT. `merged_guest` is non-null when a
// guest token was sent as the Bearer and that guest's work was reassigned to the
// account (the guest→account merge).
export interface VerifyResponse {
  token: string
  user_id: number
  display_name: string
  is_guest: false
  merged_guest: null | {
    guest_user_id: number
    proposals_claimed: number
    feedback_claimed: number
    likes_claimed: number
    comments_claimed: number
  }
}

// verify's alternate 200: a first-time (never-verified) account must pick a
// display name as a second step, after the code. The code is left unconsumed,
// so the client re-submits the same code together with the chosen name.
export interface VerifyNeedsNameResponse {
  needs_display_name: true
}

// The persisted auth cookie payload (lib/authCookie.ts). Not a wire shape —
// assembled from a guest or verify response and read back on boot.
export interface StoredAuth {
  token: string
  is_guest: boolean
  display_name: string
  user_id: number
}

// --- POST /api/proposals ----------------------------------------------------
// Backend: api/proposals.py + api/helpers/proposal_serialize.py::summary_row_to_dict().
// Read-only gallery list (every user sees every row). Rows are a mix of two
// shapes discriminated by `source` (WP10 step 6b): "proposal" (a saved
// user proposal, with financial/demand/engagement KPIs) and "existing" (a
// real night train from the ONTD catalog — a reduced descriptive shape, no
// financials). Financial/demand KPIs are per-train-km and null when a
// proposal was saved without an evaluation snapshot.

// Fields shared by both source shapes.
interface ProposalSummaryShared {
  name: string
  composition_id: string
  total_distance_km: number
  total_time_h: number
  avg_speed_kmh: number
  n_stops: number
  // countries alphabetical; stop_ids in travel order ([0] = origin, last =
  // destination — backend models/evaluation/summary.py::ordered_stops()).
  countries: string[]
  stop_ids: string[]
  co2_g_per_pax_km: number | null
}

// source === "proposal": a saved user proposal.
export interface ProposalSummaryProposal extends ProposalSummaryShared {
  source: 'proposal'
  proposal_id: number
  proposal_version: number
  user_id: number
  route_fingerprint: string
  scenario_id: number
  route_builder_version: string
  calc_version: string
  // Financial KPIs, per train-km; null without an evaluation snapshot.
  cost_eur_per_train_km: number | null
  revenue_eur_per_train_km: number | null
  margin_eur_per_train_km: number | null
  subsidy_eur_per_year: number | null
  demand_trips_per_year: number | null
  demand_trip_km_per_year: number | null
  shift_air_trips_per_year: number | null
  shift_air_trip_km_per_year: number | null
  shift_car_trips_per_year: number | null
  shift_car_trip_km_per_year: number | null
  co2_savings_t_per_year: number | null
  subsidy_eur_per_t_co2: number | null
  demand_kpis_placeholder: unknown
  likes_count: number
  comments_count: number
  // Proposer identity, live-joined from admin.users. is_guest is derived
  // server-side from the reserved "guest_" display-name prefix; the card
  // shows a generic "Guest" label instead of the raw guest_… name.
  display_name: string
  is_guest: boolean
  created_at: string
  updated_at: string
}

// source === "existing": a real night train from the ONTD catalog. Reduced
// shape — proposal-only fields (financials, demand, engagement, versions,
// timestamps, proposal/user ids) are omitted rather than null-padded.
export interface ProposalSummaryExisting extends ProposalSummaryShared {
  source: 'existing'
  route_id: string
  // Whether the drawn line is real routing or a straight-line fallback.
  geometry_routed: boolean
  ontd_url: string
}

export type ProposalSummary = ProposalSummaryProposal | ProposalSummaryExisting

// Sortable keys accepted by the backend, restricted to the subset the gallery
// UI offers. Validated server-side against filter_builder.py's
// SORTABLE_COLUMNS; an unlisted column 400s.
export const PROPOSAL_SORT_KEYS = [
  'created_at',
  'total_distance_km',
  'total_time_h',
  'margin_eur_per_train_km',
  'revenue_eur_per_train_km',
  'cost_eur_per_train_km',
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
  /** Which UNION branch(es) the gallery is built from: 'proposal' =
   *  proposals.proposal_summaries, 'existing' = the ONTD catalog's
   *  ontd.route_summaries (see adapters/proposal/filter_builder.py,
   *  SUPPORTED_SOURCES). Omitted means BOTH — the backend default. Sending
   *  ['proposal'] compiles to a query that never touches the ontd schema. */
  sources?: ProposalSourceKind[]
}

/** The two gallery row kinds. Mirrors SUPPORTED_SOURCES on the backend. */
export type ProposalSourceKind = 'proposal' | 'existing'

export interface ProposalsRequest {
  filter?: ProposalsFilter
  sort?: ProposalSort[]
  limit?: number
  offset?: number
}

// The `summaries` section of the sectioned list response (default `include`).
export interface ProposalsSummariesSection {
  // Count after filtering, before pagination — what infinite scroll compares
  // loaded length against.
  total: number
  proposals: ProposalSummary[]
}

// POST /api/proposals returns a SECTIONED response (proposals.py::_list_response):
// each key is present only if named in the request's `include` (default
// ["summaries"]). The gallery requests summaries only.
export interface ProposalsResponse {
  summaries?: ProposalsSummariesSection
}

// --- POST /api/proposal/publish ---------------------------------------------
// Backend: api/proposal_publish.py (@require_auth, guest token is enough). The
// server RECOMPUTES from compute_request — never send the route/evaluation. A
// non-base scenario_id 422s, so publish sends scenario_id: null. There is no
// dedup: mode "new" always creates a proposal; the returned proposal_id is then
// adopted so later saves "overwrite" it.
export interface PublishRequest {
  mode: 'new' | 'overwrite'
  // Non-empty (backend rejects blank). Auto-derived "Origin – Destination".
  name: string
  // The resolved `request` echo from a /calc response (with scenario_id nulled).
  compute_request: Record<string, unknown>
  // Required for mode "overwrite" (the owned proposal to replace); omitted for "new".
  proposal_id?: number
  based_on_proposal_id?: number
}

// The published proposal, full shape mirrors GET /api/proposal/<id>. Only the
// fields the frontend consumes are typed here.
export interface PublishResponse {
  proposal_id: number
  proposal_version: number
  name: string
}

// POST/DELETE /api/proposal/<id>/like — both return the resulting state
// directly (no need to compute the toggle client-side).
export interface LikeResponse {
  count: number
  liked_by_me: boolean
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

// The gallery map only reads the route geometry and endpoint stops — this is
// the default TRoute for callers (like Gallery.vue) that don't need more.
// A caller needing the full route (ProposalViewport.vue, to reuse the same
// applyPlan() the calc endpoint feeds) passes its own richer route type as
// ProposalDetailResponse<TRoute> instead — the wire shape is identical to
// POST /api/proposal/calc's `route` either way (see proposal_serialize.py's
// proposal_to_response_dict docstring).
export interface GalleryRouteShape {
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

// GET /api/proposal/<id> — flat compute-response shape
// (proposal_serialize.py::proposal_to_response_dict): `route`/`evaluation` at
// the top level, plus proposal metadata (identical to POST
// /api/proposal/publish's response).
export interface ProposalDetailResponse<TRoute = GalleryRouteShape> {
  proposal_id: number
  proposal_version: number
  user_id: number | null
  user_name: string | null
  name: string
  created_at: string | null
  updated_at: string | null
  route_builder_version: string
  calc_version: string
  route_fingerprint: string
  request: Record<string, unknown>
  // §5.4 gallery KPIs (demand / modal shift / emissions) — recomputed from the
  // route + evaluation this response carries, so a loaded proposal shows the
  // same figures /calc did.
  summary?: ProposalCalcSummary
  route: TRoute
  evaluation: {
    models: EvaluationModels
    input: { parameters: EvaluationParameters }
    views: EvaluationViews
  }
}

// A proposal reduced to what the gallery map draws: its routed line geometry
// (one entry per stored geometry leg) and endpoint stops for markers.
export interface GalleryMapRoute {
  key: string
  lines: [number, number][][]
  stops: { lat: number; lon: number; name: string }[]
}
