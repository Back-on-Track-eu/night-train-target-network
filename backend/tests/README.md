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
uv run --extra dev pytest tests/ -v
```

## Layout

Files are numbered in dependency order — from Docker build-up to the APIs
built on top of it:

| Prefix | Layer |
|---|---|
| `test_01`–`test_04` | Stack build-up: containers → seeded DB → loader → versioning |
| `test_10`–`test_11` | Read-only params + scenarios APIs |
| `test_20`–`test_21` | `POST /api/route/plan` (contract, then content logic) |
| `test_30`–`test_31` | `POST /api/evaluation/calc` (contract, then content logic) |
| `test_40` | End-to-end pipeline smoke |
| `test_50` | Persist-on-calc semantics + proposals list/load |
| `test_60` | Feedback API — submit/categories |

Shared code:

- **`conftest.py`** — DB/loader/scenario fixtures and the four **session-scoped
  route fixtures** (`route_berlin_wien`, `route_berlin_dresden_wien`,
  `route_berlin_zuerich_wien`, `route_copenhagen_stockholm`) plus
  `eval_standard`. Route builds are expensive (live OpenRailRouting) — tests
  that only *read* a route must reuse these instead of building their own.
- **`helpers.py`** — HTTP wrappers (`build_route`, `evaluate`), route-JSON
  navigation (`all_trips`, `stop_times`, `country_km`, `trip_distance_km`,
  `operating_days`, …) and demand construction (`inject_demand`,
  `directional_od`, `replicated_od`). Everything is derived strictly from
  data present in the API responses — nothing is fabricated.

---

## test_01_stack_health.py — Docker stack build-up

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `test_api_health` | API process is up | `GET /api/health` | 200, `{"status": "ok"}` |
| `test_data_status_loaded` | DB loader initialised at startup | `GET /api/data/status` | 200, `loaded=True`, `loaded_at` set, no `error` |
| `test_openrailrouting_health` | Routing engine reachable | `GET :8989/health` (host port) | 200 |
| `test_unknown_endpoint_returns_json_404` | Global JSON error handler | `GET /api/does-not-exist` | 404 with `error=not_found` JSON body |
| `test_wrong_method_returns_json_405` | Global JSON error handler | `GET /api/route/plan` | 405 with `error=method_not_allowed` JSON body |
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

## test_20_route_plan_api.py — POST /api/route/plan contract

Base input for the module fixture: 3 stops (Berlin, Dresden, Wien), STD-7.1,
all modes defaulted.

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestResponseStructure::test_top_level_keys` | Response envelope | standard request | exactly `route_builder_version, request, route` |
| `TestResponseStructure::test_request_echoed_verbatim` | Request echo | standard request | `request` == posted body |
| `TestResponseStructure::test_route_top_level_keys` | route_to_dict layout | route dict | route_id, scenario_id, schedule, trip_pairs, parkings, shuntings, track_infrastructure, geometries |
| `TestResponseStructure::test_one_trip_pair_with_both_directions` | Pair structure | route dict | 1 pair; directions {0, 1} |
| `TestResponseStructure::test_outbound_stop_order_matches_request` | Stop order | outbound trip | exactly the requested stop list |
| `TestResponseStructure::test_return_trip_stops_reversed` | Return mirroring | return trip | reversed outbound stop list |
| `TestResponseStructure::test_segment_count_equals_stops_minus_one` | Segmentation | every trip | N stops → N−1 segments |
| `TestResponseStructure::test_segments_carry_physics_fields` | Segment shape | every segment | distance/time/buffer/slack/energy/shares present; distance > 0; slack 0 outside fixed-night |
| `TestResponseStructure::test_no_monetary_values_anywhere` | Physics-only contract | whole route dict (recursive) | no `*eur*`/`*cost*` keys anywhere |
| `TestResponseStructure::test_geometries_and_segments_reference_each_other` | geometry_id integrity | geometries + segments | unique ids, non-empty coords, every reference resolves |
| `TestResponseStructure::test_composition_embedded_without_cost_fields` | Physics subset of composition | embedded composition | no cost fields; capacity/density present |
| `TestResponseStructure::test_od_pairs_populated_by_stopgap_demand` | Stopgap demand distribution runs after planning (see `api/route.py`, `OPEN_TODOS["demand_model"]`) | trip pairs | `od_pairs` non-empty, covers both trips of the pair, structural fields only (no distribution values pinned) |
| `TestResponseStructure::test_track_infrastructure_present_and_shaped` | Track infra info block | route dict | per-country entries with defaulted_fields list |
| `TestAutomaticScheduling::test_departure_time_assigned` | Scheduling contract | every trip | departure set, 0 ≤ t < 48 h |
| `TestAutomaticScheduling::test_terminal_stop_types` | Terminal classification | every trip | first=boarding/no arrival; last=alighting/no departure |
| `TestAutomaticScheduling::test_intermediate_stops_classified_three_way` | Threshold classification (never "both") | intermediate stops | boarding, night, or alighting; both times set |
| `TestAutomaticScheduling::test_stop_times_monotonically_increasing` | Time ordering | every trip | arrivals strictly sorted |
| `TestAutomaticScheduling::test_schedule_is_daily_both_seasons` | schedule_mode default | route schedule | summer+winter, both `daily` |
| `TestFixedNightMode::test_interval_covers_night_window_both_directions` | Night-window guarantee, interval reversed for return | fixed-night, Berlin→Dresden interval | dep(A) < 00:00, arr(B) ≥ 05:00, both directions |
| `TestFixedNightMode::test_short_interval_is_stretched_with_slack` | Slack distribution + time consistency | ~2h interval (must stretch) | slack only on interval legs, total > 0; per-segment elapsed = driving+dynamics+buffer+slack |
| `TestFixedNightMode::test_slow_stretch_produces_timetable_warning` | Slow-section detection | ~2h interval (must stretch) | exactly one `fixed_night_stretch_slow` warning per trip, full field set, ratio < 1 |
| `TestFixedNightMode::test_long_interval_gets_no_slack_or_warning` | No-stretch path | Berlin→Wien interval (~7h) | window satisfied, all slack 0, no warnings |
| `TestFixedNightMode::test_invalid_interval_returns_400` (×6) | Interval validation | missing / 1 stop / duplicate / non-string / not in stops / wrong order | 400 each |
| `TestFixedNightMode::test_interval_rejected_outside_fixed_night_mode` | Mode coupling | interval with `simpleAutomatic` | 400, not silently ignored |
| `TestModeSwitches::test_explicit_default_values_accepted` | Explicit defaults valid | all modes spelled out | 200 |
| `TestModeSwitches::test_simple_routing_mode_accepted` | Alternative routing mode | `routing_mode=simpleRouting` | 200, full route |
| `TestModeSwitches::test_invalid_mode_returns_400` (×4) | Mode validation | bad routing/timetable/schedule/auto_stop_addition mode | 400 each |
| `TestModeSwitches::test_auto_stop_addition_defaults_to_add_and_inserts_brno` | auto_stop_addition defaults to `"add"`; CZ_BRNO_HLN sits on the corridor and fits the budget | default request (field omitted) | stops = Berlin, Dresden, **Brno**, Wien; `auto_added` true on Brno only; return trip reversed with mirrored `auto_added`; no `suggested_stops` section |
| `TestModeSwitches::test_auto_stop_addition_add_explicit_accepted` | Explicit `"add"` behaves identically to the omitted field | `auto_stop_addition="add"` | 200, Brno inserted, no `suggested_stops` section |
| `TestModeSwitches::test_auto_stop_addition_off_returns_exact_caller_list` | Explicit opt-out | `auto_stop_addition="off"` | 200, stop list unchanged, no `suggested_stops` section |
| `TestModeSwitches::test_auto_stop_addition_suggest_returns_suggested_stops_section` | `"suggest"` envelope + routing-like-off contract + cross-mode consistency with `"add"` | `auto_stop_addition="suggest"` | 200; `suggested_stops` = exactly CZ_BRNO_HLN with full field set and `added_time_min > 0`, ordered between `request` and `route`; stop list unchanged, `auto_added=false` throughout; suggested ids == the ids `"add"` inserted |
| `TestModeSwitches::test_auto_added_field_false_throughout_when_off` | `Stop.auto_added` contract | module fixture (`auto_stop_addition="off"`) | every stop `auto_added=false` |
| `TestModeSwitches::test_auto_stop_addition_bool_returns_400` (×2) | Pre-0.9.5 booleans rejected, not mapped | `auto_stop_addition=true` / `false` | 400 each |
| `TestModeSwitches::test_auto_stop_addition_wrong_type_returns_400` | Value validation | `auto_stop_addition="yes"` | 400 |
| `TestProposalAndScenario::test_omitted_proposal_id_gets_draft_placeholder` | Draft placeholder rule | no proposal_id | route_id `P{>1e9}_V1_R1` |
| `TestProposalAndScenario::test_explicit_proposal_id_used_in_route_id` | Explicit id rule | proposal_id=42, version=7 | route_id `P42_V7_R1` |
| `TestProposalAndScenario::test_omitted_scenario_id_resolves_to_base` | Scenario defaulting | no scenario_id | embedded id = base scenario id |
| `TestProposalAndScenario::test_explicit_scenario_id_embedded` | Explicit scenario pin | scenario_id = HSR-allowed | embedded verbatim |
| `TestValidation::*` (7 tests) | Request validation | single stop / missing fields / old stop-object format / wrong types / unknown composition / non-JSON | 400 (validation) or 422 (unknown composition — domain error) |

## test_21_route_plan_content.py — Route content logic

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

## test_30_evaluation_api.py — POST /api/evaluation/calc contract

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `TestResponseStructure::test_top_level_keys` | Response envelope | `eval_standard` | calc_version, route_id, models, input, views |
| `TestResponseStructure::test_calc_version_is_semver` | Version string | response | `x.y.z` |
| `TestResponseStructure::test_route_id_echoes_input` | Identity echo | response | equals posted route_id |
| `TestResponseStructure::test_views_has_all_five` | View completeness | response | exactly the 5 view dimensions |
| `TestResponseStructure::test_every_view_carries_description_and_normalisation_docs` | Self-documenting views | every view | description + 5 normalisation docs + data |
| `TestResponseStructure::test_route_view_has_all_normalisations` | Normalisation completeness | route view | exactly the 5 normalisations |
| `TestResponseStructure::test_breakdown_tree_shape` | Breakdown tree | per_year route view | cost/revenue/margin + totals; operator variable/fixed |
| `TestResponseStructure::test_matrix_views_have_all_keys_and_filters` | Matrix contract | 4 matrix views | 'all' key; every cell has filter + values |
| `TestModelsSection::test_three_models_with_version_and_description` | Model documentation | models section | route_builder/energy/evaluation with semver + description |
| `TestModelsSection::test_evaluation_formulas_cover_all_breakdown_leaves` | Formula coverage — frontend maps view fields to formulas by key | evaluation formulas | all 17 leaf fields documented |
| `TestModelsSection::test_formulas_have_latex_and_description` | Formula content | every formula | non-empty latex (LaTeX-looking) + description |
| `TestInputSection::test_route_echoed_verbatim` | Faithful input record | input.route | == route JSON exactly as posted |
| `TestInputSection::test_parameters_carry_all_three_collections` | Parameter documentation | input.parameters | tracks/stops/compositions in /api/params shape |
| `TestValidation::*` (5 tests) | Request validation | missing route / non-JSON / empty trip_pairs / wrong scenario type / no demand | 400 ×4; the no-demand route evaluates with 200 |

## test_31_evaluation_content.py — Evaluation content logic

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

## test_40_pipeline.py — End-to-end smoke

| Test | Purpose | Input | Expected |
|---|---|---|---|
| `test_pipeline_completes_with_two_trips` | Plan step produced a costable route | shared 3-stop route | 2 trips |
| `test_pipeline_produces_all_views` | Cost step consumed the plan output | plan → demand → evaluate | all 5 views present |
| `test_pipeline_revenue_and_cost_positive` | Both ledger sides populated | pipeline result | revenue > 0, cost > 0 |

---

## test_50_proposals_api.py — Persist-on-calc + proposals read endpoints

The write path lives inside the pipelines (POST /api/proposal is gone):
these tests exercise the created/unchanged/versioned/branched contract of
`POST /api/route/plan` and the filled/unchanged/versioned/branched contract
of `POST /api/evaluation/calc`, plus the remaining list/load endpoints.
A module-scoped autouse fixture purges persisted proposals before and
after this file (the permanent seed proposal excepted). The suite
persists as the seeded `test_script` user (conftest: `script_headers`);
guest sessions supply the foreign owner. Tests within each fixture group
build on each other's version history **in definition order** — don't
reorder or `-k`-split them.

| Test | Pins | Setup | Expectation |
|---|---|---|---|
| `test_plan_persists_created` | Authenticated plan persists itself | fresh plan, no proposal_id | `action=created`, version 1, caller owns, route_id final |
| `test_plan_response_matches_stored_body` | Response IS the stored body | GET round-trip | route_body == response minus `proposal` block, no draft prefix anywhere |
| `test_plan_writes_gtfs_decomposition` | GTFS side written | DB rows | 2 trips, 2×stops stop_times, daily calendar |
| `test_tokenless_plan_computes_only` | No token → old contract | tokenless plan | `unauthenticated`, draft id ≥1e9, no row |
| `test_replan_identical_setup_is_unchanged` | Setup dedupe | replan same setup + proposal_id | `unchanged`, stored current IDs, still 1 version |
| `test_replan_changed_setup_creates_new_version` | Owner + changed setup versions | different composition | `versioned`, version 2, `is_current` flips, v1 kept |
| `test_replan_foreign_identical_setup_is_unchanged` | Dedupe outranks ownership | guest, current setup | `unchanged` |
| `test_replan_foreign_changed_setup_branches` | Foreign + changed setup branches | guest, other composition | `branched`, new id, guest owns, original untouched |
| `test_eval_fills_own_version_in_place` | The one sanctioned in-place write | eval own persisted route | `filled`, same version, evaluation_body set, no new row |
| `test_eval_identical_inputs_is_unchanged` | Deterministic no-op | same eval again | `unchanged` |
| `test_eval_scenario_override_creates_new_version` | Result-touching input versions | historical scenario override | `versioned`, v2, route carried over, response IDs already V2, `scenario_id` reported |
| `test_eval_of_historical_version_computes_only` | History never mutated | eval the V1 route after V2 exists | `historical_version` |
| `test_eval_of_unpersisted_route_computes_only` | Drafts have nowhere to land | tokenless-built session fixture | `unpersisted_route` |
| `test_eval_of_edited_route_computes_only` | Hand-edited JSON never overwrites | demand wiped from stored route | `route_mismatch` |
| `test_eval_tokenless_computes_only` | No token → compute only | tokenless eval | `unauthenticated` |
| `test_eval_by_non_owner_branches` | Foreign eval branches | guest evaluates the seed proposal | `branched`, guest owns copy with evaluation, seed untouched |
| `test_get_unknown_proposal_returns_404` | Domain check | nonexistent proposal_id | `404 not_found` |
| `test_seeded_example_proposal_is_queryable` | The DB-init-time seed proposal is real | `GET /api/proposal/1` | Berlin–Dresden–Wien, both directions, no evaluation |
| `test_list_returns_current_summaries` | List shape and current-only filtering | test_script ×2 versions + guest's Zürich + seed | `total=3`, only current versions, metrics populated |
| `test_filtered_list_by_country_stop_and_user` | Filters narrow correctly | country/stop/user filters | country/stop isolate Zürich; user filters return exactly the owner's proposals |
| `test_list_sorting_and_pagination` | Sort + limit/offset | `total_distance_km` sort, `limit=1` | ascending order, `total=3` |
| `test_list_sort_by_margin_is_null_safe` | Financial sort tolerates unevaluated proposals | none of the 3 listed has an evaluation | sort doesn't raise, `margin_eur` null for all |
| `test_list_rejects_unknown_sort_key` | Validation | bad sort key | `400 validation_error` |

Note: `db/dev/seed.py` seeds one permanent example proposal
(`proposal_id=1`, owned by the seed user, no evaluation) — preserved by
every purge here, and doubling as the foreign, evaluation-free proposal
the branch-by-eval tests (and test_70's merge test) borrow without an
extra route build. Any test asserting an exact list total counts it.
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

## Dropped from the previous suite (and why)

- **Per-class breakdown tests** (`test_density.py`: `per_available_place_of_class`
  etc.) — no per-class field exists anywhere in the Breakdown dataclasses.
  Functionality absent from current code → dropped, not skipped.
- **Density-weighted divisor test** — contradicted current behaviour:
  `normalise_per_available_place_km()` is deliberately unweighted. Replaced
  by `test_per_available_place_km_divisor_is_unweighted`, which pins the
  actual divisor exactly.
- **Terrain-effect energy tests** (skipped placeholders) — the dummy model has
  no terrain effect. The flat-factor tests in `test_21` pin current behaviour
  and are marked for replacement when the calibrated model lands.
- **model_versions / calc_formulas skip-stubs** — the evaluation response now
  serialises a full `models` section, so these became *real* tests
  (`test_30::TestModelsSection`). The route-JSON variants stayed dropped
  (model versions are still not embedded in route JSON).
- **Duplicate 200-status tests** — fixtures already assert 200 on build;
  repeating the POST purely to assert the status wasted a full routing call.
- **conftest energy-approximation helpers** — the old `country_legs` helper
  *distributed* segment energy by distance share and tests then verified that
  distribution (circular). Country attribution is now tested directly on
  `country_distance_shares`, and energy at segment level.
- **`test_pipeline_country_breakdown_infrastructure_only`** — its original
  claim (a `scope` field) never existed; its structural remainder is covered
  by `test_30::test_matrix_views_have_all_keys_and_filters`.

## Suggested seed-data additions (not yet implemented)

1. **A second operator with different `driver_factor`/`total_crew`** — would
   allow a manual recomputation test for driver/crew cost (the multiplier bug
   class already hit once) analogous to the TAC/energy tests.
2. **A composition on that second operator** — enables comparing operator
   staff rates end to end through `/api/evaluation/calc`.
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
  mutate them; use `inject_demand()` (which copies) to attach demand. They
  are built **tokenless** deliberately (compute-only, draft IDs, zero DB
  rows) — persistence is exercised solely by the dedicated tests.
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