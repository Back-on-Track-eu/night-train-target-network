# Terrain Category and Score — Per-Country Calibration

Location: `backend/models/infrastructure/calib/route_context/TERRAIN_AND_BUFFER.md`
Country-level terrain assessment. The energy consumption model that consumes it is implemented separately.

---

## 1. Definitions

| | |
|---|---|
| **Score `A`** | Cumulative ascent per kilometre, in **m/km** — the sum of all positive elevation changes along a route divided by its length. This is the quantity that drives energy consumption. |
| **Category** | A band on `A`, T1–T5. |
| **Ruling gradient `G`** | Steepest sustained gradient on the country's main corridors, in **‰**. Independent of `A` and drives traction requirement, not energy. |

`A` and `G` are not interchangeable. A rolling country climbs constantly but never steeply (high `A`, low `G`); a flat country with one mountain crossing has the reverse. Both are given below.

| Category | Name | `A` (m/km) | Energy factor, 600 t train |
|---|---|---|---|
| **T1** | Flat | < 1.5 | 1.00–1.09 |
| **T2** | Rolling | 1.5–4.0 | 1.09–1.25 |
| **T3** | Hilly | 4.0–8.0 | 1.25–1.49 |
| **T4** | Mountainous | 8.0–15.0 | 1.49–1.92 |
| **T5** | Severe | > 15.0 | > 1.92 |

Energy factors assume a 600 t train on a ~14 kWh/train-km flat baseline, using a gradient coefficient of **1.43 Wh per tonne per metre of ascent** (net of regenerative recovery at night). They are shown so the categories have a cost meaning; the consumption model computes its own values.

---

## 2. Country calibration

Scores describe the **main-line network a night train would realistically use**, not the country's topography. This distinction matters: railways follow valleys, so mountainous countries score far lower than their geography suggests, and the Danube corridor through Austria is easier than the Ardennes crossing in Belgium.

| Country | Score `A` (m/km) | Category | Ruling gradient `G` (‰) | What sets the level |
|---|---|---|---|---|
| NL | 0.6 | **T1** | ≤ 5 | Entirely flat; only the Betuweroute ramps rise |
| DK | 0.9 | **T1** | 5 | Glacial moraine, no relief of consequence |
| EE | 1.0 | **T1** | 6 | Baltic plain |
| LT | 1.1 | **T1** | 6 | Baltic plain |
| LV | 1.1 | **T1** | 6 | Baltic plain |
| HU | 1.3 | **T1** | 10 | Pannonian basin; only the Bakony and Mátra edges rise |
| PL | 1.4 | **T1** | 12 | North European Plain; Carpathian foothills only in the far south |
| IE | 1.6 | **T2** | 12 | Gentle rolling, main lines follow lowlands |
| FI | 1.8 | **T2** | 10 | Lakeland, gently undulating throughout |
| BE | 1.9 | **T2** | 16 | Flat Flanders offset by the Ardennes foothills on the Liège–Aachen axis |
| FR | 2.2 | **T2** | 25 | Large flat basins; Massif Central, Jura and Alpine approaches are edge cases |
| PT | 2.5 | **T2** | 25 | Coastal Lisboa–Porto flat; the Beira Alta interior route is far steeper |
| SE | 2.6 | **T2** | 17 | Flat in the south, rolling through Bergslagen and Norrland |
| DE | 2.8 | **T2** | 25 | Flat north, Mittelgebirge crossings on every north–south corridor |
| UK | 3.0 | **T2** | 13 | Rolling; WCML crosses Shap and Beattock, Highland lines steeper |
| CZ | 3.2 | **T2** | 20 | Bohemian basin ringed by hills; main lines follow the Labe and Vltava valleys |
| RO | 3.8 | **T2** | 20 | Wallachian and Moldavian plains, but the Carpathian crossing at Predeal is severe |
| LU | 4.2 | **T3** | 16 | Small network sitting largely on the Oesling plateau |
| BG | 4.5 | **T3** | 25 | Balkan range bisects the country; Sofia itself sits at 550 m |
| ES | 4.8 | **T3** | 20 | Meseta at 600–700 m — every line out of Madrid climbs to reach it |
| IT | 5.0 | **T3** | 30 | Po valley flat, but the Apennines split the peninsula on every north–south route |
| SK | 5.2 | **T3** | 20 | Carpathian arc runs the length of the country |
| HR | 5.6 | **T3** | 26 | Slavonian plain flat; the Dinaric crossings to Rijeka and Split are steep |
| GR | 6.2 | **T3** | 25 | Mountainous throughout; Athens–Thessaloniki crosses several ranges |
| SI | 7.0 | **T3** | 26 | Alps and Karst in a small network — little easy ground anywhere |
| NO | 7.5 | **T3** | 21 | Bergensbanen reaches 1,222 m; the Oslo–Göteborg axis is flat by contrast |
| AT | 8.5 | **T4** | 27 | Alps dominate — Semmering, Tauern, Arlberg — with only the Danube valley easy |
| CH | 9.5 | **T4** | 27 | Every transit crosses the Alps, though the Gotthard and Lötschberg base tunnels have cut the worst of it |

**No country averages T5.** T5 applies at line level only — Beograd–Bar, the steepest Balkan and Iberian branches, rack-assisted sections. If the target network extends beyond the EU/CH/UK perimeter, Montenegro and Bosnia would enter that band.

**Countries where `G` > 26 ‰** — AT, CH, and marginally HR, SI, IT — are the ones where a heavy night train may need double traction or banking on specific ramps. That is a composition decision (`n_locos`), not an energy one, and it is triggered by individual sections rather than the country average.

---

## 3. Where the country average misleads

For six countries the national figure hides a spread wide enough to change the assessment, and route-level values should override it as soon as they exist:

- **Portugal** — coastal Lisboa–Porto is T1; the Beira Alta line to the Spanish border is T3/T4. Two different countries for this purpose.
- **Norway** — Oslo–Göteborg is T1; Oslo–Bergen is solidly T4. The national 7.5 describes neither.
- **Croatia** — Slavonian plain T1, Zagreb–Rijeka T4.
- **Spain** — the high-speed network is engineered flat with long tunnels; the conventional network climbs onto the Meseta. Since gauge forces cross-border night trains onto the HS network, the *effective* Spanish score for an international night train is lower than 4.8.
- **Switzerland** — a Basel–Chiasso transit via the Gotthard base tunnel is roughly T2/T3, well below the national 9.5, because the base tunnels bypass the climb entirely. Routing choice, not geography, determines the number.
- **Austria** — the Danube corridor Wien–Linz–Salzburg is T2; anything crossing the Alps southward is T4.

---

## 4. Basis and confidence

These are **judgement-based estimates from network topography**, not computed from elevation data. They were assigned by working through each country's main corridors — the alignments a night train would actually use — against known summit elevations, valley routings and published ruling gradients. They are calibrated to be right in *ranking and band*, and are good to roughly ±1 m/km within a band; they are not measurements and should not be quoted as such.

They are fit for country-level assessment and screening. They are **not** fit for computing a specific route's energy consumption — for that, compute `A` from the routed geometry, since §3 shows the within-country spread often exceeds the between-country spread.

Two things would replace these with measured values: an elevation-enabled routing profile with tunnel/bridge interpolation, or a one-off pass over the corridors in the Back-on-Track database against a DEM. The second is cheaper and would validate the table directly against routes that exist.


---


Location: `backend/models/infrastructure/calib/route_context/TERRAIN_AND_BUFFER.md` (part 2)
Feeds the timetable generation stage: converts the routing engine's technical running time into a schedulable commercial running time.

---

## 1. What the buffer quota is, and what it is not

The routing engine returns a **technical minimum running time** derived from infrastructure `maxspeed` and the composition's traction and braking characteristics. No real timetable is built on that figure. European practice adds *running time supplements* so the schedule can absorb ordinary disturbance without cascading:

```
scheduled_running_time = technical_running_time × (1 + buffer_pct)
scheduled_total_time   = scheduled_running_time + Σ dwell_time + Σ operational_stops
```

**The buffer is a percentage of running time only.** Dwell at commercial stops, locomotive changes, border/traction changes and crew changes are modelled separately and must not be folded into this number — otherwise a route with many stops gets double-padded.

The buffer covers, in UIC 451-1 terms, the *regular running supplement* plus the *pathing and construction allowance*. It does **not** cover recovery of large disruptions, which belongs to a resilience scenario rather than the base timetable.

### Minimum dwell time — 2 minutes per commercial stop

```
dwell_time(stop) = max(2 min, operational_requirement(stop))
```

**Every commercial stop is scheduled with at least 2 minutes** for boarding and alighting, applied uniformly across all countries and all stop sizes. For a sleeper service this is a realistic floor: intermediate-station passenger exchange is small, doors are attended, and the constraint is door release and dispatch rather than passenger flow.

Two rules govern its use:

- **Dwell is additive, never multiplied by the buffer.** It is not running time, so a stop does not become longer because the country has a high buffer quota. In the equation above dwell sits outside the `(1 + buffer_pct)` term deliberately.
- **2 minutes is a floor, not a value.** Where a stop exists for another reason, the longer requirement governs and replaces it — not adds to it. Locomotive or traction changes at borders and electrification boundaries, crew changes, reversals, border control, watering and toilet discharge, and scheduled crossing or overtaking waits all produce dwells well above 2 minutes and are modelled as `operational_requirement` on that stop.

The practical effect on a night-train schedule is modest but not negligible: a route with 10 intermediate stops carries 20 minutes of minimum dwell, roughly 2 % of a 15-hour journey, and it lengthens the schedule without improving robustness — which is the argument for keeping intermediate stops few on long-distance night services.

---

## 2. Calibration formula

Two observable drivers per country, both from RMMS 2024 (data year 2022):

```
buffer_pct = 4.0 + 2.5 × √(utilisation / utilisation_EU27) + 6.0 × (1 − punctuality_LD)
```

| Term | Value | Source | Reasoning |
|---|---|---|---|
| Base | 4.0 pp | UIC 451-1 practice | Irreducible regular supplement; even an empty, perfectly punctual network needs it for driving-style variance and speed-restriction margin |
| Utilisation | 2.5 × √(u / 18.67) | RMMS Fig. 5 + 69, total train-km per line-km | Conflict probability rises with traffic density, but sub-linearly — doubling density does not double the required pathing margin, hence the square root rather than a linear term |
| Delay | 6.0 × (1 − p) | RMMS Fig. 116, punctuality of long-distance and high-speed passenger services, 2022 | Low observed punctuality means the disturbance level the network actually generates exceeds what the incumbent's supplements absorb. A new service planned to a target reliability needs more margin there |

**On causality.** Punctuality is an outcome, not a cause, and it is deliberately used as a *proxy for realised disturbance* rather than as an explanation. A country can score badly because it under-pads (Germany) or because its infrastructure is in poor condition (Romania); both raise the padding a new operator needs to hold a published arrival time, so for this purpose the distinction does not change the direction of the adjustment. It does change the confidence — see §5.

---

## 3. Calibrated buffer quotas

| Country | Utilisation (k train-km per line-km) | Punctuality LD 2022 | + util | + delay | **Buffer %** | Basis |
|---|---|---|---|---|---|---|
| LV | 5.5 | 0.880 | 1.36 | 0.72 | **6.1** | punctuality assumed |
| EE | 5.8 | 0.880 | 1.39 | 0.72 | **6.1** | punctuality assumed |
| LT | 6.3 | 0.880 | 1.46 | 0.72 | **6.2** | punctuality assumed |
| IE | 8.7 | 0.900 | 1.70 | 0.60 | **6.3** | punctuality assumed |
| BG | 7.8 | 0.867 | 1.62 | 0.80 | **6.4** | RMMS |
| FI | 8.2 | 0.830 | 1.66 | 1.02 | **6.7** | RMMS |
| ES | 11.7 | 0.843 | 1.98 | 0.94 | **6.9** | RMMS |
| NO | 12.4 | 0.800 | 2.04 | 1.20 | **7.2** | punctuality assumed |
| FR | 15.7 | 0.842 | 2.29 | 0.95 | **7.2** | RMMS |
| PL | 14.0 | 0.771 | 2.16 | 1.37 | **7.5** | RMMS |
| SK | 14.2 | 0.746 | 2.18 | 1.52 | **7.7** | RMMS |
| BE | 30.7 | 0.878 | 3.21 | 0.73 | **7.9** | RMMS |
| CZ | 18.1 | 0.747 | 2.46 | 1.52 | **8.0** | RMMS |
| SE | 15.5 | 0.712 | 2.28 | 1.73 | **8.0** | RMMS |
| DK | 31.3 | 0.851 | 3.24 | 0.89 | **8.1** | RMMS |
| AT | 30.6 | 0.814 | 3.20 | 1.12 | **8.3** | RMMS |
| LU | 27.8 | 0.757 | 3.05 | 1.46 | **8.5** | RMMS |
| HU | 14.3 | 0.592 | 2.19 | 2.45 | **8.6** | RMMS |
| NL | 49.4 | 0.880 | 4.07 | 0.72 | **8.8** | RMMS |
| IT | 24.8 | 0.669 | 2.88 | 1.99 | **8.9** | RMMS |
| CH | 55.0 | 0.900 | 4.29 | 0.60 | **8.9** | both assumed |
| HR | 7.3 | 0.444 | 1.56 | 3.34 | **8.9** | RMMS |
| PT | 13.4 | 0.534 | 2.11 | 2.80 | **8.9** | RMMS |
| GR | 5.3 | 0.339 | 1.33 | 3.97 | **9.3** | RMMS |
| UK | 38.0 | 0.700 | 3.57 | 1.80 | **9.4** | both assumed |
| DE | 30.0 | 0.536 | 3.17 | 2.78 | **10.0** | RMMS |
| RO | 5.2 | 0.197 | 1.32 | 4.82 | **10.1** | RMMS |
| SI | 18.8 | 0.386 | 2.51 | 3.68 | **10.2** | RMMS |

Median **8.1 %**, range 6.1–10.2 %. That band sits squarely inside published national practice (roughly 3–5 % regular supplement plus 3–5 % construction allowance), which is the first indication the formula is not producing nonsense.

**Assumed inputs.** RMMS covers EU27 + NO only, so CH and UK have no utilisation or punctuality entry and IE, EE, LV and LT have no long-distance punctuality entry. Values used: CH utilisation 55 and punctuality 0.90 (densest network in Europe, best-performing); UK 38 and 0.70 (PPM-equivalent); IE 0.90; Baltics 0.88 (lightly-used, punctual networks); NO 0.80.

**Two results worth noticing.** The drivers push in opposite directions often enough that the ranking is not simply "rich west low, poor east high": the **Netherlands and Switzerland need high buffers despite excellent punctuality**, purely because their networks are the densest in Europe, while **Bulgaria and the Baltics come out lowest** because an empty network generates few conflicts. **Germany at 10.0 % is the outlier among high-income countries** — it combines Dutch-level density with the worst long-distance punctuality in western Europe (53.6 % in 2022), and both terms add.

---

## 4. Reference dataset for verification: 345 real night-train trips

The Back-on-Track night train database has been parsed and is the calibration target. It yields **345 active trips** with usable origin departure and destination arrival times, matched to route distances.

**Observed commercial speed: median 65.7 km/h**, p10 50.1, p90 84.9. Single-country services, where no border effects contaminate the figure:

| Country | n trips | Median commercial speed | Range |
|---|---|---|---|
| GB | 12 | 82.2 km/h | 60–85 |
| SE | 10 | 79.8 | 68–83 |
| IT | 30 | 70.3 | 60–112 |
| FI | 10 | 68.6 | 61–76 |
| NO | 8 | 68.3 | 64–72 |
| FR | 18 | 68.1 | 50–84 |
| SK | 2 | 65.2 | 62–69 |
| BG | 10 | 62.7 | 53–68 |
| PL | 8 | 59.1 | 55–72 |
| RO | 26 | 52.3 | 47–66 |
| HR | 4 | 48.2 | 46–49 |
| UA | 96 | 65.6 | 44–679* |
| TR | 14 | 62.9 | 51–550* |

\* UA and TR contain outliers from multi-day services where the arrival time wraps past 24 h; they need day-offset handling before use and are out of the target network anyway.

**The verification equation.** For each trip in the database:

```
observed_duration = technical_duration × (1 + buffer_pct) + Σ max(2 min, operational_requirement)
```

Running the same origin–destination pairs through OpenRailRouting gives `technical_duration`. Since `trip_stop` carries the full intermediate timing chain, dwell can be measured directly rather than assumed — which also tests the 2-minute floor itself: any stop in the database scheduled at under 2 minutes would show the floor is set too high, and the distribution of measured dwells will show how often the floor binds versus how often an operational requirement governs. That leaves `buffer_pct` as the only unknown, solvable per trip and aggregatable per country.

**Order-of-magnitude check before that work is done.** A 1,000 km route at a technical 80 km/h takes 12.5 h; with an 8 % buffer and eight intermediate stops at the 2-minute floor it becomes 13.77 h, i.e. **73 km/h commercial**. Observed median is 65.7 km/h — an 11 % gap in the direction of the model being too optimistic.

That gap is informative rather than alarming, and the 2-minute floor is what sharpens it: with a generous 4-minute dwell assumption the modelled figure would have been 71 km/h and the discrepancy easier to overlook. Since dwell is now pinned at a defensible minimum, the gap has to be absorbed by one of only two things — technical speeds below 80 km/h on the mixed-quality lines night trains actually use, or buffers above the modelled 6–10 %. The verification separates them: `technical_duration` from the routing engine settles the first, and whatever remains is the second.

---

## 5. Confidence and what would change the numbers

**Ranked by how much they could move the result:**

1. **The delay coefficient (6.0) is the least anchored parameter in the model.** It sets how hard poor punctuality pushes the buffer up, and it was chosen to make the output land in the 6–10 % band that published practice occupies. The §4 verification will determine it empirically — this is the single number the night-train data should settle first.
2. **Punctuality thresholds are not harmonised across member states.** RMMS collects national figures, and what counts as "on time" differs (5 min in some states, 15 in others). A country reporting against a tight threshold looks worse than one reporting against a loose one, which distorts the delay term in an unknown direction. This is the strongest argument for replacing the term with a measured value rather than refining it analytically.
3. **The utilisation figure is network-average, not corridor-specific.** A night train on a quiet secondary route in a dense country is over-padded by this model, and one on a saturated mainline in a sparse country is under-padded. Once route geometry is available, utilisation could be resolved per line section instead of per country.
4. **Romania is a structural outlier, not just a high number.** With 19.7 % of long-distance services on time, no supplement in the 6–12 % range makes a published arrival credible; the observed 52.3 km/h commercial speed already implies heavy padding that still does not hold. Treat the RO figure as a floor and flag any route depending on Romanian punctuality as carrying schedule risk that the buffer model does not capture.
5. **Night-specific effects are not yet modelled and cut both ways.** Night paths face far less passenger-traffic conflict, which argues for a lower buffer than a daytime figure; but they run through the maintenance window, when possessions, single-line working and diversions are concentrated, which argues for more. The RMMS punctuality series is all-day and cannot separate them. The night-train dataset can, and should be checked for exactly this once the technical times are available — if night buffers come out systematically below the day-derived figures, the base term drops for every country.

**Suggested next step**, when you want to run the verification: give me the routing engine's technical durations for the origin–destination pairs in the database — ideally as a CSV of `trip_id, technical_minutes` — and I will solve the equation per trip, aggregate by country, and report measured buffers against the assumed ones in this table, including whether the delay coefficient holds and whether the 2-minute dwell floor survives contact with the observed `trip_stop` timings.
