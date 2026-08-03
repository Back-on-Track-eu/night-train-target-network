# Backend Test Suite

Integration test suite for the night-train-target-network backend. All tests
run against the **live Docker stack** (postgres + openrailrouting + api) —
there are no mocks.

**Related documentation:** endpoints under test —
[`../api/README.md`](../api/README.md) · backend dev workflow —
[`../DEVELOPMENT.md`](../DEVELOPMENT.md) · database seed the suite asserts
against — [`../db/README.md`](../db/README.md)

```bash
# 1. Start the stack
cd backend/docker && docker-compose up -d

# 2. Run tests (from backend/)
uv run --extra dev python -m pytest tests/ -v
```

## Layout

Files are numbered in dependency order — from Docker build-up to the APIs
built on top of it:

| Prefix | Layer |
|---|---|
| `test_01`–`test_04` | Stack build-up: containers → seeded DB → loader → versioning |
| `test_10`–`test_11` | Read-only params + scenarios APIs |
| `test_20` | Route-building content logic (via `POST /api/proposal/calc`) |
| `test_30` | Evaluation content logic (model-layer — `compute_evaluation_domain()`) |
| `test_35` | `POST /api/proposal/calc` — the merged compute endpoint (contract) |
| `test_36` | GTFS+sidecar round-trip (`adapters/proposal/gtfs_store.py`) — the write path `publish()` calls |
| `test_37` | Fingerprint + gallery-summary projection (`adapters/proposal/projection.py`) |
| `test_40` | End-to-end pipeline smoke |
| `test_50` | `POST /api/proposal/publish` + proposals list/load (the only write path) |
| `test_51` | Proposal engagement — likes + comments |
| `test_60` | Feedback API — submit/categories |
| `test_70`–`test_71` | Auth — integration (API + DB) and standalone units |

Content tests that need *controlled* demand (`test_30`, `test_40`) call
the model layer directly (`tests/helpers.py:compute_evaluation_domain()`),
since `POST /api/proposal/calc` deliberately offers no way to inject
custom demand into an already-built route — it always runs the stopgap
demand model (`models/demand/`) internally.

Shared code:

- **`conftest.py`** — DB/loader/scenario fixtures and the four **session-scoped
  route fixtures** (`route_berlin_wien`, `route_berlin_dresden_wien`,
  `route_berlin_zuerich_wien`, `route_copenhagen_stockholm` — built via
  `POST /api/proposal/calc`) plus `eval_standard` (model-layer, see below).
  Route builds are expensive (live OpenRailRouting) — tests that only
  *read* a route must reuse these instead of building their own.
- **`helpers.py`** — HTTP wrappers (`build_route` for `POST /api/proposal/calc`
  — route section only; `compute` for the same endpoint's full response;
  `publish` for `POST /api/proposal/publish`, the only write path),
  model-layer evaluation with controlled demand
  (`compute_evaluation_domain()` — reconstructs a route dict as a domain
  object via `route_from_dict()`, applies demand directly via
  `add_directional_domain_demand()`, and runs
  `models.pipeline.evaluate_and_build_views()`), route-JSON navigation
  (`all_trips`, `stop_times`, `country_km`, `trip_distance_km`,
  `operating_days`, …), and endpoint URL helpers (`likes_url`,
  `comments_url`). Everything is derived strictly from data present in the
  API responses — nothing is fabricated. `purge_saved_proposals` also
  unconditionally clears `proposals.likes`/`proposals.comments` (no
  permanent seed data lives there), so engagement tests can safely target
  the permanent seed proposal.

---

## test_01_stack_health.py — Docker stack build-up

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `test_api_health` | API process is up | `GET /api/health` | 200, `{"status": "ok"}` |
| `test_data_status_loaded` | DB loader initialised at startup | `GET /api/data/status` | 200, `loaded=True`, `loaded_at` set, no `error` |
| `test_openrailrouting_health` | Routing engine reachable | `GET :8989/health` (host port) | 200 |
| `test_unknown_endpoint_returns_json_404` | Global JSON error handler | `GET /api/does-not-exist` | 404 with `error=not_found` JSON body |
| `test_wrong_method_returns_json_405` | Global JSON error handler | `GET /api/proposal/calc` | 405 with `error=method_not_allowed` JSON body |
| `test_stub_endpoints_return_501` | Remaining stubs are honest | auth endpoints | every stub returns 501 |

## test_02_db_seed.py — Database seeding

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `test_schemas_exist` | All 4 project schemas created | `information_schema.schemata` | `admin`, `input_params`, `scenario`, `proposals` |
| `test_table_row_count` (parametrized ×20) | Every seeded table populated | `COUNT(*)` per table | count ≥ per-table minimum (e.g. `track_infrastructures` ≥ 56 = 2 snapshots × 28 countries) |
| `test_required_columns_not_null` (parametrized ×5) | Non-nullable columns intact | `COUNT(*) WHERE col IS NULL` | 0 NULLs |
| `test_composition_types_have_coaches` | No zero-capacity compositions | JOIN composition_types↔coaches | every composition has ≥ 1 coach |
| `test_coach_type_classes_have_places` | Positive place counts | coach_type_classes | no row with places ≤ 0 |
| `test_track_infra_one_row_per_country_at_pinned_version` | Exact-match resolution unambiguous | rows at base pinned version | exactly 1 row per country |
| `test_track_infrastructure_default_row_exists` | Default fallback row present | pinned defaults version | ≥ 1 row |
| `test_stop_infrastructure_global_default_exists` | Global stop default present | pinned version, `country_code IS NULL` | ≥ 1 row |
| `test_country_geometries_seeded` | PostGIS borders for every stop country | `country_geom IS NULL` per stop country | no missing geometries |
| `test_exactly_one_current_base_scenario` | Base scenario uniqueness | `scenario.scenarios` | exactly 1 `is_current_base` |
| `test_historical_scenario_pins_version_1` | Historical lineage owns its own snapshot | 2026-baseline vs base rows | all four table versions = 1, differ from base |
| `test_hsr_scenario_pins_version_3` | HSR lineage owns its own snapshot | HSR-allowed vs base rows | all four table versions = 3, differ from base |
| `test_stop_infrastructure_values_unchanged_by_hsr_scenario` | Stop charges independent of HSR policy | `stop_infrastructures` at base vs HSR version | identical values despite different version numbers |

## test_03_loader.py — DBDataLoader correctness

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `test_column_exists_in_schema` (parametrized ×50) | SQL schema contains every column the loader reads (static, no live DB round-trip) | parsed `db/dev/sql/*.sql` | every (table, column) pair present |
| `test_all_compositions_load` | Full composition load succeeds | `build_all_compositions()` | exactly the 8 calibrated compositions |
| `test_all_stops_load` | Full stop load succeeds | `build_all_stops()` | ≥ 8 stops |
| `test_composition_fields_match_db` | Loader values = raw DB values (incl. operator join) | STD-7.1 vs DB row | id/speed/hsr/driver-cost/ebit all match |
| `test_composition_capacity_matches_db_aggregation` | `places_by_class` (keyed by class_main) correct | SQL aggregation over coaches | loader = DB per class |
| `test_composition_weight_matches_db_aggregation` | `total_weight_t` correct | SUM of coach gross weights | loader = DB |
| `test_composition_density_matches_db` | Derived densities (`density_by_class_main_length/weight`, m and t per place) reproduce section sums ÷ places (`service_class_density` retired 2026-07-22) | coach section geometry | loader = section math per class |
| `test_track_infra_fields_match_db` | Track values at pinned version, flagged non-default | DE row at pinned version | values match, `is_default=False` |
| `test_stop_fields_match_db` | Stop identity/location correct | DE_BERLIN_HBF at pinned version | all fields match |
| `test_country_geometries_cover_stop_countries` | Runtime geometry availability for CountryIndex | `get_country_geometries()` | polygon for every stop country |
| `test_composition_indicative_figures_present` | Seeded calibration KPIs wired through, per composition, differentiated by material strategy | `build_all_compositions()` | NEW-BAL-7 & REF-BUD-6 present with distinct positive KPIs |

## test_04_versioning.py — Scenario versioning & provenance

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestVersionIsolation::test_loader_uses_base_pinned_version` | Default resolution → base snapshot | `build_all_tracks()` | DE tac = 5.40 (v2) |
| `TestVersionIsolation::test_loader_pinned_to_historical_returns_old_snapshot` | Explicit pin → exact-match old snapshot | `build_all_tracks(historical_id)` | DE tac = 3.10 (v1) |
| `TestVersionIsolation::test_db_has_both_de_versions` | Fixture sanity | DE rows | versions [1, 2] exist |
| `TestVersionIsolation::test_full_table_snapshot_invariant` | Snapshot completeness contract | country count per version | identical for all versions |
| `TestVersionIsolation::test_param_version_number_matches_db` | Provenance points at loaded row | DE tac param entry | version = scenario's pinned version |
| `TestParamProvenance::test_param_versions_key_format` | Key contract | all track entries | `table:entity:field` |
| `TestParamProvenance::test_param_versions_entries_complete` | Entry completeness | all track entries | value not None, version positive int |
| `TestParamProvenance::test_field_descriptions_populated` | Column comments captured once per collection | `tracks.descriptions.fields` | ≥ 1 non-empty description |
| `TestParamProvenance::test_explicit_value_is_not_default_and_has_source` | Explicit value provenance | DE tac | `is_default=False`, source populated |
| `TestParamProvenance::test_null_value_resolves_from_default` | NULL → default resolution + value equality | SE tac vs defaults table | `is_default=True`, value = default row |
| `TestParamProvenance::test_stop_null_charge_resolves_from_global_default` | Stop-level default resolution | SE_STOCKHOLM_C vs global default | `is_default=True`, value = global default |
| `TestParamProvenance::test_stop_explicit_charge_is_not_default` | Explicit stop value | DE_BERLIN_HBF charge | `is_default=False` |
| `test_git_sha_injected_in_ci` | CI injects GIT_SHA into all 3 model version files (skipped locally) | `GITHUB_SHA` env | all 3 `GIT_SHA` constants = commit SHA |

## test_10_params_api.py — GET /api/params/*

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestStopInfrastructures::test_response_layout` | Top-level shape | GET StopInfrastructures | descriptions/sources/default_stops/count/stops; count = len(stops) |
| `TestStopInfrastructures::test_stops_have_required_fields` | Per-stop fields | all stops | id/name/country/lat/lon/charge present |
| `TestStopInfrastructures::test_stop_charge_is_field_object` | Field-object contract | all stops | `{value, is_default, version, source_id}` |
| `TestStopInfrastructures::test_is_default_flags_via_api` | Provenance survives serialization | SE_STOCKHOLM_C / DE_BERLIN_HBF | True / False respectively |
| `TestStopInfrastructures::test_global_default_present` | Default row exposed | `default_stops.global` | present, charge > 0 |
| `TestStopInfrastructures::test_source_ids_resolve` | Source dedup integrity | field `source_id`s | every id resolves in `sources` map |
| `TestTrackInfrastructures::test_response_layout` | Top-level shape | GET TrackInfrastructures | descriptions/sources/default_track_infra/count/entries |
| `TestTrackInfrastructures::test_every_field_is_field_object` | All 10 fields field-objects (guards against a field dropping out) | every country × 10 fields | dict with value + is_default |
| `TestTrackInfrastructures::test_default_row_covers_all_fields` | EU-average default complete | `default_track_infra` | value for all 10 fields |
| `TestTrackInfrastructures::test_is_default_flags_via_api` | Provenance via API | SE / DE tac | True / False |
| `TestTrackInfrastructures::test_scenario_id_pins_parameter_version` | `?scenario_id=` pinning | base vs 2026-baseline request | DE tac 5.40 vs 3.10 |
| `TestCompositions::test_response_layout` | Top-level shape | GET compositions | descriptions/sources/count/compositions/operators |
| `TestCompositions::test_composition_sections_present` | Restructured grouped sections | every composition | routing/staff/energy/capacity/equipment/coaches/fixed_costs/variable_km/source_ids |
| `TestCompositions::test_capacity_non_empty_with_places_and_density` | Capacity content | every composition | ≥ 1 class; places > 0; density > 0 |
| `TestCompositions::test_coach_list_matches_count` | Coach list consistency | every composition | count = len(list); unique positions |
| `TestCompositions::test_operators_referenced_by_compositions` | Operator join integrity | operator_id per composition | resolves; positive staff rates |
| `TestCompositions::test_indicative_kpis_present` | Indicative KPIs exposed (placeholder model) | compositions with reference | positive KPIs |

## test_11_scenarios_api.py — GET /api/scenarios

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestScenariosResponseLayout::test_top_level_keys` | Response layout | `GET /api/scenarios` | `total_count` + `current_base`/`current_scenarios`/`historical_scenarios` groups |
| `TestScenariosResponseLayout::test_group_shape` | Group structure | response groups | each group is `{count, scenarios}`, `count` matches list length |
| `TestScenariosResponseLayout::test_total_count_matches_group_sum` | Partition completeness | response | `total_count` = sum of group counts — every scenario in exactly one group |
| `TestScenariosResponseLayout::test_scenarios_have_required_fields` | Field completeness | every scenario row | full column set exposed |
| `TestScenariosGrouping::test_current_base_group_flags` | Base group semantics | `current_base` rows | both `is_current_base` and `is_current_scenario` true |
| `TestScenariosGrouping::test_current_scenarios_group_flags` | Current group semantics | `current_scenarios` rows | non-base current lineage heads only |
| `TestScenariosGrouping::test_historical_scenarios_group_flags` | Historical group semantics | `historical_scenarios` rows | superseded versions only |
| `TestScenariosGrouping::test_base_scenario_is_in_current_base_group` | Seed cross-check | seeded base scenario | appears in `current_base`, which holds exactly that row |
| `TestScenariosGrouping::test_hsr_scenario_is_in_current_scenarios_group` | Seed cross-check | seeded HSR-allowed lineage head | appears in `current_scenarios` only |
| `TestScenariosGrouping::test_historical_scenario_is_in_historical_scenarios_group` | Seed cross-check | seeded 2026 Base Line scenario | appears in `historical_scenarios` only |

---

## test_20_route_content.py — Route content logic

Built via `POST /api/proposal/calc` (WP5 removed the standalone
`POST /api/route/plan` this originally targeted — same route-building
content, same models/route pipeline, just a different HTTP entry point).


| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestCountryAttribution::test_shares_sum_to_one_per_segment` | Allocation basis integrity | via-Zürich route | distance + time shares each sum to 1.0 per segment |
| `TestCountryAttribution::test_berlin_wien_crosses_de_and_at` | Expected countries | Berlin→Wien | DE and AT present |
| `TestCountryAttribution::test_via_zuerich_crosses_three_countries` | Multi-country routing | Berlin→Zürich→Wien | DE, CH, AT present |
| `TestCountryAttribution::test_country_km_sums_to_trip_distance` | No distance lost in attribution | per-country km | sums to trip total (rel 1e-3) |
| `TestCountryAttribution::test_track_infrastructure_matches_traversed_countries` | Info block completeness (mirrors `Route.countries`) | route dict | traversed ⊆ listed ⊆ traversed ∪ stop countries |
| `TestRouteGeometry::test_outbound_and_return_distances_symmetric` | Path symmetry | Berlin→Wien pair | distances agree within 5% |
| `TestRouteGeometry::test_detour_not_shorter_than_direct` | Routing optimality sanity | direct vs via-Zürich | detour ≥ direct |
| `TestRouteGeometry::test_distance_independent_of_composition` | Same flags → same path | STD-3.1 vs STD-7.1 | identical distance |
| `TestTimetableMath::test_arrival_equals_departure_plus_driving_plus_buffer` | Exact build_final_timetable() math | every segment | arrival = departure + driving + dynamics + buffer |
| `TestTimetableMath::test_intermediate_dwell_at_least_one_minute` | Real dwell applied | Dresden stop | dwell ≥ 1 min |
| `TestTimetableMath::test_buffer_time_non_negative` | Buffer sanity | every segment | buffer ≥ 0 |
| `TestTrackInfraDefaulting::test_se_route_lists_dk_and_se` | Defaulted country included | Copenhagen→Stockholm | DK and SE listed |
| `TestTrackInfraDefaulting::test_defaulted_fields_only_contain_exposed_fields` | No cost-field leakage | defaulted_fields lists | subset of the 6 exposed physics fields |
| `TestEnergyModel::test_energy_is_flat_factor_times_distance` | Pins the DUMMY model (28 kWh/km) — **replace when the calibrated model lands** | every segment | energy = 28 × km exactly |
| `TestEnergyModel::test_energy_independent_of_composition` | Dummy model ignores weight — **replace when the calibrated model lands** | STD-3.1 vs STD-13.1 | identical total energy |
| `TestParkingsAndShuntings::test_two_shuntings_per_trip` | Current shunting rule | Berlin→Wien | 2 per trip = 4 total |
| `TestParkingsAndShuntings::test_shuntings_at_trip_terminals` | Shunting placement | every shunting | at a terminal stop of its trip |
| `TestParkingsAndShuntings::test_parkings_deduplicated_by_stop` | Parking derivation | route parkings | ≥ 1, unique stop_ids, each with trip_ids |
| `TestModeSwitches::test_explicit_default_values_accepted` / `test_simple_routing_mode_accepted` | Mode acceptance | explicit defaults / `simpleRouting` | 200 each |
| `TestModeSwitches::test_invalid_mode_returns_400` (×4) | Mode validation | bad routing/timetable/schedule/auto_stop_addition mode | 400 each |
| `TestModeSwitches::test_auto_stop_addition_defaults_to_add_and_inserts_brno` | auto_stop_addition defaults to `"add"`; CZ_BRNO_HLN sits on the corridor and fits the budget | default request (field omitted) | stops = Berlin, Dresden, **Brno**, Wien; `auto_added` true on Brno only; return trip reversed with mirrored `auto_added`; no `suggested_stops` |
| `TestModeSwitches::test_auto_stop_addition_add_explicit_accepted` | Explicit `"add"` behaves identically to the omitted field | `auto_stop_addition="add"` | 200, Brno inserted, no `suggested_stops` |
| `TestModeSwitches::test_auto_stop_addition_off_returns_exact_caller_list` | Explicit opt-out | `auto_stop_addition="off"` | 200, stop list unchanged, no `suggested_stops` |
| `TestModeSwitches::test_auto_stop_addition_suggest_returns_suggested_stops_section` | `"suggest"` envelope + routing-like-off contract + cross-mode consistency with `"add"` | `auto_stop_addition="suggest"` | `suggested_stops` = exactly CZ_BRNO_HLN with full field set and `added_time_min > 0`, ordered between `request` and `route`; stop list unchanged, `auto_added=false` throughout; suggested ids == the ids `"add"` inserted |
| `TestModeSwitches::test_auto_added_field_false_throughout_when_off` | `Stop.auto_added` contract | module fixture (`auto_stop_addition="off"`) | every stop `auto_added=false` |
| `TestModeSwitches::test_auto_stop_addition_bool_returns_400` (×2) / `test_auto_stop_addition_wrong_type_returns_400` | Pre-0.9.5 booleans and wrong types rejected, not mapped | `auto_stop_addition=true/false/"yes"` | 400 each |
| `TestFixedNightMode::test_interval_covers_night_window_both_directions` | Night-window guarantee, interval reversed for return | fixed-night, Berlin→Dresden interval | dep(A) < 00:00, arr(B) ≥ 05:00, both directions |
| `TestFixedNightMode::test_short_interval_is_stretched_with_slack` | Slack distribution + time consistency | ~2h interval (must stretch) | slack only on interval legs, total > 0; per-segment elapsed = driving+dynamics+buffer+slack |
| `TestFixedNightMode::test_slow_stretch_produces_timetable_warning` | Slow-section detection | ~2h interval (must stretch) | exactly one `fixed_night_stretch_slow` warning per trip, full field set, ratio < 1 |
| `TestFixedNightMode::test_long_interval_gets_no_slack_or_warning` | No-stretch path | Berlin→Wien interval (~7h) | window satisfied, all slack 0, no warnings |
| `TestFixedNightMode::test_invalid_interval_returns_400` (×6) | Interval validation | missing / 1 stop / duplicate / non-string / not in stops / wrong order | 400 each |
| `TestFixedNightMode::test_interval_rejected_outside_fixed_night_mode` | Mode coupling | interval with `simpleAutomatic` | 400, not silently ignored |
| `TestScenarioHandling::test_omitted_scenario_id_resolves_to_base` | Scenario defaulting | no scenario_id | embedded id = base scenario id |
| `TestScenarioHandling::test_explicit_scenario_id_embedded` | Explicit scenario pin | scenario_id = HSR-allowed | embedded verbatim |

## test_30_evaluation_content.py — Evaluation content logic

Controlled demand scenarios need an override `POST /api/proposal/calc`
deliberately doesn't offer (it always builds fresh and runs the stopgap
demand model internally), so these tests call the model layer directly
(`tests/helpers.py:compute_evaluation_domain()` — `route_from_dict()` ->
`add_directional_domain_demand()` ->
`models.pipeline.evaluate_and_build_views()`), skipping HTTP for the
compute step entirely.

Costs are recomputed **by hand** from the route JSON physics plus the rates
served by `/api/params/*`, so these tests also pin cross-endpoint consistency.

Standard input: `eval_standard` (3-stop route, directional demand 40 Couchette
+ 30 Seat per trip; `places_sold` is annual).

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestCostRecomputation::test_tac_matches_manual_calculation` | TAC model exact | per-country km × params tac rates × operating days | == `infrastructure.tac_eur` (rel 1e-3) |
| `TestCostRecomputation::test_energy_cost_matches_manual_calculation` | Energy cost model exact | segment kWh × shares × params prices × days | == `infrastructure.energy_eur` |
| `TestCostRecomputation::test_station_charge_matches_manual_calculation` | Station charge model exact | Σ charge per stop call × days | == `infrastructure.station_charge_eur` |
| `TestCostRecomputation::test_coach_maintenance_matches_manual_calculation` | Variable-km cost exact | maint rate × total km × days | == `variable.coach_maintenance_eur` |
| `TestCostRecomputation::test_revenue_matches_manual_calculation` | Revenue model exact | Σ places_sold × avg_price (no days multiplier) | == `total_revenue_eur` |
| `TestBreakdownIdentities::*` (6 tests) | Tree arithmetic | per_year breakdown | net = revenue − cost − margin; every total = sum of its leaves |
| `TestBreakdownIdentities::test_net_identity_holds_in_all_normalisations` | Normalisation preserves identities | all 5 normalisations | net identity holds in each |
| `TestNormalisationDivisors::test_per_operating_day_times_days_equals_per_year` | Divisor: operating days from embedded schedule | per_operating_day × days | == per_year |
| `TestNormalisationDivisors::test_per_train_km_divisor_is_annual` | Divisor: all trips' km × operating days | per_train_km × annual train-km | == per_year |
| `TestNormalisationDivisors::test_per_available_place_km_divisor_is_unweighted` | Divisor: **unweighted** capacity place-km (density deliberately not applied) | per_pkm × (places × km) | == per_year |
| `TestNormalisationDivisors::test_per_sold_place_km_divisor` | Divisor: sold place-km over each OD's segment range | per_pkm × Σ(70 × trip km) | == per_year |
| `TestNormalisationDivisors::test_per_sold_cost_exceeds_per_available_at_partial_load` | Partial load relation | eval_standard | per-sold cost > per-available cost |
| `TestDemandBehaviour::test_zero_demand_gives_zero_revenue_but_positive_cost` | Zero-demand semantics | empty od_pairs | revenue 0, cost > 0 |
| `TestDemandBehaviour::test_zero_demand_per_sold_view_is_zeroed` | Divide-by-zero handling | empty od_pairs | per_sold view all zeros |
| `TestDemandBehaviour::test_zero_demand_per_available_still_positive` | Capacity view demand-independent | empty od_pairs | per_available cost > 0 |
| `TestDemandBehaviour::test_fare_scales_revenue_linearly` | Revenue linearity | fare 33 vs 99, same places | revenue exactly ×3 |
| `TestMatrixConsistency::test_country_all_all_equals_route_view` | Matrix ↔ route view consistency | (all, all) cell | == route-level total cost |
| `TestMatrixConsistency::test_country_tac_cells_sum_to_total` | Country allocation lossless | per-country tac cells | sum == route-level tac |
| `TestMatrixConsistency::test_traversed_countries_appear_in_matrix` | Matrix coverage | traversed countries | all appear as keys |
| `TestMatrixConsistency::test_od_matrix_carries_directional_keys_with_revenue` | OD keys deterministic | directional demand | both direction keys present, revenue > 0 |
| `TestMatrixConsistency::test_stop_matrix_terminal_has_station_charge` | Stop matrix content | Berlin cell | station charge > 0 |
| `TestScenarioOverride::test_historical_override_lowers_tac` | Scenario override swaps the re-pinned table | same route, base vs 2026-baseline | TAC strictly lower; station charges unchanged |

## test_35_proposal_calc_api.py — POST /api/proposal/calc contract (merged)

The merged compute endpoint (`docs/PROPOSALS_DESIGN.md` §2.1, WP2) — one
call, route + evaluation, no persistence. Covers response-structure and
validation, plus assertions specific to the merge itself (resolved
request, neutral IDs, no duplicate route under `evaluation.input`,
statelessness). Content-level route/evaluation correctness lives
elsewhere — `test_20` (route-building) and `test_30` (evaluation
formulas) — rather than being duplicated here.

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestResponseStructure::test_top_level_keys` | Response envelope | standard request | `route_builder_version, calc_version, request, route, evaluation` present |
| `TestResponseStructure::test_calc_version_is_semver` / `test_route_builder_version_is_semver` | Version strings | response | both `x.y.z` |
| `TestResponseStructure::test_no_suggested_stops_when_off` | Conditional key | `auto_stop_addition="off"` | `suggested_stops` absent |
| `TestResponseStructure::test_evaluation_has_models_input_views` | Evaluation envelope | response | exactly `models, input, views` |
| `TestResponseStructure::test_views_has_all_six` | View completeness | response | all 6 view dimensions |
| `TestResponseStructure::test_input_has_no_route_copy` | §2.1: no duplicate route | `evaluation.input` | no `route` key, exactly `{parameters}` |
| `TestResponseStructure::test_input_parameters_present` | Parameter documentation | `evaluation.input.parameters` | tracks/stops/compositions present |
| `TestResolvedRequest::test_request_has_no_proposal_identity` | Publish concerns excluded | `request` | no `proposal_id`/`proposal_version` |
| `TestResolvedRequest::test_request_echoes_composition_and_stops` | Echo fidelity | `request` | matches posted stops/composition |
| `TestResolvedRequest::test_request_scenario_id_is_concrete` | Scenario resolution | `request.scenario_id` | concrete int even when omitted |
| `TestResolvedRequest::test_omitted_defaults_resolved_explicitly` | §2.1 resolved-request contract | implicit vs explicit-default requests | identical `request` echo |
| `TestNeutralIds::test_route_id_has_no_proposal_prefix` | §2.1 neutral IDs | `route.route_id` | `"R1"`, no `P{id}_V{n}_` prefix |
| `TestNeutralIds::test_trip_ids_have_no_proposal_prefix` | Neutral trip IDs | every trip | starts with `"R1_"`, not `"P"` |
| `TestNeutralIds::test_per_trip_pair_view_keys_are_neutral` | Prefix stripped from dict **keys** too | `views.per_trip_pair.data` keys | no `P` prefix |
| `TestValidation::*` (7 tests) | Request validation | missing stops / too few stops / missing composition_id / invalid timetable_mode / boolean auto_stop_addition / non-int scenario_id / non-JSON body | 400 each |
| `TestSuggestMode::test_suggest_returns_suggested_stops_key` / `test_suggest_does_not_modify_stops` | `"suggest"` mode | `auto_stop_addition="suggest"` | `suggested_stops` present, list; stop list unchanged |
| `TestStatelessness::test_no_persistence_metadata_in_response` | No `proposal` block | response | key absent (unlike `/api/route/plan`/`/api/evaluation/calc`) |
| `TestStatelessness::test_repeated_identical_requests_are_independent` | No shared state | same request twice | identical resolved `request` and `route_id` both calls |

## test_36_proposal_gtfs_roundtrip.py — GTFS+sidecar round-trip

`adapters/proposal/gtfs_store.py`'s `insert_route_gtfs()` (write) and
`route_dict_from_gtfs()` (read) — the GTFS+sidecar persistence path
(`docs/PROPOSALS_DESIGN.md` §5.1/§5.2) that `adapters/proposal/
repository.py`'s `publish()` and `GET /api/proposal/<id>`
(`api/proposals.py`) call directly. This file still tests the two functions standalone
(writing real `POST /api/proposal/calc` responses into the DB under real
`proposal_id`s, allocated from the live `proposals.proposals` sequence
via `ProposalRepository._next_proposal_id()`, and reconstructing them
back) rather than through the endpoints, so it stays focused purely on
round-trip fidelity — endpoint-level coverage of the same write/read path
lives in `test_50`. No commit anywhere in this file; the autouse
`rollback_after_test` fixture cleans up every write.

Comparisons normalize the reconstructed side through a JSON round-trip
(`_json_normalize()`) before comparing against the "published" side —
`route_dict_from_gtfs()` returns native Python objects (e.g. `Decimal`,
int-keyed dicts) while the expected side came back from an actual HTTP
response, already JSON-flattened; comparing them raw would fail on
formatting differences that carry no real information. Separately,
`_round_avg_price()` rounds `avg_price` on the expected side to 2 decimals
— `proposals.od_pairs.avg_price NUMERIC(10,2)` genuinely rounds the
stopgap demand model's raw, unrounded fare output on storage, correctly,
so the round-trip's expectation has to match what actually persists, not
the pre-storage floating-point value.

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestRouteRoundtrip::test_two_stop_route_deep_equals_after_roundtrip` | Baseline round-trip | 2-stop route, `auto_stop_addition="off"` | reconstructed route deep-equals published (mod ID prefix + avg_price rounding) |
| `TestRouteRoundtrip::test_three_stop_route_with_intermediate_stop_deep_equals` | Longer segment chain, a night-classified intermediate stop | 3-stop route | same deep-equal contract |
| `TestRouteRoundtrip::test_auto_added_stop_survives_roundtrip` | The gap phase 1b closed | `auto_stop_addition="add"` (Brno auto-added) | `auto_added=true` survives on the inserted stop, both directions |
| `TestRouteRoundtrip::test_od_pairs_survive_roundtrip` | `proposals.od_pairs` carries real content | stopgap demand always populates `od_pairs` | reconstructed od_pairs (compared against the **published**, ID-rewritten copy — od_pairs carry `trip_id` references) match, avg_price rounded |
| `TestRouteRoundtrip::test_unknown_proposal_raises` | Domain check | nonexistent `proposal_id` | `ValueError` |
| `TestInputParametersRoundtrip::test_input_parameters_deep_equal_original` | `input_parameters_from_scenario()` — parameters rebuilt from scenario pin alone, no GTFS insert needed | same scenario_id as the original compute | rebuilt `evaluation.input.parameters` deep-equals original (JSON-normalized) |

## test_37_proposal_projection.py — Fingerprint + summary projection

`adapters/proposal/projection.py`'s pure functions (`route_fingerprint()`,
`build_summary_row()`) plus the fingerprint/`cache_hit` wiring in the
`POST /api/proposal/calc` response.

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestFingerprint::test_present_and_well_formed` | Fingerprint in the compute response | calc response | `sha256:`-prefixed hex |
| `TestFingerprint::test_deterministic_across_identical_requests` | §3.1 determinism | same request twice | identical fingerprints |
| `TestFingerprint::test_differs_for_a_different_route` | Sensitivity | different stop list | different fingerprint |
| `TestFingerprint::test_matches_direct_call_on_route_dict` | Wiring = direct function call | response route dict | `route_fingerprint()` matches response field |
| `TestFingerprint::test_ignores_id_prefix` | Prefix independence by construction | prefixed vs bare route dict | identical fingerprints |
| `TestCacheHitPlaceholder::test_always_false` | WP13 placeholder semantics | calc response | `cache_hit == false` |
| `TestSummaryRow::*` | Every non-identity summary column present, metrics plausible, KPIs match the evaluation views, demand KPIs flagged placeholder, valid simplified MultiLineString | calc response | see file |
| `TestSummaryRowSchemaConformance::test_row_inserts_cleanly` | Row shape matches `proposal_summaries` DDL | direct INSERT | insert succeeds (rolled back) |

## test_40_pipeline.py — End-to-end smoke

The "cost" half runs at the model layer (`compute_evaluation_domain()`)
— see `test_30`'s note above. "Plan" goes through a live
`POST /api/proposal/calc`.

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `test_pipeline_completes_with_two_trips` | Plan step produced a costable route | shared 3-stop route | 2 trips |
| `test_pipeline_produces_all_views` | Cost step consumed the plan output | plan → demand → evaluate | all 6 views present |
| `test_pipeline_revenue_and_cost_positive` | Both ledger sides populated | pipeline result | revenue > 0, cost > 0 |

---

## test_50_proposals_api.py — POST /api/proposal/publish + proposals read endpoints

WP5 (`docs/PROPOSALS_DESIGN.md` §2.2): `POST /api/proposal/publish` is
now the only user write path — the old persist-on-calc contract
(created/unchanged/versioned/branched on plan; filled/unchanged/
versioned/branched on evaluate) is gone along with `POST /api/route/plan`
and `POST /api/evaluation/calc`. This file is a full rewrite, not an
adaptation of the old one. A module-scoped autouse fixture purges
published proposals before and after this file (the permanent seed
proposal excepted). The suite publishes as the seeded `test_script` user
(conftest: `script_headers`); guest sessions supply the foreign owner.

| Test | Pins | Setup | Expectation |
|---|---|---|---|
| `TestPublishNew::test_publish_new_returns_full_shape` | Publish response shape | fresh publish | version 1, correct owner/name, prefixed `route_id`, evaluation has `models`/`input`/`views` |
| `TestPublishNew::test_publish_new_forbids_proposal_id` | §2.2 mode contract | `mode="new"` + `proposal_id` | `400` |
| `TestPublishNew::test_publish_requires_auth` | Write floor | no token | `401` |
| `TestPublishNew::test_publish_new_round_trips_via_load` | Load matches publish | `GET` after publish | id/version/name/fingerprint/trip_pairs agree |
| `TestPublishOverwrite::test_overwrite_bumps_version_and_changes_composition` | Edit via overwrite | different composition, same `proposal_id` | version 2, composition changed, load reflects it |
| `TestPublishOverwrite::test_overwrite_unknown_proposal_404` | Domain check | nonexistent `proposal_id` | `404 not_found` |
| `TestPublishOverwrite::test_overwrite_foreign_proposal_403` | Ownership | guest overwrites test_script's proposal | `403 forbidden` |
| `TestBaseScenarioRule::test_non_base_scenario_rejected` | §2.2 locked decision 4 | `compute_request.scenario_id` = historical | `422 scenario_not_base` |
| `TestBuildOnForeign::test_build_on_seed_publishes_new_under_caller` | §6 "build on foreign" flow | load seed, publish new with `based_on_proposal_id` | new id, owned by guest, seed untouched |
| `TestPublishValidation::*` (4 tests) | Envelope validation | missing name / invalid mode / overwrite without proposal_id / malformed compute_request | `400` each |
| `test_get_unknown_proposal_returns_404` | Domain check | nonexistent `proposal_id` | `404 not_found` |
| `test_seeded_example_proposal_is_queryable` | The DB-init-time seed proposal is real and fully evaluated | `GET /api/proposal/1` | `total_revenue_eur > 0` (WP5: no half-states, unlike the old no-evaluation seed) |
| `TestList::test_list_includes_published_and_seed` | List completeness | fresh publish + seed | both ids present |
| `TestList::test_filter_by_user_ids` | Filter | `user_ids` = test_script | only that user's proposals, includes the fresh one |
| `TestList::test_pagination` | `limit`/`offset` | `limit=1` | ≤ 1 row |
| `TestList::test_list_rejects_unknown_filter_key` | Validation | unsupported filter key | `400 validation_error` |

Note: `db/dev/seed.py` seeds one permanent example proposal
(`proposal_id=1`, owned by the seed user) — preserved by every purge
here, and doubling as the foreign, evaluated proposal the build-on-foreign
test (and test_70's merge test) borrow without an extra route build.
Unlike the pre-WP5 seed, it now carries a real evaluation (§2.4: no
half-states) — see `db/dev/seed.py:_compute_example_proposal()`.

## test_51_proposal_engagement_api.py — Proposal likes + comments

Targets the permanent seed proposal (`proposal_id=1`) directly rather than
building a fresh route — engagement rows don't depend on route content,
and this avoids a live OpenRailRouting call per test. Safe because
`proposals.likes`/`proposals.comments` carry no permanent seed data of
their own; `helpers.purge_saved_proposals` now clears both tables
unconditionally (not keyed to the kept proposal_id) on every module/session
purge. A module-scoped autouse fixture purges before and after this file;
a few tests that assert exact counts also purge per-test to avoid
cross-test interference on the shared seed proposal.

| Test | Pins | Setup | Expectation |
|---|---|---|---|
| `test_get_likes_unknown_proposal_returns_404` | Soft-reference validation | nonexistent proposal_id | `404 not_found` |
| `test_like_requires_auth` | Write floor | no token | `401` |
| `test_like_unknown_proposal_returns_404` | Soft-reference validation | authenticated, nonexistent proposal_id | `404 not_found` |
| `test_like_unliked_proposal_starts_at_zero` | Clean baseline | fresh purge | `{count: 0, liked_by_me: false}` |
| `test_like_is_idempotent_and_per_caller` | Idempotent + per-user | like twice, then a second user's GET/POST | 2nd like is a no-op; `liked_by_me` is per-caller, not global |
| `test_unlike_is_idempotent` | Idempotent unlike | unlike twice | both `200`, second is a no-op |
| `test_unlike_requires_auth` | Write floor | no token | `401` |
| `test_get_comments_unknown_proposal_returns_404` | Soft-reference validation | nonexistent proposal_id | `404 not_found` |
| `test_comment_requires_auth` | Write floor | no token | `401` |
| `test_comment_rejects_empty_body` | Validation | blank/whitespace body | `400 validation_error` |
| `test_comment_rejects_oversized_body` | Validation | 4001-char body | `400 validation_error` |
| `test_comment_unknown_proposal_returns_404` | Soft-reference validation | authenticated, nonexistent proposal_id | `404 not_found` |
| `test_add_comment_returns_stored_shape` | Stored shape | fresh comment | body stripped, `proposal_version` stamped from the target's current version, `created_at == updated_at` |
| `test_list_comments_includes_posted_comment` | Listing | GET after POST | comment_id present |
| `test_edit_comment_by_author_succeeds` | Author can edit | PATCH as author | `200`, body updated, `updated_at` bumped |
| `test_edit_comment_by_other_user_is_forbidden` | Ownership | PATCH as guest | `403 forbidden` |
| `test_edit_comment_unknown_id_returns_404` | Domain check | nonexistent comment_id | `404 not_found` |
| `test_delete_comment_by_other_user_is_forbidden` | Ownership | DELETE as guest | `403 forbidden` |
| `test_delete_comment_by_author_soft_deletes` | Soft-delete contract | DELETE as author | `204`; still listed with `is_deleted=true`, `body=""`; further PATCH/DELETE on it → `404` |

## test_60_feedback_api.py — Feedback API

A module-scoped autouse fixture purges rows tagged with the
`TEST_FEEDBACK_60_` subject prefix before and after this file. Whether
SMTP is configured varies by environment (see `adapters/mailer.py`'s
graceful-degradation behaviour) — the storage tests check
`email_sent`/`notified_at` agree with each other rather than assuming a
fixed value, so this file passes the same way whether or not SMTP_* is set.

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `test_feedback_requires_identity` | Validation | no `user_id`/`email` | `400 validation_error` |
| `test_feedback_rejects_invalid_email` | Validation | malformed `email` | `400 validation_error` |
| `test_feedback_requires_subject_category_message` | Validation | missing required fields | `400 validation_error`, one detail per field |
| `test_feedback_unknown_user_id_is_domain_error` | Domain check | nonexistent `user_id` | `422 domain_error` |
| `test_feedback_anonymous_submission_is_stored` | Email-identified submission persists correctly | `email`, no `user_id` | `201`, row has `user_id=NULL`, `email` set, `notified_at` matches `email_sent` |
| `test_feedback_logged_in_submission_is_stored` | user_id-identified submission persists correctly | seeded `user_id` | `201`, row has `user_id` set, `email=NULL` |
| `test_feedback_categories_lists_all_categories` | All nine categories present, nothing extra | — | exact set match |
| `test_feedback_categories_infrastructure_is_dynamic` | Sub-category list is derived live, not hardcoded | — | known TrackInfrastructures/StopInfrastructures fields present |
| `test_feedback_categories_compositions_is_dynamic` | Sub-category list is derived live, not hardcoded | — | non-empty, correctly grouped |
| `test_feedback_categories_calc_method_is_dynamic` | Sub-category list is derived from the Breakdown dataclass tree | — | known cost/revenue/margin leaves present, three groups |
| `test_feedback_categories_eval_view_is_dynamic` | Sub-category list matches the five evaluation views exactly | — | exact set match |
| `test_feedback_categories_static_lists_present` | Static categories have content; free-text ones don't | — | Route/General non-empty, Bug/Feature/Other empty |

## test_70_auth_api.py — Auth integration

Integration tests for the local auth plane (`api/auth.py`) — request-code,
verify, guest — plus the identity wiring on publish. OTPs are never exposed
by the API, so verify-flow tests inject a token row with a known
plaintext's hash through the DB fixture. Guest-merge coverage includes the
merged token failing loudly on `POST /api/proposal/publish` (the remaining
`@require_auth` write endpoint). Rate-limited environments make
request-code tests skip rather than fail. See the file's module docstring
and per-test docstrings for details.

## test_71_auth_units.py — Auth units

Pure unit tests for the auth building blocks — no Docker stack, no DB:
`auth_utils` (OTP, display names, local HS256 JWTs) and `auth_oidc` (plane
routing + Keycloak-token verification against a locally generated RSA
key). The only file in the suite runnable standalone.

## Dropped from the previous suite (and why)

- **Per-class breakdown tests** (`test_density.py`: `per_available_place_of_class`
  etc.) — no per-class field exists anywhere in the Breakdown dataclasses.
  Functionality absent from current code → dropped, not skipped.
- **Density-weighted divisor test** — contradicted current behaviour:
  `normalise_per_available_place_km()` is deliberately unweighted. Replaced
  by `test_per_available_place_km_divisor_is_unweighted`, which pins the
  actual divisor exactly.
- **Terrain-effect energy tests** (skipped placeholders) — the dummy model has
  no terrain effect. The flat-factor tests in `test_20` pin current behaviour
  and are marked for replacement when the calibrated model lands.
- **model_versions / calc_formulas skip-stubs** — the evaluation response now
  serialises a full `models` section, so these became *real* tests
  (now `test_35::TestModelsSection`). The route-JSON variants stayed dropped
  (model versions are still not embedded in route JSON).
- **Duplicate 200-status tests** — fixtures already assert 200 on build;
  repeating the POST purely to assert the status wasted a full routing call.
- **conftest energy-approximation helpers** — the old `country_legs` helper
  *distributed* segment energy by distance share and tests then verified that
  distribution (circular). Country attribution is now tested directly on
  `country_distance_shares`, and energy at segment level.
- **`test_pipeline_country_breakdown_infrastructure_only`** — its original
  claim (a `scope` field) never existed; its structural remainder is covered
  by `test_35::test_views_has_all_six`.

## Suggested seed-data additions (not yet implemented)

1. **A second operator with different `driver_factor`/`total_crew`** — would
   allow a manual recomputation test for driver/crew cost (the multiplier bug
   class already hit once) analogous to the TAC/energy tests.
2. **A composition on that second operator** — enables comparing operator
   staff rates end to end through `/api/proposal/calc`'s evaluation section.
3. **A stop pair inside a single defaulted country (e.g. two SE stops)** —
   would let TAC-under-default be recomputed for a route that runs entirely on
   default-resolved rates.
4. **A scenario re-pinning `stop_infrastructures` to genuinely different
   values** — all three currently-seeded snapshots (2026-baseline / base /
   2032-baseline-hsr-allowed) carry byte-identical stop charges, only the
   version number differs; a scenario with an actual stop-side value change
   would cover the other half of the override matrix.
5. ~~**A stop within `AUTO_STOP_BUFFER_M` of an existing corridor**~~ —
   **DONE**: `CZ_BRNO_HLN` (Brno hl.n., 49.191/16.613) sits ~10m off the
   natural Berlin-Dresden-Wien routing (Dresden-Praha-Brno-Wien) and
   comfortably inside the detour budget, so the full `auto_stop_addition`
   behaviour is now pinned end to end in `test_20::TestModeSwitches`: the
   actual insertion at geographic position with `auto_added=true`, the
   outbound-and-return-carry-the-same-added-stops rule (search runs once,
   from outbound — see `_build_trip_pair()` in `route_factory.py`), a
   populated `suggested_stops` list with a real `added_time_min`, and
   cross-mode consistency (`"suggest"` lists exactly what `"add"`
   inserts). Because of this, every fixed-corridor fixture in
   `conftest.py` and `test_20`'s structural `BASE_REQUEST` pin
   `auto_stop_addition="off"` — otherwise Brno (and, for the 2-stop
   Berlin-Wien fixture, Dresden too) would be auto-added into routes whose
   exact stop lists downstream tests rely on. Still open within this
   topic: a candidate that gets *rejected* by the budget check (a stop
   near a corridor but with a detour cost above
   `AUTO_STOP_MAX_DETOUR_PER`) — today every near-corridor candidate fits,
   so the rejection branch is only covered implicitly.

## Conventions

- Session-scoped route fixtures in `conftest.py` are **read-only** — never
  mutate them; `compute_evaluation_domain()` reconstructs its own domain
  objects from them, so applying demand there never touches the fixture.
  They are built **tokenless** deliberately (compute-only, draft IDs, zero
  DB rows) — persistence is exercised solely by the dedicated tests.
- The suite persists as the seeded `test_script` user via
  `script_headers` (a real JWT from the live API, OTP injected DB-side —
  no `JWT_SECRET` needed on the host). Session teardown purges everything
  the run persisted; the seed proposal survives.
- Monetary assertions use `pytest.approx(rel=1e-3)` — EUR leaves are rounded
  to 2 decimal places by the API.
- `db_conn.commit()`/rollback discipline: the autouse `rollback_after_test`
  fixture prevents an aborted transaction from cascading.
- Tests must only assert on data the API actually returns. If a field is
  genuinely absent, the test is deleted (with a note here), not skipped with
  fabricated data.