---
title: 'All formulas'
---

# All formulas

<!-- Generated from the model registries. Edit the model, not this page —
     anything outside the GENERATED markers survives regeneration. -->

<!-- BEGIN GENERATED: formulas -->
## Route & timetable builder

### `buffer_time`

<a id="f-route-buffer_time"></a>

Safety margin added to the timetable, sized by how delay-prone each country's network is.

### The formula

$$ t_{buffer,l} = t_{drive,l} \times q_{buffer,country(l)} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_drive,l` | Driving time on one country leg (the part of a segment within one country) | min | computed upstream |
| Input | `q_buffer,country(l)` | That country's schedule buffer, as a share of driving time | fraction | [track_buffer_quota_per](/reference/parameters#p-input_params-track_infrastructures-track_buffer_quota_per) |
| **Result** | `t_buffer,l` | Buffer time added for this country leg | min | — |

**Feeds into:** [total_time_per_leg](/reference/formulas#f-route-total_time_per_leg)

### `total_time_per_leg`

<a id="f-route-total_time_per_leg"></a>

Scheduled time for one country leg: driving, stop braking and acceleration, and buffer.

### The formula

$$ t_{total,l} = t_{drive,l} + t_{dyn,l} + t_{buffer,l} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_drive,l` | Driving time at cruise speed | min | computed upstream |
| Input | `t_dyn,l` | Time lost braking into and accelerating out of stops on this leg | min | [stop_dynamics_time_loss](/reference/formulas#f-route-stop_dynamics_time_loss) |
| Input | `t_buffer,l` | Schedule buffer for this leg | min | [buffer_time](/reference/formulas#f-route-buffer_time) |
| **Result** | `t_total,l` | Scheduled time for the country leg | min | — |

**Feeds into:** [auto_stop_added_time](/reference/formulas#f-route-auto_stop_added_time), [total_time_per_segment](/reference/formulas#f-route-total_time_per_segment)

### `total_time_per_segment`

<a id="f-route-total_time_per_segment"></a>

Scheduled time between two neighbouring stops, summed over its country legs.

### The formula

$$ t_{seg} = \sum_{l \in seg} t_{total,l} + t_{slack,seg} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_total,l` | Scheduled time of each country leg in the segment | min | [total_time_per_leg](/reference/formulas#f-route-total_time_per_leg) |
| Input | `t_slack,seg` | Slack time from night-window stretching (usually zero) | min | computed upstream |
| **Result** | `t_seg` | Scheduled time between the two stops | min | — |

**Feeds into:** [arrival_time](/reference/formulas#f-route-arrival_time), [total_time](/reference/formulas#f-route-total_time)

### `avg_speed`

<a id="f-route-avg_speed"></a>

Distance over pure driving time, buffers excluded — shown for orientation only.

### The formula

$$ \bar{v}_{kmh} = \frac{d_{km}}{t_{drive,h}} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `d_km` | Distance | km | computed upstream |
| Input | `t_drive,h` | Pure driving time | h | computed upstream |
| **Result** | `v̄_kmh` | Average speed | km/h | — |

### `dwell_time_boarding`

<a id="f-route-dwell_time_boarding"></a>

How long the train waits at a stop where passengers only board.

### The formula

$$ t_{dwell} = \max(t_{board,comp},\ t_{board,infra}) $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_board,comp` | Minimum boarding time the train composition needs | min | [composition_type_min_boarding_time](/reference/parameters#p-input_params-composition_types-composition_type_min_boarding_time) |
| Input | `t_board,infra` | Minimum boarding time the station needs | min | [track_min_boarding_time](/reference/parameters#p-input_params-track_infrastructures-track_min_boarding_time) |
| **Result** | `t_dwell` | Waiting time at the stop | min | — |

### `dwell_time_alighting`

<a id="f-route-dwell_time_alighting"></a>

How long the train waits at a stop where passengers only get off.

### The formula

$$ t_{dwell} = \max(t_{alight,comp},\ t_{alight,infra}) $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_alight,comp` | Minimum alighting time the train composition needs | min | [composition_type_min_alighting_time](/reference/parameters#p-input_params-composition_types-composition_type_min_alighting_time) |
| Input | `t_alight,infra` | Minimum alighting time the station needs | min | [track_min_alighting_time](/reference/parameters#p-input_params-track_infrastructures-track_min_alighting_time) |
| **Result** | `t_dwell` | Waiting time at the stop | min | — |

### `dwell_time_both`

<a id="f-route-dwell_time_both"></a>

How long the train waits at a stop where passengers both board and get off.

### The formula

$$ t_{dwell} = \max(t_{board,comp},\ t_{board,infra},\ t_{alight,comp},\ t_{alight,infra}) $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_board,comp` | Minimum boarding time the train composition needs | min | [composition_type_min_boarding_time](/reference/parameters#p-input_params-composition_types-composition_type_min_boarding_time) |
| Input | `t_board,infra` | Minimum boarding time the station needs | min | [track_min_boarding_time](/reference/parameters#p-input_params-track_infrastructures-track_min_boarding_time) |
| Input | `t_alight,comp` | Minimum alighting time the train composition needs | min | [composition_type_min_alighting_time](/reference/parameters#p-input_params-composition_types-composition_type_min_alighting_time) |
| Input | `t_alight,infra` | Minimum alighting time the station needs | min | [track_min_alighting_time](/reference/parameters#p-input_params-track_infrastructures-track_min_alighting_time) |
| **Result** | `t_dwell` | Waiting time at the stop | min | — |

**Feeds into:** [crew_eur](/cost/crew), [driver_eur](/cost/driver), [auto_stop_added_time](/reference/formulas#f-route-auto_stop_added_time), [departure_time](/reference/formulas#f-route-departure_time)

### `auto_stop_added_time`

<a id="f-route-auto_stop_added_time"></a>

Extra travel time an additional stop would cost: detour, stop dynamics and the wait itself.

### The formula

$$ \Delta t_{cand} = \left(\sum_{l \in reroute(a, cand, b)} t_{total,l}\right) - t_{total,(a,b)} + t_{dwell,cand} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `Σ t_total (reroute)` | Travel time of the leg rerouted via the candidate stop | min | [total_time_per_leg](/reference/formulas#f-route-total_time_per_leg) |
| Input | `t_total,(a,b)` | Travel time of the original leg without the stop | min | [total_time_per_leg](/reference/formulas#f-route-total_time_per_leg) |
| Input | `t_dwell,cand` | Waiting time at the candidate stop | min | [dwell_time_both](/reference/formulas#f-route-dwell_time_both) |
| **Result** | `Δt_cand` | Added travel time if the stop is included | min | — |

### `stop_dynamics_time_loss`

<a id="f-route-stop_dynamics_time_loss"></a>

Time lost braking into and accelerating out of every stop, which routing alone ignores.

### The formula

$$ \Delta t_{leg} = \underbrace{\frac{v}{2\,a_{dec}}}_{braking} + \underbrace{t_{acc}(v) - \frac{d_{acc}(v)}{v}}_{acceleration},\quad t_{acc},d_{acc}\ \text{from}\ F(u)=\min\!\left(F_{loco},\ \frac{P_{loco}}{u}\right),\ m = m_{coaches} + m_{loco} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `v` | Cruise speed on the line before and after the stop | km/h | computed upstream |
| Input | `a_dec` | Comfortable service braking deceleration | m/s² | [TRACTION_BRAKE_DECELERATION_MS2](/reference/standard-values#s-route-traction_brake_deceleration_ms2) |
| Input | `F_loco` | Locomotive pulling force from standstill | kN | [TRACTION_LOCO_TRACTIVE_EFFORT_KN](/reference/standard-values#s-route-traction_loco_tractive_effort_kn) |
| Input | `P_loco` | Locomotive power | kW | [TRACTION_LOCO_POWER_KW](/reference/standard-values#s-route-traction_loco_power_kw) |
| Input | `m_coaches` | Weight of all coaches of the composition | t | [coach_type_weight_gross_t](/reference/parameters#p-input_params-coach_types-coach_type_weight_gross_t) |
| Input | `m_loco` | Weight of the assumed standard locomotive | t | [loco_type_weight_t](/reference/parameters#p-input_params-loco_types-loco_type_weight_t) |
| **Result** | `Δt_leg` | Time lost per stop compared to passing at constant speed | min | — |

**Feeds into:** [total_time_per_leg](/reference/formulas#f-route-total_time_per_leg)

### `arrival_time`

<a id="f-route-arrival_time"></a>

When the train reaches a stop.

### The formula

$$ t_{arr,i} = t_{dep,i-1} + t_{seg,i-1} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_dep,i-1` | Departure time at the previous stop | hh:mm | [departure_time](/reference/formulas#f-route-departure_time) |
| Input | `t_seg,i-1` | Scheduled travel time of the segment in between | min | [total_time_per_segment](/reference/formulas#f-route-total_time_per_segment) |
| **Result** | `t_arr,i` | Arrival time at the stop | hh:mm | — |

**Feeds into:** [departure_time](/reference/formulas#f-route-departure_time)

### `departure_time`

<a id="f-route-departure_time"></a>

When the train leaves an intermediate stop.

### The formula

$$ t_{dep,i} = t_{arr,i} + t_{dwell,i} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_arr,i` | Arrival time at the stop | hh:mm | [arrival_time](/reference/formulas#f-route-arrival_time) |
| Input | `t_dwell,i` | Waiting time at the stop | min | [dwell_time_both](/reference/formulas#f-route-dwell_time_both) |
| **Result** | `t_dep,i` | Departure time at the stop | hh:mm | — |

**Feeds into:** [arrival_time](/reference/formulas#f-route-arrival_time)

### `total_distance`

<a id="f-route-total_distance"></a>

Total trip distance across all country legs.

### The formula

$$ d_{total} = \sum_{seg} \sum_{l \in seg} d_{m,l} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `d_m,l` | Distance of each country leg | m | computed upstream |
| **Result** | `d_total` | Total trip distance | m | — |

### `total_driving_time`

<a id="f-route-total_driving_time"></a>

Pure driving time across all country legs, without buffers or waiting times.

### The formula

$$ t_{drive,total} = \sum_{seg} \sum_{l \in seg} t_{drive,l} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_drive,l` | Driving time of each country leg | min | computed upstream |
| **Result** | `t_drive,total` | Total driving time of the trip | min | — |

### `total_time`

<a id="f-route-total_time"></a>

Total scheduled trip time, including buffers, waiting times and stop dynamics.

### The formula

$$ t_{total} = \sum_{seg} t_{seg} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_seg` | Scheduled time of each segment | min | [total_time_per_segment](/reference/formulas#f-route-total_time_per_segment) |
| **Result** | `t_total` | Total scheduled trip time | min | — |

## Energy model

### `energy_per_leg`

<a id="f-energy-energy_per_leg"></a>

Electricity used on one country leg: traction, rolling and air resistance, and on-board power.

### The formula

$$ E_{kWh,l} = A \cdot m_t + d_{km,l} \left( B + C \cdot m_t + (K_m m_t + K_L L_m) \cdot \bar{v}^2_{kmh,l} \right) + (P_{loco} + P_{hotel} \cdot n_{coach}) \cdot t_{h,l} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `m_t` | Coach train weight at 80% load, locomotive excluded | t | [train_weight](/reference/formulas#f-energy-train_weight) |
| Input | `L_m` | Coach rake length, locomotive excluded | m | computed upstream |
| Input | `n_coach` | Number of coaches | 1 | computed upstream |
| Input | `d_km,l` | Distance of the country leg | km | computed upstream |
| Input | `v̄_kmh,l` | Average speed on the leg | km/h | [avg_speed](/reference/formulas#f-energy-avg_speed) |
| Input | `t_h,l` | Driving time on the leg, dynamics included | h | computed upstream |
| Input | `A, B, C, K_m, K_L, P_loco, P_hotel` | Calibrated coefficients, fleet-wide. Fitted against DB Trassenfinder technical runs; the values live in models/energy/calibrated_coefficients.py and are regenerated by calib/02_energy_calibration.ipynb | see models/energy/calibrated_coefficients.py | computed upstream |
| **Result** | `E_kWh,l` | Electricity used on the country leg | kWh | — |

**Feeds into:** [energy_eur](/cost/energy), [energy_per_km](/reference/formulas#f-energy-energy_per_km), [total_energy](/reference/formulas#f-energy-total_energy)

### `energy_per_km`

<a id="f-energy-energy_per_km"></a>

Energy use per kilometre on a country leg, for display and comparison between countries.

### The formula

$$ e_{kWh/km,l} = \frac{E_{kWh,l}}{d_{km,l}} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `E_kWh,l` | Electricity used on the country leg | kWh | [energy_per_leg](/reference/formulas#f-energy-energy_per_leg) |
| Input | `d_km,l` | Distance of the country leg | km | computed upstream |
| **Result** | `e_kWh/km,l` | Energy use per kilometre | kWh/km | — |

### `total_energy`

<a id="f-energy-total_energy"></a>

Total electricity used across the whole trip.

### The formula

$$ E_{total} = \sum_{seg} \sum_{l \in seg} E_{kWh,l} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `E_kWh,l` | Electricity used on each country leg | kWh | [energy_per_leg](/reference/formulas#f-energy-energy_per_leg) |
| **Result** | `E_total` | Total trip energy use | kWh | — |

### `avg_speed`

<a id="f-energy-avg_speed"></a>

Average speed on a country leg; feeds the air-resistance term of the energy model.

### The formula

$$ \bar{v}_{kmh,l} = \frac{d_{km,l}}{t_{drive,h,l}} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `d_km,l` | Distance of the country leg | km | computed upstream |
| Input | `t_drive,h,l` | Driving time on the leg | h | computed upstream |
| **Result** | `v̄_kmh,l` | Average speed on the leg | km/h | — |

**Feeds into:** [energy_per_leg](/reference/formulas#f-energy-energy_per_leg)

### `train_weight`

<a id="f-energy-train_weight"></a>

Train weight as the energy model uses it: coaches at 80% load, locomotive excluded.

### The formula

$$ m_t = \sum_{coach} m_{coach,t} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `m_coach,t` | Weight of each coach | t | [coach_type_weight_gross_t](/reference/parameters#p-input_params-coach_types-coach_type_weight_gross_t) |
| **Result** | `m_t` | Coach train weight, locomotive excluded | t | — |

**Feeds into:** [energy_per_leg](/reference/formulas#f-energy-energy_per_leg)

## Cost allocation to accommodation classes

### Cost share by accommodation class — `class_main_allocation`

<a id="f-calc-class_main_allocation"></a>

How costs shared by the whole train are split between accommodation classes.

### The formula

$$ s_{c} = (1-f_{svc})\left(X \frac{L_c}{L_{rev}} + (1-X)\frac{W_c}{W_{rev}}\right) + f_{svc}\frac{P_c}{P} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `L_c` | Length of the class's sections in the train | m | [section_length_m](/reference/parameters#p-input_params-coach_type_classes-section_length_m) |
| Input | `L_rev` | Length of all passenger space in the train | m | [coach_type_length_wo_service_m](/reference/parameters#p-input_params-coach_types-coach_type_length_wo_service_m) |
| Input | `W_c` | Weight of the class's sections in the train | t | [section_weight_t](/reference/parameters#p-input_params-coach_type_classes-section_weight_t) |
| Input | `W_rev` | Weight of all passenger space in the train | t | [coach_type_weight_wo_service_t](/reference/parameters#p-input_params-coach_types-coach_type_weight_wo_service_t) |
| Input | `X` | Weighting between length and weight (0.7 = 70% length) | fraction | [composition_type_length_cost_prop](/reference/parameters#p-input_params-composition_types-composition_type_length_cost_prop) |
| Input | `f_svc` | Share of the train that is service area (dining etc.) | fraction | computed upstream |
| Input | `P_c` | Places of this class on the train | places | [coach_type_class_places](/reference/parameters#p-input_params-coach_type_classes-coach_type_class_places) |
| Input | `P` | All places on the train | places | [coach_type_class_places](/reference/parameters#p-input_params-coach_type_classes-coach_type_class_places) |
| **Result** | `s_c` | Share of a shared cost carried by the class | fraction | — |

**Feeds into:** [per_sold_place_km_by_class](/reference/formulas#f-calc-per_sold_place_km_by_class)

### Cost per sold place-km, by class — `per_sold_place_km_by_class`

<a id="f-calc-per_sold_place_km_by_class"></a>

A class's cost per sold place-kilometre; empty berths make the sold ones dearer.

### The formula

$$ c_{c} = \frac{s_{c} \cdot C}{pkm^{sold}_{c}} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `s_c` | Share of the cost carried by the class | fraction | [class_main_allocation](/reference/formulas#f-calc-class_main_allocation) |
| Input | `C` | The cost being normalised | €/year | computed upstream |
| Input | `pkm_sold,c` | Sold place-kilometres of the class per year | place-km/year | set by you |
| **Result** | `c_c` | Cost per sold place-kilometre of the class | €/place-km | — |

## Upstream derivations

### Roster efficiency (Dienstplanwirkungsgrad) — `roster_efficiency_driver`

<a id="f-calc-roster_efficiency_driver"></a>

The share of paid staff hours that is actually productive.

### The formula

$$ \eta = \eta_{ref} \cdot \frac{t_{train,h}}{t_{train,h} + t_{relief} \cdot (n_{duty} - 1)}, \quad n_{duty} = \left\lceil \frac{t_{basis,h}}{t_{duty,max}} \right\rceil $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `eta_ref` | Efficiency when the trip fits a single shift (operator_crew_roster_eff_ref for onboard staff) | – | [operator_driver_roster_eff_ref](/reference/parameters#p-input_params-operators-operator_driver_roster_eff_ref) |
| Input | `t_train,h` | Time the staff member is on the train | h | computed upstream |
| Input | `t_basis,h` | Hours measured against the shift cap — driving time for drivers, time on train for onboard staff | h | computed upstream |
| Input | `t_duty,max` | Longest permitted shift (operator_crew_max_duty_h for onboard staff) | h | [operator_driver_max_duty_h](/reference/parameters#p-input_params-operators-operator_driver_max_duty_h) |
| Input | `t_relief` | Unproductive hours added per crew handover | h | [operator_relief_allowance_h](/reference/parameters#p-input_params-operators-operator_relief_allowance_h) |
| **Result** | `eta` | Productive share of paid hours for this trip | – | — |

**Feeds into:** [crew_eur](/cost/crew), [driver_eur](/cost/driver)

### Night share of a country run (track access) — `tac_night_share`

<a id="f-calc-tac_night_share"></a>

How much of a country run is charged at that country's night track rate.

### The formula

$$ \nu_c = \begin{cases} 0 & \text{no night tariff} \\ 1 & \text{widening applies} \\ \dfrac{|[t_{in}, t_{out}) \cap B_{night,c}|}{t_{out} - t_{in}} & \text{otherwise}\end{cases} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_in, t_out` | When the train enters and leaves the country on this segment | min | computed upstream |
| Input | `B_night,c` | The country's night tariff band (band end: track_tac_night_band_end) | time of day | [track_tac_night_band_start](/reference/parameters#p-input_params-track_infrastructures-track_tac_night_band_start) |
| **Result** | `nu_c` | Share of the country run priced at the night rate | – | — |

**Feeds into:** [tac_eur](/cost/tac)

### Rush-hour share of a country run (track access) — `tac_peak_share`

<a id="f-calc-tac_peak_share"></a>

How much of a country run falls inside a rush-hour surcharge window.

### The formula

$$ \pi_c = w \cdot \frac{\sum_{j} |[t_{in}, t_{out}) \cap B_{peak,c,j}|}{t_{out} - t_{in}}, \quad w = \tfrac{5}{7} \text{ if weekdays only, else } 1 $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_in, t_out` | When the train enters and leaves the country on this segment | min | computed upstream |
| Input | `B_peak,c,j` | The country's two daily peak bands (track_tac_peak_band1_* and track_tac_peak_band2_*) | time of day | [track_tac_peak_band1_start](/reference/parameters#p-input_params-track_infrastructures-track_tac_peak_band1_start) |
| Input | `w` | Weekday blend, applied where the bands run Monday to Friday only | – | [WEEKDAY_BLEND](/reference/standard-values#s-infrastructure-weekday_blend) |
| **Result** | `pi_c` | Share of the country run falling in rush hour | – | — |

**Feeds into:** [tac_eur](/cost/tac)

### Night share of a country run (electricity) — `energy_night_share`

<a id="f-calc-energy_night_share"></a>

How much of a country leg's electricity is billed at the night rate.

### The formula

$$ \nu^{E}_{c} = \frac{|[t_{in},t_{out}] \cap B^{E}_{c}|}{t_{out}-t_{in}} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `t_in, t_out` | When the train enters and leaves the country on this segment | min | computed upstream |
| Input | `B^E_c` | The country's electricity night band (track_energy_night_band_start and _end) | time of day | [track_energy_night_band_start](/reference/parameters#p-input_params-track_infrastructures-track_energy_night_band_start) |
| **Result** | `nu^E_c` | Share of the country leg billed at the night rate | – | — |

**Feeds into:** [energy_eur](/cost/energy)

## Generic aggregation

### Generic level total — `total_eur`

<a id="f-calc-total_eur"></a>

The sum of the items directly below this one in the breakdown.

### The formula

$$ x_{total} = \sum_i x_i $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `x_i` | The individual items on that level | €/year | computed upstream |
| **Result** | `x_total` | Sum of the level's items | €/year | — |
<!-- END GENERATED: formulas -->

<FeedbackForm />
