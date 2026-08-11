# Track Access Charges (TAC) — Simplified Per-Country Calibration

Status: calibrated from official 2026/2027 documents (see per-country source lines), cross-checked against IRG-Rail TAC survey 2025 and 14th Market Monitoring report.
Implementation: `backend/models/infrastructure/calc_tac.py` (design decisions in `TAC_CALC_DESIGN.md`, unit suite `tests/test_72_calc_tac_units.py`). Values reach the DB via `06_seed_export.ipynb` → `seed/track_tac.csv` → `db/dev/seed.py`.

## 1. Scope

Model target: charge for the **minimum access package (MAP)** for a passenger night train, per routed leg.

Explicitly **excluded** (calculated separately later):

- Station charges and station-usage/stop charges — see §5 (deferred register) so nothing is lost or double-counted. Exception: the CH Haltezuschlag is a capacity element of the path price (no station-usage equivalent exists) and is included here.
- Energy-related charges: traction current, and all charges for the *use of electric supply equipment* (catenary/contact-line access, electrification wear, transformation/distribution canons). These are consistently excluded across countries even where they are formally part of the MAP, and are flagged per country.
- Shunting, parking/stabling, service facilities.
- Capacity-allocation admin fees where they are per-application flat fees (negligible); per-km reservation components are noted where material.
- Performance-regime payments (symmetric incentive schemes, net ≈ 0 in expectation).
- ~~Congestion/scarcity surcharges~~ — **no longer excluded.** The implemented model applies them as ACTIVE conservative defaults on the peak-overlapping share of a run (AT flat congestion surcharge 1.6081 EUR/trkm, CH peak factor 2 on the day rate; bands Mon–Fri 06:00–09:00 / 16:00–19:00, priced at 5/7 expected value since the model has clock minutes, not dates). Rationale: a night train's peak-hour approach into Wien Hbf or Zürich HB plausibly touches a declared high-load section, and treating every unconfirmed approach as free would systematically understate cost in exactly the pattern night trains run.

## 2. Model inputs and component schema

Available inputs per routed leg: distance by country, average/max speed, travel time, schedule (calendar + clock time), stops, market segment, composition (weight, length, seats/berths, vehicles, axles, traction type).

Not reliably available: mapping to IM-catalogued line categories (UIC class, national price-list categories). Where charges depend on line category, a **conservative fixed assumption** is made (documented per country) — conservative = do not underestimate the charge; main international corridors are assumed to be in the higher-priced mainline categories. OSM proxies (`maxspeed`, `highspeed`, `usage`) can refine this later.

Per-country calibrated columns:

| Column | Unit | Meaning |
|---|---|---|
| `per_train_km` | national currency / train-km | All train-km-proportional components incl. applicable markups |
| `per_gtkm` | national currency / gross-tonne-km | Weight-proportional component |
| `per_seat_km` | national currency / seat-km | Capacity-proportional component (CH fallback mode) |
| `per_stop` | national currency / stop | Capacity-type stop surcharges that are part of the track charge (CH Haltezuschlag only; all station-usage stop fees stay deferred, §5) |
| `revenue_share` | fraction of traffic revenues | Revenue-based contribution margin (CH primary mode) |
| `fixed_per_crossing` | national currency / train | Crossing-specific passage charges (§5a) |
| multipliers | — | Documented factors already folded into the values above |

Values are kept in **national currency at documented price basis**; FX conversion happens at model runtime via configured rates. EUR figures in the summary table are indicative only.

**Runtime mechanisms** (no fixed assumptions needed where the model has the input):

1. **Time-dependent rates:** each leg carries start/end clock time, so time-banded tariffs are applied per leg via `rate(band(t))`, not via a blanket "night trains run off-peak" assumption. Applies to: CH peak factor (legs touching Mon–Fri 06:00–09:00 / 16:00–19:00 on listed high-load sections — relevant for arrivals after 06:00), BE period classes, PT schedule bands, IT Notturno/Diurno bands, DE Nacht pro-rata rule, FR night-train qualification. Band definitions are given per country below.
2. **Weight-dependent rates:** exact composition gross weight is a model input; weight-class lookups (NL, PL WM, LU α, SI PM) and weight formulas (CZ, RO, AT/FR/FI/… gtkm terms) are evaluated at runtime. Reference-train figures below are indicative only.
3. **Speed-class rates (IT):** speed class taken from route average speed per leg (model input).
4. **High-speed vs conventional line (ES, FR):** selected per leg from infrastructure max speed (OSM `maxspeed`/`highspeed`); e.g. ES line type A when max speed ≥ 250 km/h.
5. **Crossing-specific passage charges:** modelled as a separate `passage_charges` table keyed by crossing entity (Storebælt, Øresund, Channel Tunnel, …), triggered by route geometry — independent of the per-country km-based charges. See §5a.

**Reference train** for the indicative summary: 1 electric locomotive + 10 coaches, 600 t gross, ~300 m, 500 places, timetable path, running in the night band.

## 3. Summary table (indicative, reference train)

| Country | per_train_km | per_gtkm | Indicative €/train-km @600 t | Price basis | 2027 doc? |
|---|---|---|---|---|---|
| AT | 0.643 EUR | 0.002282 EUR | 2.01 | TT2027 | yes |
| BE | 2.720 EUR (incl. markup) | — | 2.72 | 1 Jan 2026, indexed | yes |
| BG | 0.2495 EUR | 0.00083 EUR | 0.75 | from 1 Feb 2026 | 25/26 doc |
| CH | 2.50 CHF (cat A) × peak(t) | 0.0036 CHF (proxy) | ≈ 5.0 + revenue margin (+2 CHF/stop) | status 1 Feb 2026 | legal texts |
| CZ | — | 0.08163 CZK | ≈ 1.96 | 1 Jan–11 Dec 2027 | yes |
| DE | 2.76 EUR (Nacht, incl. −17% assumption) | — | 2.76 (3.33 per document) | from 14 Dec 2025 | INB 2026 |
| DK | 5.80 DKK | — | 0.78 + bridges (§5a) | 2025 order | NS 2027 (no rates) |
| EE | 0.74 EUR | 0.00299 EUR | 2.53 | TT 2025/26 | 2026 doc |
| ES | conv. 1.7303 / HS (type A) 5.3181 + seats EUR | — | 1.73 conv. / ≈ 16 HS (500 places, MAD–BCN) | rates in force since 2023 | yes |
| FI | — | 0.002054 EUR | 1.23 | CY2027 | yes |
| FR | 0.657 EUR | 0.005705 EUR (UIC 2–6) | 4.08 | TT2027 | yes |
| GR | 1.897 EUR | 0.004024 EUR | 4.31 | 2019 × infl. (NS 2026) | 2026 doc |
| HR | 2.154 EUR (L1, EN) | — | 2.15 | TT 2026/27 | yes |
| HU | 1,143 HUF (cat I) | 1.05 HUF | ≈ 4.4 | TT 2026/27 | yes |
| IE | 1.9268 EUR | — | 1.93 | from Jan 2027 | yes |
| IT | 0.185 + 2.31 EUR (Comp B) | 0.002707 EUR | 4.12 | 2027 tariff year | yes |
| LT | — | 0.0012 EUR | 0.72 | TT 2026/27 | yes |
| LU | 3.333 EUR (incl. factors) | — | 3.38 (incl. 0.05 path admin) | 2026 values | yes |
| LV | 1.30 EUR (intl pax) | 0.00106848 EUR | 1.94 | from 1 Jan 2026 | yes |
| NL | 2.2252 EUR (601–3,200 t) | — | 2.23 | TT2027 | yes |
| NO | 9.94 NOK | — | ≈ 0.85 | 2026 charges (indexed) | yes |
| PL | 8.01 PLN × WM × WK | — | ≈ 1.9 | from 13 Dec 2026 | yes |
| PT | 2.16 EUR (cat A, low, el.) | — | 2.16 | TT2027 | yes |
| RO | 9.562 + 3.45×f(m) RON (cl. A) | (folded in) | ≈ 2.6 | from 1 Mar 2024 | NS 2026 |
| SE | 4.98 SEK | 0.0218 SEK (pax ≤ 17 t axle) | ≈ 1.6 | NS 2027 Annex 1B | yes |
| SI | 2.41 EUR (incl. factors) | — | 2.41 | TT2027 | yes |
| SK | 1.0661 EUR (U1+U2, cat 1) | 1.102 EUR / 1,000 gtkm (U3) | ≈ 1.73 | Measure 2/2018 (since 2019) | yes (Annex 5.2.B) |
| UK | 361.55 p/train-mile ≈ 2.25 GBP/train-km | — | ≈ 2.6 (+ Channel Tunnel, §5a) | CP7, 2023/24 prices | yes |

CY, MT: no railways. Non-EU transit states (RS, MK, XK …) out of scope of this calibration round (IRG survey sheets available if needed).

---

## 4. Country details

### AT — Austria (ÖBB-Infrastruktur)

**Formula:** `TAC = trkm × 0.643 + gtkm × 0.002282` (long-distance passenger, excl. 20 % VAT)

**Values (TT2027):** train-km component z = 0.643 EUR/trkm (Personenfernverkehr); gross-tonne-km component btk = 0.002282 EUR/gtkm. Congestion surcharge 1.6081 EUR/trkm applies only on declared overloaded sections → assumed not applicable. No market markups in TT2027 (planned reintroduction 2029: preview +1.12 EUR/trkm commercial passenger — flag for the 2032 scenario sensitivity).

**Assumptions:** none needed beyond congestion exclusion; gross weight = full consist incl. locos.

**Source:** SNNB 2027, ch. 5.3.4 (Tabellen 11–13); publication 2025, price basis TT2027.
**IRG cross-check:** survey 2025: 0.649 / 0.002129 — consistent (small yearly drift). ✓

### BE — Belgium (Infrabel)

**Formula:** `TAC = trkm × (DC_line + RB_markup(density, period))`

**Values (1 Jan 2026, 6-decimal indexation):** DC_line = 2.142772 EUR/trkm (all trains). Ramsey–Boiteux markup applies to loaded runs of open-access passenger (HkvNPso); night trains run in *off-peak* (weekdays 19:00–05:59) and *weekend night* periods. Off-peak markup by line density class: 0.155858 (very low) … 1.028466 (very high/NSL) EUR/trkm.

**Mechanism & assumptions:** period class resolved **per leg from the schedule** (off-peak weekdays 19:00–05:59, weekend night 19:00–05:59, weekend day 06:00–18:59, normal 09:00–14:59, peak 06:00–08:59/15:00–18:59, NSL hyper-peak on the North–South Link) — evening departures before 19:00 and arrivals after 06:00 price at the day/peak coefficients on those legs (peak coefficients 1.63–10.75, NSL 16.44 EUR/trkm). Density class **High** assumed → off-peak markup 0.577410 EUR/trkm (mainline arteries are high/very-high density; conservative without per-section density data); indicative off-peak total 2.720 EUR/trkm. Direct cost catenary 17.22 EUR/MWh excluded (energy).

**Source:** NS 2027 (version 30 Jun 2026) §5.3 + Appendix F.2 workbook (sheets 2.1.1, 2.1.2.3).
**IRG cross-check:** survey 2025 DC 2.076386 — matches indexation chain 2023→2026. ✓

### BG — Bulgaria (NRIC)

**Formula:** `TAC = trkm × 0.2495 + gtkm × 0.00083` (passenger)

**Values (effective 1 Feb 2026):** 0.2495 EUR/trkm + 0.00083 EUR/gtkm. Charge for use of power-supply equipment (17.29 EUR) excluded (energy; unit ambiguous in doc).

**Source:** NRIC "Charges and Prices" (Annex 5.3.2, v.06, 18 Mar 2026), Section I.
**IRG cross-check:** survey has BG per-gtkm structure — consistent. ✓

### CH — Switzerland (SBB Infrastruktur et al.; federal ordinances)

**Formula:** `TAC = tpkm × base(line cat) × quality_factor × peak(t) + gtkm × wear + 2 CHF × stops + revenue_share × CH_revenues [CHF]`

**Values (NZV status 1 Jan 2026; NZV-BAV status 1 Feb 2026):**
- Base path price: cat A 2.50 / cat B 1.15 / cat C 1.15 / cat D 0.70 CHF/tpkm (Anhang 1 assigns lines).
- Quality factor: 1.0 for cross-border passenger under state treaty (cat B); 0.4 for non-concession passenger (cat C); 1.25 concession long-distance.
- Peak factor `peak(t)` = 2 on listed high-load standard-gauge sections Mon–Fri 06:00–09:00 and 16:00–19:00, else 1 — **applied per leg from the schedule** (a night train arriving Zurich/Basel after 06:00 pays it on the approach legs; departures before 19:00 likewise).
- Long-train rebate: −0.01 CHF/tpkm per metre of trailing load above 500 m (runtime from composition length).
- Wear price (Basispreis Verschleiss): vehicle-specific formula on standard gauge (Anhang 1a–1c); simplified proxy 0.0036 CHF/gtkm (the directly applicable rate per Art. 1(3)(b)).
- **Haltezuschlag: 2 CHF per ordered stop, incl. origin/destination stops** (NZV Art. 19a(4), NZV-BAV Art. 2) — this is a *capacity price element of the train-path price* (each stop consumes path capacity), not a station-usage fee; platform provision itself is part of the CH basic services with no separate station charge. → **included here**, no double-counting risk with the later station model.
- Contribution margin (Deckungsbeitrag), **primary mode = revenue-based** since traffic revenues are a model input: `revenue_share × CH-attributable traffic revenues` (concession / eidg. Bewilligung services, Art. 20(1bis, 2, 6) NZV; share set by the authority, observed range 0–21 % per IRG survey — concrete value for international night trains **MISSING → scenario parameter**, already first-class in the calib model). Fallback mode (non-concession): 0.0027 CHF per offered place-km, loaded runs only.
- Electricity 12–14 Rp./kWh excluded (energy).

**Assumptions:** international night trains priced as cross-border-treaty paths → quality factor 1.0 (conservative vs. 0.4); line cat A on main corridors (conservative; much of the network is B → base+wear ≈ 3.3–4.7 CHF/tpkm for the reference train before margin and stops); wear via the 0.0036 CHF/gtkm proxy instead of the per-vehicle formula; Haltezuschlag applied at all commercial stops (conservative — formally only stops on the published mixed-traffic list are charged).

**Source:** SR 742.122 (NZV) Art. 19a, 20, 20a; SR 742.122.4 (NZV-BAV) Art. 1, 2, Anhänge.
**IRG cross-check:** survey 2025 mirrors all elements (2.50/1.15/0.70, factors, 0.0027, 0.0036). ✓

### CZ — Czechia (Správa železnic)

**Formula:** `TAC = L × ZI × M × Px × kETCS` (Cs component; CPK stop component deferred → §5)

**Values:** ZI = 0.08163 CZK/gtkm (1 Jan–11 Dec 2027; 0.07956 for 13–31 Dec 2026). Px = 1.00 (passenger, P1). ZRP (traffic management) = 0.00000 CZK/km.

**Assumptions:** kETCS = 1.0 (no ETCS discount claimed — conservative; discount value not cleanly extractable from the NS text). Capacity-allocation price (k1 + k2·L + k3·days) excluded as minor admin.

**Source:** NS 2027 (SŽ, EN web version), charging annex part II/III.
**IRG cross-check:** survey 2025 lists composite 30.34 CZK/trkm passenger ≈ 0.0796 × ~380 t — consistent with ZI × M structure. ✓

### DE — Germany (DB InfraGO)

**Formula:** `TAC = trkm × 2.76` (SPFV market segment *Nacht*, flat; −17 % applied)

**Values:** documented rate (INB 2026 Anlage 5.3, valid from 14 Dec 2025): Nacht = 3.33 EUR/trkm. **Calibrated value = 3.33 × 0.83 = 2.76 EUR/trkm**, applying the BNetzA SPFV −17 % re-approval (22 Jul 2026, prior-session finding) — **marked as assumption** since the re-approval decision itself is not among the uploaded documents (BK10-25-0067 Anlage 2 = approved consolidated INB 2026 text still showing 3.33). Revert to 3.33 if the re-approval does not hold for the Nacht segment.

Segment assignment (drives pro-rata mechanism): trains running 23:00–06:00, **or** trains fully traversing the night window (incl. foreign route portions) carrying at least one couchette/sleeper — then the *entire German run* (also before 23:00 / after 06:00) is priced as Nacht. Partial-window trains without sleepers: pro-rata by travel-time share within 23:00–06:00, applied per leg from the schedule.

**Source:** INB 2026 Anlage 5.3 (Redaktionsstand 12 Dec 2025), segment definition Ziffer 5.3.2.5; BNetzA BK10-25-0067 Anlage 2.
**IRG cross-check:** DE survey sheet consistent with segment logic. ✓

### DK — Denmark (Banedanmark)

**Formula:** `TAC = trkm × 5.80 DKK + Storebælt: 4,876.73 DKK/train + Øresund (DK part): 2,592.02 DKK/train` (passenger, excl. VAT)

**Values:** 2025 executive order (bekendtgørelse 2024/1351); NS 2027 contains no numbers and points to the current order (annually indexed).

**Assumptions:** 2025 rates carried as best available; `fixed_per_crossing` triggered by route touching the respective link.

**Source:** NS 2027 §5.2/5.3; rates per Executive Order on infrastructure charges (via IRG survey capture of the order).
**IRG cross-check:** survey 2025: 0.78 EUR/trkm ≈ 5.80 DKK. ✓

### EE — Estonia (AS Eesti Raudtee)

**Formula:** `TAC = trkm × 0.74 + gtkm × 0.00299` (base MAP)

**Values (TT 2025/26):** base 0.74 EUR/trkm + 0.00299 EUR/gtkm. Markup for *domestic* passenger service: +1.45 EUR/trkm +0.00555 EUR/gtkm; markup for **international** passenger service: 0.

**Assumptions:** night train = international passenger → base only. Edelaraudtee network (if touched) not calibrated (MISSING; minor).

**Source:** TTJA published rates 2025/2026; EVR NS 2026.
**IRG cross-check:** survey EE sheet empty ("no data") — TTJA page is the better source. ✓ (one-sided)

### ES — Spain (Adif / Adif AV)

**Formula:** `TAC = trkm × (canon Mode A + canon Mode B) [+ seat_km × surcharge on type A lines]`, service type VL1, line type selected per leg from infrastructure max speed

**Values (canon regulation, rates in force since 2023, consolidated 2024):**
- Lines *other than type A* (conventional): Mode A = 0.7273 + Mode B = 1.0030 → **1.7303 EUR/trkm**.
- **Type A (high-speed) lines:** Mode A = 1.6767 + Mode B = 3.6414 → **5.3181 EUR/trkm**, plus seat surcharge per 100 seat-km: Madrid–Barcelona–Frontera 2.2014; Madrid–Toledo–Sevilla–Málaga 1.0809; other type-A lines 0.5404 EUR. For a 500-place train on the French-border corridor: +11.0 EUR/trkm → ≈ 16.3 EUR/trkm total.
- Mode C (traction-electricity transformation/distribution) excluded (energy).

**Mechanism & assumptions:** line type A vs non-A resolved per leg from infra max speed (≥ 250 km/h → type A). **Standard-gauge night trains entering from France realistically stay on the HS network** (conventional network is Iberian gauge; gauge-changing stock would be required otherwise) → default cross-border ES routing prices as type A, corridor surcharge 2.2014 (Barcelona entry) unless routed otherwise. VL1 = commercial long-distance. Under/over-use cancellation surcharges not modelled.

**Source:** BOE-A-2024-22140 (Reglamento de cánones, consolidated), Arts. 3–5; Adif NS 2027 ch. 5.3.
**IRG cross-check:** survey ES sheet consistent (canon A/B/C structure). ✓

### FI — Finland (Väylävirasto)

**Formula:** `TAC = gtkm × 0.002054`

**Values (1 Jan–31 Dec 2027):** basic component 0.2054 cents/gtkm. Additional charge for electric supply equipment 0.0167 cents/gtkm excluded (energy).

**Source:** Finnish NS 2027 (Table 2, ch. 5.3).
**IRG cross-check:** survey consistent. ✓

### FR — France (SNCF Réseau)

**Formula:** `TAC = RC = gtkm × p_t + trkm × p_km`; **RM (market charge) for night trains = 0**

**Values (TT2027, non-contracted scale, App. 5.2.2, excl. VAT):**
- Conventional lines UIC 2–6: p_t = 5.705 EUR per 1,000 CGT-km (= 0.005705 EUR/gtkm), p_km = 0.657 EUR/trkm.
- Conventional lines UIC 7–9: 1.935 / 0.526.
- Night-train definition (segment): sleeper/couchette stock, > 5.5 h travel within at least 23:30–05:00, commercial paths from/to France; RM scale shows "–" for night trains → marginal-cost-only pricing (consistent with the Art.-34-type treatment previously identified).
- RCE 0.291 EUR/electric trkm excluded (energy). Flat 4.17 EUR/path-km for reservations not captured by IT systems — edge case, excluded.

**Assumptions:** UIC group 2–6 for main corridors (conservative; refine later via OSM `maxspeed`/`usage` proxy — UIC class is not in OSM).

**Source:** NS 2027 v3 (27 Apr 2026) §5.3; Appendix 5.2 "Scale of minimum services for the 2027 timetable" (11 Dec 2025).
**IRG cross-check:** FR survey sheet structure matches (RC + RM per segment). ✓

### GR — Greece (OSE)

**Formula:** `C_MAP,p = infl × p_p × (c_T × d + c_wt × m × d [+ c_pss × stops])` → effective `trkm × 1.897 + gtkm × 0.004024`

**Values (NS 2026; 2019 base prices × inflation adjustment 1.1975; phased direct-cost recovery p_p = 0.60):** c_T = 2.64 EUR/km, c_wt = 0.00560 EUR/tkm → effective 1.897 EUR/trkm + 0.004024 EUR/gtkm. c_pss (4.21 EUR/stop, effective 3.02) deferred → §5. Electrification wear c_wte = 0.00210 EUR/tkm excluded (energy equipment).

**Assumptions:** inflation multiplier is NS-2026-specific (cumulative CPI since 2019) and must be refreshed annually.

**Source:** OSE NS 2026 ch. 6.
**IRG cross-check:** survey EL sheet consistent. ✓

### HR — Croatia (HŽ Infrastruktura)

**Formula:** `TAC = T × Σ(Li × l) × Cvlkm` (passenger; excl. VAT)

**Values (TT 2026/27):** Cvlkm = 0.54 EUR/trkm (passenger); train-path equivalent T = 2.10 for EuroCity/**EuroNight**/InterCity; line parameter Li = 0.30–1.90 by category (L1 mainlines = 1.90). Tilting surcharge +0.20 (n/a). Electric-traction surcharge 0.10 EUR/trkm excluded (energy equipment). Ad-hoc +10–20 % (n/a for timetable paths).

**Assumptions:** L1 (1.90) on the international mainline corridors → 2.10 × 1.90 × 0.54 = 2.154 EUR/trkm; refine with Annex 5.1 line list when line-matching exists.

**Source:** HŽ NS 2027 §5.3 (items 4–18).
**IRG cross-check:** survey HR sheet consistent (same formula). ✓

### HU — Hungary (MÁV; GYSEV not calibrated separately)

**Formula:** `TAC = trkm × (9 + rate(track cat)) + gtkm × 1.05` [HUF, excl. VAT]

**Values (TT 2026/27, MÁV summary table):** path ensuring 9 HUF/trkm (1 + 8 markup); passenger train-km part: cat I 1,134 / cat II 1,406 / cat III 1,204 HUF/trkm (charge + markup); gross-tonne-km part 1.05 HUF/gtkm. Catenary use 110 HUF/electric trkm excluded (energy). Station-use charges deferred → §5.

**Assumptions:** track-section category I for main international corridors → 1,143 HUF/trkm ≈ 2.9 EUR/trkm.

**Cross-check note:** ≈ 2.4× above IRG survey 2025 (1.18 EUR/trkm cat I) — consistent with the publicly protested Hungarian TAC increases from 2025/26 onward; table value confirmed directly in Annex 5.2-6, so retained.

**Source:** VPE/MÁV NS 2026–2027, Annex 5.2-6 (summary of network access charges).

### IE — Ireland (Iarnród Éireann)

**Formula:** `TAC = trkm × 1.9268`

**Values (from Jan 2027):** variable usage charge 1.9268 EUR/trkm, single network-wide rate. Fixed track access charge applies only to franchised operators on ability-to-pay basis → assumed n/a for open access. DART traction-power charge excluded (energy).

**Source:** IÉ NS ch. 6.2/6.3.
**IRG cross-check:** survey IE sheet empty; NS is primary. ✓ (one-sided)

### IT — Italy (RFI)

**Formula:** `TAC = gtkm × T_A1-2(speed class) + trkm × T_flat + trkm × CompB(segment, network, band)`

**Values (tariff year 2027, Listino PMdA 2025–2029):**
- Component A: T_A1-2 by speed class, e.g. [125–150) 0.001991, [150–175) ≤ 17 t/axle 0.002707 EUR/gtkm; T_flat = 0.185 EUR/trkm. TA3 contact-line component (0.241/0.482 EUR/trkm electric) excluded (energy equipment).
- Component B, segment **Basic**, band *Notturno*: 1.94–3.88 EUR/trkm depending on network part (LSE 2.54–2.75, FOND 2.20–2.43, COMPL 1.94–2.31, NODI 2.20–3.88).

**Mechanism & assumptions:** open-access night train = Basic segment (Servizio Universale contracted IC Notte would use the OSP-LP scale instead — switch by market segment input); **speed class for T_A1-2 taken from route average speed per leg** (model input) rather than a fixed class; Component B = FOND Standard as network pick, with the **Notturno band assumed 22:00–06:00** (`night_band` parameter; not confirmed in extracted excerpts) and applied per leg from the schedule — Diurno rates (Basic: 2.77–5.55 EUR/trkm) price the daylight fringes automatically.

**Source:** RFI Listino Tariffario PMdA (tariff period 2025–2029); RFI NS 2027.
**IRG cross-check:** survey IT sheet matches A+B structure. ✓

### LT — Lithuania (LTG Infra)

**Formula:** `TAC = gtkm × 0.0012`

**Values (TT 2026/27 tariff decision, 12 Dec 2025):** train traffic fee 0.0012 EUR/gross tkm; no markup for EU passenger services (transit-specific passenger tariff 0.0151 EUR/gtkm applies only to third-country transit). Contact-network fee 0.1709 EUR/trkm excluded (energy).

**Source:** LTG Infra tariff decision Nr. SPR-PAJ(INFRA)-138/2025; NS 2026–2027 §5.3.2.
**IRG cross-check:** survey LT sheet consistent. ✓

### LU — Luxembourg (ACF/CFL)

**Formula:** `TAC = trkm × c_C × α(bodies) × β(category) + trkm × c_A`

**Values (2026):** c_C = 2.771 EUR/trkm; towed passenger train > 8 bodies α = 1.1615; towed-passenger category β = 1.0355; path admin c_A = 0.05 EUR/km (regular timetable path). Scarcity charge 24.23 EUR/km applies only on declared saturated lines — currently none declared → 0. Electric supply c_E = 0.2583 EUR/trkm excluded (energy).

**Reference train:** ≈ 3.38 EUR/trkm.

**Source:** LU NS 2027 v1.0 §5.3.2.
**IRG cross-check:** survey LU sheet consistent. ✓

### LV — Latvia (LDz / LatRailNet)

**Formula:** `TAC = trkm × 1.30 + gtkm × 0.00106848` (international passenger, wide gauge)

**Values (from 1 Jan 2026):** maintenance + traffic control 1.30 EUR/trkm (segment "international passenger services within EEA"); renewals 0.00106848 EUR/gtkm. Electric-traction supply-equipment 0.15 EUR/trkm excluded (energy).

**Source:** LDz NS 2027 §5.2 (LatRailNet board decisions 11–12/2025).
**IRG cross-check:** survey LV sheet consistent. ✓

### NL — Netherlands (ProRail)

**Formula:** `TAC = trkm × rate(weight class)`

**Values (TT2027):** ≤120 t 0.5934; 121–160 t 0.7417; 161–320 t 0.9435; 321–600 t 1.3114; 601–3,200 t 2.2252; >3,200 t 2.7533 EUR/trkm. No markups on any segment (direct cost only — confirmed also in IRG survey: all markups 0). HRN levy applies to the domestic franchise only. Stop charges deferred → §5.

**Assumptions:** reference night train (≈ 640 t) → 2.2252; lighter compositions (< 600 t) drop to 1.3114 — model picks class from composition weight (available input, no assumption needed at runtime).

**Source:** ProRail NS 2027 v1.1 (train path service, section 4 user costs).
**IRG cross-check:** survey 2025 class rates ≈ 15–18 % lower — plausible indexation; structure identical. ✓

### NO — Norway (Bane NOR)

**Formula:** `TAC = trkm × basic charge` (open-access commercial passenger pays **no markup**)

**Values (NS 2027, "2026 charges", indexed annually):** axle load < 25 t: Oslo region 5.84 NOK/trkm; Ofotbanen and remainder 9.94 NOK/trkm. Markups exist only for PSO, airport feeder, and ore segments → n/a for open-access night trains.

**Assumptions:** apply 9.94 NOK/trkm uniformly (conservative; Oslo-region km are cheaper).

**Source:** Bane NOR NS 2027 §5.3.3 (Table 4) + mark-up methodology report (Dec, NS25).
**IRG cross-check:** survey NO sheet consistent. ✓

### PL — Poland (PKP PLK)

**Formula:** `TAC = trkm × 8.01 PLN × WM(mass) × WK(avg line category)`

**Values (price list effective 13 Dec 2026):** SMK = 8.01 PLN/trkm; WM: 600–660 t → 1.0000 (0.377–3.286 across 60–4,800 t); WK: avg category 2.1 → 1.0000 (0.672–1.179 across cat 4.0–1.0). Electric-traction component 0.29 PLN/km excluded (energy). Direct-cost-only (no markup in PLK basic fee).

**Assumptions:** WM = 1.0 (reference train), WK = 1.0 (avg category 2.1; mainlines trend better than average → mildly conservative) → 8.01 PLN/trkm ≈ 1.9 EUR.

**Source:** PLK NS 2026/2027 Annex 9.1 (Resolution 1048/2025, updated 14 Jan 2026).
**IRG cross-check:** survey PL sheet consistent (same SMK × WM × WK system). ✓

### PT — Portugal (Infraestruturas de Portugal)

**Formula:** `TAC = trkm × T(line cat, period, traction, segment)`

**Values (TT2027, excl. VAT), segment *International passenger*, electric:** Low band: cat A 2.16 / B 1.95 / C 1.84 EUR/trkm; Regular and Peak bands: A 2.55 / B 2.29 / C 2.16. Band hours (weekdays): Low 00:00–05:59 and 20:45–23:59, Regular 10:00–16:30, Peak 06:00–09:59 and 16:31–20:44; weekends/holidays: Low 00:00–05:59 and 20:45–23:59, Regular 06:00–20:44 (no peak).

**Mechanism & assumptions:** band selected **per leg from the actual schedule** (evening departures before 20:45 and morning arrivals after 06:00 price at Regular/Peak on those legs). Line category A assumed for the Norte/Sul mainlines. Diesel (NE) rates ~10 % lower if traction input says diesel.

**Source:** IP NS 2027 1st Addenda, §5.3 tariff table + line-category legend.
**IRG cross-check:** survey PT sheet consistent. ✓

### RO — Romania (CFR SA)

**Formula:** `TAC = Σ_sections Km × ( Ttsn × [1 + (m − 60) × 0.00014] + Tc )` [lei]

**Values (valid from 1 Mar 2024; passenger):** Ttsn by line class A/B/C/D = 3.45 / 2.80 / 2.14 / 1.48 lei/trkm; Tc = 9.562 / 9.562 / 9.108 / 4.085 lei/trkm; Tmin = 60 t; Ft = 0.00014. Electrification Ttse 0.676 lei/trkm excluded (energy equipment). Verified against worked examples in Annex 26.a (e.g. class A, 500 t, non-electrified: 13.22 lei/trkm ✓). Commercial-stop charge deferred → §5. Rank-based IAC reductions (rank II–IV: 84–73 %) not applied (conservative).

**Assumptions:** line class A/B on main corridors → ≈ 13.2 lei/trkm at 400–600 t ≈ 2.6 EUR/trkm.

**Source:** CFR NS Annexes 25.a (methodology), 25.b (section classes), 26.a (tariff values + examples).
**IRG cross-check:** survey RO sheet consistent (same IAC structure). ✓

### SE — Sweden (Trafikverket)

**Formula:** `TAC = gtkm × track charge(mean axle load) + trkm × train path charge`

**Values (NS 2027 Annex 1B, edition 5 Dec 2025):** track charge passenger, mean axle load ≤ 17 t: 0.0218 SEK/gtkm (> 17 t: 0.0237); train path charge: 4.98 SEK/trkm (all segments). Öresund Link: passenger trains pay the regular track + train path charges only — the **passage charge (3,445.80 SEK) applies to freight exclusively** (→ §5a). Reference train: 600 × 0.0218 + 4.98 ≈ 18.1 SEK/trkm ≈ 1.6 EUR.

**Assumptions:** passenger coaches → ≤ 17 t mean axle load class (runtime check from composition axle data possible).

**Source:** Trafikverket NS 2027 §5.3 (Table 5.1) + Annex 1B "Charges for services" (pp. 212 ff.).
**IRG cross-check:** survey 2025 (0.4366 EUR/trkm path charge ≈ 4.98 SEK; gtkm rates ≈ +10 % nominal) — consistent. ✓

### SI — Slovenia (SŽ-Infrastruktura)

**Formula:** `TAC = trkm × 2.01 × PP(line) × PD(len) × PM(wt) × PV(speed) × PTP × Pl(loco) − incentives`

**Values (TT2027):** C_P1 = 2.01 EUR; PP: R1 0.47 … R4 1.44 (all main corridors incl. Ljubljana–Sežana/Dobova/Jesenice/Šentilj and Koper line = R4); PD: > 300 m 1.05; PM: 251–1,000 t 0.75; PV: loco-hauled 0.97; PTP passenger 1.00; Pl: Vectron/Taurus-class e-loco 1.09. ETCS incentive −0.03 EUR/km if equipped.

**Assumptions:** reference train on R4 → 2.01 × 1.44 × (1.05 × 0.75 × 0.97) × 1.09 ≈ 2.41 EUR/trkm; no ETCS incentive claimed (conservative). Koper-line markup history noted but no passenger markup in the P1 formula.

**Source:** SŽ NS 2027 §5.3 (factor tables).
**IRG cross-check:** survey SI sheet consistent (same factor system). ✓

### SK — Slovakia (ŽSR)

**Formula:** `TAC = trkm × (U1 + U2)(track cat) + gtkm/1000 × U3(track cat) × ke`

**Values (Measure 2/2018 Annex 1, unchanged since 1 Jan 2019, excl. VAT):**

| Track category | U1 (timetable train) €/trkm | U2 €/trkm | U3 €/1,000 gtkm |
|---|---|---|---|
| 1 | 0.0691 | 0.997 | 1.102 |
| 2 | 0.0566 | 0.927 | 1.048 |
| 3 | 0.0487 | 0.884 | 0.945 |
| 4 | 0.0319 | 0.774 | 0.779 |
| 5 | 0.0272 | 0.588 | 0.670 |

Ad-hoc U1 rates higher (0.0981–0.1890). ke = 1.2 for diesel traction on electrified lines, else 1.0. U4 (electric supply equipment, 0.228 EUR/1,000 gtkm) excluded (energy). Component check: U1+U2+U3+U4 at 1,000 t, cat 1, electric = 2.396 EUR/trkm = IRG survey composite. ✓

**Mechanism & assumptions:** weight applied at runtime via U3; track category 1–2 assumed for main corridors. Reference train (600 t, cat 1): 0.0691 + 0.997 + 0.6 × 1.102 = **1.73 EUR/trkm**.

**Source:** ŽSR NS 2027 Annex 5.2.B (Measure 2/2018 of the Transport Authority, Annex 1); NS 2027 ch. 5.3.

### UK — Great Britain (Network Rail)

**Formula:** `TAC = vehicle_miles × VUC(vehicle class)` → per train-km: `(VUC_loco + n_coach × VUC_coach) / 1.609`

**Values (CP7, 2023/24 prices, indexed within CP7):** default rates — locomotive 127.05 p/vehicle-mile, coach 23.45 p/vehicle-mile, MU motor 60.44, MU trailer 28.23. Reference train (1 loco + 10 coaches): 361.55 p/train-mile ≈ 2.25 GBP/train-km. Class-specific rates available in the price list (incl. Caledonian Sleeper Mk5 stock) for refinement. EAUC (electrification asset usage) excluded (energy equipment); fixed track access charges apply to franchised operators only → n/a open access.

**Channel Tunnel:** separate charging regime (Getlink, not Network Rail/CP7) → modelled as a crossing entity in the `passage_charges` table (§5a), now sourced from the Fixed Link Usage Annual Statement 2026. HS1 (London–tunnel) likewise has its own charging framework outside CP7 — flag if UK routing via HS1 enters the target network.

**Source:** Network Rail CP7 Track Usage Price List (xlsm), sheets "Passenger VUC" / "Default Passenger VUC"; NR NS 2027.
**IRG cross-check:** survey UK sheet consistent (VUC per vehicle-mile system). ✓

---

## 5a. Crossing-specific passage charges (`passage_charges` table)

Fixed per-train charges tied to specific crossings, triggered by route geometry, additive to the per-country km-based charges:

| Crossing | Charged by | Passenger charge per train | Status |
|---|---|---|---|
| Storebælt | Banedanmark | 4,876.73 DKK (2025 order, excl. VAT) | sourced |
| Øresund — Danish part | Banedanmark | 2,592.02 DKK (2025 order, excl. VAT) | sourced |
| Øresund — Swedish part | Trafikverket | **none for passenger** (freight only: 3,445.80 SEK); regular SE track/path charges apply on the link | sourced (NS 2027 Annex 1B) |
| Channel Tunnel | Getlink (Eurotunnel) | Offer 1 (regular weekly paths), **night trains @120 km/h, off-peak**: reservation fee ≈ 4,039 EUR/train o/w (2,255 € + £1,486) **+ per-passenger access fee ≈ 18.35 EUR/pax o/w** (8.36 € + £8.32); maintenance periods @100 km/h: ≈ 6,732 EUR/train. 2020 price basis, indexed (RPI/IPC; pax fee −1.1 % p.a. factor); billed half EUR / half GBP (combined at £1 = 1.20 €) | sourced (Fixed Link Usage Annual Statement 2026, Annexe 4) |

Architecture note: keep these as a dedicated `passage_charges` entity keyed by crossing (extensible for Fehmarnbelt in the 2032 scenario), not as country attributes. The entity needs `fixed_per_train` **and** `per_passenger` columns — the Channel Tunnel toll has a per-carried-passenger component, which couples the passage cost to the demand model output (load-dependent, evaluated in the revenue/cost loop, not the routing stage). Getlink specifics: the Fixed Link NS states night passenger trains operate at 120 km/h in off-peak periods (100 km/h in maintenance periods) → the off-peak row is the night-train tariff by definition; Offer 2 (individual trains) runs ~10 % higher plus 7,500 EUR admin per contract — Offer 1 (regular weekly paths) is the correct basis for a scheduled night service.

## 5. Deferred stop-based components (→ station-charge calibration)

Excluded from this model to avoid double counting with the later station model; values recorded so they are not lost. The CH Haltezuschlag was moved **into** the TAC model (capacity price element of the path price, no CH station charge exists for platform provision — see CH section).

| Country | Component | Value | Nature |
|---|---|---|---|
| CZ | C_PK passenger platform access | 0.04–0.11 CZK per stop·t by station category (2027) | Platform access within statutory two-component price |
| GR | c_pss | 4.21 EUR/stop × 0.7185 ≈ 3.02 EUR/stop | Stop term of the C_MAP formula |
| NL | Stop charge by station type | 0.09 / 0.36 / 0.88 EUR/stop (2025 survey values; 2027 values in NS stop-service table) | MAP category-1 stop service |
| HU | Use of stations by passenger trains | 3,327–3,877 HUF/stop; origin/destination 3,345–3,669 HUF | Station usage (IM-levied) |
| RO | Commercial stop charge (Annex 26.a §2.1) | not extracted | Station stop charge |

## 6. MISSING register and open actions

1. **DE −17 %** — applied as assumption (calibrated 2.76 EUR/trkm); re-approval document itself still to be filed. → confirm and archive source.
2. **CH revenue_share** — authority-set contribution-margin percentage for international night trains not published in the legal texts (observed range 0–21 %). → scenario parameter; check BAV/concession publications.
3. **IT Notturno band hours** — assumed 22:00–06:00 pending confirmation from RFI PIR.
4. **Channel Tunnel price basis** — Getlink scales are at 2020 prices with monthly/annual indexation (RPI/IPC, pax fee −1.1 % p.a.); indexation to the model's price-basis year still to be applied. HS1 charging framework not sourced (only relevant if London routing enters the target network).
5. **EE Edelaraudtee** and **HU GYSEV** sub-networks not separately calibrated (minor route shares).
6. Line-category matching (price-list categories PL/RO/SK/HU/PT/SI/HR/CH, UIC classes FR) fixed by conservative assumption; ES/FR high-speed vs conventional now resolved at runtime from infra max speed; OSM proxy (`maxspeed`/`highspeed`/`usage`) is the refinement path for the rest — confirmed approach.

## 7. General sources

- Per-country official documents as cited above (TAC_sources archive, folders 01–29; price-basis years stated per country and kept separate from publication years).
- IRG-Rail TAC survey 2025 (per-country sheets) — cross-check baseline.
- IRG-Rail 14th Market Monitoring Report 2026 (main, working document, dataset) — plausibility of average charge levels.
- IRG-Rail (20) 10 — Overview of Charging Practices for the Minimum Access Package (+ Annex) — structural reference.
