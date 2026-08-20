# Night Train — Demand Model Concept

> Status: **draft for discussion**, 2026-08-19. Intended home:
> `backend/models/demand/DEMAND_MODEL_CONCEPT.md`, next to `README.md` and
> `model.py`. Supersedes the one-paragraph "Incoming design" note in
> `models/demand/README.md` once agreed. Revision 2 (2026-08-19): utility
> specification and segments reworked against the stated-choice literature
> in `03_demand/` (§2.5). Revision 3 (2026-08-19): revealed stop-time
> distribution adopted as window prior, NUTS-3 choice cross-validated,
> gravity attraction/affinity priors, node-potential heuristic comparison
> (§2.9). Revision 4 (2026-08-19): aviation feasibility screen, load-factor
> and capacity plausibility bands, habit/pivot rationale, consumer-surplus
> output, base-year and sensitivity rules (Blainey & Hare 2025; Wessling,
> Arnet & Loder 2026); demand-data source inventory (§3) still to be
> confirmed. Revision 5 (2026-08-19): zone-frame decisions taken (NUTS
> vintage pin, centroid definition, country scope — §2.1, §5); §3 replaced
> by a confirmed, acquisition-ordered inventory with a licence register;
> DM1 split into DM1a (zone frame) and DM1b (access matrix, gated on the
> airport layer). Revision 6 (2026-08-20): GHS-POP added to §3 batch 1 as the
> population-weighting fallback for zones outside the census grid, following
> Tier 2 routing moving into near-term scope.

---

## 1. What the model has to answer

One night train route proposal (stops, boarding/alighting classification,
composition, timetable, scenario) comes in. The model answers, per
operating year:

| Output | Granularity | Consumer today |
|---|---|---|
| Passengers and average fare | per trip × OD × `class_main` | `ODPair` → revenue in `evaluation/calc.py` (unchanged contract) |
| Passengers by origin mode | per OD and route total: shift from air, shift from car, shift from day rail, induced (new trips) | new value keys in `views` (`per_trip_pair_per_od`, `route`, `per_year` for free) → gallery projection (`proposal_summaries` demand columns), `summary.py` CO2 savings |
| Demand satisfied vs. demand not satisfied (capacity) | per OD × class | new — tells the proposer "this train is too small / too big" |
| Price-response curve | per class, for the fixed route and composition: demand and revenue per price point | new — the proposer's price lever; the chosen point feeds `ODPair` |
| Demand response to the other levers | composition (class mix = comfort), timetable windows | returned in the same response |
| User benefit (consumer surplus) | per origin zone × segment, € per year; route total | **stretch / DM9** — the logsum difference with vs. without the night train, divided by the segment's cost coefficient; nearly free once the logsum exists (§2.4), comparable with the subsidy figures `summary.py` already reports (§2.5: €7.5–15 M p.a. on Munich–Rome vs. €5–10 M reported support on comparable corridors) |

Everything else (cost, subsidy per t CO2, €/pax-km) already exists
downstream and needs no change once `ODPair` and the views carry real
numbers. The model introduces no new storage location for outputs
(`adapters/proposal/README.md` §8.1 stays valid).

---

## 2. Model architecture

Two halves, split along the line that keeps runtime cheap:

```
OFFLINE (seed / ETL, versioned, Drive-hosted)          RUNTIME (per /calc)
────────────────────────────────────────────          ─────────────────────────
zones + socio-economics (DM1)                          Route → NT level of service
  └─ background OD demand 2032 (DM2, DM3)                per OD (times, windows,
       per zone pair × segment:                          fare, classes) (DM6)
       trips by mode (air / car / day rail)                │
  └─ level of service per zone pair × mode (DM4)           ▼
       time, cost, access/egress                       incremental nested logit
  └─ choice parameters (DM5)                             per OD × segment
       VoT, ASCs, nests, scale — scenario-versioned       │
                                                          ▼
                                                       capacity constraint,
                                                       class choice → ODPair,
                                                       shift decomposition → views
```

Runtime touches only (a) the zone pairs whose access/egress reach the
proposed stops and (b) pre-joined background rows — no gravity model, no
external routers, no Monte Carlo at request time. That is the property that
lets `POST /api/proposal/calc` stay interactive and keeps results
deterministic for the compute cache and the test suite.

### 2.1 Zone system (DM1)

Demand unit: **NUTS-3 region** (≈1 500 zones across the catalog's
countries; UK/CH/NO/Balkans via their NUTS-equivalent statistical regions).
Each zone carries population, GDP, employment, tourist overnight stays
(Eurostat `tour_occ_nin3`), centroid, and a **weighted set of reachable
airports** rather than a single nearest one: a zone's air trips are spread
across airports with a distance-decay (gravity) weight, so trips that
continue overland after landing (Munich for Innsbruck, Copenhagen for
Malmö) are captured on both the access and the egress side. Stops get
no fixed catchment: the zone → stop relation is a precomputed
**access-time matrix** (zone centroid → every catalog stop within a cap,
e.g. 90 min car/rail), so a proposal's catchment follows from which stops
it calls at. This is what makes "Berlin Hbf vs. Berlin Südkreuz" or
"adding Würzburg" change demand without any hand-drawn catchments.

Three properties of the zone frame are pinned (2026-08-19):

- **Vintage: NUTS 2021**, carried as `nuts_version` inside the
  `demand_version` pin. NUTS 2024 is legally in force, but the sources we
  back-cast and disaggregate against (Rickfelder 2025, ETISplus, the
  national matrices) are on 2021 or older, and Eurostat's regional tables
  are currently split across both. Crosswalk columns (`nuts_2024`,
  `crosswalk_relation` ∈ identical / renamed / split / discontinued) are a
  first-class part of the DM1a artifact, so the pin can be moved later without
  re-deriving anything. Successors are established by **geometric overlap**,
  not by code matching: code sets alone cannot tell a rename from a split from
  a coincidental reuse.
- **Centroid: population-weighted**, from the Eurostat GEOSTAT 1 km²
  census grid where it reaches, from GHS-POP R2023A elsewhere, and from the
  geometric representative point only where neither does; `centroid_source`
  records which supplied each. The census grid covers 30 countries, GHS-POP
  is global, and the two are never mixed within a zone. Geometric centroids
  are badly wrong for large, sparsely settled or coastal zones — Norrbotten,
  Highland, the Alpine zones — which are precisely the zones where access
  time decides whether the zone is in a stop's catchment at all.
  - Two refinements the first run made necessary: multipart zones take the
    centroid of their **most populous part**, since a weighted mean across an
    archipelago lands in open water; and where the weighted mean falls outside
    the zone — annular zones ringing a city, such as Středočeský around
    Prague — it is **snapped to the nearest populated cell**, because a point
    beside a main station in a zone where nobody lives there would flatter the
    DM1b access time for exactly the commuter belts that matter.
- **Scope: built wide, filtered narrow.** Zones are built for EU-27 +
  EFTA + UK + candidate countries and carry a `tier` column (1 = routable
  now, 2 = UK/NO and other deferred scope, §5). Geometry is cheap;
  re-deriving the zone frame to add a country later would invalidate every
  downstream pin.

Decided: NUTS-3 (2026-08-19). NUTS-2 (~300 zones) would blur the catchment
question badly (Bavaria is one zone). NUTS-3 gives ~1.1 M unordered pairs;
filtered to the night train relevance band (say 300–2 000 km great circle)
it drops to a few hundred thousand rows — fine for PostGIS, ~50 MB CSV on
Drive. The distance band is only the *offline* pre-filter; great-circle
distance is a poor proxy for rail journey time (Blainey & Hare 2025 show
why: directness and speed vary too much). The runtime relevance test is on
the proposal's actual NT journey time per OD (§2.4), which the router gives
us for free.

Cross-check: Rickfelder (2025) independently arrives at NUTS-3 regions as
demand nodes for night train supply planning, for the same reasons
(publicly available, standardised, comparable; no station-level demand
data exists) and with usable results against the 2021 ES/PT/FR services.
Where railway lines through one NUTS-3 zone do not connect he records the
zone twice; in our design the zone itself stays unique and the
zone → stop access matrix carries the topology: a zone with several
catalog stops (Berlin Hbf / Südkreuz, Paris Nord / Est / Austerlitz) is
split across them by access time, with published station passenger counts
as an optional tie-break weight where access times are close.

### 2.2 Background demand (DM2, DM3)

Step 1 — observed OD flows per mode, at whatever granularity the source
gives (air: airport pair; rail: country pair or NUTS-2; car: country pair /
national models). Step 2 — extrapolate to 2032 with per-country, per-mode
growth factors (EU Reference Scenario; national forecasts where better).
Step 3 — disaggregate to zone pairs with a **doubly-constrained gravity
model** whose production/attraction terms use the zone socio-economics and
whose impedance is the composite generalized cost across modes; Furness/IPF
balancing so that zone-pair sums reproduce the country-pair (or
airport-pair) control totals exactly. Step 4 — split each zone pair into
**traveller segments** with fixed shares by purpose from national travel
surveys:

| Segment | Share driver in zone data | Cost sensitivity | Night train affinity | Class preference | Timing |
|---|---|---|---|---|---|
| business | employment, GDP | low (≈ 0.8× leisure) | strong penalty vs. flying the day before; early arrival valued | sleeper / capsule, private | needs a working morning at destination |
| leisure – comfort | population 30–64, income | medium (reference) | positive | couchette 2–4 / sleeper; privacy over amenities | flexible; "hotel night saved" |
| leisure – budget | population 18–29, students | very high (≈ 3× reference) | positive | capsule / couchette / seat | flexible |
| senior leisure | population 65+ | low–medium | highest (age effect) | class type matters less; lockable, lower berth | flexible; early arrival fine |

The four are the purpose × life-stage axes the stated-choice studies find
decisive (§2.5): trip purpose is by far the strongest covariate, age the
second, price sensitivity the third; income and education enter as weaker
modifiers. Private/VFR travel is carried inside the two leisure segments
(by income share), not as its own segment. Shares per zone pair are derived
from NUTS-3 age structure (Eurostat `demo_r_pjangrp3`), employment and
overnight stays; purpose split from national travel surveys. The five-year
age groups of `demo_r_pjangrp3` are required, not the broad groups of
`demo_r_pjanaggr3` (0–14 / 15–64 / 65+): the latter cannot separate
leisure-budget (18–29) from leisure-comfort (30–64).

Segment shares, VoT and ASCs are scenario-versioned parameters (§2.7),
not code constants. Party size and luggage are not segment axes in v1:
families (who value 4–6-berth compartments that solo travellers reject)
sit inside leisure-comfort, and the "heavy luggage pushes travellers to car
and plane" effect (Bavarian DCE, §2.5) is absorbed by the car/air ASC
spread. A party-size dimension is a DM9 candidate if the back-cast shows
the class nest systematically under-predicting couchette demand.

Gravity priors for DM3. Production/attraction terms start from the
additive form Rickfelder (2025) uses as a node potential — population
weighted by a GDP-per-capita index plus population weighted by the zone's
share of tourist overnight stays — with the weights per segment (business
on GDP/employment, leisure on overnight stays). His ES/PT/FR back-test
shows why the tourism term must not be folded into population: the
algorithm adds intermediate stops where real Paris→south night trains run
non-stop to rural tourist destinations, i.e. leisure attraction is strongly
asymmetric. The impedance carries, besides the composite generalised cost,
an **affinity term** (shared language, historic ties, common border —
dummies calibrated in the IPF step): operators report that only relations
with a "robust origin–destination relationship" work (Tomeš & Pařil 2026),
and such terms are standard in international gravity models. Flows are
treated as paired (return = outward), so unordered zone pairs suffice;
directional timetable effects enter only through the level of service.

This is the "synthetic trip set" of David's step 4, held as
**weighted prototypical travellers per zone pair × segment** (sample
enumeration; decided 2026-08-19) rather than drawn individuals. Segment
weights per zone pair come from survey purpose shares, modulated by the
zone attributes (business share scales with GDP/employment, tourist share
with overnight stays). The choice model below is a closed-form logit, so the
Gumbel error term already represents "some people fly even if it costs
more"; Monte Carlo adds variance without adding information. Individual
draws can be added later for visualisation, never for the headline numbers.

### 2.3 Level of service per mode (DM4)

Precomputed per zone pair, stored beside the background demand. Default
is **real routings and real schedules** for every mode; each layer has a
documented analytic fallback (air distance × country detour factor ×
average speed, plus fixed process times) for a first version should the
real data prove too heavy to gather:

- **car**: door-to-door routing pass with OpenRouteService / GraphHopper
  car profile (same engine family as `openrailrouting`, run once offline,
  not part of the runtime stack), giving time, distance, and tolls; a
  **traffic add-on** on top (time-of-day and corridor-based delay factors,
  from the router's traffic layer where available, otherwise calibrated
  per country class); cost = fuel + tolls per km by country share, with a
  per-segment occupancy assumption. Overnight driving (> ~8 h) adds a
  penalty / hotel cost.
- **air**: from real flight schedules (OAG/Cirium-type or an open schedule
  feed, cross-checked against Eurostat `avia_par` airport pairs): block
  time, frequency, plus access/egress to the zone's weighted airport set
  and fixed process time (check-in, security, buffers). Fare from a
  distance/frequency fare model calibrated on published average fares.
  The zone-pair value is the gravity-weighted mix over the served airport
  pairs (§2.1).
- **day rail**: from real timetables (GTFS feeds where available, the rail
  router on zone reference stations as fallback; `country_relations.
  rail_time_h` is the coarsest seed), fare from a per-country distance
  model.
- **night train (runtime, DM6)**: from the `Route` — departure/arrival per
  stop, duration, number of nights; access/egress from the zone → stop
  matrix; fare from the fare model; available classes from the composition.

### 2.4 Choice model (DM5, DM6)

**Nested logit, incremental form.** Base shares per zone pair × segment are
observed (after 2032 extrapolation). Adding the night train alternative:

```
P_NT = exp(V_NT / λ) / (Σ_m S_m · exp(ΔV_m / λ) + exp(V_NT / λ))
```

where the existing modes enter through their base shares `S_m` (pivot-point
logit), so the model reproduces today's split exactly when no night train
exists and only needs the *difference* in utilities to be right. The
pivot is also the right representation of **habit**: the Bavarian DCE
finds past mode use the strongest traveller covariate and prior night
train exposure raising uptake regardless of satisfaction (§2.5), i.e.
observed base shares carry inertia that no attribute explains — anchoring
on them is the cheapest correct way to keep it. That is
also why the literature's alternative-specific constants are not imported
(they range from strongly positive to strongly negative across studies):
only ratios — values of time, willingness to pay, penalties in time units —
are taken from the evidence base (§2.5); levels come from back-casting.

Utility per segment `s`, in a common money-metric form (everything divided
by the segment's cost coefficient, so parameters read as € or €/h):

```
V_m / β_cost,s =
      fare_m
    + VoT_m,s     · in-vehicle time_m            (mode-specific: plane hour ≈ 2× NT hour,
                                                  day-rail hour ≈ 0.9–1× NT hour — the
                                                  Bavarian DCE puts it at ≈ 1×: "night-train
                                                  time is real time")
    − sleep_credit_s · NT hours inside the night window   (NT only; bounded so that a
                                                  night hour never becomes a net benefit)
    + VoT_acc,s   · (access + egress time)        (≈ 1.5–2× in-vehicle VoT, all modes)
    + transfer_pen_s · transfers                 (day rail / access legs; NT v1 is direct)
    + window_pen_s · f(departure hour, arrival hour)  (piecewise; prior from the
                                                  revealed stop-time distribution, §2.5)
    + night_pen_s · (nights − 1)
    − comfort_WTP_s(class, occupancy, privacy)   (NT only, per class nest below)
    + purpose_pen_s                              (business penalty on NT, in €)
    + ASC_m,s                                    (back-cast)
```

Nest structure:

```
travel?  ── no (induced demand via logsum elasticity at this level)
         └─ yes ── air
                ── car
                ── rail ── day rail
                        └─ night train ── seat / couchette / capsule / sleeper
```

Night train inside the rail nest gives "shift from day rail is larger than
shift from air per unit of utility gain" without hand-set shift shares (what
`emissions/model.py::MODE_SHIFT_SHARES` fakes today). The Dutch stated-choice
work found a different correlation — night train and *morning plane* share
unobserved attributes (same-day arrival) — so the nest parameter λ is a
calibration quantity, and a variant with a "same-day-arrival" nest is kept
as a test case, not a second model.

**Class choice** is the lowest nest: given the composition's classes,
segment share per class follows from the class's comfort value and fare.
The evidence is unambiguous that **privacy (people per compartment) is the
comfort driver**, with diminishing returns (1→3 "stars" worth roughly
€110–140, 3→5 roughly €80–100), while showers and a restaurant car add
little. The comfort value therefore comes from a small table of
per-`service_class` attributes (berths per compartment, lockable/private,
shower) rather than from the class name alone — `input_params.
service_classes` gains those two or three columns. "Composition chosen"
thus changes demand through which classes exist, their occupancy layout,
and how many places each has (capacity).

**Timetable windows**: no stated-choice study varied departure/arrival
times, so the shape of `window_pen` comes from revealed supply behaviour:
the hour-of-day distribution of all 2 378 scheduled night train stops in
the 2021 N/C/W European timetable (Rickfelder & Schönberger 2024, Fig. 4)
peaks at 22:00–23:59 for departures and 06:00–07:59 for arrivals, with a
trough 01:00–03:59 (a 06:00 stop is ≈ 3.5× as frequent as a 02:00 stop).
The normalised inverse of that histogram is the v1 prior for the
per-hour penalty at both ends, coupled to day-journey duration and the
sleep-time floor as before (§2.8). It is a supply-side proxy — it
conflates traveller preference with operational constraints — so it is a
prior, not a fixed curve; the back-cast may flatten it. The one stated
preference on windows we have (Rüger & Matausch 2020, via Blainey & Hare
2025: preferred departure ≈ 20:00, arrival 06:00–08:00) sits on the same
peaks. **Journey-time relevance** per OD is a hard band on top of the
penalty: below ≈ 7 h there is no full night's sleep, above ≈ 16 h the
night train no longer saves a travel day (Blainey & Hare 2025; Rüger &
Matausch give 12–14 h as the competitive ceiling) — STANDARD VALUES
`NT_MIN_JOURNEY_H` / `NT_MAX_JOURNEY_H`, outside which the OD gets no NT
alternative at all. This also closes the critique Blainey & Hare level at
the 2022 Back-on-Track potential estimate (Maier 2022): routes under 7 h
were counted, and no sensitivity on load factors was shown (§2.6). The **boarding /
alighting classification** default follows the UIC travel-phase rule the
same data confirm: boarding stops until midnight, alighting stops from
06:00, intermediate stops neither unless the proposer says so.

**Induced demand (logsum elasticity)**: the logsum
`L = ln Σ_m exp(V_m)` of the travel nest is the expected best utility a
traveller gets from all modes on a relation. Adding a night train raises
`L`; total trips respond with a per-segment elasticity `η`:
`T_new = T_base · exp(η · ΔL)`. Internally consistent with the mode split
(a night train nobody chooses induces nearly nothing), one parameter per
segment, conservative by construction (long-distance `η` ≈ 0.1–0.3 in the
literature). Shift is computed on the base total; induced trips come on top.
The German aggregate studies assume induced ≈ 10 % of night train riders —
a plausibility band for the back-cast, not an input.

**Capacity**: demand per OD × class vs. places offered per night ×
operating days (the same `places_by_class` the stopgap uses). First cut:
`places_sold = min(demand, capacity)` with proportional cut across ODs of
a trip. Both **demand satisfied** and **demand not satisfied** are kept and
returned per OD × class — a first-class output, not a diagnostic. Two
cheap diagnostics ride along: a flag when a single stop (or OD) absorbs
more than a configurable share of the train's places (Rickfelder 2025
uses 20 % as a per-stop loading cap — for us a warning, never a
constraint), and the resulting load factor per class against the
published bands (ÖBB Nightjet ≈ 55 % in 2017; 75 % assumed necessary for
viability; §2.5).
The revenue-management alternative — serve long ODs first (the
"breakpoint" rule: no alighting before, no boarding after a chosen node,
Rickfelder & Schönberger 2024) — is the DM9 yield-pricing extension, not
v1. Yield-style capacity pricing is an extension (§6).

**Fare model and price-response curve**: fare per class = base per-km rate
× distance^γ × price level, per class; base rates and γ are calibrated
parameters (replaces `STOPGAP_FARE_PER_KM_BY_CLASS`). Price is the lever
that stays flexible: for the fixed route and composition the engine sweeps
the price level per class over a grid and returns **demand and revenue per
price point and class** (the curve). The sweep is cheap — only the fare
term of the utility changes between points, everything else is computed
once. The proposer's chosen point (default: a calibrated reference level)
is the one written into `ODPair.avg_price` / `places_sold`. The stated-
preference direct price elasticity of night train demand (−1.3 to −2.7,
Sweden) is steep; revealed long-distance rail elasticities are flatter
(−0.7 to −1.2); the curve's slope is therefore one of the quantities the
back-cast must pin down.

### 2.5 Evidence base — what the stated-choice literature settles

Sources read (folder `03_demand/`): Heufke Kantelaar 2019 thesis and the
2022 *Travel Behaviour and Society* paper (NL, 1 600 resp., night train vs.
morning/evening plane, panel mixed logit + latent classes); Moors 2023
thesis (BE, Brussels–Vienna, night train configurations vs. usual mode, MNL
+ 5-class latent class); Curtale/Larsson/Nässén 2023 (SE, 1 571 resp.,
night vs. day train vs. plane, ICLV incl. fear of flying and
pro-environmental norm, price elasticities); the Vienna TPB survey
2024 (AT, attitudes/barriers, SEM); Swiss night-train user profiling 2024
(CH, 389 users, latent classes + interviews); Ramboll/BMDV 2024–25 national
night train study and the Berlin-hub feasibility study (DE, aggregate
potentials); de Bie 2023 and Hueso-Kortekaas 2024 (qualitative context);
Rickfelder & Schönberger 2024 and Rickfelder 2025 (supply-design
heuristic, revealed 2021 market data, §2.9); Tomeš & Pařil 2026 (operator
interviews CZ/SK, supply-side context); Blainey & Hare 2025 (literature
synthesis + aviation feasibility screen, Eurostat 2022/23); Wessling,
Arnet & Loder 2026 (WCTR slides: Munich–Rome DCE, 482 Bavarian
respondents, MNL with full choice set incl. car, day rail and opt-out,
logsum consumer surplus).

What transfers into our specification, normalised to € and hours:

| Quantity | Evidence | Our parameter |
|---|---|---|
| Value of in-vehicle time, night train | ≈ €13/h leisure, ≈ €16/h business (NL); ≈ €12–24/h (SE, depending on cost coefficient) | `VoT_NT` per segment, prior 13 / 16 / 9 / 11 €/h (leisure-comfort / business / budget / senior) |
| Mode-specific time weights | a plane hour weighs ≈ 2× a night train hour (NL, SE); day train ≈ 0.9× night train hour (SE) | ratios fixed as priors, not free |
| Sleep credit | expected sleeping hours raise NT utility strongly (SE, ≈ +0.5 per h vs −0.26 per travel hour); "sleep while moving" is the top qualitative driver everywhere | `sleep_credit`, capped at the in-vehicle VoT (a night hour is at best free, never a gain) |
| Comfort / privacy | 1→3 stars ≈ €110–140, 3→5 ≈ €80–100 (NL); couchette +€127, capsule +€200, sleeper +€206 over seat at SP scale (BE); people per compartment dominates; shower ≈ €10–18, restaurant car ≈ €2 | class comfort value from `service_classes` attributes; WTP priors deflated 30–50 % for SP inflation, exact factor from back-cast |
| Purpose | business penalty on NT ≈ 10–11 night-train hours (≈ €350 at SP scale) and lower cost sensitivity (×0.8); business prefers early arrival | `purpose_pen`, segment-specific VoT and cost coefficient |
| Age | +0.017 utility per year of age for NT (NL); older → less sensitive to class type, more to lockability; cost sensitivity falls with age (BE) | senior segment with own coefficients |
| Price sensitivity heterogeneity | BE latent classes: 12.6 % never-users, 15.6 % young and ≈ 3× price sensitive, 18.7 % price-insensitive sleeper buyers, 40 % capsule-leaning mainstream | budget segment cost coefficient ≈ 3× reference; "never" share folded into ASC level |
| Arrival window | 08:00 vs. 10:00 worth ≈ 1–1.5 NT hours, direction differs by sample (NL early, BE late) | small piecewise `window_pen`; business weights early arrival |
| Transfers | one change ≈ −1.7, two ≈ −2.5 utility (SE) — about 6–9 night train hours | `transfer_pen` on day-rail LoS; NT v1 direct only |
| Gender / security | women penalise sharing and perceived insecurity (AT, NL) | no gender axis in v1; enters via privacy WTP |
| Attitudes | fear of flying and pro-environmental norm raise NT utility (SE); familiarity raises intention (AT); price is the lever that moves pragmatists (CH) | latent, not modelled explicitly; part of ASC level and its spread |
| Price elasticity of NT | direct −1.3 … −2.7, cross from air fare 0.03 … 0.5 (SE SP) | back-cast target band; flight-tax-only scenarios move little |
| Aggregate shares (DE studies) | NT takes 9–18 % of a relation; 10–30 % of air pax; car 5–10 % decaying to zero at 1 500 km; day rail/bus ≈ 5 %; induced ≈ 10 % of NT riders; 100 000 air pax/yr as relation threshold; 70 % load factor achievable | plausibility bands for the back-cast and for the gallery's "is this relation viable" hint |
| Stop time-of-day attractiveness | revealed: 2 378 scheduled stops / 589 stations / 77 lines in 2021; hourly frequency 18 (17:00) → 202 (23:00) → 59 (02:00) → 206 (06:00) → 36 (10:00); UIC phases: no boarding after 00:00, alighting from 06:00 | `window_pen` shape prior; boarding/alighting default (§2.4) |
| Market geometry | 2021 services: mean 982 km, 12:26 h, 79 km/h (75 km/h Morfeldt et al.); Campenon's 300–1 400 km gap; at 2 000 km rail share ≈ 5 % | relevance band 300–2 000 km confirmed; routing sanity checks |
| Non-circulation | ≈ 60 of 365 days diversions/closures on a new cross-border line (operator interviews, CZ/SK) | plausibility band for the non-circulation correction of back-cast ridership (§2.6) |
| Class economics | seat compartments: highest load factor at lowest cost; low-cost and premium segments behave as separate markets | class-nest back-cast target; supports budget vs. comfort split |
| Relation-level latent share | Munich–Rome (≈ 14 h, seat/couchette/sleeper €100/200/300): predicted air 40 %, NT 26 %, car 15 %, day rail 13 %, opt-out 6 % (DE, 482 resp., MNL, raked) — an SP share, upper band | plausibility band per relation (cf. DE aggregate 9–18 %); the opt-out share is the no-travel nest |
| Attribute ranking | price decisive for every mode; comfort matters only for NT (sleeper lifts utility most); NT hour ≈ day-train hour; habit (past mode) strongest covariate; prior NT exposure raises uptake; heavy luggage pushes to car/plane (DE) | NT-only comfort term confirmed; `VoT_NT ≈ VoT_rail`; pivot-point logit carries habit; luggage inside car/air ASC spread |
| Consumer surplus per traveller | mean (median) €189 (101) sleeper, €32 (15) couchette, €17 (8) seat at the realistic price ladder; best case €468; regions without airport gain ≈ 1.4× per capita (DE) | `user_benefit` output (§1); report median beside mean — the distribution is skewed |
| Air feasibility screen | intra-EEA+UK 2022/23: 607 M pax/yr, 3 744 city pairs; 30 % on "disconnected" airports (islands); of the 184 pairs > 500 k pax/yr, 93 have a 7–16 h rail time (96 M pax, 16 %), cumulative feasible ≈ 36 % of air pax; 500 k pax/yr ≈ 685/day ≈ two 7-car sets | DM2 exclusion rule for disconnected airports; 7–16 h band; the 93-pair list as coverage check of our air OD layer |
| Shift-willingness by destination (SE) | 20–30 % of Swedish flyers to Central Europe, 6–10 % to Southern Europe would shift (Curtale 2023) | air-shift plausibility band by OD distance class |
| Capacity & load factors | new-gen Nightjet 260 places/set, 520 doubled, mix ≈ 15/48/37 % seat/couchette/sleeper (508 places); older NJ 310–430; ÖBB load factor ≈ 55 % (2017), 75 % assumed for viability, 80 % used in scenarios; 5–15 % air shift fills a train to > 75 % on some corridors (DB Int. 2013) | capacity-cut and load-factor bands; class-mix prior for the composition catalog |
| Corridor aggregation | one train serves several air city pairs; the 500 k-pax single-pair threshold is a pessimistic viability test (Blainey & Hare) vs. 100 k air pax/yr per relation in the DE studies | both thresholds recorded; our per-OD sum along the route is the model's own answer |
| Emissions (context) | rail 15–45 g CO₂/pkm vs. air 190–215; NT ≈ +20 % per pkm over day rail (DB Int. 2013) | plausibility band for `emissions/model.py`, not a demand parameter |

What does *not* transfer: the ASC levels (study-specific, sign flips),
the absolute logit scale (differs by survey), and anything about
departure-time windows from the SP experiments (never varied — the
revealed-supply prior above is what fills that gap). All coefficients above
enter the calibration notebook as priors with stated ranges; the notebook,
not this document, is the home of the numbers (§2.6/2.7).

### 2.6 Calibration and validation (DM5)

Two layers. **Parameters from literature** — the priors in §2.5, cross-
checked against EU value-of-time handbook / national appraisal guidelines
and mode-choice meta-analyses for the non-NT modes. **ASCs, scale, nest λ
and the SP-deflation factor by back-casting**: run the model on today's existing night train
routes (ONTD snapshot already in the DB) and tune until modelled loads match
published ridership (ÖBB Nightjet totals, SJ, European Sleeper, Snälltåget)
at route level. Until that is done, every surfaced demand number carries
`demand_kpis_placeholder`-style honesty — the flag already exists, its
semantics widen to "uncalibrated".

Back-cast targets, in order of quality: French 2024 ridership corrected
for non-circulation and sold-out trains (RAC 2025); the 2021 N/C/W
European service table (77 lines with distance, journey time, speed —
Rickfelder & Schönberger 2024, Table 1, data on GitHub) as the route set
for structural checks (stop count, stop hours, distance band); published
operator totals (ÖBB, SJ, European Sleeper, Snälltåget). The
non-circulation correction uses the ≈ 15 % operator-reported band
(§2.5) where line-specific data are missing. The model is back-cast on
*unconstrained* demand — the analogue of Rickfelder's utilisation
correction δ (observed ÷ load factor), which is why sold-out corrections
matter. Relation-level cases: Munich–Rome (Nightjet since July 2025;
the Bavarian DCE's pre-launch 26 % share and €7.5–15 M p.a. user benefit
against the ridership ÖBB will publish), and the 2021 Trenhotel /
Intercités de Nuit services (Rickfelder 2025) for the non-stop-to-tourist-
destination stopping pattern. The base year for observed flows is stated
explicitly in `DEMAND_CALIBRATION.md` and is 2019 or ≥ 2023 — never
2020–22 (operators report ridership still below pre-COVID in 2023).
Every back-cast report carries a sensitivity block on load factor /
capacity and on the 7–16 h journey-time band, the two quantities Blainey
& Hare (2025) fault earlier Back-on-Track estimates for omitting.

Calibration lives in notebooks under `models/demand/calib/` (same shape as
`tac/calib/`, `facility/calib/`, `compositions/calib/`) with a
`DEMAND_CALIBRATION.md`; the notebooks are the single source of truth for
the seeded parameter values.

### 2.7 Parameter placement (follows `AGENTS.md`)

| Value | Home |
|---|---|
| zones, socio-economics, background OD, LoS matrices | new `demand` schema tables, snapshot-versioned (`demand_version`), seeded from Drive-hosted CSVs via the `seed.py` soft-fail/download pattern |
| VoT, sleep credit, comfort WTP, purpose/transfer/window penalties, ASCs, nest λ, η, segment shares, fare base rates, growth factors | `input_params` demand parameter tables, versioned with the same `demand_version` pin, full provenance columns |
| per-class comfort attributes (berths per compartment, private/lockable, shower) | `input_params.service_classes` (catalog, two or three new columns) |
| schedule-window definition, relevance band (distance offline, `NT_MIN_JOURNEY_H` / `NT_MAX_JOURNEY_H` at runtime), access cap, single-stop share warning threshold | `models/demand/model.py` STANDARD VALUES (changing them changes output → version bump) |
| price-level multiplier, boarding/alighting classification | runtime request (API boundary applies defaults) |
| Drive file ids for demand seeds | `backend/docker/.env` |

The zone frame's own vintage (`nuts_version`, currently NUTS 2021 — §2.1)
travels inside `demand_version` rather than as a seventh pin: a demand
snapshot is only meaningful against the classification its zones were built
on, so the two can never be pinned independently.

`scenario.scenarios` gains a sixth pin column, `demand_version`. This
invokes the `§4.2` refresh machinery (`db/README.md`): a scenario is a
complete pin, never partial — same contract as the five existing ones.

---

### 2.8 Comparison with the French model (Oui au train de nuit / Réseau Action Climat)

Read: the RAC report *Trains de nuit — le réveil a sonné* (2025, part III and
"Méthodologie"), N. Forien's UGI 2022 presentation, and the model itself
(`Night train model for Back-on-Track`: C++ program, `constants.h`,
`explications.odt`, `Output-v17.ods`). It is an **aggregate shift-rate
model**, not a choice model: for every observed air (airport pair) or road
(département pair) flow, a shift rate to the proposed night train is the
product of a base rate and a chain of multiplicative factors, and each flow
is assigned to the single best night-train line/stop pair. Summary of what
it does, what it does not, and what we take over:

| Aspect | French model | Our concept | Consequence |
|---|---|---|---|
| Demand unit | observed air (Eurostat `avia_par`, 9 countries) and road flows (FR département matrix redistributed to sub-prefectures by population; European road flows synthesised by population × population × distance decay against regional ENTD totals) | same air source; NUTS-3 zones; gravity-disaggregated OD for all modes incl. day rail | their synthetic European road layer is exactly our DM3 gravity step — their `DISTANCE_FACTOR` decay is a usable prior |
| Day-rail shift | not modelled (explicitly excluded) | in the rail nest | we cover a channel they do not |
| Choice mechanism | multiplicative factors on a base rate (time-based, saturating at ~10–12 h, zero below 2 h) | nested logit on generalised cost | ours can price, segment and nest; theirs is cheaper and transparent |
| Price | absent | central (fare model, price curve) | their model cannot answer the price question at all |
| Segments / comfort / class | absent | four segments, class nest, comfort attributes | — |
| Timetable | departure and arrival attractiveness curves whose width **widens with the duration of the day alternative**; applied at both ends and at feeder connection points; explicit sleep-time floor (<8 h penalised, <6.5 h strongly) | piecewise window penalty, sleep credit | **adopt**: couple window penalty to day-journey duration; adopt the sleep floor |
| Competing day rail | direct-train frequency (10 directs ÷ 3 vs. 1 direct); transfers; bonus ×2.25 when the night train avoids a change that day rail needs | day-rail LoS in the logit | **adopt**: frequency and transfer count must be in the day-rail LoS; the "avoided transfer" effect then falls out of the transfer penalty |
| Access/egress | multimodal shortest path (day train, coach, car, ferry); each change ×0.7, halving per 2 h of feeder time, car feeder ×1/3 and its time counted double; detour penalty vs. best day-rail path | zone → stop access matrix | **adopt**: feeder legs by rail with transfers, detour penalty relative to the best day-rail path, coach/car as penalised feeders |
| Air specifics | smaller air routes more shiftable (36 % → 5 % as pax grow to 3 M — a frequency/attractiveness proxy); hub deflation ×0.7 major / ×0.85 secondary for long-haul connecting pax | air LoS incl. frequency; nothing on hubs yet | **adopt**: hub-transfer deflation of air OD in DM2; frequency in air LoS |
| Multiple night lines | each OD assigned to the one best line/stop pair, never double-counted | single proposal at a time; network effects DM9 | **adopt** as the DM9 rule for competing proposals and ONTD lines |
| Induced demand | constant 10–15 % applied post-hoc | logsum elasticity | — |
| Capacity | none in the model; carriages sized afterwards at 75 % load, 50 places/car | satisfied / not satisfied per OD × class | — |
| Calibration | against 2024 French ridership **corrected for non-circulation and sold-out trains**; per-line error −27 … +26 %, total +3 % | back-cast on ONTD routes | **adopt** their corrected-ridership approach and their 2024 table as one back-cast target (§2.6) |
| Outputs | per line, per OD, per branch: pax, base rate, variable factor, transfer path; FR-FR / FR-abroad / abroad-abroad split; carriages; CO₂ (ADEME 259/188 g air incl. contrails, 109 g car) | views + price curve | **adopt**: export the per-OD factor decomposition (explainability), and the country-pair split already in `views` |

Their own stated limits (arbitrary curves, no price, no seasonality, air
pax assigned to the airport city, missing foreign road data) are the gaps
our design closes; their strengths are the operational realism of the
night-train and day-rail level-of-service treatment and the disciplined
calibration. Both are folded into the packages below.

### 2.9 Comparison with the node-potential heuristic (Rickfelder & Schönberger 2024; Rickfelder 2025)

An **expectation model for supply design**: given origin and destination,
Dijkstra picks a route; each node gets a potential (station frequency ×
night-train share γ ÷ utilisation δ, modified by stop hour αₕ, municipality
size βₛ, competition θ — 2025: NUTS-3 population × GDP index + population ×
tourism share); stops are added in descending potential as a rucksack
problem until capacity K is covered and max travel time T holds; an OD
matrix is then derived from boarding/alighting shares around a breakpoint.

| Aspect | Node-potential heuristic | Our concept | Consequence |
|---|---|---|---|
| Question answered | which stops on a given route, with no demand data | how many travel, from which mode, at which price, given the proposer's route | complementary; theirs is the `suggested_stops` problem |
| Demand unit | station (2024) → NUTS-3 (2025) | NUTS-3 | **confirms** DM1 |
| Node attraction | population × GDP index + population × tourism share | gravity production/attraction per segment | **adopt** as prior shape (§2.2) |
| Time of stop | αₕ from revealed 2021 stop distribution | `window_pen` | **adopt** as prior (§2.4) |
| Competition | θ < 1 if node already served by night trains | DM9 network rule (best line per OD) | same idea; ours per OD |
| Alternatives / price / segments | none | nested logit, fare model, four segments | — |
| OD matrix | boarding/alighting shares around breakpoint, capacity-scaled | choice model per OD, capacity cut | breakpoint = DM9 yield rule |
| Stop selection | rucksack on potential, K and T | not in v1 | DM9: marginal logsum as node potential |
| Validation | route/stop pattern vs. 2021 timetable | ridership back-cast | **adopt** pattern benchmark once `suggested_stops` is demand-aware |

Not taken over: the 2024 station-frequency × γ ÷ δ potential as a demand
driver. It needs a known night-train share at benchmark stations (operator
data) and proxies demand by total station footfall, which overweights
transfer hubs — the authors say so themselves. Zone socio-economics plus
the access matrix is the better-founded version of the same idea.

---

## 3. Data inventory

Ordered by acquisition dependency, not by model stage: each batch is
buildable once the batches above it exist. Batch 0 has external lead time
(requests, correspondence) and is therefore opened first even though it is
consumed last. Eurostat dataset codes below are confirmed current
(2026-08-19); the download recipes live in
`models/demand/DEMAND_DATA_SOURCES.md`, not here.

### Batch 0 — external lead time (blocks DM5/DM6 validation)

| Need | Source | Status |
|---|---|---|
| Wessling, Arnet & Loder working paper + estimated coefficients | TUM, contact in §7 | to request |
| Rickfelder (2025) NUTS-3 night-train data | author, "on request" | to request |
| Pan-European multimodal passenger OD newer than ETISplus 2010 | TRT (TRIMODE / TRUST — NUTS-3, ~1 600 zones, calibrated to the DG MOVE pocketbook), JRC, DG MOVE | to ask; answer decides whether the car layer is observed or synthesised (batch 4) |
| Operator ridership (ÖBB Nightjet incl. Munich–Rome, SJ, Snälltåget, European Sleeper) | operators, Back-on-Track contacts | to request |
| Station passenger counts | DB Station&Service, SBB (open), ÖBB, SNCF | optional tie-break, §2.1 |
| Studies still to read | UIC/DB Int. 2013, Steer 2017, DGITM 2021, EC/Steer & KCW 2021, Rüger & Matausch 2020 | 2013 is the origin of the 75 % load-factor and 5–15 % shift figures currently cited second-hand |

### Batch 1 — zone frame (DM1a)

| Need | Source | Notes |
|---|---|---|
| NUTS geometries, level 3 and 0 | GISCO distribution, `NUTS_RG_01M_2021_3035_LEVL_3` (+ 2024 for the crosswalk) | 1:1M, not generalised — point-in-polygon on stops and airports follows |
| NUTS code list, names, hierarchy, release notes | GISCO `nuts-2021-units.json`, `nuts-2024-units.json` | crosswalk input |
| Population grid | Eurostat GEOSTAT / GISCO 1 km² census grid (2021 round) | population-weighted centroids (§2.1). Covers 30 countries: EU-27 + CH, NO, LI |
| Fallback population grid | GHS-POP R2023A (EC JRC), epoch 2020, 1 km | global, so it closes every remaining gap from one file — UK, candidate countries, IS, LI, and the French DOM, which EPSG:3035 does not reach. Modelled rather than counted, so it is a fallback: the census grid wins wherever it exists and the two are never mixed within a zone |
| Non-EU statistical regions | UK ONS ITL3 + lookup; CH BFS; NO SSB; candidate countries (check GISCO coverage first) | harmonised into the same column shape |
| Country geometries | **in repo** (Marine Regions EEZ land union v4) | reuse |

Not needed here: the LAU layer and LAU–NUTS correspondence. Placing a point
in a NUTS-3 zone is a point-in-polygon test against the NUTS-3 geometry
itself; LAU would only add a hop. It becomes relevant in batch 4, and only
conditionally — see there.

### Batch 2 — zone attributes (DM1a)

| Need | Dataset | Notes |
|---|---|---|
| Population by five-year age group | `demo_r_pjangrp3` | **not** `demo_r_pjanaggr3` — see §2.2 |
| GDP at current market prices | `nama_10r_3gdp` | EUR_HAB and PPS variants for the GDP index |
| Population denominator for GDP ratios | `nama_10r_3popgdp` | Eurostat's own denominator |
| Employment (persons) | `nama_10r_3empers` | business-segment driver |
| Tourist overnight stays | `tour_occ_nin3` | leisure attraction, kept separate from population (§2.2) |
| Household income (modifier) | `nama_10r_2hhinc` | NUTS-2 only; downscale or accept the coarser level, documented |
| Non-EU equivalents | national statistical offices | expect gaps → honest MISSING + group means |

### Batch 3 — nodes and network extracts (DM1b, DM4)

| Need | Source | Notes |
|---|---|---|
| Stop catalog | **in DB** (`stop_seed_catalog.csv`, OSM-keyed) | access matrix re-runs per `stop_infra_version` |
| Airport master list | OurAirports (public domain) + OpenFlights cross-check | IATA/ICAO, coordinates, type |
| **Eurostat airport code ↔ ICAO/IATA crosswalk** | Eurostat `avia` metadata / airport code list | Eurostat uses its own `DE_EDDF`-style codes; without this the entire air layer joins to nothing, or worse, joins partially and silently. Build it with an explicit coverage assertion (every `avia_par` code resolves, or is a listed exclusion) |
| "Disconnected" airport flag | derived: airport → nearest catalog stop / rail network | ≈ 30 % of intra-EEA pax (Blainey & Hare 2025); derived, not hand-listed |
| Rail network | **in repo** (OpenRailRouting + graph cache) | zone → stop access, rail feeders |
| Road network extract | Geofabrik OSM Europe PBF | only if the car-router route is taken (DM4) |
| Toll / fuel inputs | EC Weekly Oil Bulletin; national toll tariffs; OSM `toll=*` | car generalised cost |

### Batch 4 — background OD flows (DM2)

Base year fixed before download (2019 or ≥ 2023, never 2020–22 — §2.6).

| Need | Source | Traps |
|---|---|---|
| Air OD passengers | Eurostat `avia_par_<cc>` (one dataset per reporting country) | both ends report the same pair — deduplicate, never sum; it is passengers carried per leg, not true OD (hence the hub deflation); main airports only |
| Air country totals | `ttr00016`; DG MOVE Statistical Pocketbook | control totals |
| Hub transfer shares | Destatis 46421 (DE), ACI, national airport statistics | replaces the French ×0.7 / ×0.85 fallback where measured |
| Air feasibility benchmark | Blainey & Hare 2025, Fig. 1 / Table 2 (93 city pairs > 500 k pax with 7–16 h rail time) | coverage check, not an input |
| International rail OD | `rail_pa_intcmng`, `rail_pa_intgong` | country pair; control totals only |
| Domestic long-distance rail | DE Destatis 46131 + BVWP/VVP 2040 (Kreis ≈ NUTS-3, public); FR SNCF open data; AT/CH/IT/ES national | VVP 2040 is the best NUTS-3 matrix in Europe — it also anchors the DE car layer |
| Car long-distance OD | ETISplus 2010; VVP 2040; national travel surveys (MiD 2017, EMP/ENTD 2019, MZMV, RVU) | lowest-confidence layer; if batch 0 returns nothing, fully synthetic gravity against national totals, limitation documented explicitly |
| Purpose shares by segment | national travel surveys | one harmonisation pass |
| LAU–NUTS correspondence | GISCO LAU | **conditional**: only if a chosen OD source is keyed on place names rather than coordinates (the French road layer, some travel surveys, municipal tourism statistics). The name column plus municipal population is then the join and the weight |

### Batch 5 — growth to 2032 (DM2)

| Need | Source | Notes |
|---|---|---|
| Transport activity projections | EC **FF55-MIX** and **CETO 2024** scenarios (EU Reference Scenario 2020 is superseded); EEA *Sustainability of Europe's mobility systems 2025* summarises both with 2030 pkm by mode | pin one as default, keep the other as a sensitivity |
| Population projections | Eurostat EUROPOP (`proj_23*`) at NUTS-3 where available | zone-level rather than uniform country factors |
| National forecasts where better | BVWP/VVP 2040 (DE), SNCF/DGITM (FR) | |

### Batch 6 — level of service (DM4)

| Need | Source | Notes |
|---|---|---|
| Day rail timetables | `eu.data.public-transport.earth` (curated per-country aggregated GTFS/NeTEx); Mobility Database; `gtfs.de` for the DE long-distance feed from DELFI | Delegated Regulation 2017/1926 means every member state has a national access point; several are NeTEx-only → budget a conversion |
| Day rail frequency and transfer count | derived from the feeds | frequency alone moves the shift by ~3× between 1 and 10 directs (French model) — not optional |
| Rail fare model | national tariff structures; scraped sample | per-country distance model |
| Air schedules / frequency | Eurocontrol R&D Data Archive (free for research, flight-level) or OpenSky; OAG/Cirium if budget allows | **open decision** (§5) |
| Air fares | no open pan-European source: scraped sample → distance/frequency fare model, EC air-fare studies, CPI sub-indices as deflators | weakest link in the air layer, flagged in `DEMAND_CALIBRATION.md` |
| Car routing | OpenRouteService/GraphHopper offline pass, or analytic fallback | decision recorded in DM4 |
| Traffic add-on | router-native layer vs. calibrated per-country factors | open (§5) |
| Ferry links | OSM + operator schedules | feeder legs, island/Nordic cases |

### Batch 7 — choice parameters (DM5)

| Need | Source |
|---|---|
| Values of time | DG MOVE *Handbook on the external costs of transport*; EC Value of Time study |
| National appraisal VoT | BVWP 2030 Methodenhandbuch, ARE (CH), DfT TAG data book, Instruction-cadre (FR) |
| Meta-analytic VoT / elasticities | Wardman et al. 2016 |
| Night train SP coefficients | **read** (§2.5, `03_demand/`), plus batch 0 items |

### Batch 8 — back-cast targets (DM5/DM6)

| Need | Source | Status |
|---|---|---|
| ONTD snapshot | in DB | ready |
| 2021 N/C/W European service table (77 lines, 2 378 stops, hourly distribution) | GitHub `tr-tud/2024_TR-JS_Supplementary-information` | downloadable now; also the `window_pen` prior (§2.4) |
| French 2024 ridership corrected for non-circulation and sold-out | RAC 2025 "Méthodologie"; Forien `Output-v17.ods` | shared |
| Operator totals | batch 0 | pending |
| Munich–Rome relation case | batch 0 + published ÖBB ridership | pending |

### Licence register

Tracked per source in `models/demand/calib/SOURCES.md` — URL, retrieval date,
hash, licence, and redistribution status — and deliberately not duplicated
here. Terms are recorded as sources are acquired; the decisions they gate
(publication, Drive upload of derived data) are deferred and do not block
calibration work.

## 4. Implementation packages

Ordered so that every package leaves the stack runnable and the stopgap
replaceable at the end, not mid-way. Estimates are rough relative sizes.

### DM0 — Concept, sources, decisions (this document) — small
- Review sources David shares; §3 filled with the confirmed,
  acquisition-ordered inventory and the licence register (rev. 5); the
  per-source download recipes live in `DEMAND_DATA_SOURCES.md`.
- Decide: zone level (NUTS-3 recommended), segment list, nest structure,
  deterministic vs. drawn travellers (deterministic recommended), capacity
  treatment v1.
- Deliverable: this file finalised + `OPEN_TODOS["demand_model"]` in
  `models/demand/model.py` pointing at it.

### DM1a — Zone frame & socio-economics — medium
- ETL step `calib/etl/step1_zones.py`: NUTS-3 geometries (§3 batch 1) →
  **one artifact**, `calib/out/01_zones.parquet` — identity, membership, tier,
  geometry, population-weighted centroid, centroid source and the NUTS
  2021↔2024 crosswalk, in EPSG:4326. Batch 2 attributes join onto it rather
  than producing a second file.
- **Delivered 2026-08-20**: 1 514 zones, 1 199 weighted from the census grid
  and 315 from GHS-POP, none geometric (`IMPLEMENTATION_DOCU.md` F29).
- Validation asserts are the point of the step: zone count per country
  against the official NUTS 2021 table, no duplicate `zone_id`, every
  geometry valid and non-empty, every centroid inside its own polygon, no
  gaps against the level-0 layer beyond tolerance, population-grid coverage
  per country above threshold with any shortfall listed rather than
  silently defaulted.
- `db/schema.py`: `demand.zones` (attributes included — written once, after
  batch 2, not migrated); `demand_version` incl. `nuts_version` on
  `scenario.scenarios` (§4.2 refresh).
- `seed.py`: Drive download + soft-fail, mirroring `ONTD_SEED_STOPS_FILE_ID`;
  `DEMAND_ZONES_FILE_ID` in `backend/docker/.env`.
- Tests: snapshot identity, scenario pin resolution, crosswalk totality.

### DM1b — Airport weighting & access matrix — medium
Gated on the airport layer (§3 batch 3), hence split from DM1a.
- `calib/step1b_access.ipynb`: zone → weighted airport set
  (`zone_airports.csv`, distance-decay per §2.1) and zone → stop access-time
  matrix (`zone_stop_access.csv`, car/rail time, capped) built against the
  pinned stop catalog, so it re-runs per `stop_infra_version`.
- `db/schema.py`: `demand.zone_airports`, `demand.zone_stop_access`.
- Tests: coverage (every catalog stop reachable from ≥ 1 zone), cap
  behaviour, re-run determinism against a pinned catalog.

### DM2 — Background OD ETL & 2032 extrapolation — medium/large
- `calib/step2_od_*.ipynb` per mode: load, harmonise to country pair (air:
  airport pair), apply growth factors → control totals 2032.
- Air: deflate airport-pair pax for long-haul connecting traffic at hubs
  (French model: ×0.7 major, ×0.85 secondary hubs; refine with Eurostat
  transfer shares where available); drop airport pairs where either end
  has no mainland rail connection (Blainey & Hare's "disconnected"
  airports) before control totals are formed.
- Base year: 2019 or ≥ 2023, stated in `DEMAND_CALIBRATION.md`; 2020–22
  flows are not used as a base (§2.6).
- Documented in `DEMAND_CALIBRATION.md` §"Background demand" with the
  honest-MISSING rule: no invented per-country figures, group means for
  uncalibrated countries (same principle as infrastructure calibration).

### DM3 — Gravity disaggregation & segmentation — medium
- `calib/step3_gravity.ipynb`: doubly-constrained gravity to zone pairs,
  IPF against DM2 totals, segment split → `demand_od_background.csv`
  (zone_a, zone_b, segment, mode, trips_2032).
- Attraction prior (population × GDP index + population × tourism share)
  and affinity dummies (language, historic ties, border) per §2.2;
  paired-flow symmetry.
- Distance-band filter as a STANDARD VALUE.
- `demand.od_background` table + seed; validation notebook comparing
  reproduced country-pair totals.

### DM4 — Level of service per mode — medium
- `calib/step4_los.ipynb`: car (router pass or analytic first cut), air
  (airport pair + access/egress + fare model), day rail → `demand_los.csv`,
  joined onto `demand.od_background` (one wide table, read once per request).
- Day rail LoS carries direct-train frequency and transfer count (French
  model: frequency alone divides the shift by ~3 between 1 and 10 directs).
- Access/egress: rail feeders with transfers, coach and car as penalised
  feeders, detour penalty relative to the best day-rail path (§2.8).
- Car router decision: second GraphHopper instance with car profile offline
  (not in the runtime stack) vs. analytic — document choice.

### DM5 — Choice parameters & calibration — medium/large
- `models/demand/model.py`: segments, nest structure, schedule-window rule,
  STANDARD VALUES; `DEMAND_MODEL_VERSION` → `0.1.0`.
- `db/schema.py`: `input_params.demand_segments`, `demand_choice_params`,
  `demand_fare_params`, `demand_growth_factors` (provenance columns, `_src`).
- `db/schema.py`: comfort attribute columns on `input_params.service_classes`
  (berths per compartment, private/lockable, shower) feeding the class
  comfort value.
- `calib/step5_calibration.ipynb`: §2.5 priors with ranges as the starting
  point; SP-deflation factor, ASC levels, nest λ, η and the fare-curve slope
  fitted by back-cast on ONTD routes against published ridership, the
  German aggregate share bands, the Swedish shift-willingness bands by
  destination and the Munich–Rome SP shares (§2.5); `DEMAND_CALIBRATION.md`
  documents every prior with its source row from §2.5.
- Journey-time relevance band `NT_MIN_JOURNEY_H` / `NT_MAX_JOURNEY_H`
  (7 / 16 h priors, §2.4) as STANDARD VALUES.
- Back-cast targets include the French 2024 ridership **corrected for
  non-circulation and sold-out trains** (RAC 2025, "Méthodologie" table) —
  the unconstrained figure our model should reproduce, not the sold one —
  and the 2021 service table for structural checks (§2.6).
- Timetable window penalty: hourly prior from the revealed 2021 stop
  distribution (§2.4), coupled to day-journey duration and a sleep-time
  floor (<6.5–8 h), all as STANDARD VALUES with the French curves as
  secondary priors; UIC phase rule as the boarding/alighting default.
- `DBDataLoader.build_demand_params()` → `DemandParamCollection` in
  `models/params.py` (same shape as the infrastructure collections,
  `param_versions` provenance).

### DM6 — Runtime choice engine — large
- `models/demand/level_of_service.py`: `Route` → per (origin stop,
  destination stop, trip) NT level of service (times, windows, nights,
  classes); zone → stop expansion via the access matrix.
- `models/demand/fare.py`: fare model (replaces `STOPGAP_FARE_PER_KM_BY_CLASS`).
- `models/demand/choice.py`: incremental nested logit, induced-demand
  logsum, class nest; pure functions, numpy-vectorised over the joined
  background rows.
- `models/demand/capacity.py`: constraint + proportional cut; satisfied /
  not-satisfied split; load factor per class and the single-stop share
  warning (§2.4) as diagnostics on `DemandResult`.
- `models/demand/price_curve.py`: price-level sweep per class → demand and
  revenue per point (reuses the choice engine with fare as the only varying
  term).
- `models/demand/estimate.py`: `estimate_demand(route, params, background,
  price_levels) -> Route` (writes `TripPair.od_pairs`) + `DemandResult`
  (satisfied / not-satisfied, per-mode-origin split per OD × class, price
  curve per class, and a per-OD factor decomposition — fare, time, window,
  transfers, access — for explainability, mirroring the French per-OD
  export). `DemandResult` is a new domain
  object beside `EvaluationResult`; it is the input to the views' new keys.
- `stopgap.py` retired (kept one version behind a flag only if tests need
  controlled demand — they don't, `tests/helpers.py` sets OD pairs directly).
- Tests: unit (logit shares sum to one, pivot reproduces base shares with no
  NT, monotonicity in fare and time), integration on a known route.

### DM7 — Wiring & contracts — medium (Bjarne coordination)
- `pipeline.py::run_compute()`: plan → **estimate_demand** → evaluate →
  views; `evaluate_and_build_views()` takes the optional `DemandResult`.
- `evaluation/views.py`: value keys `pax`, `pax_km`, `pax_unsatisfied`,
  `shift_air_*`, `shift_car_*`, `shift_rail_*`, `induced_*`, `co2_savings_t`
  on `route`, `per_trip_pair`, `per_trip_pair_per_od` (normalisations free);
  the price curve is a separate block in the calc response, not a matrix
  value (it is not money attributable to an event).
- `evaluation/summary.py`: `_placeholder_demand_kpis()` removed; real
  extraction; `demand_kpis_placeholder` keeps its column but means
  "uncalibrated" until DM5 back-cast passes.
- `emissions/model.py`: `MODE_SHIFT_SHARES` removed (consumer gone).
- `api/helpers/evaluation_serialize.py`: `models.demand` entry
  (`ModelVersions` slot), demand params under `evaluation.input.parameters`;
  request gains per-class `price_level` (defaulted at the API boundary),
  response gains `demand.price_curve`.
- `frontend/src/types/api.ts` audit with Bjarne; joins the existing
  `backend-dev → staging` coordination batch.
- `generate_model_docs.py`: demand formulas get `Formula` entries (LaTeX
  legend) like every other model.

### DM8 — Validation, performance, docs — medium
- Back-cast report; sensitivity table (VoT ±30 %, fare ±20 %, load factor /
  places ±20 %, journey-time band 6–18 h) — the load-factor and band
  sensitivities are mandatory in every published potential figure (§2.6).
- Runtime budget: per-request demand step ≤ 1–2 s on the full catalog
  (measure; the joined background table read should be the only I/O).
- READMEs: `models/demand/README.md`, `models/README.md` pipeline diagram,
  `adapters/proposal/README.md` §8.1 placeholder policy closed,
  `db/README.md` schema overview (sixth pin), `docs/MODEL.md` regenerated.

### DM9 — Extensions (not in first release)
- Network effects: competition/complementarity with other published
  proposals and ONTD routes on the same relation — French rule as the
  starting point: each OD goes to the single best night service, no
  double-counting; Rickfelder's competition factor θ as the share-split
  variant where two services are near-equal.
- Demand-aware `suggested_stops`: node potential = marginal logsum gain of
  adding a stop on the fixed route, added greedily under capacity and
  max-duration (the rucksack of Rickfelder & Schönberger 2024); benchmark
  the resulting stop pattern against the 2021 service table.
- Yield rule variant for the capacity cut: long ODs first / breakpoint
  entry-exit ban, instead of proportional.
- Seasonality / frequency (re-check fingerprinting if `schedule_mode`
  becomes demand-aware — §8.1 note).
- Yield-style capacity pricing; energy-based country-resolved NT emissions
  feeding `co2_savings_t` (band: NT ≈ +20 % per pkm over day rail, §2.5).
- User benefit (consumer surplus) per origin zone × segment from the
  logsum difference, in € per year (§1); the equity view "who gains" —
  regions without airport access gain most per capita (Bavarian DCE).
- Reliability / punctuality attribute for the business segment (route
  length as the only available proxy at proposal time) and a party-size
  axis if the class nest under-predicts couchette demand (§2.2).

---

## 5. Decisions (2026-08-19) and what stays open

Decided:

1. Zone level: NUTS-3 with the relevance-band filter (cross-validated by
   Rickfelder 2025).
2. Traveller representation: weighted prototypical travellers per zone pair
   × segment, deterministic; weights from survey purpose shares modulated by
   zone attributes.
3. Segment list: business / leisure-comfort / leisure-budget / senior
   leisure (§2.2), the purpose × life-stage axes the evidence supports;
   VFR inside the leisure segments.
4. Induced demand: logsum elasticity (§2.4).
5. Level of service: real routings and schedules by default (car via
   OpenRouteService/GraphHopper with a traffic add-on, air from flight
   schedules, day rail from timetables), analytic fallback per layer.
6. Capacity v1: hard cut; demand satisfied and not satisfied both returned.
7. Price: flexible by design — price-response curve per class for the fixed
   route and composition in the first release; the chosen point feeds
   `ODPair`.
8. Timetable window prior: revealed 2021 stop-time distribution; UIC phase
   rule as boarding/alighting default (§2.4).
9. Relevance: distance band offline, NT journey-time band (7–16 h priors)
   per OD at runtime; every published potential carries load-factor and
   band sensitivities (§2.4, §2.6).
10. Zone frame vintage: NUTS 2021, pinned inside `demand_version` as
    `nuts_version`, with a 2021 ↔ 2024 crosswalk built in DM1a so the pin
    can move later (§2.1).
11. Centroids: population-weighted from the GEOSTAT 1 km² census grid,
    geometric representative point as second column and documented
    fallback, `centroid_source` recording which was used (§2.1).
12. Country scope: zones built for EU-27 + EFTA + UK + candidate countries
    with a `tier` column; Tier 2 filtered out of OD generation, not out of
    the zone frame (§2.1).
13. Package split: DM1a (zone frame) ships without the airport layer;
    DM1b (airport weighting, access matrix) follows batch 3 (§4).

Open:

- Base year for observed flows: 2019 vs. ≥ 2023 (§2.6). 2023 avoids the
  pre-COVID objection; 2019 has better completeness. Decides the vintage of
  every batch-4 download, so it is settled before that batch opens.
- Air schedule source: Eurocontrol R&D archive vs. commercial (OAG/Cirium);
  and whether an open air-fare source exists at all (§3 batch 6).

- Choice model specification (§2.4) — structure settled against §2.5; nest λ,
  SP-deflation factor and ASC levels are back-cast quantities.
- Whether a "same-day-arrival" nest (NT + morning plane) beats the rail nest
  on the back-cast.
- Airport distance-decay form and cap for the zone → airport weighting.
- Traffic add-on source: router-native traffic layer vs. calibrated factors.
- Price grid (points, range) and the default reference level per class.
- Affinity term specification in the gravity impedance (which dummies,
  calibrated jointly with IPF or fixed from literature).
- Whether the consumer-surplus output (§1) ships in the first release as a
  view key (it is cheap once the logsum exists, but its € level depends on
  the back-cast ASC/scale) or waits for DM9.

---

## 6. How this maps onto David's original step list

| Original step | Where it lands |
|---|---|
| ETL OD demand (air/car/train, country level) | DM2 |
| Extrapolate to 2032 | DM2 (growth factors, parameter table) |
| Gravity disaggregation on socio-demographics | DM1 (zones) + DM3 |
| Synthetic trip set by traveller type | DM3 segmentation, held as weighted prototypes (§2.2) |
| Enrich with car / rail / air alternatives incl. access/egress | DM4 (offline), DM6 (NT at runtime) |
| Utility functions per traveller type | DM5 |
| Runtime: compare NT against alternatives | DM6 `choice.py` |
| Probabilistic choice with error term | nested logit (closed form), DM6 |
| Aggregates by shift origin and class, by composition and price | DM6 `DemandResult` (incl. price curve, satisfied/unsatisfied) → DM7 views/gallery |

---

## 7. Sources (§2.5 evidence base)

All read in full from the `03_demand/` folder; links point to the publisher, DOI, or institutional repository.

- Heufke Kantelaar, M. (2019). *Night-Time Train Travel: A Stated-Preference Study into the Willingness to Use Night Trains for European Long-Distance Travel.* MSc thesis, TU Delft. https://resolver.tudelft.nl/uuid:21e9731a-6ec3-4230-847f-38ffa364ba8a
- Heufke Kantelaar, M., Molin, E., Cats, O., Donners, B., & van Wee, B. (2022). Willingness to use night trains for long-distance travel. *Travel Behaviour and Society*, 29, 339–349. https://doi.org/10.1016/j.tbs.2022.08.002
- Moors, W. (2023). *Night Train Services: A Stated Choice Experiment — Exploring Preferences for Night Trains.* MSc thesis, TU Delft (Transport, Infrastructure & Logistics), in cooperation with SNCB/NMBS. https://repository.tudelft.nl/file/File_106b481e-165d-4a7e-bb61-3729d32e9805?preview=1
- Curtale, R., Larsson, J., & Nässén, J. (2023). Understanding preferences for night trains and their potential to replace flights in Europe: The case of Sweden. *Tourism Management Perspectives*, 47, 101115. https://doi.org/10.1016/j.tmp.2023.101115 (open-access PDF: https://research.chalmers.se/publication/535501/file/535501_Fulltext.pdf)
- (Vienna, Austria) Environmental concern and the determinants of night train use: Evidence from Vienna (Austria). (2024). *Travel Behaviour and Society*, 36, 100802. https://doi.org/10.1016/j.tbs.2024.100802
- Who uses night trains and why? A mixed-method study profiling night train users in Switzerland. (2024). *Travel Behaviour and Society*, 37, 100854. https://doi.org/10.1016/j.tbs.2024.100854
- Hueso-Kortekaas, K. (2024). An Overview of Sustainability-Related Strengths and Weaknesses of Night Trains in Europe. *Global Journal of Tourism, Leisure and Hospitality Management*, 1(1), 555555. DOI:10.19080/GJTLH.2024.01.555555 — https://repositorio.comillas.edu/xmlui/handle/11531/87199
- Berschin, F., Böttger, C., & Brümmer, H. (Ramboll Deutschland), for BMDV (2025). *Ökologische und gesamtgesellschaftliche Effekte von Nachtzugverkehren inter- und intramodal* (presentation of the study below, 31.3.2025). Companion presentation to the study; no standalone stable URL located — distributed alongside the full study (next entry).
- Ramboll Deutschland, for BMDV (2024). *Studie zur Betrachtung der ökologischen und gesamtgesellschaftlichen Bilanz von Nachtzugverkehren auf der Schiene im inter- und intramodalen Vergleich.* https://bmdv.bund.de/SharedDocs/DE/Publikationen/E/studie-bilanz-nachtzugverkehre.pdf?__blob=publicationFile
- Ramboll Deutschland, for Senatsverwaltung für Umwelt, Mobilität, Verbraucher- und Klimaschutz Berlin (2022). *Machbarkeitsuntersuchung: Berlin als Drehkreuz eines Europäischen Nachtzugnetzes — Schlussbericht.* https://www.berlin.de/sen/uvk/_assets/verkehr/verkehrsplanung/eisenbahnverkehr/planungen/berlin-als-drehkreuz-eines-europaeischen-nachtzugnetzes.pdf
- de Bie, J. (2023). *The Re-Awakening of the International Night Train: Analysing Social Practices and Travel Transformations.* Wageningen University, Environmental Policy Group. https://edepot.wur.nl/634826
- Rickfelder, T., & Schönberger, J. (2024/2026). Determining the potential of international passenger rail services with applications to the European night train market. *Transportation*, 53, 2301–2333. https://doi.org/10.1007/s11116-024-10565-7 (open access; supplementary data: https://github.com/tr-tud/2024_TR-JS_Supplementary-information)
- Rickfelder, T. (2025). Using NUTS for supply planning of night trains by creating and evaluating overnight services in Portugal, Spain and France. *Transportation Research Procedia*, 91, 560–567. https://doi.org/10.1016/j.trpro.2025.10.072 (open access; data on request from the author)
- Tomeš, Z., & Pařil, V. (2026). Night trains – Sustainable alternative or niche market? *Research in Transportation Business & Management*, 64, 101569. https://doi.org/10.1016/j.rtbm.2025.101569
- Blainey, S., & Hare, B. (2025). An assessment of the potential contribution of overnight trains to sustainable long distance travel in Europe. *Case Studies on Transport Policy*, 22, 101599. https://doi.org/10.1016/j.cstp.2025.101599 (open access, CC BY 4.0)
- Wessling, V., Arnet, F., & Loder, A. (2026). *Who Benefits from Night Trains? Measuring Consumer Surplus in Long-Distance Travel between Bavaria and Rome.* Presentation, World Conference on Transport Research (WCTR), Toulouse, 6–10 July 2026. TUM Professorship of Mobility Policy; slides shared with Back-on-Track (file `WCTR_2026_Night_Trains_vSend.pdf`). Contact: vincent.wessling@tum.de — no paper published yet; ask for the working paper and the estimated coefficients.

Secondary sources cited through the above (to obtain):

- DB International GmbH (2013). *Night trains 2.0 – New opportunities by HSR?* UIC, Berlin. (75 % load-factor assumption, 5–15 % shift fills a train, 15–45 vs. 190–215 g CO₂/pkm)
- Rüger, B., & Matausch, P. (2020). High speed overnight trains – potential opportunities and customer requirements. In Marinov & Piip (eds.), *Sustainable Rail Transport*, Springer, 257–273. (min. 6 h continuous travel, 12–14 h competitive ceiling, preferred windows)
- Steer Davies Gleave & Politecnico di Milano (2017). *Passenger night trains in Europe: the end of the line?* European Parliament, Policy Department B. (ÖBB Nightjet load factor 55 %)
- Maier, J. (2022). *The global warming reduction potential of night trains.* Back-on-Track.eu — the estimate Blainey & Hare criticise; our model must not repeat its two omissions (§2.4, §2.6).

French aggregate model (§2.8):

- Réseau Action Climat (Chailloux, A.; modelling contribution Forien, N., Oui au train de nuit) (2025). *Trains de nuit — le réveil a sonné. Une fréquentation record, bridée faute de trains.* Report, part III and "Méthodologie". https://reseauactionclimat.org (file `rac-train-vdef.pdf`)
- Forien, N., Fischer, S., Marsal, Q., Jouve, C., Dauboin, P. (2022). *10 million passengers would choose the night train over air or road.* Oui au train de nuit, presentation at UGI/IGU Paris 2022 (file `Presentation-Geography-congress.pdf`)
- Forien, N. *Night train model for Back-on-Track* — C++ source, data and `explications.odt` (shared with Back-on-Track, 2026-08). Detailed method note: Oui au train de nuit, online presentation referenced in the RAC report.
