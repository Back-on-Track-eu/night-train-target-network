---
title: Parameter reference
---

# Parameter reference

<!-- Generated from the model registries. Edit the model, not this page —
     anything outside the GENERATED markers survives regeneration. -->

<!-- BEGIN GENERATED: parameters -->
## `input_params.countries`

Country reference table with border polygons.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-countries-country_code"></a>`country_code` | Two-letter country code (ISO 3166-1 alpha-2). Primary key. | — | — |
| <a id="p-input_params-countries-country_name"></a>`country_name` | Full English country name. | — | — |
| <a id="p-input_params-countries-country_geom"></a>`country_geom` | Country border polygon (SRID 4326) covering the country's land area AND its maritime zones (territorial sea, internal and archipelagic waters, EEZ) — seeded from the Marine Regions union of the ESRI country shapefile and the Exclusive Economic Zones, v4. The maritime coverage is what attributes belt, strait and tunnel crossings to a country instead of the UNK sentinel: this is a routing-attribution geometry, not a cartographic land border. NULL for countries with no rail network, which no route can transit. | — | — |

## `input_params.country_relations`

Which pairs of countries are close enough to each other for one night train to plausibly connect them — the candidate set the proposal statistics rank top and flop relations over (GET /api/proposals/stats). One row per unordered country pair, measured between each country's reference station (the catalog stop closest to that country's stop centroid) and routed on real track, so sea crossings that force a long land detour drop out on their own. Derived, rebuildable data, NOT hand-maintained: scripts/build_country_relations.py rebuilds it from the pinned stop catalog, and countries with no stops in the catalog yet simply have no rows.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-country_relations-country_a"></a>`country_a` | First country of the pair — always the alphabetically smaller code, so each pair appears exactly once. | — | — |
| <a id="p-input_params-country_relations-country_b"></a>`country_b` | Second country of the pair — always the alphabetically larger code. | — | — |
| <a id="p-input_params-country_relations-ref_stop_a"></a>`ref_stop_a` | Reference station used for country_a: the catalog stop closest to that country's stop centroid. | — | — |
| <a id="p-input_params-country_relations-ref_stop_b"></a>`ref_stop_b` | Reference station used for country_b. | — | — |
| <a id="p-input_params-country_relations-great_circle_km"></a>`great_circle_km` | Straight-line distance between the two reference stations. Only used to decide whether routing the pair is worth attempting. | km | — |
| <a id="p-input_params-country_relations-rail_km"></a>`rail_km` | Distance on real track between the two reference stations. Empty when no rail path could be found. | km | — |
| <a id="p-input_params-country_relations-rail_time_h"></a>`rail_time_h` | Travel time on that rail path, for a future travel-time-based threshold. Empty when no rail path could be found. | h | — |
| <a id="p-input_params-country_relations-routing_status"></a>`routing_status` | Why this pair does or does not carry a rail distance: routed, prefiltered (too far apart to be worth routing), no_connection (no rail path exists), gauge_mismatch (the two reference stations share no track gauge, so no through service is possible), or snap_failed (a reference station could not be placed on the network). | — | — |
| <a id="p-input_params-country_relations-stop_infra_version"></a>`stop_infra_version` | Stop catalog snapshot the reference stations were picked from. Resolved via scenario.scenarios.stop_infrastructures_version — never inferred. | — | — |
| <a id="p-input_params-country_relations-built_at"></a>`built_at` | When this row was last rebuilt. | — | — |

## `input_params.sources`

Registry of data sources. Every parameter row can point to the source its values came from, so every number in the tool stays traceable. One row per source document or dataset.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-sources-source_id"></a>`source_id` | — | — | — |
| <a id="p-input_params-sources-source_description"></a>`source_description` | Human-readable description of the source (e.g. "DB Netz Trassenpreissystem 2025"). | — | — |
| <a id="p-input_params-sources-source_url"></a>`source_url` | Optional link to the source document or dataset. | — | — |
| <a id="p-input_params-sources-source_date"></a>`source_date` | Date the source data was published or retrieved. | — | — |

## `input_params.service_classes`

Accommodation class taxonomy. service_class_main groups the detailed classes into: Seat, Couchette, Sleeper, Capsule, Catering.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-service_classes-service_class_id"></a>`service_class_id` | Detailed class name (e.g. "couchette (6-berth)", "Sleeper (2-berth) with shower & WC"). | — | — |
| <a id="p-input_params-service_classes-service_class_main"></a>`service_class_main` | Top-level accommodation category: Seat, Couchette, Sleeper, Capsule, or Catering. | — | — |
| <a id="p-input_params-service_classes-service_class_is_night_accommodation"></a>`service_class_is_night_accommodation` | Whether places of this class make the train count as carrying night accommodation for tariff purposes. Germany prices such a train at its night rate over the whole German run (see track_tac_night_full_if_accommodation). True for every class a passenger can lie down in; a dining car alone does not make a night train. | — | — |

## `input_params.operators`

Train operating company and its cost rates. A catalog, not history: operator_id is a permanent natural key — changed rates mean adding a new operator_id, never editing a row in place (soft-referenced from coach_types and composition_types).

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-operators-operator_row_id"></a>`operator_row_id` | — | — | — |
| <a id="p-input_params-operators-operator_id"></a>`operator_id` | Operator identifier (e.g. STD-REF, STD-NEW). | — | — |
| <a id="p-input_params-operators-operator_name"></a>`operator_name` | Full operator name. | — | — |
| <a id="p-input_params-operators-operator_driver_costs_eur_h"></a>`operator_driver_costs_eur_h` | Driver pay per PRODUCTIVE hour, i.e. the raw wage rate before roster inefficiency. Evaluation divides it by the Dienstplanwirkungsgrad it computes per trip from the four roster columns below. | €/h | [driver_eur](/cost/driver) |
| <a id="p-input_params-operators-operator_crew_costs_eur_h"></a>`operator_crew_costs_eur_h` | Cabin crew pay per PRODUCTIVE hour, per attendant, before roster inefficiency (same treatment as the driver rate). The train manager is counted with a factor on the composition. | €/h | [crew_eur](/cost/crew) |
| <a id="p-input_params-operators-operator_driver_max_duty_h"></a>`operator_driver_max_duty_h` | Longest driving time one driver may work between daily rest periods. Directive 2005/47/EC sets 8 h on a night shift (9 h by day); national agreements may be stricter. A trip whose driving time exceeds it needs a relief driver, which lowers the roster efficiency. | h | [roster_efficiency_driver](/reference/formulas#f-calc-roster_efficiency_driver) |
| <a id="p-input_params-operators-operator_crew_max_duty_h"></a>`operator_crew_max_duty_h` | Longest working time one onboard attendant may work between daily rest periods, per the applicable collective agreement. Same relief mechanism as the driver column. | h | — |
| <a id="p-input_params-operators-operator_driver_roster_eff_ref"></a>`operator_driver_roster_eff_ref` | Dienstplanwirkungsgrad for a driver duty that needs no relief: the share of paid hours that is productive once sign-on/off, reserve cover and leave are absorbed. | fraction | [roster_efficiency_driver](/reference/formulas#f-calc-roster_efficiency_driver) |
| <a id="p-input_params-operators-operator_crew_roster_eff_ref"></a>`operator_crew_roster_eff_ref` | Dienstplanwirkungsgrad for an onboard duty that needs no relief. Higher than the driver value: onboard links position less and rest away from base more predictably. | fraction | — |
| <a id="p-input_params-operators-operator_relief_allowance_h"></a>`operator_relief_allowance_h` | Unproductive hours added per relief event — positioning to and from the relief point, the extra sign-on/off, and away-base rest handling. Applied once per additional duty beyond the first, for both roles. | h | [roster_efficiency_driver](/reference/formulas#f-calc-roster_efficiency_driver) |
| <a id="p-input_params-operators-operator_ebit_margin_per"></a>`operator_ebit_margin_per` | Operating profit the operator requires, as a share of ticket revenue. | fraction of revenue | [ebit_margin_eur](/cost/ebit-margin) |
| <a id="p-input_params-operators-operator_financing_quota_per"></a>`operator_financing_quota_per` | Annual financing cost as a share of the capital tied up in coaches. | fraction/year | [financing_eur](/cost/financing) |
| <a id="p-input_params-operators-operator_var_overhead_per"></a>`operator_var_overhead_per` | Variable overhead — ticket sales, distribution, customer service — as a share of ticket revenue. | fraction of revenue | [var_overhead_eur](/cost/var-overhead) |
| <a id="p-input_params-operators-operator_fix_overhead_quota_per"></a>`operator_fix_overhead_quota_per` | Fixed overhead — administration, management, planning — as a share of all other operating costs. | fraction of other costs | [fix_overhead_eur](/cost/fix-overhead) |
| <a id="p-input_params-operators-source_id"></a>`source_id` | Source for all values in this row. | — | — |

## `input_params.operator_class_costs`

Onboard service cost per operator and accommodation class.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-operator_class_costs-operator_row_id"></a>`operator_row_id` | — | — | — |
| <a id="p-input_params-operator_class_costs-service_class_id"></a>`service_class_id` | — | — | — |
| <a id="p-input_params-operator_class_costs-operator_class_svc_stockings_eur_place"></a>`operator_class_svc_stockings_eur_place` | Onboard service cost — bedding, breakfast, amenities — per sold place and trip, for this class. | €/place | [svc_stockings_eur](/cost/svc-stockings) |
| <a id="p-input_params-operator_class_costs-source_id"></a>`source_id` | Source for all values in this row. | — | — |

## `input_params.coach_types`

Individual railcar/coach types. Capacity is derived from coach_type_classes, not stored here. A catalog, not history: coach_type_id is a permanent natural key — a changed spec means a new coach_type_id, never editing a row in place.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-coach_types-coach_type_row_id"></a>`coach_type_row_id` | — | — | — |
| <a id="p-input_params-coach_types-coach_type_id"></a>`coach_type_id` | Coach type name (e.g. WLABmz, Bcmz, type1). | — | — |
| <a id="p-input_params-coach_types-coach_type_operator_id"></a>`coach_type_operator_id` | Operator this coach type belongs to (soft reference to operators.operator_id). Empty for generic/shared types. | — | — |
| <a id="p-input_params-coach_types-coach_type_weight_gross_t"></a>`coach_type_weight_gross_t` | Gross weight of one coach of this type. | t | [train_weight](/reference/formulas#f-energy-train_weight), [stop_dynamics_time_loss](/reference/formulas#f-route-stop_dynamics_time_loss) |
| <a id="p-input_params-coach_types-coach_type_length_m"></a>`coach_type_length_m` | Coach length over buffers — basis of the per-metre purchase price and of the composition's total length. | m | — |
| <a id="p-input_params-coach_types-coach_type_has_wifi"></a>`coach_type_has_wifi` | Coach offers WiFi. A composition offers an amenity if any of its coaches does. | — | — |
| <a id="p-input_params-coach_types-coach_type_length_wo_service_m"></a>`coach_type_length_wo_service_m` | Coach length excluding dining/shared service areas — the passenger-space basis of the class cost split. | m | [class_main_allocation](/reference/formulas#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_types-coach_type_weight_wo_service_t"></a>`coach_type_weight_wo_service_t` | Coach weight excluding service areas. | t | [class_main_allocation](/reference/formulas#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_types-coach_type_bikes"></a>`coach_type_bikes` | Number of bicycle spaces in this coach type. | — | — |
| <a id="p-input_params-coach_types-coach_type_climatization"></a>`coach_type_climatization` | Whether this coach type has air conditioning. | — | — |
| <a id="p-input_params-coach_types-coach_type_plugs"></a>`coach_type_plugs` | Whether this coach type has passenger power sockets. | — | — |
| <a id="p-input_params-coach_types-coach_type_crew_factor"></a>`coach_type_crew_factor` | Cabin crew this coach needs, as a fraction of an attendant (0.5 = one attendant covers two coaches). | — | [crew_eur](/cost/crew) |
| <a id="p-input_params-coach_types-coach_type_remarks"></a>`coach_type_remarks` | Free-text remarks. | — | — |
| <a id="p-input_params-coach_types-source_id"></a>`source_id` | Source for all values in this row. | — | — |

## `input_params.coach_type_classes`

Places per accommodation class within a coach type, with the class section's share of the coach.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-coach_type_classes-coach_type_row_id"></a>`coach_type_row_id` | — | — | — |
| <a id="p-input_params-coach_type_classes-service_class_id"></a>`service_class_id` | — | — | — |
| <a id="p-input_params-coach_type_classes-coach_type_class_places"></a>`coach_type_class_places` | Number of places of this class in the coach type. | places | [class_main_allocation](/reference/formulas#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_type_classes-section_length_m"></a>`section_length_m` | Length of this class's section within the coach — basis of the class cost split and derived per-class densities. | m | [class_main_allocation](/reference/formulas#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_type_classes-section_weight_t"></a>`section_weight_t` | Weight of this class's section within the coach. | t | [class_main_allocation](/reference/formulas#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_type_classes-section_crew_factor"></a>`section_crew_factor` | Cabin crew this class section needs, as a fraction of an attendant. | — | — |
| <a id="p-input_params-coach_type_classes-source_id"></a>`source_id` | Source for all values in this row. | — | — |

## `input_params.composition_types`

Train composition blueprint: which coaches, at which speed, with which cost parameters. Capacity comes from the coach list (composition_type_coaches → coach_type_classes). Which locomotives it hauls comes from composition_type_locos; they are rented, not purchased, and the rate is per operator and machine (operator_loco_costs). A catalog, not history: composition_type_id is a permanent natural key — new settings mean a new composition_type_id, never editing a row in place.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-composition_types-composition_type_row_id"></a>`composition_type_row_id` | — | — | — |
| <a id="p-input_params-composition_types-composition_type_id"></a>`composition_type_id` | Composition name (e.g. STD-3.1). | — | — |
| <a id="p-input_params-composition_types-composition_type_description"></a>`composition_type_description` | Short human-readable description of the composition. | — | — |
| <a id="p-input_params-composition_types-composition_type_operator_id"></a>`composition_type_operator_id` | Operator running this composition (soft reference to operators.operator_id). | — | — |
| <a id="p-input_params-composition_types-composition_type_hsr_allowed"></a>`composition_type_hsr_allowed` | Whether this train may use high-speed lines at all (combined with each country's own permission). | — | — |
| <a id="p-input_params-composition_types-composition_type_max_speed_kmh"></a>`composition_type_max_speed_kmh` | Maximum operational speed. | km/h | — |
| <a id="p-input_params-composition_types-composition_type_min_boarding_time"></a>`composition_type_min_boarding_time` | Minimum waiting time this train needs at stops where passengers board. | interval (hh:mm:ss) | [dwell_time_boarding](/reference/formulas#f-route-dwell_time_boarding), [dwell_time_both](/reference/formulas#f-route-dwell_time_both) |
| <a id="p-input_params-composition_types-composition_type_min_alighting_time"></a>`composition_type_min_alighting_time` | Minimum waiting time this train needs at stops where passengers get off. | interval (hh:mm:ss) | [dwell_time_alighting](/reference/formulas#f-route-dwell_time_alighting), [dwell_time_both](/reference/formulas#f-route-dwell_time_both) |
| <a id="p-input_params-composition_types-composition_type_purchase_coach_eur"></a>`composition_type_purchase_coach_eur` | Average purchase price per coach, from the per-metre price model (new 145 / refurbished 53 k€ per metre of coach, double-deck ×1.12) applied to this composition's coach lengths. Derivation: calib/CALIBRATION.md. | €/coach | [coach_amortisation_eur](/cost/coach-amortisation), [financing_eur](/cost/financing) |
| <a id="p-input_params-composition_types-composition_type_coach_avail_per"></a>`composition_type_coach_avail_per` | Share of calendar days a coach is available for service (the rest it is in the workshop). | fraction | — |
| <a id="p-input_params-composition_types-composition_type_coach_amort_years"></a>`composition_type_coach_amort_years` | Useful life over which a coach is written off. | years | [coach_amortisation_eur](/cost/coach-amortisation) |
| <a id="p-input_params-composition_types-composition_type_cleaning_eur_day"></a>`composition_type_cleaning_eur_day` | Cleaning and preparation for the next night, per coach and operating day, at 2032 prices. | €/coach/day | [cleaning_eur](/cost/cleaning) |
| <a id="p-input_params-composition_types-composition_type_coach_maint_eur_km"></a>`composition_type_coach_maint_eur_km` | Coach maintenance for the whole train per kilometre (per-coach rate × number of coaches; new 1.00 / refurbished 1.30 €/coach-km, 2032 prices). | €/train-km | [coach_maintenance_eur](/cost/coach-maintenance) |
| <a id="p-input_params-composition_types-composition_type_driver_factor"></a>`composition_type_driver_factor` | Number of drivers required per trip (e.g. 1 or 2). | persons | [driver_eur](/cost/driver) |
| <a id="p-input_params-composition_types-composition_type_zugchef_crew_factor"></a>`composition_type_zugchef_crew_factor` | Train manager, counted in attendant-equivalents (1.19; 2.38 for trains with 10 or more coaches). Total crew = sum of coach crew factors + this factor. | attendant-equivalents | — |
| <a id="p-input_params-composition_types-composition_type_length_cost_prop"></a>`composition_type_length_cost_prop` | Weighting X of the class cost split: X by length, (1−X) by weight, on passenger space; service areas are split per place. See calib/CALIBRATION.md. | fraction | [class_main_allocation](/reference/formulas#f-calc-class_main_allocation) |
| <a id="p-input_params-composition_types-composition_type_food_and_beverages"></a>`composition_type_food_and_beverages` | Catering concept (e.g. 'dining car'). Coach amenities aggregate separately. | — | — |
| <a id="p-input_params-composition_types-composition_type_material_strategy"></a>`composition_type_material_strategy` | Rolling stock family: 'new' (230 km/h-capable, 30-year write-off, 0.909 availability) or 'refurbished' (200 km/h cap, 12 years, 0.80). Selects the matching operator row (STD-NEW / STD-REF) and parameter family — see calib/CALIBRATION.md. | — | — |
| <a id="p-input_params-composition_types-composition_type_indicative_cost_eur_train_km"></a>`composition_type_indicative_cost_eur_train_km` | Indicative operator cost per train-kilometre on the 1,000 km reference route (14.5 h trip, 350 operating days, 2 trainsets) at 2032 prices, excluding infrastructure charges, energy, variable overhead and profit — a comparison figure between compositions, not a route evaluation. Derivation: calib/CALIBRATION.md. | €/train-km | — |
| <a id="p-input_params-composition_types-composition_type_indicative_cost_ct_place_km"></a>`composition_type_indicative_cost_ct_place_km` | The same cost basis divided by the number of places. | ct/place-km | — |
| <a id="p-input_params-composition_types-source_id"></a>`source_id` | Source for all values in this row. | — | — |

## `input_params.loco_types`

Locomotive types — the physical machine, independent of who runs it. Weight and speed live here; the rental rate does not, because it is a commercial term that varies by operator (operator_loco_costs), exactly as onboard service cost varies by operator over service_classes. A catalog, not history: loco_type_id is a permanent natural key — a changed spec means a new loco_type_id, never editing a row in place.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-loco_types-loco_type_row_id"></a>`loco_type_row_id` | — | — | — |
| <a id="p-input_params-loco_types-loco_type_id"></a>`loco_type_id` | Stable natural key, e.g. VECTRON-MS-230. | — | — |
| <a id="p-input_params-loco_types-loco_type_description"></a>`loco_type_description` | Machine and configuration in plain words, including the national class designation where the calibration pins one and an explicit note where it does not. | — | — |
| <a id="p-input_params-loco_types-loco_type_traction"></a>`loco_type_traction` | Traction system, e.g. 'electric multi-system'. Not yet read by any model — recorded so a future electrification or traction-change model has it. | — | — |
| <a id="p-input_params-loco_types-loco_type_weight_t"></a>`loco_type_weight_t` | Mass of one locomotive. Completes the gross weight the weight-dependent track access charge and the traction dynamics both work on — coach weight alone is not what gets hauled or weighed. | t | [tac_eur](/cost/tac), [stop_dynamics_time_loss](/reference/formulas#f-route-stop_dynamics_time_loss) |
| <a id="p-input_params-loco_types-loco_type_max_speed_kmh"></a>`loco_type_max_speed_kmh` | Design maximum speed. The composition's own max speed still governs the timetable; this records what the machine could do. | km/h | — |
| <a id="p-input_params-loco_types-source_id"></a>`source_id` | Source for all values in this row. | — | — |
| <a id="p-input_params-loco_types-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |

## `input_params.operator_loco_costs`

Locomotive rental rate per operator and machine — the locomotive counterpart of operator_class_costs. A pairing with no row is not priced, and the loader refuses to resolve a composition that needs one rather than substituting a fallback: a missing pairing is a wiring error, and a silent default would hide exactly the mistake this table exists to catch.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-operator_loco_costs-operator_row_id"></a>`operator_row_id` | — | — | — |
| <a id="p-input_params-operator_loco_costs-loco_type_row_id"></a>`loco_type_row_id` | — | — | — |
| <a id="p-input_params-operator_loco_costs-operator_loco_lease_eur_h"></a>`operator_loco_lease_eur_h` | All-inclusive rental rate (maintenance and insurance included), billed per hour the locomotive is in use. | €/h | [loco_eur](/cost/loco) |
| <a id="p-input_params-operator_loco_costs-source_id"></a>`source_id` | Source for all values in this row. | — | — |

## `input_params.composition_type_locos`

Ordered locomotive slots per composition type — the locomotive counterpart of composition_type_coaches. The number of locomotives is the number of rows here, never a stored column, so the two cannot disagree. position expresses machines hauling TOGETHER (double heading); a traction change part-way along a route is route-dependent and cannot be expressed on a composition type at all — that belongs on the trip when it is modelled.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-composition_type_locos-composition_type_row_id"></a>`composition_type_row_id` | — | — | — |
| <a id="p-input_params-composition_type_locos-position"></a>`position` | 1-based position in the consist. | — | — |
| <a id="p-input_params-composition_type_locos-loco_type_row_id"></a>`loco_type_row_id` | — | — | — |

## `input_params.composition_type_coaches`

Ordered coach slots per composition type.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-composition_type_coaches-composition_type_row_id"></a>`composition_type_row_id` | — | — | — |
| <a id="p-input_params-composition_type_coaches-position"></a>`position` | Position of the coach in the train (1 = first coach behind the locomotive). | — | — |
| <a id="p-input_params-composition_type_coaches-coach_type_row_id"></a>`coach_type_row_id` | — | — | — |

## `input_params.track_infrastructure_defaults`

EU-average fallback track parameters, applied wherever a country's own field is empty. Version bumps are full-table snapshots, resolved via scenario.scenarios.track_infrastructure_defaults_version — see db/README.md for the versioning contract.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-track_infrastructure_defaults-track_infra_default_id"></a>`track_infra_default_id` | — | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_infra_default_key"></a>`track_infra_default_key` | Identifier of the default set (e.g. 'EU'). | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_eur_train_km"></a>`track_tac_eur_train_km` | Indicative track access charge for the reference night train — a single headline number for display and comparison. The cost model does NOT read it: it prices track access from the calibrated component columns further down. | €/train-km | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_src"></a>`track_tac_src` | Source for the track access charge. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_eur_day"></a>`track_parking_eur_day` | Indicative cost of one stabling occupation for the reference train — a single headline number for display and comparison. The cost model does NOT read it: it prices stabling from the basis and rate columns further down, against the actual layover and train length. | €/occupation (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_src"></a>`track_parking_src` | Source for the parking cost. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_shunting_eur_event"></a>`track_shunting_eur_event` | All-in cost of one shunting movement: what the infrastructure manager charges plus what it does not supply. Roughly nine tenths of the figure is the market cost of a shunting locomotive and crew where the IM sells only facility access — see the calibration document. | €/event (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_shunting_src"></a>`track_shunting_src` | Source for the shunting cost. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_energy_price_eur_kwh"></a>`track_energy_price_eur_kwh` | Traction electricity price: the day rate, and the rate around the clock for the twenty-five countries whose tariff is not banded. Where a night band exists the cost model prices the in-band share at track_energy_price_night_eur_kwh instead. | €/kWh (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_energy_price_src"></a>`track_energy_price_src` | Source for the electricity price. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_terrain_category"></a>`track_terrain_category` | Rough terrain classification: Flat, Hilly, or Mountainous. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_terrain_score"></a>`track_terrain_score` | Terrain difficulty score — hills and mountains increase energy use. | 1–100 | — |
| <a id="p-input_params-track_infrastructure_defaults-track_terrain_src"></a>`track_terrain_src` | Source for terrain category and score. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_hsr_allowed"></a>`track_hsr_allowed` | Whether night trains may use the country's high-speed lines. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_hsr_src"></a>`track_hsr_src` | Source for the high-speed permission. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_min_boarding_time"></a>`track_min_boarding_time` | Minimum waiting time the country's stations need at stops where passengers board. | interval (hh:mm:ss) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_min_boarding_src"></a>`track_min_boarding_src` | Source for the minimum boarding time. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_min_alighting_time"></a>`track_min_alighting_time` | Minimum waiting time the country's stations need at stops where passengers get off. | interval (hh:mm:ss) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_min_alighting_src"></a>`track_min_alighting_src` | Source for the minimum alighting time. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_buffer_quota_per"></a>`track_buffer_quota_per` | Schedule buffer added on top of driving time, reflecting how congested and delay-prone the network is. | fraction of driving time | — |
| <a id="p-input_params-track_infrastructure_defaults-track_buffer_src"></a>`track_buffer_src` | Source for the buffer quota. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_b_day"></a>`track_tac_b_day` | Base day rate of the minimum access package. Empty means the country levies no distance-based day rate. | €/train-km (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_b_night"></a>`track_tac_b_night` | Night rate of the minimum access package, charged on the share of a run falling inside the country's night band. Empty means the country has no separate night rate. | €/train-km (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_gamma"></a>`track_tac_gamma` | Weight-dependent term, charged on the whole consist — coaches plus locomotives. | €/gross-tonne-km (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_seat_km"></a>`track_tac_seat_km` | Capacity-dependent term, charged per place the train offers (Spanish corridor surcharge). | €/seat-km (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_per_stop"></a>`track_tac_per_stop` | Per-stop element of the path price: stopping and restarting consumes path capacity (Swiss Haltezuschlag). NOT a station usage fee — those are stop_infrastructures.stop_charge_eur. Charged at each stop's own country rate. | €/stop (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_revenue_share"></a>`track_tac_revenue_share` | Share of the traffic revenue earned in this country that the infrastructure manager takes on top of the distance charges (Swiss Deckungsbeitrag). | fraction | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_fixed_per_train_km"></a>`track_tac_fixed_per_train_km` | Flat administrative add-on charged per kilometre alongside the base rate (Luxembourgish path administration). | €/train-km (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_peak_multiplier"></a>`track_tac_peak_multiplier` | Factor the day rate is multiplied by on the share of a run falling inside the country's peak bands (Swiss NZV: 2). | factor | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_congestion_surcharge_eur_km"></a>`track_tac_congestion_surcharge_eur_km` | Flat surcharge on congested sections, charged on the share of a run falling inside the peak bands (Austrian überlastete Schienenwege). Kept apart from the multiplier above so a congestion charge can be shown as one. | €/train-km (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_night_mode"></a>`track_tac_night_mode` | How the country prices night traffic: 'none' (one rate around the clock) or 'time_band' (the night rate applies pro rata to the time a run spends inside the band below). | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_night_band_start"></a>`track_tac_night_band_start` | Start of the national night tariff band, local clock. Bands may run across midnight (23:00–06:00). | time of day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_night_band_end"></a>`track_tac_night_band_end` | End of the national night tariff band, local clock. | time of day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_night_full_if_accommodation"></a>`track_tac_night_full_if_accommodation` | German SPFV Nacht rule: when true, a train carrying night accommodation (couchette, sleeper or capsule) is priced at the night rate over its ENTIRE run in this country, not just the part inside the band. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_peak_band1_start"></a>`track_tac_peak_band1_start` | Start of the first daily peak band (morning commuter peak), local clock. | time of day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_peak_band1_end"></a>`track_tac_peak_band1_end` | End of the first daily peak band. | time of day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_peak_band2_start"></a>`track_tac_peak_band2_start` | Start of the second daily peak band (evening commuter peak), local clock. | time of day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_peak_band2_end"></a>`track_tac_peak_band2_end` | End of the second daily peak band. | time of day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_peak_weekdays_only"></a>`track_tac_peak_weekdays_only` | Whether the peak bands apply Monday to Friday only. The model knows a departure's clock time but not its weekday, so such a band is charged at its expected value — five sevenths of the overlap. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_energy_price_night_eur_kwh"></a>`track_energy_price_night_eur_kwh` | Traction electricity price inside the country's night tariff band, charged pro rata on the share of a run that falls in it. Empty means one rate around the clock (AT, CH and HR are the only banded tariffs). Never resolved from the defaults row, which leaves it empty: a banded tariff is a national particularity, not a gap to fill. | €/kWh (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_energy_night_band_start"></a>`track_energy_night_band_start` | Start of the national electricity night tariff band, local clock. Bands may run across midnight (22:00–06:00). This is the ENERGY band and is independent of the track access night band (track_tac_night_band_start): Germany bands the track charge 23:00–06:00 and does not band electricity at all, Switzerland the reverse. | time of day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_energy_night_band_end"></a>`track_energy_night_band_end` | End of the national electricity night tariff band, local clock. | time of day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_energy_catenary_eur_train_km"></a>`track_energy_catenary_eur_train_km` | Charge for using the catenary and traction power-supply installations, where the infrastructure manager levies it per train-kilometre (FR, HR, HU, IT, LT, LU, LV, PL, RO). Empty means not levied in this unit — either not levied at all, or charged on weight in the column below, or already inside the energy price. Never resolved from the defaults row: roughly half of Europe's infrastructure managers levy this charge, so an uncalibrated country is priced without one rather than given an invented median. | €/train-km (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_energy_catenary_eur_gross_tonne_km"></a>`track_energy_catenary_eur_gross_tonne_km` | The same supply-equipment charge where the infrastructure manager levies it on the weight moved instead (FI, GR, SK), charged on the whole consist — coaches plus locomotives. | €/gross-tonne-km (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_basis"></a>`track_parking_basis` | How the country prices one stabling occupation: per metre of train length per started 24 hours, per started hour (length-independent, as Germany's Anlagenpreissystem is by design), a flat charge per occupation with no time term, or 'none' where the network statement documents that no siding charge is levied. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_eur_metre_day"></a>`track_parking_eur_metre_day` | Stabling rate where the country prices by length and time. Empty means it prices in one of the other units. | €/metre per started 24 h (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_eur_hour"></a>`track_parking_eur_hour` | Stabling rate where the country prices per started hour, independent of train length. | €/started hour (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_eur_event"></a>`track_parking_eur_event` | Stabling charge where the country prices one occupation flat, with no time or length term. | €/occupation (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_free_hours"></a>`track_parking_free_hours` | Free stabling allowance before the charge starts. Material where it exceeds a layover: Norway's 48 h and Croatia's 24 h zero a twelve-hour turnaround entirely. | hours | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_hotel_power_eur_hour"></a>`track_parking_hotel_power_eur_hour` | Power the train draws while stabled, charged on ACTUAL stabled hours rather than on the billable hours after a free track allowance — the electricity flows whether or not the siding is free. One European proxy rate, from DB InfraGO's unmetered Elektrant flat charge. | €/stabled hour (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructure_defaults-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_infra_default_version"></a>`track_infra_default_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.track_infrastructure_defaults_version — never inferred. | — | — |

## `input_params.track_infrastructures`

Country-level track parameters. Empty fields are resolved against track_infrastructure_defaults by the loader. Version bumps are full-table snapshots — every country's row is duplicated forward on any single-country edit — resolved via scenario.scenarios.track_infrastructures_version. See db/README.md for the versioning contract.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-track_infrastructures-track_infra_row_id"></a>`track_infra_row_id` | — | — | — |
| <a id="p-input_params-track_infrastructures-country_code"></a>`country_code` | Two-letter country code (ISO 3166-1 alpha-2). | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_eur_train_km"></a>`track_tac_eur_train_km` | Indicative track access charge for the reference night train — a single headline number for display and comparison. The cost model does NOT read it: it prices track access from the calibrated component columns further down. | €/train-km | — |
| <a id="p-input_params-track_infrastructures-track_tac_src"></a>`track_tac_src` | Source for the track access charge. | — | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_day"></a>`track_parking_eur_day` | Indicative cost of one stabling occupation for the reference train — a single headline number for display and comparison. The cost model does NOT read it: it prices stabling from the basis and rate columns further down, against the actual layover and train length. | €/occupation (EUR at 2032 prices) | [parking_eur](/cost/parking) |
| <a id="p-input_params-track_infrastructures-track_parking_src"></a>`track_parking_src` | Source for the parking cost. | — | — |
| <a id="p-input_params-track_infrastructures-track_shunting_eur_event"></a>`track_shunting_eur_event` | All-in cost of one shunting movement: what the infrastructure manager charges plus what it does not supply. Roughly nine tenths of the figure is the market cost of a shunting locomotive and crew where the IM sells only facility access — see the calibration document. | €/event (EUR at 2032 prices) | [shunting_eur](/cost/shunting) |
| <a id="p-input_params-track_infrastructures-track_shunting_src"></a>`track_shunting_src` | Source for the shunting cost. | — | — |
| <a id="p-input_params-track_infrastructures-track_energy_price_eur_kwh"></a>`track_energy_price_eur_kwh` | Traction electricity price: the day rate, and the rate around the clock for the twenty-five countries whose tariff is not banded. Where a night band exists the cost model prices the in-band share at track_energy_price_night_eur_kwh instead. | €/kWh (EUR at 2032 prices) | [energy_eur](/cost/energy) |
| <a id="p-input_params-track_infrastructures-track_energy_price_src"></a>`track_energy_price_src` | Source for the electricity price. | — | — |
| <a id="p-input_params-track_infrastructures-track_terrain_category"></a>`track_terrain_category` | Rough terrain classification: Flat, Hilly, or Mountainous. | — | — |
| <a id="p-input_params-track_infrastructures-track_terrain_score"></a>`track_terrain_score` | Terrain difficulty score — hills and mountains increase energy use. | 1–100 | — |
| <a id="p-input_params-track_infrastructures-track_terrain_src"></a>`track_terrain_src` | Source for terrain category and score. | — | — |
| <a id="p-input_params-track_infrastructures-track_hsr_allowed"></a>`track_hsr_allowed` | Whether night trains may use the country's high-speed lines. | — | — |
| <a id="p-input_params-track_infrastructures-track_hsr_src"></a>`track_hsr_src` | Source for the high-speed permission. | — | — |
| <a id="p-input_params-track_infrastructures-track_min_boarding_time"></a>`track_min_boarding_time` | Minimum waiting time the country's stations need at stops where passengers board. | interval (hh:mm:ss) | [dwell_time_boarding](/reference/formulas#f-route-dwell_time_boarding), [dwell_time_both](/reference/formulas#f-route-dwell_time_both) |
| <a id="p-input_params-track_infrastructures-track_min_boarding_src"></a>`track_min_boarding_src` | Source for the minimum boarding time. | — | — |
| <a id="p-input_params-track_infrastructures-track_min_alighting_time"></a>`track_min_alighting_time` | Minimum waiting time the country's stations need at stops where passengers get off. | interval (hh:mm:ss) | [dwell_time_alighting](/reference/formulas#f-route-dwell_time_alighting), [dwell_time_both](/reference/formulas#f-route-dwell_time_both) |
| <a id="p-input_params-track_infrastructures-track_min_alighting_src"></a>`track_min_alighting_src` | Source for the minimum alighting time. | — | — |
| <a id="p-input_params-track_infrastructures-track_buffer_quota_per"></a>`track_buffer_quota_per` | Schedule buffer added on top of driving time, reflecting how congested and delay-prone the network is. | fraction of driving time | [buffer_time](/reference/formulas#f-route-buffer_time) |
| <a id="p-input_params-track_infrastructures-track_buffer_src"></a>`track_buffer_src` | Source for the buffer quota. | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_b_day"></a>`track_tac_b_day` | Base day rate of the minimum access package. Empty means the country levies no distance-based day rate. | €/train-km (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_b_night"></a>`track_tac_b_night` | Night rate of the minimum access package, charged on the share of a run falling inside the country's night band. Empty means the country has no separate night rate. | €/train-km (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_gamma"></a>`track_tac_gamma` | Weight-dependent term, charged on the whole consist — coaches plus locomotives. | €/gross-tonne-km (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_seat_km"></a>`track_tac_seat_km` | Capacity-dependent term, charged per place the train offers (Spanish corridor surcharge). | €/seat-km (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_per_stop"></a>`track_tac_per_stop` | Per-stop element of the path price: stopping and restarting consumes path capacity (Swiss Haltezuschlag). NOT a station usage fee — those are stop_infrastructures.stop_charge_eur. Charged at each stop's own country rate. | €/stop (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_revenue_share"></a>`track_tac_revenue_share` | Share of the traffic revenue earned in this country that the infrastructure manager takes on top of the distance charges (Swiss Deckungsbeitrag). | fraction | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_fixed_per_train_km"></a>`track_tac_fixed_per_train_km` | Flat administrative add-on charged per kilometre alongside the base rate (Luxembourgish path administration). | €/train-km (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_peak_multiplier"></a>`track_tac_peak_multiplier` | Factor the day rate is multiplied by on the share of a run falling inside the country's peak bands (Swiss NZV: 2). | factor | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_congestion_surcharge_eur_km"></a>`track_tac_congestion_surcharge_eur_km` | Flat surcharge on congested sections, charged on the share of a run falling inside the peak bands (Austrian überlastete Schienenwege). Kept apart from the multiplier above so a congestion charge can be shown as one. | €/train-km (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-track_infrastructures-track_tac_night_mode"></a>`track_tac_night_mode` | How the country prices night traffic: 'none' (one rate around the clock) or 'time_band' (the night rate applies pro rata to the time a run spends inside the band below). | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_night_band_start"></a>`track_tac_night_band_start` | Start of the national night tariff band, local clock. Bands may run across midnight (23:00–06:00). | time of day | [tac_night_share](/reference/formulas#f-calc-tac_night_share) |
| <a id="p-input_params-track_infrastructures-track_tac_night_band_end"></a>`track_tac_night_band_end` | End of the national night tariff band, local clock. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_tac_night_full_if_accommodation"></a>`track_tac_night_full_if_accommodation` | German SPFV Nacht rule: when true, a train carrying night accommodation (couchette, sleeper or capsule) is priced at the night rate over its ENTIRE run in this country, not just the part inside the band. | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_peak_band1_start"></a>`track_tac_peak_band1_start` | Start of the first daily peak band (morning commuter peak), local clock. | time of day | [tac_peak_share](/reference/formulas#f-calc-tac_peak_share) |
| <a id="p-input_params-track_infrastructures-track_tac_peak_band1_end"></a>`track_tac_peak_band1_end` | End of the first daily peak band. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_tac_peak_band2_start"></a>`track_tac_peak_band2_start` | Start of the second daily peak band (evening commuter peak), local clock. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_tac_peak_band2_end"></a>`track_tac_peak_band2_end` | End of the second daily peak band. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_tac_peak_weekdays_only"></a>`track_tac_peak_weekdays_only` | Whether the peak bands apply Monday to Friday only. The model knows a departure's clock time but not its weekday, so such a band is charged at its expected value — five sevenths of the overlap. | — | — |
| <a id="p-input_params-track_infrastructures-track_energy_price_night_eur_kwh"></a>`track_energy_price_night_eur_kwh` | Traction electricity price inside the country's night tariff band, charged pro rata on the share of a run that falls in it. Empty means one rate around the clock (AT, CH and HR are the only banded tariffs). Never resolved from the defaults row, which leaves it empty: a banded tariff is a national particularity, not a gap to fill. | €/kWh (EUR at 2032 prices) | [energy_eur](/cost/energy) |
| <a id="p-input_params-track_infrastructures-track_energy_night_band_start"></a>`track_energy_night_band_start` | Start of the national electricity night tariff band, local clock. Bands may run across midnight (22:00–06:00). This is the ENERGY band and is independent of the track access night band (track_tac_night_band_start): Germany bands the track charge 23:00–06:00 and does not band electricity at all, Switzerland the reverse. | time of day | [energy_night_share](/reference/formulas#f-calc-energy_night_share) |
| <a id="p-input_params-track_infrastructures-track_energy_night_band_end"></a>`track_energy_night_band_end` | End of the national electricity night tariff band, local clock. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_energy_catenary_eur_train_km"></a>`track_energy_catenary_eur_train_km` | Charge for using the catenary and traction power-supply installations, where the infrastructure manager levies it per train-kilometre (FR, HR, HU, IT, LT, LU, LV, PL, RO). Empty means not levied in this unit — either not levied at all, or charged on weight in the column below, or already inside the energy price. Never resolved from the defaults row: roughly half of Europe's infrastructure managers levy this charge, so an uncalibrated country is priced without one rather than given an invented median. | €/train-km (EUR at 2032 prices) | [energy_eur](/cost/energy) |
| <a id="p-input_params-track_infrastructures-track_energy_catenary_eur_gross_tonne_km"></a>`track_energy_catenary_eur_gross_tonne_km` | The same supply-equipment charge where the infrastructure manager levies it on the weight moved instead (FI, GR, SK), charged on the whole consist — coaches plus locomotives. | €/gross-tonne-km (EUR at 2032 prices) | [energy_eur](/cost/energy) |
| <a id="p-input_params-track_infrastructures-track_parking_basis"></a>`track_parking_basis` | How the country prices one stabling occupation: per metre of train length per started 24 hours, per started hour (length-independent, as Germany's Anlagenpreissystem is by design), a flat charge per occupation with no time term, or 'none' where the network statement documents that no siding charge is levied. | — | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_metre_day"></a>`track_parking_eur_metre_day` | Stabling rate where the country prices by length and time. Empty means it prices in one of the other units. | €/metre per started 24 h (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_hour"></a>`track_parking_eur_hour` | Stabling rate where the country prices per started hour, independent of train length. | €/started hour (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_event"></a>`track_parking_eur_event` | Stabling charge where the country prices one occupation flat, with no time or length term. | €/occupation (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructures-track_parking_free_hours"></a>`track_parking_free_hours` | Free stabling allowance before the charge starts. Material where it exceeds a layover: Norway's 48 h and Croatia's 24 h zero a twelve-hour turnaround entirely. | hours | — |
| <a id="p-input_params-track_infrastructures-track_parking_hotel_power_eur_hour"></a>`track_parking_hotel_power_eur_hour` | Power the train draws while stabled, charged on ACTUAL stabled hours rather than on the billable hours after a free track allowance — the electricity flows whether or not the siding is free. One European proxy rate, from DB InfraGO's unmetered Elektrant flat charge. | €/stabled hour (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructures-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-track_infrastructures-track_infra_version"></a>`track_infra_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.track_infrastructures_version — never inferred. | — | — |

## `input_params.passage_charges`

Crossings that are charged per traverse instead of per kilometre — the Storebælt and Øresund fixed links and the Channel Tunnel. A crossing is its own entity rather than a country attribute because the charging party is the crossing's operator: Øresund is two rows over one polygon, each infrastructure manager billing its half. Which trip segment crosses which passage is decided at routing time by polygon intersection, so a crossing split by an intermediate stop is still paid for once. Version bumps are full-table snapshots, resolved via scenario.scenarios.passage_charges_version — see db/README.md for the versioning contract.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-passage_charges-passage_row_id"></a>`passage_row_id` | — | — | — |
| <a id="p-input_params-passage_charges-passage_id"></a>`passage_id` | Stable crossing identifier (STOREBAELT, OERESUND_DK, OERESUND_SE, CHANNEL_TUNNEL). | — | — |
| <a id="p-input_params-passage_charges-passage_name"></a>`passage_name` | Full crossing name. | — | — |
| <a id="p-input_params-passage_charges-passage_fixed_eur"></a>`passage_fixed_eur` | Charge per train crossing, one way. | €/traverse (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-passage_charges-passage_per_passenger_eur"></a>`passage_per_passenger_eur` | Charge per carried passenger, one way (Channel Tunnel). Evaluated against the passengers actually aboard on the crossing segment, so this term follows demand. | €/passenger (EUR at 2032 prices) | [tac_eur](/cost/tac) |
| <a id="p-input_params-passage_charges-passage_src"></a>`passage_src` | Source for the crossing charges. | — | — |
| <a id="p-input_params-passage_charges-passage_geom"></a>`passage_geom` | Crossing polygon (SRID 4326). A routed trip leg intersecting it owns the crossing. Static reference geometry — a tunnel does not move between scenarios; what the version pins are the charges. | — | — |
| <a id="p-input_params-passage_charges-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-passage_charges-passage_version"></a>`passage_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.passage_charges_version — never inferred. | — | — |

## `input_params.stop_infrastructure_defaults`

Fallback station charge per country (empty country = global default). Version bumps are full-table snapshots, resolved via scenario.scenarios.stop_infrastructure_defaults_version — see db/README.md for the versioning contract.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-stop_infrastructure_defaults-stop_infra_default_id"></a>`stop_infra_default_id` | — | — | — |
| <a id="p-input_params-stop_infrastructure_defaults-country_code"></a>`country_code` | Country this default applies to. Empty = global fallback. | — | — |
| <a id="p-input_params-stop_infrastructure_defaults-stop_charge_eur"></a>`stop_charge_eur` | Fallback station fee per scheduled stop. | €/stop | — |
| <a id="p-input_params-stop_infrastructure_defaults-stop_charge_src"></a>`stop_charge_src` | Source for the station fee. | — | — |
| <a id="p-input_params-stop_infrastructure_defaults-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-stop_infrastructure_defaults-stop_infra_default_version"></a>`stop_infra_default_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.stop_infrastructure_defaults_version — never inferred. | — | — |

## `input_params.stop_infrastructures`

Catalog of possible night train stops. An empty stop_charge_eur is resolved against stop_infrastructure_defaults by the loader. Version bumps are full-table snapshots — every stop's row is duplicated forward on any single-stop edit — resolved via scenario.scenarios.stop_infrastructures_version. See db/README.md for the versioning contract.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-stop_infrastructures-stop_infra_row_id"></a>`stop_infra_row_id` | — | — | — |
| <a id="p-input_params-stop_infrastructures-stop_id"></a>`stop_id` | Unique stop identifier. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_name"></a>`stop_name` | Official station name. | — | — |
| <a id="p-input_params-stop_infrastructures-country_code"></a>`country_code` | Two-letter country code (ISO 3166-1 alpha-2). | — | — |
| <a id="p-input_params-stop_infrastructures-stop_timezone"></a>`stop_timezone` | IANA timezone identifier (e.g. Europe/Berlin). | — | — |
| <a id="p-input_params-stop_infrastructures-stop_lat"></a>`stop_lat` | Latitude in WGS-84 decimal degrees. | ° | — |
| <a id="p-input_params-stop_infrastructures-stop_lon"></a>`stop_lon` | Longitude in WGS-84 decimal degrees. | ° | — |
| <a id="p-input_params-stop_infrastructures-stop_loc_src"></a>`stop_loc_src` | Source for the coordinates. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_charge_eur"></a>`stop_charge_eur` | Station fee per scheduled stop. Empty = the country or global default applies. | €/stop | [station_charge_eur](/cost/station-charge) |
| <a id="p-input_params-stop_infrastructures-stop_charge_src"></a>`stop_charge_src` | Source for the station fee. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_charge_vat_rate_per"></a>`stop_charge_vat_rate_per` | VAT rate applying to the station charge, as a percentage (19.00 = 19%). NULL where no charge is calibrated. | % | — |
| <a id="p-input_params-stop_infrastructures-stop_charge_incl_vat_eur"></a>`stop_charge_incl_vat_eur` | The station charge including VAT. The model prices from the net stop_charge_eur; this is carried so both figures can be compared against whichever one the tariff document printed. | EUR | — |
| <a id="p-input_params-stop_infrastructures-stop_charge_basis"></a>`stop_charge_basis` | What the charge is per — 'per_call' unless a country's tariff genuinely differs. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_charge_price_basis_year"></a>`stop_charge_price_basis_year` | The year the published figure applies to, before any escalation. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_charge_class"></a>`stop_charge_class` | The country's own category for the station ('Preisklasse 2'), which is why two stations in one country differ. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_charge_source"></a>`stop_charge_source` | source_id of the tariff document the charge was read from, in the charge pipeline's own register (models/infrastructure/stops/charges/01_source_extraction). | — | — |
| <a id="p-input_params-stop_infrastructures-stop_provenance"></a>`stop_provenance` | Why the stop is in the catalog, as a human-readable category (step 10 PROVENANCE_LABELS: 'existing night train stop', 'urban area currently without night train service', ...). The detailed per-stop reasons stay in the pipeline's step 6 notebook. | — | — |
| <a id="p-input_params-stop_infrastructures-name_latin"></a>`name_latin` | Latin-script form of the station name (transliterated where the original is Cyrillic/Greek, otherwise the name itself). | — | — |
| <a id="p-input_params-stop_infrastructures-name_ascii"></a>`name_ascii` | ASCII fold of name_latin — the diacritic-free search form. | — | — |
| <a id="p-input_params-stop_infrastructures-uic_ref"></a>`uic_ref` | UIC station code from OSM, where tagged. Join key for station-charge tariff documents. | — | — |
| <a id="p-input_params-stop_infrastructures-country_en"></a>`country_en` | Country name in 'en' (ISO 3166 translation catalogs via the pipeline). | — | — |
| <a id="p-input_params-stop_infrastructures-country_de"></a>`country_de` | Country name in 'de' (ISO 3166 translation catalogs via the pipeline). | — | — |
| <a id="p-input_params-stop_infrastructures-country_fr"></a>`country_fr` | Country name in 'fr' (ISO 3166 translation catalogs via the pipeline). | — | — |
| <a id="p-input_params-stop_infrastructures-country_nl"></a>`country_nl` | Country name in 'nl' (ISO 3166 translation catalogs via the pipeline). | — | — |
| <a id="p-input_params-stop_infrastructures-country_it"></a>`country_it` | Country name in 'it' (ISO 3166 translation catalogs via the pipeline). | — | — |
| <a id="p-input_params-stop_infrastructures-country_es"></a>`country_es` | Country name in 'es' (ISO 3166 translation catalogs via the pipeline). | — | — |
| <a id="p-input_params-stop_infrastructures-country_pl"></a>`country_pl` | Country name in 'pl' (ISO 3166 translation catalogs via the pipeline). | — | — |
| <a id="p-input_params-stop_infrastructures-city"></a>`city` | Municipality the stop belongs to (Berlin Gesundbrunnen -> Berlin), resolved geographically against OSM place nodes. Empty for rural halts beyond any city/town radius. | — | — |
| <a id="p-input_params-stop_infrastructures-city_osm_id"></a>`city_osm_id` | OSM node id of the resolved place — the stable key behind the localized city names. | — | — |
| <a id="p-input_params-stop_infrastructures-city_en"></a>`city_en` | City name in 'en' from the place node's own name:* tags (exonyms as curated in OSM — an Italian search for 'Monaco' reaches München's stops here). | — | — |
| <a id="p-input_params-stop_infrastructures-city_de"></a>`city_de` | City name in 'de' from the place node's own name:* tags (exonyms as curated in OSM — an Italian search for 'Monaco' reaches München's stops here). | — | — |
| <a id="p-input_params-stop_infrastructures-city_fr"></a>`city_fr` | City name in 'fr' from the place node's own name:* tags (exonyms as curated in OSM — an Italian search for 'Monaco' reaches München's stops here). | — | — |
| <a id="p-input_params-stop_infrastructures-city_nl"></a>`city_nl` | City name in 'nl' from the place node's own name:* tags (exonyms as curated in OSM — an Italian search for 'Monaco' reaches München's stops here). | — | — |
| <a id="p-input_params-stop_infrastructures-city_it"></a>`city_it` | City name in 'it' from the place node's own name:* tags (exonyms as curated in OSM — an Italian search for 'Monaco' reaches München's stops here). | — | — |
| <a id="p-input_params-stop_infrastructures-city_es"></a>`city_es` | City name in 'es' from the place node's own name:* tags (exonyms as curated in OSM — an Italian search for 'Monaco' reaches München's stops here). | — | — |
| <a id="p-input_params-stop_infrastructures-city_pl"></a>`city_pl` | City name in 'pl' from the place node's own name:* tags (exonyms as curated in OSM — an Italian search for 'Monaco' reaches München's stops here). | — | — |
| <a id="p-input_params-stop_infrastructures-gauges_mm"></a>`gauges_mm` | Night-train-capable track gauges at the stop (railway=rail, >= 1435 mm; trams/Stadtbahn/narrow gauge are excluded by the pipeline). Several values at break-of-gauge stations (Kaunas 1435+1520). NULL = no usable tracks found nearby. | mm | — |
| <a id="p-input_params-stop_infrastructures-gauge_evidence"></a>`gauge_evidence` | How the gauge set was established from OSM: tagged tracks, rail present but untagged, only sub-1435 rail nearby (review flag), no rail within the search radius, or a hand-verified override (step 8's GAUGE_OVERRIDES — the station node is right but OSM carries no gauge-tagged way within the radius). | — | — |
| <a id="p-input_params-stop_infrastructures-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_infra_version"></a>`stop_infra_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.stop_infrastructures_version — never inferred. | — | — |

## `scenario.scenarios`

Container pinning one version of each versioned infrastructure table. Exactly one row has is_current_base = TRUE (the live default); exactly one row per scenario_key has is_current_scenario = TRUE (the head of that what-if lineage). All five *_version columns are per-table full-snapshot version numbers, resolved by exact match, and are NOT NULL — a scenario is always a complete, self-contained pin, never a partial diff. routing_graph_key pins the routing graph the same way (the one piece of infrastructure living outside the database). Compositions, coach types, and operators are catalogs, not scenario-versioned. Full versioning contract: db/README.md.

| Parameter | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-scenario-scenarios-scenario_id"></a>`scenario_id` | — | — | — |
| <a id="p-scenario-scenarios-scenario_key"></a>`scenario_key` | Stable identifier for one lineage of scenario edits, e.g. "base", "whatif-de-track-infra". Shared across every row belonging to that lineage; scenario_id changes on every edit, scenario_key does not. | — | — |
| <a id="p-scenario-scenarios-scenario_name"></a>`scenario_name` | Short human-readable label, e.g. "2032 Base Line", "What-if: DE power tax -10%". | — | — |
| <a id="p-scenario-scenarios-description"></a>`description` | Free-text explanation of what this scenario represents and why it exists. | — | — |
| <a id="p-scenario-scenarios-change_log"></a>`change_log` | Free-text summary of what changed relative to the scenario this was derived from — the batch-level narrative; per-value rationale lives in each parameter table's own change_log. | — | — |
| <a id="p-scenario-scenarios-editor"></a>`editor` | User who created this scenario. | — | — |
| <a id="p-scenario-scenarios-created_at"></a>`created_at` | — | — | — |
| <a id="p-scenario-scenarios-is_current_base"></a>`is_current_base` | TRUE for the single live default scenario, used whenever an API call is not given an explicit scenario_id. | — | — |
| <a id="p-scenario-scenarios-is_current_scenario"></a>`is_current_scenario` | TRUE for the newest row within this scenario_key. Exactly one per key. | — | — |
| <a id="p-scenario-scenarios-track_infrastructures_version"></a>`track_infrastructures_version` | Pinned input_params.track_infrastructures version (full-table snapshot). | — | — |
| <a id="p-scenario-scenarios-track_infrastructure_defaults_version"></a>`track_infrastructure_defaults_version` | Pinned input_params.track_infrastructure_defaults version (full-table snapshot). | — | — |
| <a id="p-scenario-scenarios-stop_infrastructures_version"></a>`stop_infrastructures_version` | Pinned input_params.stop_infrastructures version (full-table snapshot). | — | — |
| <a id="p-scenario-scenarios-stop_infrastructure_defaults_version"></a>`stop_infrastructure_defaults_version` | Pinned input_params.stop_infrastructure_defaults version (full-table snapshot). | — | — |
| <a id="p-scenario-scenarios-passage_charges_version"></a>`passage_charges_version` | Pinned input_params.passage_charges version (full-table snapshot). | — | — |
| <a id="p-scenario-scenarios-routing_graph_key"></a>`routing_graph_key` | Routing graph this scenario routes on — the physical rail network (OSM state) behind every distance and travel time, e.g. "infra_2026" or "infra_2032". Pinned like the *_version columns but not itself a snapshot version: the graph lives outside the database, in an OpenRailRouting instance. Naming contract with the deployment: key <k> is served by the instance at env OPENRAILROUTING_URL_<K>, the key uppercased — every graph alike, none implicit — see models/route/routing/rail_router.py. The TAC and passage changes an upgraded network implies are NOT carried here; they ride this same row's track_infrastructures_version and passage_charges_version pins. | — | — |
<!-- END GENERATED: parameters -->
