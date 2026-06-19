# Night Train Route Evaluation Model

A quantitative cost and revenue model for evaluating night train route economics. Built in Python, it combines a routing engine (OpenRailRouting / GraphHopper) with a Google Sheets parameter database to produce a full cost/revenue breakdown per trip, including class-level cost allocation.

---

## Architecture

```
models/
    params.py                                   # Shared parameter dataclasses + collections
    route_evaluation_model/
        data_loader_from_spreadsheet.py         # Google Sheets data access layer
        model.py                                # Cost/revenue model classes
        run_model.py                            # Full pipeline entry point
        model_config.yml                        # Sheet structure configuration
        routing/
            rail_router.py                      # OpenRailRouting wrapper
```

**Pipeline:** `run_model.run()` → load → route → extract → calculate → assemble → `ModelResult`

---

## Database Parameters

All parameters are stored in Google Sheets (`B-o-T_targetnetwork_DB`). The sheet structure is defined in `model_config.yml`.

### Sheet: `c_compositions` — Train Composition Parameters

| Parameter | Column | Description | Unit | Typical Range |
|---|---|---|---|---|
| `comp_id` | A | Unique composition identifier | — | e.g. `NJ-3.1` |
| `comp_description` | D | Human-readable description | — | — |
| `comp_weight_gross_t` | E | Gross weight of full train (loco + coaches) | t | 400–700 |
| `comp_hsr_allowed` | F | Whether composition may use HSR infrastructure | yes/no | — |
| `comp_max_speed_kmh` | G | Maximum operational speed | km/h | 160–250 |
| `comp_company` | J | Operating railway company | — | e.g. `ÖBB` |
| `comp_ebit_margin_per` | K | Required EBIT margin as share of revenue | % | 0–15% |
| `comp_energy_factor_weight` | N | Energy regression: tonne-km coefficient | kWh/(t·km) | 0.00010–0.00025 |
| `comp_energy_factor_speed` | O | Energy regression: speed² coefficient | kWh/((km/h)²·km) | 0.010–0.020 |
| `comp_energy_factor_terrain` | P | Energy regression: terrain score multiplier | — | 0.02–0.05 |
| `comp_seats_total` | T | Total seat capacity (derived formula) | pax | 0–300 |
| `comp_couchettes_total` | U | Total couchette capacity (derived formula) | pax | 0–400 |
| `comp_sleepers_total` | V | Total sleeper capacity (derived formula) | pax | 0–150 |
| `comp_seat_density` | W | Space weight per seat berth (1/seats_per_coach) | — | 0.010–0.025 |
| `comp_couchette_density` | X | Space weight per couchette berth | — | 0.015–0.035 |
| `comp_sleeper_density` | Y | Space weight per sleeper berth | — | 0.025–0.060 |
| `comp_veh_min_boarding_time_h` | Z | Vehicle minimum dwell time at boarding stops | h | 0.017–0.083 |
| `comp_veh_min_alighting_time_h` | AA | Vehicle minimum dwell time at alighting stops | h | 0.017–0.083 |
| `comp_purchase_loco_eur` | AD | Total purchase/leasing cost for all locomotives | € | 3M–10M |
| `comp_purchase_coach_eur` | AE | Total purchase/leasing cost for all coaches | € | 10M–40M |
| `comp_loco_avail_per` | AF | Locomotive availability (share of calendar days) | % | 75–90% |
| `comp_coach_avail_per` | AG | Coach availability (share of calendar days) | % | 75–90% |
| `comp_loco_amort_years` | AH | Locomotive amortisation period | years | 20–35 |
| `comp_coach_amort_years` | AI | Coach amortisation period | years | 25–40 |
| `comp_financing_quota_per` | AJ | Annual financing cost as share of capital employed | %/year | 3–6% |
| `comp_fix_overhead_quota_per` | AK | Fixed overhead as share of operating costs (excl. capital costs). Covers overhead payroll, tools, HQ, marketing, R&D | % | 10–25% |
| `comp_cleaning_services_eur_day` | AL | Daily cleaning and onboard service preparation | €/day | 500–3,000 |
| `comp_shunting_eur_day` | AM | Daily shunting operations at origin/destination | €/day | 300–2,000 |
| `comp_loco_maint_eur_km` | AP | Variable locomotive maintenance cost per km | €/km | 1.0–5.0 |
| `comp_coach_maint_eur_km` | AQ | Variable coach maintenance cost per km | €/km | 1.0–5.0 |
| `comp_driver_costs_eur_h` | AT | Driver staff cost per billable hour | €/h | 60–150 |
| `comp_crew_costs_eur_h` | AU | Cabin crew cost per billable hour | €/h | 40–120 |
| `comp_driver_overhead_h` | AV | Fixed overhead hours added per trip for driver (briefing, handover) | h/trip | 0.5–2.0 |
| `comp_crew_overhead_h` | AW | Fixed overhead hours added per trip for cabin crew | h/trip | 0.5–2.0 |
| `comp_svc_stockings_seat_per` | AZ | Onboard services & stockings for seat class as share of seat revenue | % | 1–5% |
| `comp_svc_stockings_couchette_per` | BA | Onboard services & stockings for couchette class | % | 3–10% |
| `comp_svc_stockings_sleeper_per` | BB | Onboard services & stockings for sleeper class | % | 8–20% |
| `comp_var_overhead_per` | BC | Variable overhead as share of total revenue. Covers customer service, compensations, payments | % | 5–15% |

---

### Sheet: `c_infrastructure` — Per-Country Infrastructure Parameters

One row per country (ISO 3166-1 alpha-2 key). A `_default` row provides fallback values for countries not explicitly listed.

| Parameter | Column | Description | Unit | Typical Range |
|---|---|---|---|---|
| `infra_country_code` | D | ISO 3166-1 alpha-2 country code. Primary key | — | e.g. `AT`, `DE` |
| `infra_country_name` | C | Full country name | — | — |
| `infra_tac_eur_train_km` | F | Track access charge per train-kilometre | €/train-km | 0.5–20.0 |
| `infra_parking_eur_day` | G | Daily stabling/parking fee at origin or destination | €/day | 20–200 |
| `infra_energy_price_eur_kwh` | I | Traction electricity price | €/kWh | 0.10–0.35 |
| `infra_terrain_category` | J | Qualitative terrain classification | — | Flat / Hilly / Mountainous |
| `infra_terrain_score` | K | Numerical terrain difficulty score used in energy regression | 1–100 | 10–90 |
| `infra_hsr_allowed` | M | Whether HSR infrastructure may be used in this country | yes/no | — |
| `infra_min_boarding_time_h` | O | Infrastructure minimum dwell time at boarding stops | h | 0.017–0.083 |
| `infra_min_alighting_time_h` | P | Infrastructure minimum dwell time at alighting stops | h | 0.017–0.083 |
| `infra_buffer_quota_per` | Q | Schedule buffer added on top of driving time (construction, delays) | % | 5–15% |

---

### Sheet: `c_stops` — Stop Parameters

| Parameter | Column | Description | Unit | Typical Range |
|---|---|---|---|---|
| `stop_id` | A | Unique stop identifier. Primary key | — | e.g. `Wien Hbf` |
| `stop_name` | B | Official station name | — | — |
| `stop_country_code` | C | ISO 3166-1 alpha-2 country code | — | e.g. `AT` |
| `stop_lat` | E | Latitude in WGS-84 decimal degrees | ° | 35–72 |
| `stop_lon` | F | Longitude in WGS-84 decimal degrees | ° | -10–40 |
| `stop_charge_eur` | N | Station access charge per train stop | €/stop | 0–500 |

---

### Sheet: `demand` — OD Pair Demand (for future use)

| Parameter | Column | Description | Unit | Typical Range |
|---|---|---|---|---|
| `demand_relation_id` | A | Unique OD relation identifier. Primary key | — | e.g. `AT_WIEN_DE_MUEN` |
| `demand_origin_stop_id` | D | Origin stop ID (must match `stop_id` in `c_stops`) | — | — |
| `demand_destination_stop_id` | E | Destination stop ID | — | — |
| `demand_type` | G | Demand source type | — | e.g. `potential airline shift` |
| `demand_seat_pax` | H | Estimated daily demand for seat class | pax/day | 0–500 |
| `demand_couchette_pax` | I | Estimated daily demand for couchette class | pax/day | 0–500 |
| `demand_sleeper_pax` | J | Estimated daily demand for sleeper class | pax/day | 0–300 |

---

## Runtime Input Parameters

Passed directly to `run_model.run()` — not stored in the spreadsheet.

| Parameter | Description | Unit | Typical Range |
|---|---|---|---|
| `stop_inputs` | Ordered stop list as `(stop_id, stop_type)` pairs. `stop_type`: `boarding` / `alighting` / `both` | — | 2–10 stops |
| `composition_id` | Composition key matching `comp_id` in `c_compositions` | — | e.g. `NJ-3.1` |
| `departure_time_h` | Departure time from first stop in decimal hours | h | 17.0–23.0 |
| `utilization_seat` | Fraction of seat capacity filled per trip | 0–1 | 0.40–0.85 |
| `utilization_couchette` | Fraction of couchette capacity filled per trip | 0–1 | 0.50–0.90 |
| `utilization_sleeper` | Fraction of sleeper capacity filled per trip | 0–1 | 0.55–0.90 |
| `avg_fare_seat` | Average ticket price for seat class | € | 20–120 |
| `avg_fare_couchette` | Average ticket price for couchette class | € | 40–180 |
| `avg_fare_sleeper` | Average ticket price for sleeper class | € | 80–350 |
| `operating_days_year` | Number of operating days per year | days | 300–365 |

---

## Output Parameters

Returned as a `ModelResult` object with three nested breakdowns. Access via `result.summary()`, `result.to_dict()`, or directly via attributes.

### Route Metadata

| Parameter | Description | Unit |
|---|---|---|
| `composition_id` | Composition used | — |
| `total_distance_km` | Total rail distance | km |
| `total_driving_time_h` | Pure driving time (no buffers, no dwell) | h |
| `total_time_h` | Total trip time including buffers | h |
| `operating_days_year` | Operating days used for annual margin | days |
| `capacity_seats` | Total seat capacity | pax |
| `capacity_couchettes` | Total couchette capacity | pax |
| `capacity_sleepers` | Total sleeper capacity | pax |

### Revenue (`result.revenue`)

| Parameter | Description | Unit |
|---|---|---|
| `passengers_seat` | Expected seat passengers per trip | pax |
| `passengers_couchette` | Expected couchette passengers per trip | pax |
| `passengers_sleeper` | Expected sleeper passengers per trip | pax |
| `total_passengers` | Total passengers per trip | pax |
| `revenue_seat` | Seat class revenue per trip | € |
| `revenue_couchette` | Couchette class revenue per trip | € |
| `revenue_sleeper` | Sleeper class revenue per trip | € |
| `total` | Total revenue per trip | € |

### Costs (`result.cost`)

| Parameter | Description | Unit |
|---|---|---|
| `loco_amortisation` | Locomotive amortisation per trip | € |
| `coach_amortisation` | Coach amortisation per trip | € |
| `financing` | Financing cost per trip | € |
| `fix_overhead` | Fixed overhead per trip (% of operating costs) | € |
| `cleaning_services` | Cleaning and service preparation per trip | € |
| `shunting` | Shunting cost per trip | € |
| `parking` | Infrastructure stabling fee per trip | € |
| `fixed_day_total` | Sum of all fixed daily costs | € |
| `loco_maintenance` | Loco variable maintenance per trip | € |
| `coach_maintenance` | Coach variable maintenance per trip | € |
| `variable_km_total` | Sum of variable per-km costs | € |
| `driver` | Driver staff cost per trip | € |
| `crew` | Cabin crew cost per trip | € |
| `variable_hour_total` | Sum of variable per-hour costs | € |
| `svc_stockings_seat` | Onboard services/stockings for seat class | € |
| `svc_stockings_couchette` | Onboard services/stockings for couchette class | € |
| `svc_stockings_sleeper` | Onboard services/stockings for sleeper class | € |
| `var_overhead` | Variable overhead per trip | € |
| `variable_ticket_total` | Sum of variable per-ticket costs | € |
| `track_access` | Track access charges (sum over all country legs) | € |
| `energy` | Traction energy cost (sum over all country legs) | € |
| `station_charges` | Station access charges at intermediate stops | € |
| `infra_total` | Sum of all infrastructure variable costs | € |
| `ebit_margin` | EBIT margin target deducted as cost | € |
| `total` | Total cost per trip | € |

### Class Cost Allocation (`result.allocation`)

| Parameter | Description | Unit |
|---|---|---|
| `space_units_seat` | Total space units allocated to seat class | — |
| `space_units_couchette` | Total space units allocated to couchette class | — |
| `space_units_sleeper` | Total space units allocated to sleeper class | — |
| `total_space_units` | Total space units across all classes | — |
| `cost_seat_class` | Total cost allocated to seat class | € |
| `cost_couchette_class` | Total cost allocated to couchette class | € |
| `cost_sleeper_class` | Total cost allocated to sleeper class | € |
| `cost_per_seat` | Cost per individual seat berth | €/berth |
| `cost_per_couchette` | Cost per individual couchette berth | €/berth |
| `cost_per_sleeper` | Cost per individual sleeper berth | €/berth |

### Summary KPIs (`result`)

| Parameter | Description | Unit |
|---|---|---|
| `margin` | Revenue minus total cost per trip | € |
| `margin_pct` | Margin as share of revenue | % |
| `annual_margin` | Margin × operating days per year | €/year |
| `cost_per_seat_km` | Total cost per available seat-kilometre | €/seat-km |

### Schedule (`result` via `RouteResult`)

The router also returns a full schedule accessible via `route_result.schedule` (list of `ScheduleStop`):

| Field | Description | Unit |
|---|---|---|
| `stop_id` | Stop identifier | — |
| `stop_name` | Stop display name | — |
| `stop_type` | `boarding` / `alighting` / `both` | — |
| `arrival_time_h` | Arrival time in decimal hours (`None` for first stop) | h |
| `departure_time_h` | Departure time in decimal hours (`None` for last stop) | h |
| `dwell_time_h` | Dwell time at stop | h |

---

## Energy Model

Energy consumption is estimated per country leg using a regression model:

```
energy_kwh = weight_gross_t × distance_km × (
    comp_energy_factor_weight
    + comp_energy_factor_speed × avg_speed_kmh²
    + comp_energy_factor_terrain × infra_terrain_score
)
```

**Note:** The energy regression coefficients (`comp_energy_factor_*`) require calibration against real train energy consumption data. The terrain score (`infra_terrain_score`) is a qualitative proxy for gradient difficulty. Elevation data is not currently used by the routing engine — this is a known limitation.

---

## Known Limitations

- **Energy model not calibrated** — regression coefficients are placeholders. A separate regression session against real consumption data is required before energy costs are meaningful.
- **Elevation excluded** — the OpenRailRouting engine does not currently import SRTM elevation data. Terrain score is used as a flat proxy.
- **No demand model** — utilization is a direct runtime input. A demand model based on market share × addressable market is planned for a future version.
- **Country attribution approximation** — country leg boundaries are derived from point-in-polygon midpoint lookups; very short cross-border segments may be misattributed.
- **`UNK` country segments** — small segments that cannot be attributed to any country fall back to the `_default` infrastructure row.