# The Calculation Model

This document is the full, transparent documentation of everything the
Night Train Target Network tool calculates: which models exist, every
formula with its inputs and outputs, every parameter in the database
with its meaning and unit, and where each number comes from. The web
frontend shows a condensed view of the same information — this is the
place to dig deeper.

Everything between the generated markers below is rendered directly
from the code's own model registries (`backend/models/*/model.py`) and
the database schema definition (`backend/db/schema.py`) by
[`generate_model_docs.py`](../backend/scripts/generate_model_docs.py),
so this document can never drift from what the tool actually computes.
The narrative text is written by hand. To regenerate after a model
change: `cd backend && uv run python scripts/generate_model_docs.py`.

**Deeper material this document links into:** composition cost
calibration — [CALIBRATION.md](../backend/models/compositions/calib/CALIBRATION.md) ·
model layer overview — [models/README.md](../backend/models/README.md) ·
database layer & versioning — [db/README.md](../backend/db/README.md) ·
stop catalog classification — [STOP_CLASSIFICATION.md](../backend/models/infrastructure/STOP_CLASSIFICATION.md) ·
proposals subsystem design — [PROPOSALS_DESIGN.md](PROPOSALS_DESIGN.md) ·
API reference — [api/README.md](../backend/api/README.md)

---

## 1. What the tool computes

A user describes a night train route — a list of stops, a train
composition, and a few mode selections — and the tool answers: what
would this route cost per year, what could it earn, and what does that
mean per train-kilometre, per place-kilometre, per country, per
connection?

The computation runs as a pipeline of models, each documented in its
own section below:

```
stops + composition + modes
        │
        ▼
  Route & timetable builder ──► trips, segments, travel & stopping times,
        │                       night schedule mirrored around 02:30
        ▼
  Energy model ──────────────► electricity use per route segment
        │
        ▼
  Demand model (placeholder) ─► places sold & fares per connection
        │
        ▼
  Cost & revenue evaluation ──► annual costs, revenue, net result,
        │                       normalised views (per year / operating
        │                       day / train-km / place-km)
        ▼
  Emissions model ────────────► CO2 comparison vs plane and car
```

Two models have no calculation code of their own but anchor calibrated
parameter sets: the **composition cost model** (what a train costs to
buy and operate — see the [calibration documentation](../backend/models/compositions/calib/CALIBRATION.md))
and the **infrastructure parameter model** (per-country track and
station parameters).

### Model versions

<!-- BEGIN GENERATED: versions -->
| Model | Version | What it computes | Anchor file | Documentation |
|---|---|---|---|---|
| Route & timetable builder | `0.9.31` | Route and timetable builder: turns a list of stops, a train composition, and a few mode selections into a complete route — trip pairs, travel and stopping times with schedule buffers, and a mirrored outbound/return night schedule. | [`model.py`](../backend/models/route/model.py) | [README.md](../backend/models/README.md) |
| Energy model | `1.1.1` | Traction energy model calibrated against Deutsche Bahn Trassenfinder technical runs: start/stop energy per leg, rolling resistance per tonne-kilometre, air resistance growing with train length and the square of average speed, plus a constant auxiliary and hotel-power draw for the running time. Coach hotel power is an assumption, not a measurement - Trassenfinder was queried with it switched off. | [`model.py`](../backend/models/energy/model.py) | [README.md](../backend/models/energy/README.md) |
| Demand model | `0.0.2` | Demand model (placeholder): assumes every accommodation class is 70% booked at a flat per-kilometre fare, spread evenly across all connections — a stand-in until a real demand model with directional demand, price sensitivity, and competition from other modes replaces it. | [`model.py`](../backend/models/demand/model.py) | [README.md](../backend/models/demand/README.md) |
| Cost & revenue evaluation | `0.9.24` | Cost and revenue evaluation: computes the operator's fixed and variable costs, the charges paid to infrastructure companies, and the ticket revenue of a route, then aggregates the result into views per route, trip pair, country, connection, route section, and stop. | [`model.py`](../backend/models/evaluation/model.py) | [README.md](../backend/models/evaluation/README.md) |
| Emissions model | `0.1.1` | Climate impact factors: how many grams of CO2-equivalent one passenger-kilometre causes by night train, plane, and car — used for the mode comparison and the CO2-savings estimate. The night-train value is a European average until a country-resolved, energy-based model replaces it. | [`model.py`](../backend/models/emissions/model.py) | [README.md](../backend/models/emissions/README.md) |
| Composition cost model | `0.9.3` | Composition cost model: calibrated purchase, maintenance, cleaning, crew, and availability parameters per train composition, in a 'new' and a 'refurbished' rolling stock family, at 2032 prices. | [`model.py`](../backend/models/compositions/model.py) | [CALIBRATION.md](../backend/models/compositions/calib/CALIBRATION.md) |
| Infrastructure parameter model | `0.9.5` | Infrastructure parameter model: per-country track access charges, station charges, traction energy prices, shunting and stabling, terrain, schedule supplements and minimum stopping times, with EU-average fallbacks — plus the catalog of possible night train stops. Four calibrated domains, each a package under models/infrastructure/ with its own source register, notebooks and published calibration document. | [`model.py`](../backend/models/infrastructure/model.py) | [STOP_CLASSIFICATION.md](../backend/models/infrastructure/STOP_CLASSIFICATION.md) |
<!-- END GENERATED: versions -->

---

## 2. Route & timetable builder

Turns the user's stop list into a fully timed route. The routing itself
runs on [OpenRailRouting/GraphHopper](../backend/models/route/routing/README.md)
over the OpenStreetMap rail network; the formulas below describe what
the model computes on top of the routed geometry: schedule buffers,
braking/acceleration physics at stops, waiting times, and the night
schedule. Reading aid: a **segment** is the piece of a trip between two
neighbouring stops; a **country leg** is the part of a segment within
one country (charges and buffers are country-specific).

<!-- BEGIN GENERATED: route_formulas -->
<a id="f-route-buffer_time"></a>
#### `buffer_time`

$$ t_{buffer,l} = t_{drive,l} \times q_{buffer,country(l)} $$

Safety margin added to the timetable on top of pure driving time. Each country has its own buffer percentage, reflecting how congested and delay-prone its network is.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_drive,l` | Driving time on one country leg (the part of a segment within one country) | min | computed upstream |
| Input | `q_buffer,country(l)` | That country's schedule buffer, as a share of driving time | fraction | parameter [`track_buffer_quota_per`](#p-input_params-track_infrastructures-track_buffer_quota_per) |
| **Output** | `t_buffer,l` | Buffer time added for this country leg | min | — |

**Used by:** [`total_time_per_leg`](#f-route-total_time_per_leg)

<a id="f-route-total_time_per_leg"></a>
#### `total_time_per_leg`

$$ t_{total,l} = t_{drive,l} + t_{dyn,l} + t_{buffer,l} $$

Scheduled travel time for one country leg: driving time, plus the time lost braking and accelerating at stops, plus the schedule buffer.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_drive,l` | Driving time at cruise speed | min | computed upstream |
| Input | `t_dyn,l` | Time lost braking into and accelerating out of stops on this leg | min | formula [`stop_dynamics_time_loss`](#f-route-stop_dynamics_time_loss) |
| Input | `t_buffer,l` | Schedule buffer for this leg | min | formula [`buffer_time`](#f-route-buffer_time) |
| **Output** | `t_total,l` | Scheduled time for the country leg | min | — |

**Used by:** [`auto_stop_added_time`](#f-route-auto_stop_added_time), [`total_time_per_segment`](#f-route-total_time_per_segment)

<a id="f-route-total_time_per_segment"></a>
#### `total_time_per_segment`

$$ t_{seg} = \sum_{l \in seg} t_{total,l} + t_{slack,seg} $$

Scheduled travel time between two neighbouring stops: the sum of all its country legs, plus any slack added when the timetable is stretched to cover the night window.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_total,l` | Scheduled time of each country leg in the segment | min | formula [`total_time_per_leg`](#f-route-total_time_per_leg) |
| Input | `t_slack,seg` | Slack time from night-window stretching (usually zero) | min | computed upstream |
| **Output** | `t_seg` | Scheduled time between the two stops | min | — |

**Used by:** [`arrival_time`](#f-route-arrival_time), [`total_time`](#f-route-total_time)

<a id="f-route-avg_speed"></a>
#### `avg_speed`

$$ \bar{v}_{kmh} = \frac{d_{km}}{t_{drive,h}} $$

Average speed over a stretch: distance divided by pure driving time, buffers excluded. Shown for orientation only.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `d_km` | Distance | km | computed upstream |
| Input | `t_drive,h` | Pure driving time | h | computed upstream |
| **Output** | `v̄_kmh` | Average speed | km/h | — |

<a id="f-route-dwell_time_boarding"></a>
#### `dwell_time_boarding`

$$ t_{dwell} = \max(t_{board,comp},\ t_{board,infra}) $$

How long the train waits at a stop where passengers board: the larger of the two minimum boarding times — one set by the train, one by the station.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_board,comp` | Minimum boarding time the train composition needs | min | parameter [`composition_type_min_boarding_time`](#p-input_params-composition_types-composition_type_min_boarding_time) |
| Input | `t_board,infra` | Minimum boarding time the station needs | min | parameter [`track_min_boarding_time`](#p-input_params-track_infrastructures-track_min_boarding_time) |
| **Output** | `t_dwell` | Waiting time at the stop | min | — |

<a id="f-route-dwell_time_alighting"></a>
#### `dwell_time_alighting`

$$ t_{dwell} = \max(t_{alight,comp},\ t_{alight,infra}) $$

How long the train waits at a stop where passengers get off: the larger of the two minimum alighting times — one set by the train, one by the station.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_alight,comp` | Minimum alighting time the train composition needs | min | parameter [`composition_type_min_alighting_time`](#p-input_params-composition_types-composition_type_min_alighting_time) |
| Input | `t_alight,infra` | Minimum alighting time the station needs | min | parameter [`track_min_alighting_time`](#p-input_params-track_infrastructures-track_min_alighting_time) |
| **Output** | `t_dwell` | Waiting time at the stop | min | — |

<a id="f-route-dwell_time_both"></a>
#### `dwell_time_both`

$$ t_{dwell} = \max(t_{board,comp},\ t_{board,infra},\ t_{alight,comp},\ t_{alight,infra}) $$

How long the train waits at a stop where passengers both board and get off: the largest of all four minimum times.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_board,comp` | Minimum boarding time the train composition needs | min | parameter [`composition_type_min_boarding_time`](#p-input_params-composition_types-composition_type_min_boarding_time) |
| Input | `t_board,infra` | Minimum boarding time the station needs | min | parameter [`track_min_boarding_time`](#p-input_params-track_infrastructures-track_min_boarding_time) |
| Input | `t_alight,comp` | Minimum alighting time the train composition needs | min | parameter [`composition_type_min_alighting_time`](#p-input_params-composition_types-composition_type_min_alighting_time) |
| Input | `t_alight,infra` | Minimum alighting time the station needs | min | parameter [`track_min_alighting_time`](#p-input_params-track_infrastructures-track_min_alighting_time) |
| **Output** | `t_dwell` | Waiting time at the stop | min | — |

**Used by:** [`crew_eur`](#f-calc-crew_eur), [`driver_eur`](#f-calc-driver_eur), [`auto_stop_added_time`](#f-route-auto_stop_added_time), [`departure_time`](#f-route-departure_time)

<a id="f-route-auto_stop_added_time"></a>
#### `auto_stop_added_time`

$$ \Delta t_{cand} = \left(\sum_{l \in reroute(a, cand, b)} t_{total,l}\right) - t_{total,(a,b)} + t_{dwell,cand} $$

Extra travel time a suggested additional stop would cost: the detour to reach it, the braking and accelerating it causes, and the waiting time at the stop itself. Used to automatically pick extra stops that fit the time budget, and to report suggestions.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `Σ t_total (reroute)` | Travel time of the leg rerouted via the candidate stop | min | formula [`total_time_per_leg`](#f-route-total_time_per_leg) |
| Input | `t_total,(a,b)` | Travel time of the original leg without the stop | min | formula [`total_time_per_leg`](#f-route-total_time_per_leg) |
| Input | `t_dwell,cand` | Waiting time at the candidate stop | min | formula [`dwell_time_both`](#f-route-dwell_time_both) |
| **Output** | `Δt_cand` | Added travel time if the stop is included | min | — |

<a id="f-route-stop_dynamics_time_loss"></a>
#### `stop_dynamics_time_loss`

$$ \Delta t_{leg} = \underbrace{\frac{v}{2\,a_{dec}}}_{braking} + \underbrace{t_{acc}(v) - \frac{d_{acc}(v)}{v}}_{acceleration},\quad t_{acc},d_{acc}\ \text{from}\ F(u)=\min\!\left(F_{loco},\ \frac{P_{loco}}{u}\right),\ m = m_{coaches} + m_{loco} $$

Time lost at every stop because a real train has to brake before it and accelerate after it — the routing engine alone assumes constant cruise speed. Braking uses a comfortable constant deceleration; acceleration follows the physics of a standard locomotive pulling the train's weight.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `v` | Cruise speed on the line before and after the stop | km/h | computed upstream |
| Input | `a_dec` | Comfortable service braking deceleration | m/s² | standard value [`TRACTION_BRAKE_DECELERATION_MS2`](#s-route-traction_brake_deceleration_ms2) |
| Input | `F_loco` | Locomotive pulling force from standstill | kN | standard value [`TRACTION_LOCO_TRACTIVE_EFFORT_KN`](#s-route-traction_loco_tractive_effort_kn) |
| Input | `P_loco` | Locomotive power | kW | standard value [`TRACTION_LOCO_POWER_KW`](#s-route-traction_loco_power_kw) |
| Input | `m_coaches` | Weight of all coaches of the composition | t | parameter [`coach_type_weight_gross_t`](#p-input_params-coach_types-coach_type_weight_gross_t) |
| Input | `m_loco` | Weight of the assumed standard locomotive | t | parameter [`loco_type_weight_t`](#p-input_params-loco_types-loco_type_weight_t) |
| **Output** | `Δt_leg` | Time lost per stop compared to passing at constant speed | min | — |

**Used by:** [`total_time_per_leg`](#f-route-total_time_per_leg)

<a id="f-route-arrival_time"></a>
#### `arrival_time`

$$ t_{arr,i} = t_{dep,i-1} + t_{seg,i-1} $$

Arrival time at a stop: departure time at the previous stop plus the scheduled travel time in between.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_dep,i-1` | Departure time at the previous stop | hh:mm | formula [`departure_time`](#f-route-departure_time) |
| Input | `t_seg,i-1` | Scheduled travel time of the segment in between | min | formula [`total_time_per_segment`](#f-route-total_time_per_segment) |
| **Output** | `t_arr,i` | Arrival time at the stop | hh:mm | — |

**Used by:** [`departure_time`](#f-route-departure_time)

<a id="f-route-departure_time"></a>
#### `departure_time`

$$ t_{dep,i} = t_{arr,i} + t_{dwell,i} $$

Departure time at an intermediate stop: arrival time plus the waiting time at the stop.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_arr,i` | Arrival time at the stop | hh:mm | formula [`arrival_time`](#f-route-arrival_time) |
| Input | `t_dwell,i` | Waiting time at the stop | min | formula [`dwell_time_both`](#f-route-dwell_time_both) |
| **Output** | `t_dep,i` | Departure time at the stop | hh:mm | — |

**Used by:** [`arrival_time`](#f-route-arrival_time)

<a id="f-route-total_distance"></a>
#### `total_distance`

$$ d_{total} = \sum_{seg} \sum_{l \in seg} d_{m,l} $$

Total trip distance: the distances of all country legs added up.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `d_m,l` | Distance of each country leg | m | computed upstream |
| **Output** | `d_total` | Total trip distance | m | — |

<a id="f-route-total_driving_time"></a>
#### `total_driving_time`

$$ t_{drive,total} = \sum_{seg} \sum_{l \in seg} t_{drive,l} $$

Total driving time: the pure driving times of all country legs added up, without buffers or waiting times.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_drive,l` | Driving time of each country leg | min | computed upstream |
| **Output** | `t_drive,total` | Total driving time of the trip | min | — |

<a id="f-route-total_time"></a>
#### `total_time`

$$ t_{total} = \sum_{seg} t_{seg} $$

Total scheduled trip time: all segment times added up — driving, braking and accelerating at stops, buffers, and any slack.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_seg` | Scheduled time of each segment | min | formula [`total_time_per_segment`](#f-route-total_time_per_segment) |
| **Output** | `t_total` | Total scheduled trip time | min | — |
<!-- END GENERATED: route_formulas -->

---

## 3. Energy model

Estimates the electricity a train uses. **Currently a flat placeholder
factor is in use** (see `energy_dummy` below); the weight/speed/terrain
model above it is what the energy team is calibrating against Deutsche
Bahn Trassenfinder data — see the [energy model README](../backend/models/energy/README.md)
and [onboarding notes](../backend/models/energy/ONBOARDING.md).

<!-- BEGIN GENERATED: energy_formulas -->
<a id="f-energy-energy_per_leg"></a>
#### `energy_per_leg`

$$ E_{kWh,l} = A \cdot m_t + d_{km,l} \left( B + C \cdot m_t + (K_m m_t + K_L L_m) \cdot \bar{v}^2_{kmh,l} \right) + (P_{loco} + P_{hotel} \cdot n_{coach}) \cdot t_{h,l} $$

Electricity used on one country leg: start/stop energy for the train's weight, rolling resistance over the distance, air resistance growing with train length and the square of average speed, and the on-board power supply (locomotive systems plus heating, air conditioning and light in the coaches) for as long as the leg takes.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `m_t` | Coach train weight at 80% load, locomotive excluded | t | formula [`train_weight`](#f-energy-train_weight) |
| Input | `L_m` | Coach rake length, locomotive excluded | m | computed upstream |
| Input | `n_coach` | Number of coaches | 1 | computed upstream |
| Input | `d_km,l` | Distance of the country leg | km | computed upstream |
| Input | `v̄_kmh,l` | Average speed on the leg | km/h | formula [`avg_speed`](#f-energy-avg_speed) |
| Input | `t_h,l` | Driving time on the leg, dynamics included | h | computed upstream |
| Input | `A, B, C, K_m, K_L, P_loco, P_hotel` | Calibrated coefficients, fleet-wide. Fitted against DB Trassenfinder technical runs; the values live in models/energy/calibrated_coefficients.py and are regenerated by calib/02_energy_calibration.ipynb | see models/energy/calibrated_coefficients.py | computed upstream |
| **Output** | `E_kWh,l` | Electricity used on the country leg | kWh | — |

**Used by:** [`energy_eur`](#f-calc-energy_eur), [`energy_per_km`](#f-energy-energy_per_km), [`total_energy`](#f-energy-total_energy)

<a id="f-energy-energy_per_km"></a>
#### `energy_per_km`

$$ e_{kWh/km,l} = \frac{E_{kWh,l}}{d_{km,l}} $$

Energy use per kilometre on a country leg: total energy divided by distance. Used for display and for comparing countries.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `E_kWh,l` | Electricity used on the country leg | kWh | formula [`energy_per_leg`](#f-energy-energy_per_leg) |
| Input | `d_km,l` | Distance of the country leg | km | computed upstream |
| **Output** | `e_kWh/km,l` | Energy use per kilometre | kWh/km | — |

<a id="f-energy-total_energy"></a>
#### `total_energy`

$$ E_{total} = \sum_{seg} \sum_{l \in seg} E_{kWh,l} $$

Total electricity used on the trip: the energy of all country legs added up.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `E_kWh,l` | Electricity used on each country leg | kWh | formula [`energy_per_leg`](#f-energy-energy_per_leg) |
| **Output** | `E_total` | Total trip energy use | kWh | — |

<a id="f-energy-avg_speed"></a>
#### `avg_speed`

$$ \bar{v}_{kmh,l} = \frac{d_{km,l}}{t_{drive,h,l}} $$

Average speed per country leg: distance divided by driving time. Feeds the air resistance term of the energy model.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `d_km,l` | Distance of the country leg | km | computed upstream |
| Input | `t_drive,h,l` | Driving time on the leg | h | computed upstream |
| **Output** | `v̄_kmh,l` | Average speed on the leg | km/h | — |

**Used by:** [`energy_per_leg`](#f-energy-energy_per_leg)

<a id="f-energy-train_weight"></a>
#### `train_weight`

$$ m_t = \sum_{coach} m_{coach,t} $$

Train weight as the energy model uses it: all coach gross weights at 80% load added up, WITHOUT the locomotive. The calibration data was collected on this basis (Trassenfinder's Wagenzugmasse excludes the traction unit), so the locomotive's own resistance is inside the per-km constant B rather than scaled by weight.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `m_coach,t` | Weight of each coach | t | parameter [`coach_type_weight_gross_t`](#p-input_params-coach_types-coach_type_weight_gross_t) |
| **Output** | `m_t` | Coach train weight, locomotive excluded | t | — |

**Used by:** [`energy_per_leg`](#f-energy-energy_per_leg)
<!-- END GENERATED: energy_formulas -->

---

## 4. Demand model (placeholder)

There is no real demand model yet: every accommodation class is assumed
70% booked at a flat per-kilometre fare, spread evenly across all
connections. Ticket counts and prices in the evaluation are therefore
**user inputs or placeholder assumptions, not predictions** — every
revenue figure must be read with that in mind. The planned replacement
(directional demand, price sensitivity, competition from plane and car)
is described in the [demand model README](../backend/models/demand/README.md).

---

## 5. Cost & revenue evaluation

The heart of the tool: computes every operator cost line, every charge
paid to infrastructure companies, and ticket revenue, then aggregates
the result into views. All cost and revenue leaves below are **annual
figures for the selected part of the route** — the whole route, one
trip pair, one country, one connection, one route section, or one stop.
Each view offers the same figures in five normalisations: per year, per
operating day, per train-kilometre, per available place-kilometre, and
per sold place-kilometre, each additionally split by accommodation
class. The formulas below follow the tool's own cost/revenue tree
exactly (`backend/models/evaluation/views.py`): each subtotal — total
cost, operator cost, variable, fixed, infrastructure — appears with its
own formula directly above the leaves it sums, so the tree can be
followed top to bottom or clicked through bottom-up via each leaf's
source link. How costs are split across accommodation classes is
documented first, as it feeds every per-class normalisation.

<!-- BEGIN GENERATED: calc_formulas -->
**Cost allocation to accommodation classes** — an upstream step used by every per-class normalisation below, not a cost or revenue line itself:

<a id="f-calc-class_main_allocation"></a>
#### Cost share by accommodation class — `class_main_allocation`

$$ s_{c} = (1-f_{svc})\left(X \frac{L_c}{L_{rev}} + (1-X)\frac{W_c}{W_{rev}}\right) + f_{svc}\frac{P_c}{P} $$

How costs shared by the whole train are split between accommodation classes (seat, couchette, sleeper, ...): mostly by how much of the train's length and weight a class occupies; dining and service areas are split evenly per place.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `L_c` | Length of the class's sections in the train | m | parameter [`section_length_m`](#p-input_params-coach_type_classes-section_length_m) |
| Input | `L_rev` | Length of all passenger space in the train | m | parameter [`coach_type_length_wo_service_m`](#p-input_params-coach_types-coach_type_length_wo_service_m) |
| Input | `W_c` | Weight of the class's sections in the train | t | parameter [`section_weight_t`](#p-input_params-coach_type_classes-section_weight_t) |
| Input | `W_rev` | Weight of all passenger space in the train | t | parameter [`coach_type_weight_wo_service_t`](#p-input_params-coach_types-coach_type_weight_wo_service_t) |
| Input | `X` | Weighting between length and weight (0.7 = 70% length) | fraction | parameter [`composition_type_length_cost_prop`](#p-input_params-composition_types-composition_type_length_cost_prop) |
| Input | `f_svc` | Share of the train that is service area (dining etc.) | fraction | computed upstream |
| Input | `P_c` | Places of this class on the train | places | parameter [`coach_type_class_places`](#p-input_params-coach_type_classes-coach_type_class_places) |
| Input | `P` | All places on the train | places | parameter [`coach_type_class_places`](#p-input_params-coach_type_classes-coach_type_class_places) |
| **Output** | `s_c` | Share of a shared cost carried by the class | fraction | — |

**Used by:** [`per_sold_place_km_by_class`](#f-calc-per_sold_place_km_by_class)

<a id="f-calc-per_sold_place_km_by_class"></a>
#### Cost per sold place-km, by class — `per_sold_place_km_by_class`

$$ c_{c} = \frac{s_{c} \cdot C}{pkm^{sold}_{c}} $$

Cost per sold place-kilometre of one class: the class's share of a cost divided by the place-kilometres it actually sells. Empty berths make the sold ones more expensive.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `s_c` | Share of the cost carried by the class | fraction | formula [`class_main_allocation`](#f-calc-class_main_allocation) |
| Input | `C` | The cost being normalised | €/year | computed upstream |
| Input | `pkm_sold,c` | Sold place-kilometres of the class per year | place-km/year | set by the tool user |
| **Output** | `c_c` | Cost per sold place-kilometre of the class | €/place-km | — |

**Upstream derivations** — quantities the cost leaves below divide or multiply by, computed per trip rather than read from a parameter:

<a id="f-calc-roster_efficiency_driver"></a>
#### Roster efficiency (Dienstplanwirkungsgrad) — `roster_efficiency_driver`

$$ \eta = \eta_{ref} \cdot \frac{t_{train,h}}{t_{train,h} + t_{relief} \cdot (n_{duty} - 1)}, \quad n_{duty} = \left\lceil \frac{t_{basis,h}}{t_{duty,max}} \right\rceil $$

Dienstplanwirkungsgrad — the share of paid staff hours that is actually productive. Paid time exceeds time on the train because of sign-on and sign-off, positioning to and from the train, rest away from the home base, and reserve cover. A shift may not exceed a legal maximum, so a long trip has to be worked by two or more crews in succession; each handover adds a fixed unproductive allowance. The value therefore drops at every shift boundary and then recovers as that fixed allowance is spread over a longer trip.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `eta_ref` | Efficiency when the trip fits a single shift (operator_crew_roster_eff_ref for onboard staff) | – | parameter [`operator_driver_roster_eff_ref`](#p-input_params-operators-operator_driver_roster_eff_ref) |
| Input | `t_train,h` | Time the staff member is on the train | h | computed upstream |
| Input | `t_basis,h` | Hours measured against the shift cap — driving time for drivers, time on train for onboard staff | h | computed upstream |
| Input | `t_duty,max` | Longest permitted shift (operator_crew_max_duty_h for onboard staff) | h | parameter [`operator_driver_max_duty_h`](#p-input_params-operators-operator_driver_max_duty_h) |
| Input | `t_relief` | Unproductive hours added per crew handover | h | parameter [`operator_relief_allowance_h`](#p-input_params-operators-operator_relief_allowance_h) |
| **Output** | `eta` | Productive share of paid hours for this trip | – | — |

**Used by:** [`crew_eur`](#f-calc-crew_eur), [`driver_eur`](#f-calc-driver_eur)

<a id="f-calc-tac_night_share"></a>
#### Night share of a country run (track access) — `tac_night_share`

$$ \nu_c = \begin{cases} 0 & \text{no night tariff} \\ 1 & \text{widening applies} \\ \dfrac{|[t_{in}, t_{out}) \cap B_{night,c}|}{t_{out} - t_{in}} & \text{otherwise}\end{cases} $$

How much of a country run is charged at the night rate. Countries with a night tariff define a band — Germany 23:00 to 06:00, for instance — and the run is split between day and night rate in proportion to the clock time it actually spends inside it, rather than being priced entirely one way based on where its middle falls. Germany adds a rule of its own: a train carrying couchettes, sleepers or capsules is charged the night rate over its whole German run, whatever the clock says.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_in, t_out` | When the train enters and leaves the country on this segment | min | computed upstream |
| Input | `B_night,c` | The country's night tariff band (band end: track_tac_night_band_end) | time of day | parameter [`track_tac_night_band_start`](#p-input_params-track_infrastructures-track_tac_night_band_start) |
| **Output** | `nu_c` | Share of the country run priced at the night rate | – | — |

**Used by:** [`tac_eur`](#f-calc-tac_eur)

<a id="f-calc-tac_peak_share"></a>
#### Rush-hour share of a country run (track access) — `tac_peak_share`

$$ \pi_c = w \cdot \frac{\sum_{j} |[t_{in}, t_{out}) \cap B_{peak,c,j}|}{t_{out} - t_{in}}, \quad w = \tfrac{5}{7} \text{ if weekdays only, else } 1 $$

How much of a country run falls in rush hour. Austria and Switzerland charge extra for running through a congested area during the morning or evening commuter peak. Because the tool knows a departure's clock time but not which day of the week it runs, a peak that applies Monday to Friday only is charged at five sevenths of the overlap — the average over a week — rather than all or nothing.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_in, t_out` | When the train enters and leaves the country on this segment | min | computed upstream |
| Input | `B_peak,c,j` | The country's two daily peak bands (track_tac_peak_band1_* and track_tac_peak_band2_*) | time of day | parameter [`track_tac_peak_band1_start`](#p-input_params-track_infrastructures-track_tac_peak_band1_start) |
| Input | `w` | Weekday blend, applied where the bands run Monday to Friday only | – | standard value [`WEEKDAY_BLEND`](#s-infrastructure-weekday_blend) |
| **Output** | `pi_c` | Share of the country run falling in rush hour | – | — |

**Used by:** [`tac_eur`](#f-calc-tac_eur)

<a id="f-calc-energy_night_share"></a>
#### Night share of a country run (electricity) — `energy_night_share`

$$ \nu^{E}_{c} = \frac{|[t_{in},t_{out}] \cap B^{E}_{c}|}{t_{out}-t_{in}} $$

Share of a country leg whose electricity is billed at the night rate: how much of the time the train spends in the country falls inside that country's electricity night tariff window. Only Austria, Switzerland and Croatia have one. The share of the clock is applied to the kilowatt-hours drawn, which is exact at constant speed — the routed geometry does not record where along the leg the clock crossed the boundary. This window is not the track access night band: Germany discounts track access at night and not electricity, Switzerland the reverse.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `t_in, t_out` | When the train enters and leaves the country on this segment | min | computed upstream |
| Input | `B^E_c` | The country's electricity night band (track_energy_night_band_start and _end) | time of day | parameter [`track_energy_night_band_start`](#p-input_params-track_infrastructures-track_energy_night_band_start) |
| **Output** | `nu^E_c` | Share of the country leg billed at the night rate | – | — |

**Used by:** [`energy_eur`](#f-calc-energy_eur)

**The cost/revenue tree** — every subtotal shown with the exact leaves it sums, in the same structure as the tool's cost breakdown views:

<a id="f-calc-total_cost_eur"></a>
#### Total cost — `total_cost_eur`

$$ C_{total} = C_{operator} + C_{infrastructure} $$

Total annual cost: everything the operator spends plus everything paid to infrastructure companies.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `C_operator` | All operator costs, fixed and variable | €/year | formula [`operator_total_eur`](#f-calc-operator_total_eur) |
| Input | `C_infrastructure` | All charges paid to infrastructure companies | €/year | formula [`infrastructure_total_eur`](#f-calc-infrastructure_total_eur) |
| **Output** | `C_total` | Total annual cost | €/year | — |

**Used by:** [`net_eur`](#f-calc-net_eur)

<a id="f-calc-operator_total_eur"></a>
##### Operator cost — `operator_total_eur`

$$ C_{operator} = C_{op,var} + C_{op,fix} $$

Everything the operator spends: variable costs plus fixed costs.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `C_op,var` | Total variable operator cost | €/year | formula [`operator_variable_total_eur`](#f-calc-operator_variable_total_eur) |
| Input | `C_op,fix` | Total fixed operator cost | €/year | formula [`operator_fixed_total_eur`](#f-calc-operator_fixed_total_eur) |
| **Output** | `C_operator` | Total operator cost | €/year | — |

**Used by:** [`total_cost_eur`](#f-calc-total_cost_eur)

<a id="f-calc-operator_variable_total_eur"></a>
###### Variable operator cost — `operator_variable_total_eur`

$$ C_{op,var} = C_{driver} + C_{crew} + C_{coach,maint} + C_{loco} + C_{svc} + C_{var,oh} $$

Costs that scale with how much the train runs — driving and staffing hours, kilometres, tickets sold.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `C_driver` | Driver cost | €/year | formula [`driver_eur`](#f-calc-driver_eur) |
| Input | `C_crew` | Cabin crew cost | €/year | formula [`crew_eur`](#f-calc-crew_eur) |
| Input | `C_coach,maint` | Coach maintenance cost | €/year | formula [`coach_maintenance_eur`](#f-calc-coach_maintenance_eur) |
| Input | `C_loco` | Locomotive rental cost | €/year | formula [`loco_eur`](#f-calc-loco_eur) |
| Input | `C_svc` | Onboard service cost | €/year | formula [`svc_stockings_eur`](#f-calc-svc_stockings_eur) |
| Input | `C_var,oh` | Variable overhead | €/year | formula [`var_overhead_eur`](#f-calc-var_overhead_eur) |
| **Output** | `C_op,var` | Total variable operator cost | €/year | — |

**Used by:** [`operator_total_eur`](#f-calc-operator_total_eur)

<a id="f-calc-driver_eur"></a>
####### Driver cost — `driver_eur`

$$ C_{driver} = \frac{c_{driver/h}}{\eta_{driver}} \times \left( \sum_{seg} t_{drive,h} \cdot f_{driver} + \sum_{stop} t_{dwell,h} \cdot f_{driver} \right) $$

Driver cost: the driver wage per productive hour, divided by the share of paid hours that is productive, times all hours the driver is on duty — driving between stops and waiting at them. Trips too long for one driver shift need a relief driver, which lowers that share and raises the effective rate.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_driver/h` | Driver wage per productive hour | €/h | parameter [`operator_driver_costs_eur_h`](#p-input_params-operators-operator_driver_costs_eur_h) |
| Input | `eta_driver` | Share of paid driver hours that is productive | – | formula [`roster_efficiency_driver`](#f-calc-roster_efficiency_driver) |
| Input | `t_drive,h` | Driving time between stops | h | computed upstream |
| Input | `t_dwell,h` | Waiting time at stops | h | formula [`dwell_time_both`](#f-route-dwell_time_both) |
| Input | `f_driver` | Number of drivers the train needs | persons | parameter [`composition_type_driver_factor`](#p-input_params-composition_types-composition_type_driver_factor) |
| **Output** | `C_driver` | Annual driver cost | €/year | — |

**Used by:** [`operator_variable_total_eur`](#f-calc-operator_variable_total_eur)

<a id="f-calc-crew_eur"></a>
####### Cabin crew cost — `crew_eur`

$$ C_{crew} = \frac{c_{crew/h}}{\eta_{crew}} \times \left( \sum_{seg} t_{drive,h} \cdot n_{crew} + \sum_{stop} t_{dwell,h} \cdot n_{crew} \right) $$

Cabin crew cost: the crew wage per productive hour, divided by the share of paid hours that is productive, times all hours the crew is on board — while driving and while waiting at stops. Trips too long for one shift need a relief crew, which lowers that share and raises the effective rate.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_crew/h` | Crew wage per productive hour, per attendant | €/h | parameter [`operator_crew_costs_eur_h`](#p-input_params-operators-operator_crew_costs_eur_h) |
| Input | `eta_crew` | Share of paid crew hours that is productive | – | formula [`roster_efficiency_driver`](#f-calc-roster_efficiency_driver) |
| Input | `t_drive,h` | Driving time between stops | h | computed upstream |
| Input | `t_dwell,h` | Waiting time at stops | h | formula [`dwell_time_both`](#f-route-dwell_time_both) |
| Input | `n_crew` | Crew members on board (train manager counted with a factor) | persons | parameter [`coach_type_crew_factor`](#p-input_params-coach_types-coach_type_crew_factor) |
| **Output** | `C_crew` | Annual cabin crew cost | €/year | — |

**Used by:** [`operator_variable_total_eur`](#f-calc-operator_variable_total_eur)

<a id="f-calc-coach_maintenance_eur"></a>
####### Coach maintenance — `coach_maintenance_eur`

$$ C_{coach,maint} = \sum_{seg} c_{coach,maint/km} \times d_{km,seg} $$

Coach maintenance: a per-kilometre rate for the whole train times the distance driven. Locomotive maintenance is included in the locomotive rental instead.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_coach,maint/km` | Maintenance rate for all coaches of the train, per kilometre | €/train-km | parameter [`composition_type_coach_maint_eur_km`](#p-input_params-composition_types-composition_type_coach_maint_eur_km) |
| Input | `d_km,seg` | Distance driven | km | computed upstream |
| **Output** | `C_coach,maint` | Annual coach maintenance cost | €/year | — |

**Used by:** [`operator_variable_total_eur`](#f-calc-operator_variable_total_eur)

<a id="f-calc-loco_eur"></a>
####### Locomotive rental — `loco_eur`

$$ C_{loco} = c_{loco,lease/h} \times \frac{t_{loco,propulsion,min}}{60} $$

Locomotive rental: an all-inclusive hourly rate (maintenance and insurance included) times the hours the locomotive is in use. A locomotive shared between several trips is only counted once.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_loco,lease/h` | All-inclusive locomotive rental rate per hour in use | €/h | parameter [`operator_loco_lease_eur_h`](#p-input_params-operator_loco_costs-operator_loco_lease_eur_h) |
| Input | `t_loco,propulsion,min` | Minutes the locomotive is in use | min | computed upstream |
| **Output** | `C_loco` | Annual locomotive rental cost | €/year | — |

**Used by:** [`operator_variable_total_eur`](#f-calc-operator_variable_total_eur)

<a id="f-calc-svc_stockings_eur"></a>
####### Onboard service — `svc_stockings_eur`

$$ C_{svc} = \sum_{od} c_{svc,class(od)/place} \times n_{places\_sold,od} $$

Onboard service cost — bedding, breakfast, amenities: a per-passenger rate for each accommodation class times the tickets sold in that class.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_svc,class/place` | Service cost per sold place, by class | €/place | parameter [`operator_class_svc_stockings_eur_place`](#p-input_params-operator_class_costs-operator_class_svc_stockings_eur_place) |
| Input | `n_places_sold,od` | Places sold per connection and year | places/year | set by the tool user |
| **Output** | `C_svc` | Annual onboard service cost | €/year | — |

**Used by:** [`operator_variable_total_eur`](#f-calc-operator_variable_total_eur)

<a id="f-calc-var_overhead_eur"></a>
####### Variable overhead — `var_overhead_eur`

$$ C_{var,oh} = \sum_{od} R_{od} \times q_{var,oh} $$

Variable overhead — ticket sales, distribution, customer service: a fixed share of ticket revenue.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `R_od` | Ticket revenue per connection and year | €/year | formula [`ticket_revenue_eur`](#f-calc-ticket_revenue_eur) |
| Input | `q_var,oh` | Overhead share of revenue | fraction | parameter [`operator_var_overhead_per`](#p-input_params-operators-operator_var_overhead_per) |
| **Output** | `C_var,oh` | Annual variable overhead | €/year | — |

**Used by:** [`fix_overhead_eur`](#f-calc-fix_overhead_eur), [`operator_variable_total_eur`](#f-calc-operator_variable_total_eur)

<a id="f-calc-operator_fixed_total_eur"></a>
###### Fixed operator cost — `operator_fixed_total_eur`

$$ C_{op,fix} = C_{coach,amort} + C_{fin} + C_{fix,oh} + C_{clean} + C_{shunt} $$

Costs that stay the same regardless of how much the train runs.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `C_coach,amort` | Coach write-off | €/year | formula [`coach_amortisation_eur`](#f-calc-coach_amortisation_eur) |
| Input | `C_fin` | Financing cost | €/year | formula [`financing_eur`](#f-calc-financing_eur) |
| Input | `C_fix,oh` | Fixed overhead | €/year | formula [`fix_overhead_eur`](#f-calc-fix_overhead_eur) |
| Input | `C_clean` | Cleaning cost | €/year | formula [`cleaning_eur`](#f-calc-cleaning_eur) |
| Input | `C_shunt` | Shunting cost | €/year | formula [`shunting_eur`](#f-calc-shunting_eur) |
| **Output** | `C_op,fix` | Total fixed operator cost | €/year | — |

**Used by:** [`operator_total_eur`](#f-calc-operator_total_eur)

<a id="f-calc-coach_amortisation_eur"></a>
####### Coach write-off — `coach_amortisation_eur`

$$ C_{coach,amort} = \frac{C_{coach,purchase}}{T_{coach,amort}} \times n $$

Annual write-off of the coaches: purchase price divided by their useful life, times the number of coaches the service needs — including a reserve for coaches in the workshop.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `C_coach,purchase` | Purchase price per coach | €/coach | parameter [`composition_type_purchase_coach_eur`](#p-input_params-composition_types-composition_type_purchase_coach_eur) |
| Input | `T_coach,amort` | Useful life over which the coach is written off | years | parameter [`composition_type_coach_amort_years`](#p-input_params-composition_types-composition_type_coach_amort_years) |
| Input | `n` | Coaches needed for the service, incl. reserve | coaches | computed upstream |
| **Output** | `C_coach,amort` | Annual coach write-off | €/year | — |

**Used by:** [`operator_fixed_total_eur`](#f-calc-operator_fixed_total_eur)

<a id="f-calc-financing_eur"></a>
####### Financing — `financing_eur`

$$ C_{fin} = C_{coach,purchase} \times q_{fin} \times n $$

Cost of financing the coaches: purchase price times an annual financing rate, times the number of coaches.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `C_coach,purchase` | Purchase price per coach | €/coach | parameter [`composition_type_purchase_coach_eur`](#p-input_params-composition_types-composition_type_purchase_coach_eur) |
| Input | `q_fin` | Annual financing rate on the purchase price | fraction/year | parameter [`operator_financing_quota_per`](#p-input_params-operators-operator_financing_quota_per) |
| Input | `n` | Coaches needed for the service, incl. reserve | coaches | computed upstream |
| **Output** | `C_fin` | Annual financing cost | €/year | — |

**Used by:** [`operator_fixed_total_eur`](#f-calc-operator_fixed_total_eur)

<a id="f-calc-fix_overhead_eur"></a>
####### Fixed overhead — `fix_overhead_eur`

$$ C_{fix,oh} = q_{fix,oh} \times \left(C_{op,var} - C_{var,oh} + C_{op,fix}\right) $$

Fixed overhead — administration, management, planning: a fixed share on top of all other operator costs. Charges paid to infrastructure companies are not part of the base.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `q_fix,oh` | Fixed overhead share | fraction | parameter [`operator_fix_overhead_quota_per`](#p-input_params-operators-operator_fix_overhead_quota_per) |
| Input | `C_op,var` | All variable operator costs | €/year | computed upstream |
| Input | `C_var,oh` | Variable overhead (excluded from the base) | €/year | formula [`var_overhead_eur`](#f-calc-var_overhead_eur) |
| Input | `C_op,fix` | All fixed operator costs | €/year | computed upstream |
| **Output** | `C_fix,oh` | Annual fixed overhead | €/year | — |

**Used by:** [`operator_fixed_total_eur`](#f-calc-operator_fixed_total_eur)

<a id="f-calc-cleaning_eur"></a>
####### Cleaning — `cleaning_eur`

$$ C_{clean} = c_{clean/day} \times n \times d_{op} $$

Cleaning and preparing the train for the next night: a daily rate per coach times the number of coaches and the operating days per year.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_clean/day` | Cleaning and preparation rate per coach and day | €/coach/day | parameter [`composition_type_cleaning_eur_day`](#p-input_params-composition_types-composition_type_cleaning_eur_day) |
| Input | `n` | Coaches needed for the service | coaches | computed upstream |
| Input | `d_op` | Operating days per year | days/year | computed upstream |
| **Output** | `C_clean` | Annual cleaning cost | €/year | — |

**Used by:** [`operator_fixed_total_eur`](#f-calc-operator_fixed_total_eur)

<a id="f-calc-shunting_eur"></a>
####### Shunting — `shunting_eur`

$$ C_{shunt} = c_{shunt/event} \times n_{events} $$

Moving the train around in stations and yards — coupling, uncoupling, parking moves: a rate per movement times the number of movements.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_shunt/event` | Cost per shunting movement | €/event | parameter [`track_shunting_eur_event`](#p-input_params-track_infrastructures-track_shunting_eur_event) |
| Input | `n_events` | Shunting movements per year | events/year | computed upstream |
| **Output** | `C_shunt` | Annual shunting cost | €/year | — |

**Used by:** [`operator_fixed_total_eur`](#f-calc-operator_fixed_total_eur)

<a id="f-calc-infrastructure_total_eur"></a>
##### Infrastructure cost — `infrastructure_total_eur`

$$ C_{infrastructure} = C_{TAC} + C_{energy} + C_{station} + C_{park} $$

Everything paid to infrastructure companies: track access charges, traction electricity, station charges, and overnight parking.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `C_TAC` | Track access charges | €/year | formula [`tac_eur`](#f-calc-tac_eur) |
| Input | `C_energy` | Traction electricity cost | €/year | formula [`energy_eur`](#f-calc-energy_eur) |
| Input | `C_station` | Station charges | €/year | formula [`station_charge_eur`](#f-calc-station_charge_eur) |
| Input | `C_park` | Overnight parking cost | €/year | formula [`parking_eur`](#f-calc-parking_eur) |
| **Output** | `C_infrastructure` | Total infrastructure cost | €/year | — |

**Used by:** [`total_cost_eur`](#f-calc-total_cost_eur)

<a id="f-calc-tac_eur"></a>
###### Track access charge — `tac_eur`

$$ C_{TAC} = \sum_{seg}\Big[\sum_{c \in seg} \big( d_{c}\,(1{-}\nu_c)\,b_{day,c}\,\mu_c + d_{c}\,\nu_c\,b_{night,c} + d_{c}\,(\gamma_c m_{gross} + \sigma_c P + \phi_c + \kappa_c \pi_c) \big) + \sum_{stop} h_{country(stop)} + \rho_{c}\,R_{seg,c} + \sum_{x \in seg}\big(F_x + f_x n_{seg}\big)\Big] $$

Track access charge — what the operator pays each country's infrastructure company for using the track. Every country charges its own mix: a rate per kilometre driven (higher or lower at night), a rate per tonne of train weight and kilometre, in some countries a rate per seat, a flat administrative add-on, a fee per stop made, a share of the ticket revenue earned there, and a surcharge for running through a congested area at rush hour. Crossings billed separately — the Storebælt and Øresund links and the Channel Tunnel — are added per crossing, one of them also per passenger carried. A term a country does not levy is simply absent.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `d_c` | Distance driven in this country on this segment | km | computed upstream |
| Input | `nu_c` | Share of the run in this country priced at the night rate | – | formula [`tac_night_share`](#f-calc-tac_night_share) |
| Input | `b_day,c` | The country's day rate per train-kilometre | €/train-km | parameter [`track_tac_b_day`](#p-input_params-track_infrastructures-track_tac_b_day) |
| Input | `b_night,c` | The country's night rate per train-kilometre | €/train-km | parameter [`track_tac_b_night`](#p-input_params-track_infrastructures-track_tac_b_night) |
| Input | `gamma_c` | The country's rate per tonne of train weight and kilometre | €/(t·km) | parameter [`track_tac_gamma`](#p-input_params-track_infrastructures-track_tac_gamma) |
| Input | `m_gross` | Weight of the whole train — coaches plus locomotives | t | parameter [`loco_type_weight_t`](#p-input_params-loco_types-loco_type_weight_t) |
| Input | `sigma_c` | The country's rate per place and kilometre | €/(place·km) | parameter [`track_tac_seat_km`](#p-input_params-track_infrastructures-track_tac_seat_km) |
| Input | `P` | Places the train offers | places | computed upstream |
| Input | `phi_c` | The country's flat administrative add-on per train-kilometre | €/train-km | parameter [`track_tac_fixed_per_train_km`](#p-input_params-track_infrastructures-track_tac_fixed_per_train_km) |
| Input | `kappa_c` | The country's congestion surcharge per train-kilometre | €/train-km | parameter [`track_tac_congestion_surcharge_eur_km`](#p-input_params-track_infrastructures-track_tac_congestion_surcharge_eur_km) |
| Input | `pi_c` | Share of the run in this country falling in rush hour | – | formula [`tac_peak_share`](#f-calc-tac_peak_share) |
| Input | `mu_c` | Factor the day rate is multiplied by over the rush-hour share of the run (1 outside it) | factor | parameter [`track_tac_peak_multiplier`](#p-input_params-track_infrastructures-track_tac_peak_multiplier) |
| Input | `h_country(stop)` | Fee for making one stop, at that stop's own country rate. A trip's first segment pays for both of its ends, since no other segment owns the starting station | €/stop | parameter [`track_tac_per_stop`](#p-input_params-track_infrastructures-track_tac_per_stop) |
| Input | `rho_c` | Share of the ticket revenue earned in this country that the infrastructure manager takes | fraction | parameter [`track_tac_revenue_share`](#p-input_params-track_infrastructures-track_tac_revenue_share) |
| Input | `R_seg,c` | Ticket revenue attributable to this segment in this country, per train run | €/trip | computed upstream |
| Input | `F_x` | Charge for crossing a separately billed link, per train | €/traverse | parameter [`passage_fixed_eur`](#p-input_params-passage_charges-passage_fixed_eur) |
| Input | `f_x` | Charge for crossing a separately billed link, per passenger | €/passenger | parameter [`passage_per_passenger_eur`](#p-input_params-passage_charges-passage_per_passenger_eur) |
| Input | `n_seg` | Passengers aboard on this segment, per train run | passengers | computed upstream |
| **Output** | `C_TAC` | Annual track access charges | €/year | — |

**Used by:** [`infrastructure_total_eur`](#f-calc-infrastructure_total_eur)

<a id="f-calc-energy_eur"></a>
###### Traction electricity — `energy_eur`

$$ C_{energy} = \sum_{seg} \sum_{c \in seg} \left[ E_{kWh,c} \left( (1-\nu^{E}_{c}) p_{c} + \nu^{E}_{c} p^{night}_{c} \right) + d_{c} \left( e_{c} + e^{gt}_{c} m_{gross} \right) \right] $$

Traction energy cost: the electricity the train uses in each country at that country's price, plus what the infrastructure manager charges for supplying it through the catenary. The electricity is billed at the day rate outside the national night window and at the night rate inside it. The supply charge is levied per kilometre by nine countries and on the weight moved by three; it is kept in the unit each one publishes rather than converted into a price per kilowatt-hour, since converting it would depend on an assumed consumption.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `E_kWh,c` | Energy used in the country (from the energy model) | kWh | formula [`energy_per_leg`](#f-energy-energy_per_leg) |
| Input | `p_c` | The country's day traction electricity price | €/kWh | parameter [`track_energy_price_eur_kwh`](#p-input_params-track_infrastructures-track_energy_price_eur_kwh) |
| Input | `p^night_c` | Its night-band price, where the tariff is banded | €/kWh | parameter [`track_energy_price_night_eur_kwh`](#p-input_params-track_infrastructures-track_energy_price_night_eur_kwh) |
| Input | `nu^E_c` | Share of the country leg billed at the night rate | – | formula [`energy_night_share`](#f-calc-energy_night_share) |
| Input | `e_c` | Charge for using the catenary and traction power-supply installations, per train-kilometre | €/train-km | parameter [`track_energy_catenary_eur_train_km`](#p-input_params-track_infrastructures-track_energy_catenary_eur_train_km) |
| Input | `e^gt_c` | The same charge where the country levies it on the weight moved instead | €/gross-tonne-km | parameter [`track_energy_catenary_eur_gross_tonne_km`](#p-input_params-track_infrastructures-track_energy_catenary_eur_gross_tonne_km) |
| Input | `m_gross` | Gross weight of the whole consist, coaches plus locomotives | t | computed upstream |
| Input | `d_c` | Kilometres run in the country on this segment | km | computed upstream |
| **Output** | `C_energy` | Annual traction energy cost | €/year | — |

**Used by:** [`infrastructure_total_eur`](#f-calc-infrastructure_total_eur)

<a id="f-calc-station_charge_eur"></a>
###### Station charges — `station_charge_eur`

$$ C_{station} = \sum_{stop} c_{stop,charge} $$

Station charge: the fee paid for every scheduled stop at a station, added up over all stops.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_stop,charge` | Station fee per scheduled stop | €/stop | parameter [`stop_charge_eur`](#p-input_params-stop_infrastructures-stop_charge_eur) |
| **Output** | `C_station` | Annual station charges | €/year | — |

**Used by:** [`infrastructure_total_eur`](#f-calc-infrastructure_total_eur)

<a id="f-calc-parking_eur"></a>
###### Overnight parking — `parking_eur`

$$ C_{park} = \sum_{l \in \text{endpoints}} p_{park,country(l)} $$

Overnight parking of the train between two nights of service: a daily rate at each end point of the route.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `p_park,country(l)` | Daily parking rate in the end point's country | €/day | parameter [`track_parking_eur_day`](#p-input_params-track_infrastructures-track_parking_eur_day) |
| **Output** | `C_park` | Annual overnight parking cost | €/year | — |

**Used by:** [`infrastructure_total_eur`](#f-calc-infrastructure_total_eur)

<a id="f-calc-total_revenue_eur"></a>
#### Total revenue — `total_revenue_eur`

$$ R_{total} = R_{ticket} $$

Total annual revenue — currently ticket income is the only revenue source.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `R_ticket` | Annual ticket revenue | €/year | formula [`ticket_revenue_eur`](#f-calc-ticket_revenue_eur) |
| **Output** | `R_total` | Total annual revenue | €/year | — |

**Used by:** [`net_eur`](#f-calc-net_eur)

<a id="f-calc-ticket_revenue_eur"></a>
##### Ticket revenue — `ticket_revenue_eur`

$$ R = \sum_{od} n_{places\_sold,od} \times \bar{f}_{od} $$

Ticket income: tickets sold per connection times the average ticket price. Both are set by the user of the tool — they are not yet predicted by a demand model.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `n_places_sold,od` | Places sold per connection and year | places/year | set by the tool user |
| Input | `f̄_od` | Average ticket price on the connection | €/ticket | set by the tool user |
| **Output** | `R` | Annual ticket revenue | €/year | — |

**Used by:** [`ebit_margin_eur`](#f-calc-ebit_margin_eur), [`total_revenue_eur`](#f-calc-total_revenue_eur), [`var_overhead_eur`](#f-calc-var_overhead_eur)

<a id="f-calc-ebit_margin_eur"></a>
#### Profit requirement (margin) — `ebit_margin_eur`

$$ C_{EBIT} = \sum_{od} R_{od} \times q_{EBIT} $$

The operator's profit requirement: a share of ticket revenue that must remain as operating profit. It is deducted in the net result — it is not a cost paid to anyone.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `R_od` | Ticket revenue per connection and year | €/year | formula [`ticket_revenue_eur`](#f-calc-ticket_revenue_eur) |
| Input | `q_EBIT` | Required operating profit as a share of revenue | fraction | parameter [`operator_ebit_margin_per`](#p-input_params-operators-operator_ebit_margin_per) |
| **Output** | `C_EBIT` | Annual profit requirement | €/year | — |

**Used by:** [`net_eur`](#f-calc-net_eur)

<a id="f-calc-net_eur"></a>
#### Net result — `net_eur`

$$ N = R_{total} - C_{total} - C_{EBIT} $$

Net annual result: revenue minus all costs minus the operator's profit requirement. A negative value is the subsidy the route would need.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `R_total` | Total annual revenue | €/year | formula [`total_revenue_eur`](#f-calc-total_revenue_eur) |
| Input | `C_total` | Total annual cost | €/year | formula [`total_cost_eur`](#f-calc-total_cost_eur) |
| Input | `C_EBIT` | The operator's profit requirement | €/year | formula [`ebit_margin_eur`](#f-calc-ebit_margin_eur) |
| **Output** | `N` | Net annual result | €/year | — |

**Generic aggregation** — the same summation rule the matrix views (by country, connection, route section, or stop) apply at levels not named individually above:

<a id="f-calc-total_eur"></a>
#### Generic level total — `total_eur`

$$ x_{total} = \sum_i x_i $$

Sum of the items directly below it in the cost breakdown — the same rule applies at every level.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `x_i` | The individual items on that level | €/year | computed upstream |
| **Output** | `x_total` | Sum of the level's items | €/year | — |
<!-- END GENERATED: calc_formulas -->

---

## 6. Emissions model

Flat per-mode climate impact factors used for the mode comparison and
the CO2-savings estimate. The night-train value is a European average
until a country-resolved, energy-based model replaces it — see the
[emissions model README](../backend/models/emissions/README.md).

<!-- BEGIN GENERATED: emission_factors -->
| Mode | g CO2e per passenger-km | Source |
|---|---|---|
| night train | 33 | EEA TERM 2020: EU-average passenger rail, 2018 (33 g CO2e/pkm) — flat proxy for night trains until the energy-based, country-resolved model lands |
| air | 160 | EEA TERM 2020: intra-EU aviation, 2018 (160 g CO2/pkm, CO2 only — excludes non-CO2 radiative forcing such as contrails and NOx, which would push the effective value substantially higher) |
| car | 143 | EEA TERM 2020: passenger car at average occupancy, 2018 (143 g CO2e/pkm) |

Placeholder mode-shift assumption for the CO2-savings estimate (share of a route's passengers assumed shifted from each mode): air 35%, car 20%.
<!-- END GENERATED: emission_factors -->

---

## 7. Standard values

Fixed model assumptions that are not user-adjustable and not stored in
the database — changing one is a model change and bumps the owning
model's version. Each constant lives in its model's `model.py`.

<!-- BEGIN GENERATED: standard_values -->
#### Route model — [`model.py`](../backend/models/route/model.py)

| Constant | Value | Meaning |
|---|---|---|
| <a id="s-route-default_timetable_mode"></a>`DEFAULT_TIMETABLE_MODE` | `'simpleAutomatic'` | — |
| <a id="s-route-default_schedule_mode"></a>`DEFAULT_SCHEDULE_MODE` | `'alwaysDaily'` | — |
| <a id="s-route-default_routing_mode"></a>`DEFAULT_ROUTING_MODE` | `'fullRouting'` | — |
| <a id="s-route-default_auto_stop_addition"></a>`DEFAULT_AUTO_STOP_ADDITION` | `'add'` | — |
| <a id="s-route-default_composition_id"></a>`DEFAULT_COMPOSITION_ID` | `'NEW-BAL-7'` | Composition a request without composition_id is computed with — the seven-coach new-fleet balanced train. It is the middle of the catalog on every axis a first result is read on (places, length, cost per place-km), so a first evaluation neither flatters the concept with the cheapest formation nor burdens it with the largest. The frontend posts no composition until the user picks one; it reads back which one was used from route.trip_pairs[].composition_id. db/dev/seed.py asserts the id exists once the catalog is seeded. |
| <a id="s-route-gtfs_service_start"></a>`GTFS_SERVICE_START` | `'2032-12-12'` | — |
| <a id="s-route-gtfs_service_end"></a>`GTFS_SERVICE_END` | `'2033-12-10'` | Nominal GTFS calendar window for persisted services — the project's target timetable year, 2032 (per the December-to-December European rail timetable-change convention: 2nd Sunday of December through the day before the following year's 2nd Sunday). GTFS requires concrete dates; the model itself only knows seasonal frequencies, so every saved service is pinned to this window until real timetable-year handling exists. Changing it changes persisted GTFS calendars, hence a version bump. If "2032" means the timetable period covering most of calendar year 2032 (starting Dec 2031) rather than the one starting Dec 2032, use "2031-12-14" / "2032-12-11". |
| <a id="s-route-mirror_min"></a>`MIRROR_MIN` | `26 * 60 + 30` | 02:30, expressed 'next day' (1590) on the continuous minutes-from-midnight scale used throughout (see models.utils.hhmm_to_min). Fixed constant that timetable_mode='simpleAutomatic' schedules are mirrored around, and that 'simpleAutomaticWithFixedNight' centers the fixed night interval on. |
| <a id="s-route-night_start_min"></a>`NIGHT_START_MIN` | `24 * 60` | 00:00 next day (1440) — threshold X of the night window. Boarding is judged on DEPARTURE time: a stop departing strictly before this classifies boarding; the fixed-night interval's start stop must depart strictly before this (23:59 at the latest). |
| <a id="s-route-night_end_min"></a>`NIGHT_END_MIN` | `29 * 60` | 05:00 next day (1740) — threshold Y of the night window. Alighting is judged on ARRIVAL time: a stop arriving at/after this classifies alighting; anything neither boarding nor alighting is a night stop. The fixed-night interval's end stop must arrive no earlier than this. |
| <a id="s-route-fixed_night_min_speed_ratio"></a>`FIXED_NIGHT_MIN_SPEED_RATIO` | `0.7` | timetable_mode='simpleAutomaticWithFixedNight' only: minimum acceptable ratio of the fixed interval's timetable speed (incl. slack + dwell) to its pure routing speed (driving + dynamics + buffer). Stretching a short interval to cover the night window can make it arbitrarily slow — below this ratio the trip carries a 'fixed_night_stretch_slow' entry in general_parameters.timetable_warnings (a warning, never an error). |
| <a id="s-route-weeks_per_season"></a>`WEEKS_PER_SEASON` | `26` | SUMMER (April–Sep) and WINTER (Oct–Mar) are each a fixed 26 weeks. |
| <a id="s-route-days_per_operating_week"></a>`DAYS_PER_OPERATING_WEEK` | `{'DAILY': 7, 'THREE_PER_WEEK': 3}` | Operating days per week per Frequency name — specific days of week aren't modelled, they don't affect cost or fleet sizing. |
| <a id="s-route-max_composition_speed_kmh"></a>`MAX_COMPOSITION_SPEED_KMH` | `230` | Speed ceiling baked into the routing graph — the fastest composition the catalog can hold. Not a per-trip value: fullRouting caps every trip at its own composition.max_speed_kmh in the request custom model, and that is always at most this, so the baked rule never binds there. What it does bound is the paths that send no composition at all — route_geometry() (ONTD map lines, which have no composition by design) and simpleRouting. 230 rather than a higher number because above it the composition parameter breaks rather than scales: true high speed means distributed-traction trainsets, a different concept outside this model's scope (compositions calibration step 6b). It equals HSR_TRACK_SPEED_THRESHOLD_KMH by construction — track a night train could physically use is never treated as forbidden high-speed infrastructure. This value has two homes by necessity: GraphHopper reads the JSON at import time, not this constant. The JSON is the sanctioned mirror and carries a comment pointing back here — keep the two equal, and note that changing either requires a graph re-import. |
| <a id="s-route-standard_gauge_mm"></a>`STANDARD_GAUGE_MM` | `1435` | The European mainline gauge — the tie-break winner when a trip's stops support several gauges, and the fallback when every stop's gauge is unknown (routing/gauge.py's resolution rules). Also the one gauge whose routing profile carries no suffix (see SUPPORTED_GAUGES_MM). |
| <a id="s-route-supported_gauges_mm"></a>`SUPPORTED_GAUGES_MM` | `(1435, 1520, 1600, 1668)` | Every gauge FAMILY with a routing profile in the graph. NAMING CONTRACT with docker/config.yml: STANDARD_GAUGE_MM routes on the bare OPENRAILROUTING_PROFILE (night_train); every other member on <profile>_<gauge_mm> (night_train_1520, ...). Sanctioned mirror of the profile list in config.yml — keep the two equal; adding a gauge means a new profile there, a graph re-import, and the member here. |
| <a id="s-route-gauge_family_mm"></a>`GAUGE_FAMILY_MM` | `{1524: 1520}` | Gauges folded into another gauge's profile — {tagged: representative}. 1524 (Finnish) and 1520 (ex-Soviet) are 4 mm apart, historically the same gauge, and interoperable in practice: Finnish and ex-Soviet stock runs on both, and VR services crossed the border for decades. OSM tags them separately, and treating the tags as separate networks made the seam impassable exactly where the target network cares: Estonia, whose track is tagged both ways, ended up with stops the resolver put on one profile and platform track the graph put on the other. The night_train_1520 profile accepts BOTH tags (docker/custom_models/nt_gauge_1520.json — the other half of this mapping; keep them in step), and routing/gauge.py normalizes every stop's gauge set through this table before intersecting, so 1524 never reaches profile selection. Trips on the family report track_gauge_mm=1520. |
| <a id="s-route-blocked_countries"></a>`BLOCKED_COUNTRIES` | `('BY', 'RU')` | Countries no route may pass through, under any routing mode — a project decision (Back-on-Track EU, 2026-08), not an infrastructure fact. Enforced at request time: rail_router attaches a speed-0 area rule over each country's border polygon to every routing request (the graph-side `country` encoded value is not registered by this OpenRailRouting fork, so the block cannot be baked in — see docker/config.yml). input_params.countries carries rows for these codes SOLELY to hold the polygons; they are deliberately NOT in seed.py's placeholder tuple, so if the block ever failed, the route would still 422 on country coverage rather than silently pricing Belarusian kilometres — defence in depth, not redundancy. |
| <a id="s-route-hsr_track_speed_threshold_kmh"></a>`HSR_TRACK_SPEED_THRESHOLD_KMH` | `230` | A track segment counts as high-speed infrastructure when its permitted track speed (GraphHopper's max_speed encoded value, from OSM maxspeed) STRICTLY exceeds this. 230 deliberately targets dedicated NEW-BUILD high-speed lines only (250+ per the UIC/EU convention, e.g. LGV, NBS, AV): upgraded conventional lines (200-230, e.g. German ABS corridors at 230) stay fully usable for night trains regardless of hsr_allowed, and 230 also matches the fastest seeded composition's own max_speed_kmh — track a night train could physically exploit is never treated as forbidden high-speed infrastructure. |
| <a id="s-route-hsr_track_speed_sanity_max_kmh"></a>`HSR_TRACK_SPEED_SANITY_MAX_KMH` | `500` | Upper guard on the same condition — excludes segments whose maxspeed is untagged in OSM. GraphHopper encodes a missing maxspeed as a sentinel (0 or infinity depending on version); the two-sided range (THRESHOLD, SANITY_MAX) excludes both conventions, so unknown-speed track is never mistaken for high-speed infrastructure. No real European rail line exceeds this value. |
| <a id="s-route-hsr_avoidance_priority_factor"></a>`HSR_AVOIDANCE_PRIORITY_FACTOR` | `0.01` | GraphHopper custom-model priority multiplier applied to high-speed segments where HSR is not allowed — a strong penalty (100x) rather than a hard block, so a route is still found if high-speed track is genuinely the only physical connection. |
| <a id="s-route-hsr_avoidance_ring_simplify_deg"></a>`HSR_AVOIDANCE_RING_SIMPLIFY_DEG` | `0.01` | Douglas-Peucker tolerance in degrees (~1.1km) applied to a country's outer ring before it is sent to the routing engine as an HSR-avoidance area (rail_router.CountryIndex.get_largest_polygon). The area exists to say "this country's high-speed lines are off-limits", so it only has to contain the rail network — border precision is irrelevant, ring size is not: the raw EEZ rings total ~165k vertices across the seeded countries and would be serialized into every mixed-avoidance routing request. At this tolerance the same set costs ~10k vertices. |
| <a id="s-route-auto_stop_buffer_m"></a>`AUTO_STOP_BUFFER_M` | `10000` | Max distance (metres) from a stop to the already-routed path for that stop to be considered a candidate — covers both stops that sit right on the line and ones merely 'close by'. |
| <a id="s-route-auto_stop_analytic_detour_m"></a>`AUTO_STOP_ANALYTIC_DETOUR_M` | `100` | Perpendicular distance to the routed geometry under which an auto-stop candidate is costed purely analytically (dwell + the dynamics model's accel/brake pair + out-and-back detour at cruise speed) with no router call — at this distance the stop sits on the routed line and a mini-reroute measures the same number at ~1.5s of router time (introduced 2026-08-06 after the 575-stop catalog made per-candidate routing the dominant calc cost). Candidates further out are refined by a real 3-point mini-reroute, since their true track detour can exceed the straight-line bound — e.g. a station the initial routing bypassed on a parallel line, which is also why AUTO_STOP_BUFFER_M is wide. |
| <a id="s-route-auto_stop_max_detour_per"></a>`AUTO_STOP_MAX_DETOUR_PER` | `0.05` | Max allowed increase in TECHNICAL trip time (driving + dynamics + dwell), as a fraction of the original trip's technical time, before mode 'add' stops adding further candidates. Mode 'suggest' deliberately ignores this budget. The schedule supplement is excluded from the basis: a detour costs real running and stopping minutes, while the supplement is margin, and margin should not fund extra stops. It also kept stop selection independent of the route-context calibration — with per-country supplements of 0.35 to 0.71, measuring against padded time would have given the same physical route a quarter more detour budget in France than in Austria. |
| <a id="s-route-traction_loco_power_kw"></a>`TRACTION_LOCO_POWER_KW` | `6400.0` | Assumed locomotive continuous power at the wheel (Siemens Vectron AC: 6.4 MW). Governs the constant-power phase of acceleration above P / F ≈ 77 km/h. |
| <a id="s-route-traction_loco_tractive_effort_kn"></a>`TRACTION_LOCO_TRACTIVE_EFFORT_KN` | `300.0` | Assumed locomotive starting tractive effort (Siemens Vectron: 300 kN). Governs the constant-force phase of acceleration from standstill. |
| <a id="s-route-traction_brake_deceleration_ms2"></a>`TRACTION_BRAKE_DECELERATION_MS2` | `0.5` | Service braking deceleration. Rail braking is effectively mass-independent (brake systems are dimensioned per vehicle to a standard deceleration); 0.5 m/s² is a comfortable service value appropriate for sleeping passengers — full emergency capability is far higher and irrelevant for timetabling. |
| <a id="s-route-neutral_proposal_id"></a>`NEUTRAL_PROPOSAL_ID` | `0` | — |

#### Demand model — [`model.py`](../backend/models/demand/model.py)

| Constant | Value | Meaning |
|---|---|---|
| <a id="s-demand-stopgap_utilization_per"></a>`STOPGAP_UTILIZATION_PER` | `0.7` | Placeholder scalar utilization applied uniformly to every class until a real demand model lands. |
| <a id="s-demand-stopgap_fare_per_km_by_class"></a>`STOPGAP_FARE_PER_KM_BY_CLASS` | `{'Seat': 0.1, 'Couchette': 0.13, 'Sleeper': 0.18, 'Capsule': 0.12, 'Catering': 0.0}` | Placeholder flat per-km fares by class_main — same caveat as above. |

#### Infrastructure model — [`model.py`](../backend/models/infrastructure/model.py)

| Constant | Value | Meaning |
|---|---|---|
| <a id="s-infrastructure-weekday_blend"></a>`WEEKDAY_BLEND` | `5.0 / 7.0` | Share of departures assumed to fall on a weekday. Austria and Switzerland levy their congestion surcharge and peak multiplier Monday to Friday only, but a Segment carries clock minutes and no service date, so a weekday-only tariff window is priced at five sevenths of its overlap rather than all or nothing — see calc_tac.py and OPEN_TODOS['tac_weekday_blend']. |
<!-- END GENERATED: standard_values -->

---

## 8. Parameter reference

Every parameter table in the database, with each column's meaning and
unit. This is rendered from [`db/schema.py`](../backend/db/schema.py) —
the same definition the database itself is created from, so the
documentation and the database cannot disagree. The "Used in" column
links every parameter to the formulas that consume it.

Two kinds of tables exist (full rationale: [db/README.md](../backend/db/README.md)):

- **Catalogs** (operators, coach types, compositions): permanent entries
  you add to — a changed value means a new entry, never editing in place.
- **Versioned snapshots** (track and stop infrastructure): any edit
  copies the whole table forward into a new version number, and a
  **scenario** pins exactly one version of each. That is what makes
  what-if comparisons ("what if night trains may use high-speed lines?")
  and reproducible results possible.

<!-- BEGIN GENERATED: parameters -->
#### `input_params.countries`

Country reference table with border polygons.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-countries-country_code"></a>`country_code` | Two-letter country code (ISO 3166-1 alpha-2). Primary key. | — | — |
| <a id="p-input_params-countries-country_name"></a>`country_name` | Full English country name. | — | — |
| <a id="p-input_params-countries-country_geom"></a>`country_geom` | Country border polygon (SRID 4326) covering the country's land area AND its maritime zones (territorial sea, internal and archipelagic waters, EEZ) — seeded from the Marine Regions union of the ESRI country shapefile and the Exclusive Economic Zones, v4. The maritime coverage is what attributes belt, strait and tunnel crossings to a country instead of the UNK sentinel: this is a routing-attribution geometry, not a cartographic land border. NULL for countries with no rail network, which no route can transit. | — | — |

#### `input_params.country_relations`

Which pairs of countries are close enough to each other for one night train to plausibly connect them — the candidate set the proposal statistics rank top and flop relations over (GET /api/proposals/stats). One row per unordered country pair, measured between each country's reference station (the catalog stop closest to that country's stop centroid) and routed on real track, so sea crossings that force a long land detour drop out on their own. Derived, rebuildable data, NOT hand-maintained: scripts/build_country_relations.py rebuilds it from the pinned stop catalog, and countries with no stops in the catalog yet simply have no rows.

| Column | Meaning | Unit | Used in |
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

#### `input_params.sources`

Registry of data sources. Every parameter row can point to the source its values came from, so every number in the tool stays traceable. One row per source document or dataset.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-sources-source_id"></a>`source_id` | — | — | — |
| <a id="p-input_params-sources-source_description"></a>`source_description` | Human-readable description of the source (e.g. "DB Netz Trassenpreissystem 2025"). | — | — |
| <a id="p-input_params-sources-source_url"></a>`source_url` | Optional link to the source document or dataset. | — | — |
| <a id="p-input_params-sources-source_date"></a>`source_date` | Date the source data was published or retrieved. | — | — |

#### `input_params.service_classes`

Accommodation class taxonomy. service_class_main groups the detailed classes into: Seat, Couchette, Sleeper, Capsule, Catering.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-service_classes-service_class_id"></a>`service_class_id` | Detailed class name (e.g. "couchette (6-berth)", "Sleeper (2-berth) with shower & WC"). | — | — |
| <a id="p-input_params-service_classes-service_class_main"></a>`service_class_main` | Top-level accommodation category: Seat, Couchette, Sleeper, Capsule, or Catering. | — | — |
| <a id="p-input_params-service_classes-service_class_is_night_accommodation"></a>`service_class_is_night_accommodation` | Whether places of this class make the train count as carrying night accommodation for tariff purposes. Germany prices such a train at its night rate over the whole German run (see track_tac_night_full_if_accommodation). True for every class a passenger can lie down in; a dining car alone does not make a night train. | — | — |

#### `input_params.operators`

Train operating company and its cost rates. A catalog, not history: operator_id is a permanent natural key — changed rates mean adding a new operator_id, never editing a row in place (soft-referenced from coach_types and composition_types).

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-operators-operator_row_id"></a>`operator_row_id` | — | — | — |
| <a id="p-input_params-operators-operator_id"></a>`operator_id` | Operator identifier (e.g. STD-REF, STD-NEW). | — | — |
| <a id="p-input_params-operators-operator_name"></a>`operator_name` | Full operator name. | — | — |
| <a id="p-input_params-operators-operator_driver_costs_eur_h"></a>`operator_driver_costs_eur_h` | Driver pay per PRODUCTIVE hour, i.e. the raw wage rate before roster inefficiency. Evaluation divides it by the Dienstplanwirkungsgrad it computes per trip from the four roster columns below. | €/h | [`driver_eur`](#f-calc-driver_eur) |
| <a id="p-input_params-operators-operator_crew_costs_eur_h"></a>`operator_crew_costs_eur_h` | Cabin crew pay per PRODUCTIVE hour, per attendant, before roster inefficiency (same treatment as the driver rate). The train manager is counted with a factor on the composition. | €/h | [`crew_eur`](#f-calc-crew_eur) |
| <a id="p-input_params-operators-operator_driver_max_duty_h"></a>`operator_driver_max_duty_h` | Longest driving time one driver may work between daily rest periods. Directive 2005/47/EC sets 8 h on a night shift (9 h by day); national agreements may be stricter. A trip whose driving time exceeds it needs a relief driver, which lowers the roster efficiency. | h | [`roster_efficiency_driver`](#f-calc-roster_efficiency_driver) |
| <a id="p-input_params-operators-operator_crew_max_duty_h"></a>`operator_crew_max_duty_h` | Longest working time one onboard attendant may work between daily rest periods, per the applicable collective agreement. Same relief mechanism as the driver column. | h | — |
| <a id="p-input_params-operators-operator_driver_roster_eff_ref"></a>`operator_driver_roster_eff_ref` | Dienstplanwirkungsgrad for a driver duty that needs no relief: the share of paid hours that is productive once sign-on/off, reserve cover and leave are absorbed. | fraction | [`roster_efficiency_driver`](#f-calc-roster_efficiency_driver) |
| <a id="p-input_params-operators-operator_crew_roster_eff_ref"></a>`operator_crew_roster_eff_ref` | Dienstplanwirkungsgrad for an onboard duty that needs no relief. Higher than the driver value: onboard links position less and rest away from base more predictably. | fraction | — |
| <a id="p-input_params-operators-operator_relief_allowance_h"></a>`operator_relief_allowance_h` | Unproductive hours added per relief event — positioning to and from the relief point, the extra sign-on/off, and away-base rest handling. Applied once per additional duty beyond the first, for both roles. | h | [`roster_efficiency_driver`](#f-calc-roster_efficiency_driver) |
| <a id="p-input_params-operators-operator_ebit_margin_per"></a>`operator_ebit_margin_per` | Operating profit the operator requires, as a share of ticket revenue. | fraction of revenue | [`ebit_margin_eur`](#f-calc-ebit_margin_eur) |
| <a id="p-input_params-operators-operator_financing_quota_per"></a>`operator_financing_quota_per` | Annual financing cost as a share of the capital tied up in coaches. | fraction/year | [`financing_eur`](#f-calc-financing_eur) |
| <a id="p-input_params-operators-operator_var_overhead_per"></a>`operator_var_overhead_per` | Variable overhead — ticket sales, distribution, customer service — as a share of ticket revenue. | fraction of revenue | [`var_overhead_eur`](#f-calc-var_overhead_eur) |
| <a id="p-input_params-operators-operator_fix_overhead_quota_per"></a>`operator_fix_overhead_quota_per` | Fixed overhead — administration, management, planning — as a share of all other operating costs. | fraction of other costs | [`fix_overhead_eur`](#f-calc-fix_overhead_eur) |
| <a id="p-input_params-operators-source_id"></a>`source_id` | Source for all values in this row. | — | — |

#### `input_params.operator_class_costs`

Onboard service cost per operator and accommodation class.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-operator_class_costs-operator_row_id"></a>`operator_row_id` | — | — | — |
| <a id="p-input_params-operator_class_costs-service_class_id"></a>`service_class_id` | — | — | — |
| <a id="p-input_params-operator_class_costs-operator_class_svc_stockings_eur_place"></a>`operator_class_svc_stockings_eur_place` | Onboard service cost — bedding, breakfast, amenities — per sold place and trip, for this class. | €/place | [`svc_stockings_eur`](#f-calc-svc_stockings_eur) |
| <a id="p-input_params-operator_class_costs-source_id"></a>`source_id` | Source for all values in this row. | — | — |

#### `input_params.coach_types`

Individual railcar/coach types. Capacity is derived from coach_type_classes, not stored here. A catalog, not history: coach_type_id is a permanent natural key — a changed spec means a new coach_type_id, never editing a row in place.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-coach_types-coach_type_row_id"></a>`coach_type_row_id` | — | — | — |
| <a id="p-input_params-coach_types-coach_type_id"></a>`coach_type_id` | Coach type name (e.g. WLABmz, Bcmz, type1). | — | — |
| <a id="p-input_params-coach_types-coach_type_operator_id"></a>`coach_type_operator_id` | Operator this coach type belongs to (soft reference to operators.operator_id). Empty for generic/shared types. | — | — |
| <a id="p-input_params-coach_types-coach_type_weight_gross_t"></a>`coach_type_weight_gross_t` | Gross weight of one coach of this type. | t | [`train_weight`](#f-energy-train_weight), [`stop_dynamics_time_loss`](#f-route-stop_dynamics_time_loss) |
| <a id="p-input_params-coach_types-coach_type_length_m"></a>`coach_type_length_m` | Coach length over buffers — basis of the per-metre purchase price and of the composition's total length. | m | — |
| <a id="p-input_params-coach_types-coach_type_has_wifi"></a>`coach_type_has_wifi` | Coach offers WiFi. A composition offers an amenity if any of its coaches does. | — | — |
| <a id="p-input_params-coach_types-coach_type_length_wo_service_m"></a>`coach_type_length_wo_service_m` | Coach length excluding dining/shared service areas — the passenger-space basis of the class cost split. | m | [`class_main_allocation`](#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_types-coach_type_weight_wo_service_t"></a>`coach_type_weight_wo_service_t` | Coach weight excluding service areas. | t | [`class_main_allocation`](#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_types-coach_type_bikes"></a>`coach_type_bikes` | Number of bicycle spaces in this coach type. | — | — |
| <a id="p-input_params-coach_types-coach_type_climatization"></a>`coach_type_climatization` | Whether this coach type has air conditioning. | — | — |
| <a id="p-input_params-coach_types-coach_type_plugs"></a>`coach_type_plugs` | Whether this coach type has passenger power sockets. | — | — |
| <a id="p-input_params-coach_types-coach_type_crew_factor"></a>`coach_type_crew_factor` | Cabin crew this coach needs, as a fraction of an attendant (0.5 = one attendant covers two coaches). | — | [`crew_eur`](#f-calc-crew_eur) |
| <a id="p-input_params-coach_types-coach_type_remarks"></a>`coach_type_remarks` | Free-text remarks. | — | — |
| <a id="p-input_params-coach_types-source_id"></a>`source_id` | Source for all values in this row. | — | — |

#### `input_params.coach_type_classes`

Places per accommodation class within a coach type, with the class section's share of the coach.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-coach_type_classes-coach_type_row_id"></a>`coach_type_row_id` | — | — | — |
| <a id="p-input_params-coach_type_classes-service_class_id"></a>`service_class_id` | — | — | — |
| <a id="p-input_params-coach_type_classes-coach_type_class_places"></a>`coach_type_class_places` | Number of places of this class in the coach type. | places | [`class_main_allocation`](#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_type_classes-section_length_m"></a>`section_length_m` | Length of this class's section within the coach — basis of the class cost split and derived per-class densities. | m | [`class_main_allocation`](#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_type_classes-section_weight_t"></a>`section_weight_t` | Weight of this class's section within the coach. | t | [`class_main_allocation`](#f-calc-class_main_allocation) |
| <a id="p-input_params-coach_type_classes-section_crew_factor"></a>`section_crew_factor` | Cabin crew this class section needs, as a fraction of an attendant. | — | — |
| <a id="p-input_params-coach_type_classes-source_id"></a>`source_id` | Source for all values in this row. | — | — |

#### `input_params.composition_types`

Train composition blueprint: which coaches, at which speed, with which cost parameters. Capacity comes from the coach list (composition_type_coaches → coach_type_classes). Which locomotives it hauls comes from composition_type_locos; they are rented, not purchased, and the rate is per operator and machine (operator_loco_costs). A catalog, not history: composition_type_id is a permanent natural key — new settings mean a new composition_type_id, never editing a row in place.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-composition_types-composition_type_row_id"></a>`composition_type_row_id` | — | — | — |
| <a id="p-input_params-composition_types-composition_type_id"></a>`composition_type_id` | Composition name (e.g. STD-3.1). | — | — |
| <a id="p-input_params-composition_types-composition_type_description"></a>`composition_type_description` | Short human-readable description of the composition. | — | — |
| <a id="p-input_params-composition_types-composition_type_operator_id"></a>`composition_type_operator_id` | Operator running this composition (soft reference to operators.operator_id). | — | — |
| <a id="p-input_params-composition_types-composition_type_hsr_allowed"></a>`composition_type_hsr_allowed` | Whether this train may use high-speed lines at all (combined with each country's own permission). | — | — |
| <a id="p-input_params-composition_types-composition_type_max_speed_kmh"></a>`composition_type_max_speed_kmh` | Maximum operational speed. | km/h | — |
| <a id="p-input_params-composition_types-composition_type_min_boarding_time"></a>`composition_type_min_boarding_time` | Minimum waiting time this train needs at stops where passengers board. | interval (hh:mm:ss) | [`dwell_time_boarding`](#f-route-dwell_time_boarding), [`dwell_time_both`](#f-route-dwell_time_both) |
| <a id="p-input_params-composition_types-composition_type_min_alighting_time"></a>`composition_type_min_alighting_time` | Minimum waiting time this train needs at stops where passengers get off. | interval (hh:mm:ss) | [`dwell_time_alighting`](#f-route-dwell_time_alighting), [`dwell_time_both`](#f-route-dwell_time_both) |
| <a id="p-input_params-composition_types-composition_type_purchase_coach_eur"></a>`composition_type_purchase_coach_eur` | Average purchase price per coach, from the per-metre price model (new 145 / refurbished 53 k€ per metre of coach, double-deck ×1.12) applied to this composition's coach lengths. Derivation: calib/CALIBRATION.md. | €/coach | [`coach_amortisation_eur`](#f-calc-coach_amortisation_eur), [`financing_eur`](#f-calc-financing_eur) |
| <a id="p-input_params-composition_types-composition_type_coach_avail_per"></a>`composition_type_coach_avail_per` | Share of calendar days a coach is available for service (the rest it is in the workshop). | fraction | — |
| <a id="p-input_params-composition_types-composition_type_coach_amort_years"></a>`composition_type_coach_amort_years` | Useful life over which a coach is written off. | years | [`coach_amortisation_eur`](#f-calc-coach_amortisation_eur) |
| <a id="p-input_params-composition_types-composition_type_cleaning_eur_day"></a>`composition_type_cleaning_eur_day` | Cleaning and preparation for the next night, per coach and operating day, at 2032 prices. | €/coach/day | [`cleaning_eur`](#f-calc-cleaning_eur) |
| <a id="p-input_params-composition_types-composition_type_coach_maint_eur_km"></a>`composition_type_coach_maint_eur_km` | Coach maintenance for the whole train per kilometre (per-coach rate × number of coaches; new 1.00 / refurbished 1.30 €/coach-km, 2032 prices). | €/train-km | [`coach_maintenance_eur`](#f-calc-coach_maintenance_eur) |
| <a id="p-input_params-composition_types-composition_type_driver_factor"></a>`composition_type_driver_factor` | Number of drivers required per trip (e.g. 1 or 2). | persons | [`driver_eur`](#f-calc-driver_eur) |
| <a id="p-input_params-composition_types-composition_type_zugchef_crew_factor"></a>`composition_type_zugchef_crew_factor` | Train manager, counted in attendant-equivalents (1.19; 2.38 for trains with 10 or more coaches). Total crew = sum of coach crew factors + this factor. | attendant-equivalents | — |
| <a id="p-input_params-composition_types-composition_type_length_cost_prop"></a>`composition_type_length_cost_prop` | Weighting X of the class cost split: X by length, (1−X) by weight, on passenger space; service areas are split per place. See calib/CALIBRATION.md. | fraction | [`class_main_allocation`](#f-calc-class_main_allocation) |
| <a id="p-input_params-composition_types-composition_type_food_and_beverages"></a>`composition_type_food_and_beverages` | Catering concept (e.g. 'dining car'). Coach amenities aggregate separately. | — | — |
| <a id="p-input_params-composition_types-composition_type_material_strategy"></a>`composition_type_material_strategy` | Rolling stock family: 'new' (230 km/h-capable, 30-year write-off, 0.909 availability) or 'refurbished' (200 km/h cap, 12 years, 0.80). Selects the matching operator row (STD-NEW / STD-REF) and parameter family — see calib/CALIBRATION.md. | — | — |
| <a id="p-input_params-composition_types-composition_type_indicative_cost_eur_train_km"></a>`composition_type_indicative_cost_eur_train_km` | Indicative operator cost per train-kilometre on the 1,000 km reference route (14.5 h trip, 350 operating days, 2 trainsets) at 2032 prices, excluding infrastructure charges, energy, variable overhead and profit — a comparison figure between compositions, not a route evaluation. Derivation: calib/CALIBRATION.md. | €/train-km | — |
| <a id="p-input_params-composition_types-composition_type_indicative_cost_ct_place_km"></a>`composition_type_indicative_cost_ct_place_km` | The same cost basis divided by the number of places. | ct/place-km | — |
| <a id="p-input_params-composition_types-source_id"></a>`source_id` | Source for all values in this row. | — | — |

#### `input_params.loco_types`

Locomotive types — the physical machine, independent of who runs it. Weight and speed live here; the rental rate does not, because it is a commercial term that varies by operator (operator_loco_costs), exactly as onboard service cost varies by operator over service_classes. A catalog, not history: loco_type_id is a permanent natural key — a changed spec means a new loco_type_id, never editing a row in place.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-loco_types-loco_type_row_id"></a>`loco_type_row_id` | — | — | — |
| <a id="p-input_params-loco_types-loco_type_id"></a>`loco_type_id` | Stable natural key, e.g. VECTRON-MS-230. | — | — |
| <a id="p-input_params-loco_types-loco_type_description"></a>`loco_type_description` | Machine and configuration in plain words, including the national class designation where the calibration pins one and an explicit note where it does not. | — | — |
| <a id="p-input_params-loco_types-loco_type_traction"></a>`loco_type_traction` | Traction system, e.g. 'electric multi-system'. Not yet read by any model — recorded so a future electrification or traction-change model has it. | — | — |
| <a id="p-input_params-loco_types-loco_type_weight_t"></a>`loco_type_weight_t` | Mass of one locomotive. Completes the gross weight the weight-dependent track access charge and the traction dynamics both work on — coach weight alone is not what gets hauled or weighed. | t | [`tac_eur`](#f-calc-tac_eur), [`stop_dynamics_time_loss`](#f-route-stop_dynamics_time_loss) |
| <a id="p-input_params-loco_types-loco_type_max_speed_kmh"></a>`loco_type_max_speed_kmh` | Design maximum speed. The composition's own max speed still governs the timetable; this records what the machine could do. | km/h | — |
| <a id="p-input_params-loco_types-source_id"></a>`source_id` | Source for all values in this row. | — | — |
| <a id="p-input_params-loco_types-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |

#### `input_params.operator_loco_costs`

Locomotive rental rate per operator and machine — the locomotive counterpart of operator_class_costs. A pairing with no row is not priced, and the loader refuses to resolve a composition that needs one rather than substituting a fallback: a missing pairing is a wiring error, and a silent default would hide exactly the mistake this table exists to catch.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-operator_loco_costs-operator_row_id"></a>`operator_row_id` | — | — | — |
| <a id="p-input_params-operator_loco_costs-loco_type_row_id"></a>`loco_type_row_id` | — | — | — |
| <a id="p-input_params-operator_loco_costs-operator_loco_lease_eur_h"></a>`operator_loco_lease_eur_h` | All-inclusive rental rate (maintenance and insurance included), billed per hour the locomotive is in use. | €/h | [`loco_eur`](#f-calc-loco_eur) |
| <a id="p-input_params-operator_loco_costs-source_id"></a>`source_id` | Source for all values in this row. | — | — |

#### `input_params.composition_type_locos`

Ordered locomotive slots per composition type — the locomotive counterpart of composition_type_coaches. The number of locomotives is the number of rows here, never a stored column, so the two cannot disagree. position expresses machines hauling TOGETHER (double heading); a traction change part-way along a route is route-dependent and cannot be expressed on a composition type at all — that belongs on the trip when it is modelled.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-composition_type_locos-composition_type_row_id"></a>`composition_type_row_id` | — | — | — |
| <a id="p-input_params-composition_type_locos-position"></a>`position` | 1-based position in the consist. | — | — |
| <a id="p-input_params-composition_type_locos-loco_type_row_id"></a>`loco_type_row_id` | — | — | — |

#### `input_params.composition_type_coaches`

Ordered coach slots per composition type.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-composition_type_coaches-composition_type_row_id"></a>`composition_type_row_id` | — | — | — |
| <a id="p-input_params-composition_type_coaches-position"></a>`position` | Position of the coach in the train (1 = first coach behind the locomotive). | — | — |
| <a id="p-input_params-composition_type_coaches-coach_type_row_id"></a>`coach_type_row_id` | — | — | — |

#### `input_params.track_infrastructure_defaults`

EU-average fallback track parameters, applied wherever a country's own field is empty. Version bumps are full-table snapshots, resolved via scenario.scenarios.track_infrastructure_defaults_version — see db/README.md for the versioning contract.

| Column | Meaning | Unit | Used in |
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

#### `input_params.track_infrastructures`

Country-level track parameters. Empty fields are resolved against track_infrastructure_defaults by the loader. Version bumps are full-table snapshots — every country's row is duplicated forward on any single-country edit — resolved via scenario.scenarios.track_infrastructures_version. See db/README.md for the versioning contract.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-track_infrastructures-track_infra_row_id"></a>`track_infra_row_id` | — | — | — |
| <a id="p-input_params-track_infrastructures-country_code"></a>`country_code` | Two-letter country code (ISO 3166-1 alpha-2). | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_eur_train_km"></a>`track_tac_eur_train_km` | Indicative track access charge for the reference night train — a single headline number for display and comparison. The cost model does NOT read it: it prices track access from the calibrated component columns further down. | €/train-km | — |
| <a id="p-input_params-track_infrastructures-track_tac_src"></a>`track_tac_src` | Source for the track access charge. | — | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_day"></a>`track_parking_eur_day` | Indicative cost of one stabling occupation for the reference train — a single headline number for display and comparison. The cost model does NOT read it: it prices stabling from the basis and rate columns further down, against the actual layover and train length. | €/occupation (EUR at 2032 prices) | [`parking_eur`](#f-calc-parking_eur) |
| <a id="p-input_params-track_infrastructures-track_parking_src"></a>`track_parking_src` | Source for the parking cost. | — | — |
| <a id="p-input_params-track_infrastructures-track_shunting_eur_event"></a>`track_shunting_eur_event` | All-in cost of one shunting movement: what the infrastructure manager charges plus what it does not supply. Roughly nine tenths of the figure is the market cost of a shunting locomotive and crew where the IM sells only facility access — see the calibration document. | €/event (EUR at 2032 prices) | [`shunting_eur`](#f-calc-shunting_eur) |
| <a id="p-input_params-track_infrastructures-track_shunting_src"></a>`track_shunting_src` | Source for the shunting cost. | — | — |
| <a id="p-input_params-track_infrastructures-track_energy_price_eur_kwh"></a>`track_energy_price_eur_kwh` | Traction electricity price: the day rate, and the rate around the clock for the twenty-five countries whose tariff is not banded. Where a night band exists the cost model prices the in-band share at track_energy_price_night_eur_kwh instead. | €/kWh (EUR at 2032 prices) | [`energy_eur`](#f-calc-energy_eur) |
| <a id="p-input_params-track_infrastructures-track_energy_price_src"></a>`track_energy_price_src` | Source for the electricity price. | — | — |
| <a id="p-input_params-track_infrastructures-track_terrain_category"></a>`track_terrain_category` | Rough terrain classification: Flat, Hilly, or Mountainous. | — | — |
| <a id="p-input_params-track_infrastructures-track_terrain_score"></a>`track_terrain_score` | Terrain difficulty score — hills and mountains increase energy use. | 1–100 | — |
| <a id="p-input_params-track_infrastructures-track_terrain_src"></a>`track_terrain_src` | Source for terrain category and score. | — | — |
| <a id="p-input_params-track_infrastructures-track_hsr_allowed"></a>`track_hsr_allowed` | Whether night trains may use the country's high-speed lines. | — | — |
| <a id="p-input_params-track_infrastructures-track_hsr_src"></a>`track_hsr_src` | Source for the high-speed permission. | — | — |
| <a id="p-input_params-track_infrastructures-track_min_boarding_time"></a>`track_min_boarding_time` | Minimum waiting time the country's stations need at stops where passengers board. | interval (hh:mm:ss) | [`dwell_time_boarding`](#f-route-dwell_time_boarding), [`dwell_time_both`](#f-route-dwell_time_both) |
| <a id="p-input_params-track_infrastructures-track_min_boarding_src"></a>`track_min_boarding_src` | Source for the minimum boarding time. | — | — |
| <a id="p-input_params-track_infrastructures-track_min_alighting_time"></a>`track_min_alighting_time` | Minimum waiting time the country's stations need at stops where passengers get off. | interval (hh:mm:ss) | [`dwell_time_alighting`](#f-route-dwell_time_alighting), [`dwell_time_both`](#f-route-dwell_time_both) |
| <a id="p-input_params-track_infrastructures-track_min_alighting_src"></a>`track_min_alighting_src` | Source for the minimum alighting time. | — | — |
| <a id="p-input_params-track_infrastructures-track_buffer_quota_per"></a>`track_buffer_quota_per` | Schedule buffer added on top of driving time, reflecting how congested and delay-prone the network is. | fraction of driving time | [`buffer_time`](#f-route-buffer_time) |
| <a id="p-input_params-track_infrastructures-track_buffer_src"></a>`track_buffer_src` | Source for the buffer quota. | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_b_day"></a>`track_tac_b_day` | Base day rate of the minimum access package. Empty means the country levies no distance-based day rate. | €/train-km (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_b_night"></a>`track_tac_b_night` | Night rate of the minimum access package, charged on the share of a run falling inside the country's night band. Empty means the country has no separate night rate. | €/train-km (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_gamma"></a>`track_tac_gamma` | Weight-dependent term, charged on the whole consist — coaches plus locomotives. | €/gross-tonne-km (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_seat_km"></a>`track_tac_seat_km` | Capacity-dependent term, charged per place the train offers (Spanish corridor surcharge). | €/seat-km (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_per_stop"></a>`track_tac_per_stop` | Per-stop element of the path price: stopping and restarting consumes path capacity (Swiss Haltezuschlag). NOT a station usage fee — those are stop_infrastructures.stop_charge_eur. Charged at each stop's own country rate. | €/stop (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_revenue_share"></a>`track_tac_revenue_share` | Share of the traffic revenue earned in this country that the infrastructure manager takes on top of the distance charges (Swiss Deckungsbeitrag). | fraction | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_fixed_per_train_km"></a>`track_tac_fixed_per_train_km` | Flat administrative add-on charged per kilometre alongside the base rate (Luxembourgish path administration). | €/train-km (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_peak_multiplier"></a>`track_tac_peak_multiplier` | Factor the day rate is multiplied by on the share of a run falling inside the country's peak bands (Swiss NZV: 2). | factor | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_congestion_surcharge_eur_km"></a>`track_tac_congestion_surcharge_eur_km` | Flat surcharge on congested sections, charged on the share of a run falling inside the peak bands (Austrian überlastete Schienenwege). Kept apart from the multiplier above so a congestion charge can be shown as one. | €/train-km (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_night_mode"></a>`track_tac_night_mode` | How the country prices night traffic: 'none' (one rate around the clock) or 'time_band' (the night rate applies pro rata to the time a run spends inside the band below). | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_night_band_start"></a>`track_tac_night_band_start` | Start of the national night tariff band, local clock. Bands may run across midnight (23:00–06:00). | time of day | [`tac_night_share`](#f-calc-tac_night_share) |
| <a id="p-input_params-track_infrastructures-track_tac_night_band_end"></a>`track_tac_night_band_end` | End of the national night tariff band, local clock. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_tac_night_full_if_accommodation"></a>`track_tac_night_full_if_accommodation` | German SPFV Nacht rule: when true, a train carrying night accommodation (couchette, sleeper or capsule) is priced at the night rate over its ENTIRE run in this country, not just the part inside the band. | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_peak_band1_start"></a>`track_tac_peak_band1_start` | Start of the first daily peak band (morning commuter peak), local clock. | time of day | [`tac_peak_share`](#f-calc-tac_peak_share) |
| <a id="p-input_params-track_infrastructures-track_tac_peak_band1_end"></a>`track_tac_peak_band1_end` | End of the first daily peak band. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_tac_peak_band2_start"></a>`track_tac_peak_band2_start` | Start of the second daily peak band (evening commuter peak), local clock. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_tac_peak_band2_end"></a>`track_tac_peak_band2_end` | End of the second daily peak band. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_tac_peak_weekdays_only"></a>`track_tac_peak_weekdays_only` | Whether the peak bands apply Monday to Friday only. The model knows a departure's clock time but not its weekday, so such a band is charged at its expected value — five sevenths of the overlap. | — | — |
| <a id="p-input_params-track_infrastructures-track_energy_price_night_eur_kwh"></a>`track_energy_price_night_eur_kwh` | Traction electricity price inside the country's night tariff band, charged pro rata on the share of a run that falls in it. Empty means one rate around the clock (AT, CH and HR are the only banded tariffs). Never resolved from the defaults row, which leaves it empty: a banded tariff is a national particularity, not a gap to fill. | €/kWh (EUR at 2032 prices) | [`energy_eur`](#f-calc-energy_eur) |
| <a id="p-input_params-track_infrastructures-track_energy_night_band_start"></a>`track_energy_night_band_start` | Start of the national electricity night tariff band, local clock. Bands may run across midnight (22:00–06:00). This is the ENERGY band and is independent of the track access night band (track_tac_night_band_start): Germany bands the track charge 23:00–06:00 and does not band electricity at all, Switzerland the reverse. | time of day | [`energy_night_share`](#f-calc-energy_night_share) |
| <a id="p-input_params-track_infrastructures-track_energy_night_band_end"></a>`track_energy_night_band_end` | End of the national electricity night tariff band, local clock. | time of day | — |
| <a id="p-input_params-track_infrastructures-track_energy_catenary_eur_train_km"></a>`track_energy_catenary_eur_train_km` | Charge for using the catenary and traction power-supply installations, where the infrastructure manager levies it per train-kilometre (FR, HR, HU, IT, LT, LU, LV, PL, RO). Empty means not levied in this unit — either not levied at all, or charged on weight in the column below, or already inside the energy price. Never resolved from the defaults row: roughly half of Europe's infrastructure managers levy this charge, so an uncalibrated country is priced without one rather than given an invented median. | €/train-km (EUR at 2032 prices) | [`energy_eur`](#f-calc-energy_eur) |
| <a id="p-input_params-track_infrastructures-track_energy_catenary_eur_gross_tonne_km"></a>`track_energy_catenary_eur_gross_tonne_km` | The same supply-equipment charge where the infrastructure manager levies it on the weight moved instead (FI, GR, SK), charged on the whole consist — coaches plus locomotives. | €/gross-tonne-km (EUR at 2032 prices) | [`energy_eur`](#f-calc-energy_eur) |
| <a id="p-input_params-track_infrastructures-track_parking_basis"></a>`track_parking_basis` | How the country prices one stabling occupation: per metre of train length per started 24 hours, per started hour (length-independent, as Germany's Anlagenpreissystem is by design), a flat charge per occupation with no time term, or 'none' where the network statement documents that no siding charge is levied. | — | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_metre_day"></a>`track_parking_eur_metre_day` | Stabling rate where the country prices by length and time. Empty means it prices in one of the other units. | €/metre per started 24 h (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_hour"></a>`track_parking_eur_hour` | Stabling rate where the country prices per started hour, independent of train length. | €/started hour (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_event"></a>`track_parking_eur_event` | Stabling charge where the country prices one occupation flat, with no time or length term. | €/occupation (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructures-track_parking_free_hours"></a>`track_parking_free_hours` | Free stabling allowance before the charge starts. Material where it exceeds a layover: Norway's 48 h and Croatia's 24 h zero a twelve-hour turnaround entirely. | hours | — |
| <a id="p-input_params-track_infrastructures-track_parking_hotel_power_eur_hour"></a>`track_parking_hotel_power_eur_hour` | Power the train draws while stabled, charged on ACTUAL stabled hours rather than on the billable hours after a free track allowance — the electricity flows whether or not the siding is free. One European proxy rate, from DB InfraGO's unmetered Elektrant flat charge. | €/stabled hour (EUR at 2032 prices) | — |
| <a id="p-input_params-track_infrastructures-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-track_infrastructures-track_infra_version"></a>`track_infra_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.track_infrastructures_version — never inferred. | — | — |

#### `input_params.passage_charges`

Crossings that are charged per traverse instead of per kilometre — the Storebælt and Øresund fixed links and the Channel Tunnel. A crossing is its own entity rather than a country attribute because the charging party is the crossing's operator: Øresund is two rows over one polygon, each infrastructure manager billing its half. Which trip segment crosses which passage is decided at routing time by polygon intersection, so a crossing split by an intermediate stop is still paid for once. Version bumps are full-table snapshots, resolved via scenario.scenarios.passage_charges_version — see db/README.md for the versioning contract.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-passage_charges-passage_row_id"></a>`passage_row_id` | — | — | — |
| <a id="p-input_params-passage_charges-passage_id"></a>`passage_id` | Stable crossing identifier (STOREBAELT, OERESUND_DK, OERESUND_SE, CHANNEL_TUNNEL). | — | — |
| <a id="p-input_params-passage_charges-passage_name"></a>`passage_name` | Full crossing name. | — | — |
| <a id="p-input_params-passage_charges-passage_fixed_eur"></a>`passage_fixed_eur` | Charge per train crossing, one way. | €/traverse (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-passage_charges-passage_per_passenger_eur"></a>`passage_per_passenger_eur` | Charge per carried passenger, one way (Channel Tunnel). Evaluated against the passengers actually aboard on the crossing segment, so this term follows demand. | €/passenger (EUR at 2032 prices) | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-passage_charges-passage_src"></a>`passage_src` | Source for the crossing charges. | — | — |
| <a id="p-input_params-passage_charges-passage_geom"></a>`passage_geom` | Crossing polygon (SRID 4326). A routed trip leg intersecting it owns the crossing. Static reference geometry — a tunnel does not move between scenarios; what the version pins are the charges. | — | — |
| <a id="p-input_params-passage_charges-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-passage_charges-passage_version"></a>`passage_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.passage_charges_version — never inferred. | — | — |

#### `input_params.stop_infrastructure_defaults`

Fallback station charge per country (empty country = global default). Version bumps are full-table snapshots, resolved via scenario.scenarios.stop_infrastructure_defaults_version — see db/README.md for the versioning contract.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-stop_infrastructure_defaults-stop_infra_default_id"></a>`stop_infra_default_id` | — | — | — |
| <a id="p-input_params-stop_infrastructure_defaults-country_code"></a>`country_code` | Country this default applies to. Empty = global fallback. | — | — |
| <a id="p-input_params-stop_infrastructure_defaults-stop_charge_eur"></a>`stop_charge_eur` | Fallback station fee per scheduled stop. | €/stop | — |
| <a id="p-input_params-stop_infrastructure_defaults-stop_charge_src"></a>`stop_charge_src` | Source for the station fee. | — | — |
| <a id="p-input_params-stop_infrastructure_defaults-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-stop_infrastructure_defaults-stop_infra_default_version"></a>`stop_infra_default_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.stop_infrastructure_defaults_version — never inferred. | — | — |

#### `input_params.stop_infrastructures`

Catalog of possible night train stops. An empty stop_charge_eur is resolved against stop_infrastructure_defaults by the loader. Version bumps are full-table snapshots — every stop's row is duplicated forward on any single-stop edit — resolved via scenario.scenarios.stop_infrastructures_version. See db/README.md for the versioning contract.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-stop_infrastructures-stop_infra_row_id"></a>`stop_infra_row_id` | — | — | — |
| <a id="p-input_params-stop_infrastructures-stop_id"></a>`stop_id` | Unique stop identifier. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_name"></a>`stop_name` | Official station name. | — | — |
| <a id="p-input_params-stop_infrastructures-country_code"></a>`country_code` | Two-letter country code (ISO 3166-1 alpha-2). | — | — |
| <a id="p-input_params-stop_infrastructures-stop_timezone"></a>`stop_timezone` | IANA timezone identifier (e.g. Europe/Berlin). | — | — |
| <a id="p-input_params-stop_infrastructures-stop_lat"></a>`stop_lat` | Latitude in WGS-84 decimal degrees. | ° | — |
| <a id="p-input_params-stop_infrastructures-stop_lon"></a>`stop_lon` | Longitude in WGS-84 decimal degrees. | ° | — |
| <a id="p-input_params-stop_infrastructures-stop_loc_src"></a>`stop_loc_src` | Source for the coordinates. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_charge_eur"></a>`stop_charge_eur` | Station fee per scheduled stop. Empty = the country or global default applies. | €/stop | [`station_charge_eur`](#f-calc-station_charge_eur) |
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

#### `scenario.scenarios`

Container pinning one version of each versioned infrastructure table. Exactly one row has is_current_base = TRUE (the live default); exactly one row per scenario_key has is_current_scenario = TRUE (the head of that what-if lineage). All five *_version columns are per-table full-snapshot version numbers, resolved by exact match, and are NOT NULL — a scenario is always a complete, self-contained pin, never a partial diff. routing_graph_key pins the routing graph the same way (the one piece of infrastructure living outside the database). Compositions, coach types, and operators are catalogs, not scenario-versioned. Full versioning contract: db/README.md.

| Column | Meaning | Unit | Used in |
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

---

## 9. Known limitations & placeholders

Full transparency about what is not (yet) a real model:

- **Demand**: uniform 70% booking at flat fares — see section 4. All
  revenue and per-sold-place figures inherit this assumption.
- **Energy**: flat 28 kWh/km regardless of weight, speed, terrain —
  calibration in progress (section 3).
- **CO2**: the night-train factor is an EU passenger-rail average, not
  yet derived from the route's own energy use and country power mixes;
  the savings estimate additionally rests on placeholder mode-shift
  shares (section 6).
- **Track access charges**: one flat rate per country — a
  segment-resolved model matching real infrastructure pricing systems is
  in preparation (see `OPEN_TODOS` in
  [`infrastructure/model.py`](../backend/models/infrastructure/model.py)).
- **Shunting**: fixed two movements per trip, a placeholder rule.

Every model records its open items in the `OPEN_TODOS` section of its
`model.py`, and every change to computed numbers is logged in that
file's `CHANGELOG` with date and rationale.
