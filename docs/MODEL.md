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
| Route & timetable builder | `0.9.18` | Route and timetable builder: turns a list of stops, a train composition, and a few mode selections into a complete route — trip pairs, travel and stopping times with schedule buffers, and a mirrored outbound/return night schedule. | [`model.py`](../backend/models/route/model.py) | [README.md](../backend/models/README.md) |
| Energy model | `0.9.1` | Traction energy model: estimates the electricity a train uses on each part of the route. Currently a flat 28 kWh per kilometre placeholder, until the weight/speed/terrain model is calibrated against Deutsche Bahn Trassenfinder data. | [`model.py`](../backend/models/energy/model.py) | [README.md](../backend/models/energy/README.md) |
| Demand model | `0.0.2` | Demand model (placeholder): assumes every accommodation class is 70% booked at a flat per-kilometre fare, spread evenly across all connections — a stand-in until a real demand model with directional demand, price sensitivity, and competition from other modes replaces it. | [`model.py`](../backend/models/demand/model.py) | [README.md](../backend/models/demand/README.md) |
| Cost & revenue evaluation | `0.9.14` | Cost and revenue evaluation: computes the operator's fixed and variable costs, the charges paid to infrastructure companies, and the ticket revenue of a route, then aggregates the result into views per route, trip pair, country, connection, route section, and stop. | [`model.py`](../backend/models/evaluation/model.py) | [README.md](../backend/models/evaluation/README.md) |
| Emissions model | `0.1.1` | Climate impact factors: how many grams of CO2-equivalent one passenger-kilometre causes by night train, plane, and car — used for the mode comparison and the CO2-savings estimate. The night-train value is a European average until a country-resolved, energy-based model replaces it. | [`model.py`](../backend/models/emissions/model.py) | [README.md](../backend/models/emissions/README.md) |
| Composition cost model | `0.9.2` | Composition cost model: calibrated purchase, maintenance, cleaning, crew, and availability parameters per train composition, in a 'new' and a 'refurbished' rolling stock family, at 2032 prices. | [`model.py`](../backend/models/compositions/model.py) | [CALIBRATION.md](../backend/models/compositions/calib/CALIBRATION.md) |
| Infrastructure parameter model | `0.9.1` | Infrastructure parameter model: per-country track access charges, station charges, electricity prices, terrain, schedule buffers, and minimum stopping times, with EU-average fallbacks — plus the catalog of possible night train stops. | [`model.py`](../backend/models/infrastructure/model.py) | [STOP_CLASSIFICATION.md](../backend/models/infrastructure/STOP_CLASSIFICATION.md) |
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
| Input | `m_loco` | Weight of the assumed standard locomotive | t | standard value [`TRACTION_LOCO_WEIGHT_T`](#s-route-traction_loco_weight_t) |
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

$$ E_{kWh,l} = m_t \times d_{km,l} \times \left( f_{weight} + f_{speed} \cdot \bar{v}^2_{kmh,l} + f_{terrain} \cdot s_{terrain,l} \right) $$

Electricity used on one country leg: the train's weight times the distance, scaled by three factors — a base factor, one growing with the square of speed (air resistance), and one for the terrain (hills and mountains cost energy).

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `m_t` | Train gross weight | t | formula [`train_weight`](#f-energy-train_weight) |
| Input | `d_km,l` | Distance of the country leg | km | computed upstream |
| Input | `f_weight` | Base energy factor per tonne-kilometre | kWh/(t·km) | parameter [`composition_type_energy_factor_weight`](#p-input_params-composition_types-composition_type_energy_factor_weight) |
| Input | `f_speed` | Air resistance factor, applied to speed squared | kWh/(t·km·(km/h)²) | parameter [`composition_type_energy_factor_speed`](#p-input_params-composition_types-composition_type_energy_factor_speed) |
| Input | `f_terrain` | Terrain factor, applied to the terrain score | kWh/(t·km) per terrain point | parameter [`composition_type_energy_factor_terrain`](#p-input_params-composition_types-composition_type_energy_factor_terrain) |
| Input | `v̄_kmh,l` | Average speed on the leg | km/h | formula [`avg_speed`](#f-energy-avg_speed) |
| Input | `s_terrain,l` | Terrain difficulty score of the leg's country | 1–100 | parameter [`track_terrain_score`](#p-input_params-track_infrastructures-track_terrain_score) |
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

$$ m_t = \sum_{coach} m_{coach,t} + m_{loco,t} $$

Total train weight: all coach weights added up, plus the locomotive.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `m_coach,t` | Weight of each coach | t | parameter [`coach_type_weight_gross_t`](#p-input_params-coach_types-coach_type_weight_gross_t) |
| Input | `m_loco,t` | Locomotive weight | t | standard value [`TRACTION_LOCO_WEIGHT_T`](#s-route-traction_loco_weight_t) |
| **Output** | `m_t` | Train gross weight | t | — |

**Used by:** [`energy_per_leg`](#f-energy-energy_per_leg)

<a id="f-energy-energy_dummy"></a>
#### `energy_dummy`

$$ E_{kWh,l} = c_{dummy} \times d_{km,l} $$

Placeholder currently in use: a flat 28 kWh per kilometre, regardless of weight, speed, or terrain — until the model above is calibrated.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_dummy` | Flat energy factor | kWh/km | standard value [`ENERGY_FLAT_FACTOR_KWH_KM`](#s-energy-energy_flat_factor_kwh_km) |
| Input | `d_km,l` | Distance of the country leg | km | computed upstream |
| **Output** | `E_kWh,l` | Electricity used on the country leg | kWh | — |
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

$$ C_{driver} = c_{driver/h} \times \left( \sum_{seg} t_{drive,h} \cdot f_{driver} + \sum_{stop} t_{dwell,h} \cdot f_{driver} \right) $$

Driver cost: the hourly driver rate times all hours the driver is on duty — driving between stops and waiting at them.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_driver/h` | Driver cost per hour on duty | €/h | parameter [`operator_driver_costs_eur_h`](#p-input_params-operators-operator_driver_costs_eur_h) |
| Input | `t_drive,h` | Driving time between stops | h | computed upstream |
| Input | `t_dwell,h` | Waiting time at stops | h | formula [`dwell_time_both`](#f-route-dwell_time_both) |
| Input | `f_driver` | Number of drivers the train needs | persons | parameter [`composition_type_driver_factor`](#p-input_params-composition_types-composition_type_driver_factor) |
| **Output** | `C_driver` | Annual driver cost | €/year | — |

**Used by:** [`operator_variable_total_eur`](#f-calc-operator_variable_total_eur)

<a id="f-calc-crew_eur"></a>
####### Cabin crew cost — `crew_eur`

$$ C_{crew} = c_{crew/h} \times \left( \sum_{seg} t_{drive,h} \cdot n_{crew} + \sum_{stop} t_{dwell,h} \cdot n_{crew} \right) $$

Cabin crew cost: the hourly rate per crew member times all hours the crew is on board — while driving and while waiting at stops.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `c_crew/h` | Cost per crew member per hour on duty | €/h | parameter [`operator_crew_costs_eur_h`](#p-input_params-operators-operator_crew_costs_eur_h) |
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
| Input | `c_loco,lease/h` | All-inclusive locomotive rental rate per hour in use | €/h | parameter [`operator_loco_lease_eur_h`](#p-input_params-operators-operator_loco_lease_eur_h) |
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

$$ C_{TAC} = \sum_{seg} \sum_{l \in seg} d_{km,l} \times p_{TAC,country(l)} $$

Track access charge — the 'rail toll' paid to each country's infrastructure company: the distance driven in the country times its per-kilometre rate.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `d_km,l` | Distance driven in the country | km | computed upstream |
| Input | `p_TAC,country(l)` | The country's track access charge per train-kilometre | €/train-km | parameter [`track_tac_eur_train_km`](#p-input_params-track_infrastructures-track_tac_eur_train_km) |
| **Output** | `C_TAC` | Annual track access charges | €/year | — |

**Used by:** [`infrastructure_total_eur`](#f-calc-infrastructure_total_eur)

<a id="f-calc-energy_eur"></a>
###### Traction electricity — `energy_eur`

$$ C_{energy} = \sum_{seg} \sum_{l \in seg} E_{kWh,l} \times p_{energy,country(l)} $$

Electricity cost for traction: the energy the train uses in each country times that country's electricity price.

| | Symbol | Meaning | Unit | Source |
|---|---|---|---|---|
| Input | `E_kWh,l` | Energy used in the country (from the energy model) | kWh | formula [`energy_per_leg`](#f-energy-energy_per_leg) |
| Input | `p_energy,country(l)` | The country's traction electricity price | €/kWh | parameter [`track_energy_price_eur_kwh`](#p-input_params-track_infrastructures-track_energy_price_eur_kwh) |
| **Output** | `C_energy` | Annual traction electricity cost | €/year | — |

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
| <a id="s-route-gtfs_service_start"></a>`GTFS_SERVICE_START` | `'2032-12-12'` | — |
| <a id="s-route-gtfs_service_end"></a>`GTFS_SERVICE_END` | `'2033-12-10'` | Nominal GTFS calendar window for persisted services — the project's target timetable year, 2032 (per the December-to-December European rail timetable-change convention: 2nd Sunday of December through the day before the following year's 2nd Sunday). GTFS requires concrete dates; the model itself only knows seasonal frequencies, so every saved service is pinned to this window until real timetable-year handling exists. Changing it changes persisted GTFS calendars, hence a version bump. If "2032" means the timetable period covering most of calendar year 2032 (starting Dec 2031) rather than the one starting Dec 2032, use "2031-12-14" / "2032-12-11". |
| <a id="s-route-mirror_min"></a>`MIRROR_MIN` | `26 * 60 + 30` | 02:30, expressed 'next day' (1590) on the continuous minutes-from-midnight scale used throughout (see models.utils.hhmm_to_min). Fixed constant that timetable_mode='simpleAutomatic' schedules are mirrored around, and that 'simpleAutomaticWithFixedNight' centers the fixed night interval on. |
| <a id="s-route-night_start_min"></a>`NIGHT_START_MIN` | `24 * 60` | 00:00 next day (1440) — threshold X of the night window. Boarding is judged on DEPARTURE time: a stop departing strictly before this classifies boarding; the fixed-night interval's start stop must depart strictly before this (23:59 at the latest). |
| <a id="s-route-night_end_min"></a>`NIGHT_END_MIN` | `29 * 60` | 05:00 next day (1740) — threshold Y of the night window. Alighting is judged on ARRIVAL time: a stop arriving at/after this classifies alighting; anything neither boarding nor alighting is a night stop. The fixed-night interval's end stop must arrive no earlier than this. |
| <a id="s-route-fixed_night_min_speed_ratio"></a>`FIXED_NIGHT_MIN_SPEED_RATIO` | `0.7` | timetable_mode='simpleAutomaticWithFixedNight' only: minimum acceptable ratio of the fixed interval's timetable speed (incl. slack + dwell) to its pure routing speed (driving + dynamics + buffer). Stretching a short interval to cover the night window can make it arbitrarily slow — below this ratio the trip carries a 'fixed_night_stretch_slow' entry in general_parameters.timetable_warnings (a warning, never an error). |
| <a id="s-route-weeks_per_season"></a>`WEEKS_PER_SEASON` | `26` | SUMMER (April–Sep) and WINTER (Oct–Mar) are each a fixed 26 weeks. |
| <a id="s-route-days_per_operating_week"></a>`DAYS_PER_OPERATING_WEEK` | `{'DAILY': 7, 'THREE_PER_WEEK': 3}` | Operating days per week per Frequency name — specific days of week aren't modelled, they don't affect cost or fleet sizing. |
| <a id="s-route-hsr_track_speed_threshold_kmh"></a>`HSR_TRACK_SPEED_THRESHOLD_KMH` | `230` | A track segment counts as high-speed infrastructure when its permitted track speed (GraphHopper's max_speed encoded value, from OSM maxspeed) STRICTLY exceeds this. 230 deliberately targets dedicated NEW-BUILD high-speed lines only (250+ per the UIC/EU convention, e.g. LGV, NBS, AV): upgraded conventional lines (200-230, e.g. German ABS corridors at 230) stay fully usable for night trains regardless of hsr_allowed, and 230 also matches the fastest seeded composition's own max_speed_kmh — track a night train could physically exploit is never treated as forbidden high-speed infrastructure. |
| <a id="s-route-hsr_track_speed_sanity_max_kmh"></a>`HSR_TRACK_SPEED_SANITY_MAX_KMH` | `500` | Upper guard on the same condition — excludes segments whose maxspeed is untagged in OSM. GraphHopper encodes a missing maxspeed as a sentinel (0 or infinity depending on version); the two-sided range (THRESHOLD, SANITY_MAX) excludes both conventions, so unknown-speed track is never mistaken for high-speed infrastructure. No real European rail line exceeds this value. |
| <a id="s-route-hsr_avoidance_priority_factor"></a>`HSR_AVOIDANCE_PRIORITY_FACTOR` | `0.01` | GraphHopper custom-model priority multiplier applied to high-speed segments where HSR is not allowed — a strong penalty (100x) rather than a hard block, so a route is still found if high-speed track is genuinely the only physical connection. |
| <a id="s-route-auto_stop_buffer_m"></a>`AUTO_STOP_BUFFER_M` | `10000` | Max distance (metres) from a stop to the already-routed path for that stop to be considered a candidate — covers both stops that sit right on the line and ones merely 'close by'. |
| <a id="s-route-auto_stop_analytic_detour_m"></a>`AUTO_STOP_ANALYTIC_DETOUR_M` | `100` | Perpendicular distance to the routed geometry under which an auto-stop candidate is costed purely analytically (dwell + the dynamics model's accel/brake pair + out-and-back detour at cruise speed) with no router call — at this distance the stop sits on the routed line and a mini-reroute measures the same number at ~1.5s of router time (introduced 2026-08-06 after the 575-stop catalog made per-candidate routing the dominant calc cost). Candidates further out are refined by a real 3-point mini-reroute, since their true track detour can exceed the straight-line bound — e.g. a station the initial routing bypassed on a parallel line, which is also why AUTO_STOP_BUFFER_M is wide. |
| <a id="s-route-auto_stop_max_detour_per"></a>`AUTO_STOP_MAX_DETOUR_PER` | `0.05` | Max allowed increase in full (driving + dynamics + buffer + dwell) trip time, as a fraction of the original trip's time, before mode 'add' stops adding further candidates. Mode 'suggest' deliberately ignores this budget. |
| <a id="s-route-traction_loco_weight_t"></a>`TRACTION_LOCO_WEIGHT_T` | `90.0` | Assumed standard locomotive weight (Siemens Vectron, ~90t). Locomotives are full-service leased and not part of the composition data, so the loco is a fixed standard assumption added on top of Composition.total_weight_t (which covers coaches only). |
| <a id="s-route-traction_loco_power_kw"></a>`TRACTION_LOCO_POWER_KW` | `6400.0` | Assumed locomotive continuous power at the wheel (Siemens Vectron AC: 6.4 MW). Governs the constant-power phase of acceleration above P / F ≈ 77 km/h. |
| <a id="s-route-traction_loco_tractive_effort_kn"></a>`TRACTION_LOCO_TRACTIVE_EFFORT_KN` | `300.0` | Assumed locomotive starting tractive effort (Siemens Vectron: 300 kN). Governs the constant-force phase of acceleration from standstill. |
| <a id="s-route-traction_brake_deceleration_ms2"></a>`TRACTION_BRAKE_DECELERATION_MS2` | `0.5` | Service braking deceleration. Rail braking is effectively mass-independent (brake systems are dimensioned per vehicle to a standard deceleration); 0.5 m/s² is a comfortable service value appropriate for sleeping passengers — full emergency capability is far higher and irrelevant for timetabling. |
| <a id="s-route-neutral_proposal_id"></a>`NEUTRAL_PROPOSAL_ID` | `0` | — |

#### Energy model — [`model.py`](../backend/models/energy/model.py)

| Constant | Value | Meaning |
|---|---|---|
| <a id="s-energy-energy_flat_factor_kwh_km"></a>`ENERGY_FLAT_FACTOR_KWH_KM` | `28.0` | Flat placeholder energy factor used by calc_energy_consumption.py until the weight/speed/terrain regression is calibrated. Every train is assumed to use this much electricity per kilometre, regardless of weight, speed, or terrain. |

#### Demand model — [`model.py`](../backend/models/demand/model.py)

| Constant | Value | Meaning |
|---|---|---|
| <a id="s-demand-stopgap_utilization_per"></a>`STOPGAP_UTILIZATION_PER` | `0.7` | Placeholder scalar utilization applied uniformly to every class until a real demand model lands. |
| <a id="s-demand-stopgap_fare_per_km_by_class"></a>`STOPGAP_FARE_PER_KM_BY_CLASS` | `{'Seat': 0.1, 'Couchette': 0.13, 'Sleeper': 0.18, 'Capsule': 0.12, 'Catering': 0.0}` | Placeholder flat per-km fares by class_main — same caveat as above. |
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
| <a id="p-input_params-countries-country_geom"></a>`country_geom` | Country border polygon (SRID 4326), seeded from Natural Earth admin-0 countries geojson. Empty for countries without a matched source feature. | — | — |

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

#### `input_params.operators`

Train operating company and its cost rates. A catalog, not history: operator_id is a permanent natural key — changed rates mean adding a new operator_id, never editing a row in place (soft-referenced from coach_types and composition_types).

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-operators-operator_row_id"></a>`operator_row_id` | — | — | — |
| <a id="p-input_params-operators-operator_id"></a>`operator_id` | Operator identifier (e.g. STD-REF, STD-NEW). | — | — |
| <a id="p-input_params-operators-operator_name"></a>`operator_name` | Full operator name. | — | — |
| <a id="p-input_params-operators-operator_driver_costs_eur_h"></a>`operator_driver_costs_eur_h` | Driver pay per hour on duty (roster inefficiency already included — billable hours equal trip time). | €/h | [`driver_eur`](#f-calc-driver_eur) |
| <a id="p-input_params-operators-operator_crew_costs_eur_h"></a>`operator_crew_costs_eur_h` | Cabin crew pay per hour on duty, per attendant. The train manager is counted with a factor on the composition. | €/h | [`crew_eur`](#f-calc-crew_eur) |
| <a id="p-input_params-operators-operator_ebit_margin_per"></a>`operator_ebit_margin_per` | Operating profit the operator requires, as a share of ticket revenue. | fraction of revenue | [`ebit_margin_eur`](#f-calc-ebit_margin_eur) |
| <a id="p-input_params-operators-operator_financing_quota_per"></a>`operator_financing_quota_per` | Annual financing cost as a share of the capital tied up in coaches. | fraction/year | [`financing_eur`](#f-calc-financing_eur) |
| <a id="p-input_params-operators-operator_var_overhead_per"></a>`operator_var_overhead_per` | Variable overhead — ticket sales, distribution, customer service — as a share of ticket revenue. | fraction of revenue | [`var_overhead_eur`](#f-calc-var_overhead_eur) |
| <a id="p-input_params-operators-operator_fix_overhead_quota_per"></a>`operator_fix_overhead_quota_per` | Fixed overhead — administration, management, planning — as a share of all other operating costs. | fraction of other costs | [`fix_overhead_eur`](#f-calc-fix_overhead_eur) |
| <a id="p-input_params-operators-operator_loco_lease_eur_h"></a>`operator_loco_lease_eur_h` | All-inclusive locomotive rental rate (maintenance and insurance included), billed per hour the locomotive is in use. Two speed configurations exist as separate operator rows: up to 200 km/h (STD-REF) and 230 km/h (STD-NEW). | €/h | [`loco_eur`](#f-calc-loco_eur) |
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

Train composition blueprint: which coaches, at which speed, with which cost parameters. Capacity comes from the coach list (composition_type_coaches → coach_type_classes). Locomotives are rented, not purchased — see operators.operator_loco_lease_eur_h. A catalog, not history: composition_type_id is a permanent natural key — new settings mean a new composition_type_id, never editing a row in place.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-composition_types-composition_type_row_id"></a>`composition_type_row_id` | — | — | — |
| <a id="p-input_params-composition_types-composition_type_id"></a>`composition_type_id` | Composition name (e.g. STD-3.1). | — | — |
| <a id="p-input_params-composition_types-composition_type_description"></a>`composition_type_description` | Short human-readable description of the composition. | — | — |
| <a id="p-input_params-composition_types-composition_type_operator_id"></a>`composition_type_operator_id` | Operator running this composition (soft reference to operators.operator_id). | — | — |
| <a id="p-input_params-composition_types-composition_type_hsr_allowed"></a>`composition_type_hsr_allowed` | Whether this train may use high-speed lines at all (combined with each country's own permission). | — | — |
| <a id="p-input_params-composition_types-composition_type_max_speed_kmh"></a>`composition_type_max_speed_kmh` | Maximum operational speed. | km/h | — |
| <a id="p-input_params-composition_types-composition_type_energy_factor_weight"></a>`composition_type_energy_factor_weight` | Energy model: base factor per tonne-kilometre. | kWh/(t·km) | [`energy_per_leg`](#f-energy-energy_per_leg) |
| <a id="p-input_params-composition_types-composition_type_energy_factor_speed"></a>`composition_type_energy_factor_speed` | Energy model: air resistance factor, applied to speed squared. | kWh/(t·km·(km/h)²) | [`energy_per_leg`](#f-energy-energy_per_leg) |
| <a id="p-input_params-composition_types-composition_type_energy_factor_terrain"></a>`composition_type_energy_factor_terrain` | Energy model: terrain factor, applied to the terrain score. | kWh/(t·km) per terrain point | [`energy_per_leg`](#f-energy-energy_per_leg) |
| <a id="p-input_params-composition_types-composition_type_min_boarding_time"></a>`composition_type_min_boarding_time` | Minimum waiting time this train needs at stops where passengers board. | interval (hh:mm:ss) | [`dwell_time_boarding`](#f-route-dwell_time_boarding), [`dwell_time_both`](#f-route-dwell_time_both) |
| <a id="p-input_params-composition_types-composition_type_min_alighting_time"></a>`composition_type_min_alighting_time` | Minimum waiting time this train needs at stops where passengers get off. | interval (hh:mm:ss) | [`dwell_time_alighting`](#f-route-dwell_time_alighting), [`dwell_time_both`](#f-route-dwell_time_both) |
| <a id="p-input_params-composition_types-composition_type_purchase_coach_eur"></a>`composition_type_purchase_coach_eur` | Average purchase price per coach, from the per-metre price model (new 145 / refurbished 53 k€ per metre of coach, double-deck ×1.12) applied to this composition's coach lengths. Derivation: calib/CALIBRATION.md. | €/coach | [`coach_amortisation_eur`](#f-calc-coach_amortisation_eur), [`financing_eur`](#f-calc-financing_eur) |
| <a id="p-input_params-composition_types-composition_type_coach_avail_per"></a>`composition_type_coach_avail_per` | Share of calendar days a coach is available for service (the rest it is in the workshop). | fraction | — |
| <a id="p-input_params-composition_types-composition_type_coach_amort_years"></a>`composition_type_coach_amort_years` | Useful life over which a coach is written off. | years | [`coach_amortisation_eur`](#f-calc-coach_amortisation_eur) |
| <a id="p-input_params-composition_types-composition_type_cleaning_eur_day"></a>`composition_type_cleaning_eur_day` | Cleaning and preparation for the next night, per coach and operating day, at 2032 prices. | €/coach/day | [`cleaning_eur`](#f-calc-cleaning_eur) |
| <a id="p-input_params-composition_types-composition_type_coach_maint_eur_km"></a>`composition_type_coach_maint_eur_km` | Coach maintenance for the whole train per kilometre (per-coach rate × number of coaches; new 1.00 / refurbished 1.30 €/coach-km, 2032 prices). | €/train-km | [`coach_maintenance_eur`](#f-calc-coach_maintenance_eur) |
| <a id="p-input_params-composition_types-composition_type_driver_factor"></a>`composition_type_driver_factor` | Number of drivers required per trip (e.g. 1 or 2). | persons | [`driver_eur`](#f-calc-driver_eur) |
| <a id="p-input_params-composition_types-composition_type_n_locos"></a>`composition_type_n_locos` | Number of locomotives. Scales the locomotive rental cost and (once calibrated) the energy weight basis. | count | — |
| <a id="p-input_params-composition_types-composition_type_zugchef_crew_factor"></a>`composition_type_zugchef_crew_factor` | Train manager, counted in attendant-equivalents (1.19; 2.38 for trains with 10 or more coaches). Total crew = sum of coach crew factors + this factor. | attendant-equivalents | — |
| <a id="p-input_params-composition_types-composition_type_length_cost_prop"></a>`composition_type_length_cost_prop` | Weighting X of the class cost split: X by length, (1−X) by weight, on passenger space; service areas are split per place. See calib/CALIBRATION.md. | fraction | [`class_main_allocation`](#f-calc-class_main_allocation) |
| <a id="p-input_params-composition_types-composition_type_food_and_beverages"></a>`composition_type_food_and_beverages` | Catering concept (e.g. 'dining car'). Coach amenities aggregate separately. | — | — |
| <a id="p-input_params-composition_types-composition_type_material_strategy"></a>`composition_type_material_strategy` | Rolling stock family: 'new' (230 km/h-capable, 30-year write-off, 0.909 availability) or 'refurbished' (200 km/h cap, 12 years, 0.80). Selects the matching operator row (STD-NEW / STD-REF) and parameter family — see calib/CALIBRATION.md. | — | — |
| <a id="p-input_params-composition_types-composition_type_indicative_cost_eur_train_km"></a>`composition_type_indicative_cost_eur_train_km` | Indicative operator cost per train-kilometre on the 1,000 km reference route (14.5 h trip, 350 operating days, 2 trainsets) at 2032 prices, excluding infrastructure charges, energy, variable overhead and profit — a comparison figure between compositions, not a route evaluation. Derivation: calib/CALIBRATION.md. | €/train-km | — |
| <a id="p-input_params-composition_types-composition_type_indicative_cost_ct_place_km"></a>`composition_type_indicative_cost_ct_place_km` | The same cost basis divided by the number of places. | ct/place-km | — |
| <a id="p-input_params-composition_types-source_id"></a>`source_id` | Source for all values in this row. | — | — |

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
| <a id="p-input_params-track_infrastructure_defaults-track_tac_eur_train_km"></a>`track_tac_eur_train_km` | Track access charge — the 'rail toll' paid to the country's infrastructure company per kilometre driven. | €/train-km | — |
| <a id="p-input_params-track_infrastructure_defaults-track_tac_src"></a>`track_tac_src` | Source for the track access charge. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_eur_day"></a>`track_parking_eur_day` | Cost of parking the train overnight between two nights of service. | €/day | — |
| <a id="p-input_params-track_infrastructure_defaults-track_parking_src"></a>`track_parking_src` | Source for the parking cost. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_shunting_eur_event"></a>`track_shunting_eur_event` | Cost of one shunting movement (coupling, uncoupling, moving the train in the yard). | €/event | — |
| <a id="p-input_params-track_infrastructure_defaults-track_shunting_src"></a>`track_shunting_src` | Source for the shunting cost. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_energy_price_eur_kwh"></a>`track_energy_price_eur_kwh` | Traction electricity price. | €/kWh | — |
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
| <a id="p-input_params-track_infrastructure_defaults-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-track_infrastructure_defaults-track_infra_default_version"></a>`track_infra_default_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.track_infrastructure_defaults_version — never inferred. | — | — |

#### `input_params.track_infrastructures`

Country-level track parameters. Empty fields are resolved against track_infrastructure_defaults by the loader. Version bumps are full-table snapshots — every country's row is duplicated forward on any single-country edit — resolved via scenario.scenarios.track_infrastructures_version. See db/README.md for the versioning contract.

| Column | Meaning | Unit | Used in |
|---|---|---|---|
| <a id="p-input_params-track_infrastructures-track_infra_row_id"></a>`track_infra_row_id` | — | — | — |
| <a id="p-input_params-track_infrastructures-country_code"></a>`country_code` | Two-letter country code (ISO 3166-1 alpha-2). | — | — |
| <a id="p-input_params-track_infrastructures-track_tac_eur_train_km"></a>`track_tac_eur_train_km` | Track access charge — the 'rail toll' paid to the country's infrastructure company per kilometre driven. | €/train-km | [`tac_eur`](#f-calc-tac_eur) |
| <a id="p-input_params-track_infrastructures-track_tac_src"></a>`track_tac_src` | Source for the track access charge. | — | — |
| <a id="p-input_params-track_infrastructures-track_parking_eur_day"></a>`track_parking_eur_day` | Cost of parking the train overnight between two nights of service. | €/day | [`parking_eur`](#f-calc-parking_eur) |
| <a id="p-input_params-track_infrastructures-track_parking_src"></a>`track_parking_src` | Source for the parking cost. | — | — |
| <a id="p-input_params-track_infrastructures-track_shunting_eur_event"></a>`track_shunting_eur_event` | Cost of one shunting movement (coupling, uncoupling, moving the train in the yard). | €/event | [`shunting_eur`](#f-calc-shunting_eur) |
| <a id="p-input_params-track_infrastructures-track_shunting_src"></a>`track_shunting_src` | Source for the shunting cost. | — | — |
| <a id="p-input_params-track_infrastructures-track_energy_price_eur_kwh"></a>`track_energy_price_eur_kwh` | Traction electricity price. | €/kWh | [`energy_eur`](#f-calc-energy_eur) |
| <a id="p-input_params-track_infrastructures-track_energy_price_src"></a>`track_energy_price_src` | Source for the electricity price. | — | — |
| <a id="p-input_params-track_infrastructures-track_terrain_category"></a>`track_terrain_category` | Rough terrain classification: Flat, Hilly, or Mountainous. | — | — |
| <a id="p-input_params-track_infrastructures-track_terrain_score"></a>`track_terrain_score` | Terrain difficulty score — hills and mountains increase energy use. | 1–100 | [`energy_per_leg`](#f-energy-energy_per_leg) |
| <a id="p-input_params-track_infrastructures-track_terrain_src"></a>`track_terrain_src` | Source for terrain category and score. | — | — |
| <a id="p-input_params-track_infrastructures-track_hsr_allowed"></a>`track_hsr_allowed` | Whether night trains may use the country's high-speed lines. | — | — |
| <a id="p-input_params-track_infrastructures-track_hsr_src"></a>`track_hsr_src` | Source for the high-speed permission. | — | — |
| <a id="p-input_params-track_infrastructures-track_min_boarding_time"></a>`track_min_boarding_time` | Minimum waiting time the country's stations need at stops where passengers board. | interval (hh:mm:ss) | [`dwell_time_boarding`](#f-route-dwell_time_boarding), [`dwell_time_both`](#f-route-dwell_time_both) |
| <a id="p-input_params-track_infrastructures-track_min_boarding_src"></a>`track_min_boarding_src` | Source for the minimum boarding time. | — | — |
| <a id="p-input_params-track_infrastructures-track_min_alighting_time"></a>`track_min_alighting_time` | Minimum waiting time the country's stations need at stops where passengers get off. | interval (hh:mm:ss) | [`dwell_time_alighting`](#f-route-dwell_time_alighting), [`dwell_time_both`](#f-route-dwell_time_both) |
| <a id="p-input_params-track_infrastructures-track_min_alighting_src"></a>`track_min_alighting_src` | Source for the minimum alighting time. | — | — |
| <a id="p-input_params-track_infrastructures-track_buffer_quota_per"></a>`track_buffer_quota_per` | Schedule buffer added on top of driving time, reflecting how congested and delay-prone the network is. | fraction of driving time | [`buffer_time`](#f-route-buffer_time) |
| <a id="p-input_params-track_infrastructures-track_buffer_src"></a>`track_buffer_src` | Source for the buffer quota. | — | — |
| <a id="p-input_params-track_infrastructures-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-track_infrastructures-track_infra_version"></a>`track_infra_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.track_infrastructures_version — never inferred. | — | — |

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
| <a id="p-input_params-stop_infrastructures-change_log"></a>`change_log` | Free-text description of what changed in this version and why. | — | — |
| <a id="p-input_params-stop_infrastructures-stop_infra_version"></a>`stop_infra_version` | Per-table full-snapshot version number. Resolved via scenario.scenarios.stop_infrastructures_version — never inferred. | — | — |

#### `scenario.scenarios`

Container pinning one version of each versioned infrastructure table. Exactly one row has is_current_base = TRUE (the live default); exactly one row per scenario_key has is_current_scenario = TRUE (the head of that what-if lineage). All four *_version columns are per-table full-snapshot version numbers, resolved by exact match, and are NOT NULL — a scenario is always a complete, self-contained pin, never a partial diff. Compositions, coach types, and operators are catalogs, not scenario-versioned. Full versioning contract: db/README.md.

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
