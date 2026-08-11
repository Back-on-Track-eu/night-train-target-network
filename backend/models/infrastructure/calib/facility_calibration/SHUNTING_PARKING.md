# Shunting and Parking Charges — Per-Event Calibration

Location: `backend/models/infrastructure/calib/facility_calibration/SHUNTING_PARKING.md`
Third companion to `TAC_MODEL.md` and `ENERGY_MODEL.md`. Station and stop charges remain separate and are **not** in this file.

---

## 1. Event definitions and reference rotation

| Event | Definition |
|---|---|
| **Shunting event** | One assisted movement of a trainset or locomotive within a service facility or between platform and siding, using shunting staff and a shunting locomotive |
| **Parking event** | One continuous stabling occupation of a trainset on a siding or storage track, outside commercial service |

**Reference rotation:** 1 locomotive + 10 coaches, ~300 m, arriving in the morning and departing the same evening → **2 shunting events + 1 parking event of 12 h** per turnaround. A turnaround serves both the inbound and the outbound trip, so **per one-way trip the model books 1 shunting event + 0.5 parking events**.

Reference parameters: train length **300 m**, parking duration **12 h**, shunting crew time **1 h per event**.

**Not included:** traction energy or hotel power drawn while stabled (→ `ENERGY_MODEL.md`), cleaning and interior servicing, maintenance-facility use, station and platform stop charges.

---

## 2. Why a mixed (two-component) model is necessary

The raw network-statement tariffs span a factor of 150 for what is physically the same operation — Hungary charges ~263 € per shunting move, Poland ~1.7 €, Denmark nothing. Reading that as a price-level difference would be wrong. **The spread is driven by scope, not by cost level:**

- MÁV's tariff bundles the shunting locomotive itself (79,752 HUF/vehicle/h) plus crew (24,480 HUF/person/h).
- DB InfraGO charges **only for the track**: Zugbildung I is 10.80 €/use-hour, and the shunting locomotive and crew are bought on a separate market.
- Adif prices the operation as a service: 148 €/h shunting driving, 200 €/h overall shunting operations.
- OSE charges 30 €/manoeuvre and states explicitly that this covers the manoeuvring team **only, not the locomotive or driver**.

So the model separates:

```
shunting_event_allin = IM_tariff(country) + market_topup(scope, labour_index)
parking_event        = IM_tariff(country, length, duration)      # no market top-up
```

**Scope classes and top-ups** (per event, at index 1.00):

| Scope | Meaning | Top-up |
|---|---|---|
| `full` | IM supplies locomotive **and** crew | 0 |
| `crew` | IM supplies crew only | +110 € (locomotive) |
| `track` | IM supplies track/facility access only | +190 € (locomotive + crew) |

**Labour index.** The Ramboll/BMDV night-train study prices train-driver time across the 15 countries it covers at **62–104 €/h**, i.e. a spread of 1.68× between cheapest and dearest — a far narrower band than the raw tariffs suggest. Scaled around the midpoint this gives a three-tier index of **1.25 / 1.00 / 0.75**:

- **1.25** — AT, BE, CH, DE, DK, FI, FR, IE, LU, NL, NO, SE, UK
- **1.00** — CZ, EE, ES, IT, PT, SI
- **0.75** — BG, GR, HR, HU, LT, LV, PL, RO, SK

Applying this collapses the 150× raw spread to a **2.8× all-in spread (99–277 €)** centred near 200 € — which is what one would expect for one hour of a shunting locomotive plus crew anywhere in Europe.

**Parking is *not* index-scaled.** The sourced length-based rates give no wage signal at all: Bulgaria charges 0.20 €/m/day, Austria 0.15–0.31 €/m/day, Norway 0.12 €/m/day. A low-wage and a high-wage country sit on the same rate, because stabling is land and track, not labour.

---

## 3. Length-based parking — yes, introduce it

Four IMs price stabling explicitly per metre of occupied track, which confirms the approach:

| Country | Sourced rate | € per metre per 24 h |
|---|---|---|
| AT | 0.31 €/m/day short-term; 0.24 €/m/day long-term; 4.57 €/m/month | 0.31 / 0.24 / **0.150** |
| BG | 0.20 € per metre per 24 h | **0.20** |
| NO | 6 NOK/h per commenced 100 m (31 at Alnabru) | **0.123** (0.636 Alnabru) |
| HR | 0.0013–0.0022 €/m/h by duration band | **0.031–0.053** |

Median of the sourced set ≈ **0.20 €/m per started 24 h**, which for the 300 m reference train gives **60 € per day** — landing squarely between DE's sourced 72.24 €, GR's 60.00 € and AT's 45.10 €. The convergence is the reason to adopt it as the default rather than a flat per-event figure.

```
parking_event = length_m × rate_per_m_per_day × ceil(hours / 24) − free_allowance
```

**Default rate: 0.20 €/m per started 24 h.** Free allowances are country-specific and material (§4).

**Documented exception — Germany is length-independent.** DB InfraGO's Anlagenpreissystem charges per use-hour per usage object, and the APS states the disponent-managed charge is expressly *"infrastruktur- und zuglängenunabhängig"*. DE therefore keeps a flat hourly rate.

---

## 4. Master calibration table

FX as in the other files (1 EUR = 396 HUF / 4.25 PLN / 11.7 NOK / 7.46 DKK / …), refreshed at runtime.

| Country | Scope | Idx | IM shunting €/ev | **Shunting all-in €/ev** | Parking basis | **Parking €/ev (300 m, 12 h)** |
|---|---|---|---|---|---|---|
| AT | full | 1.25 | 99.25 | **99.25** | 0.150 €/m/day (monthly booking) | **45.10** |
| BE | track | 1.25 | 39.00 | **276.50** | congested yards only | **0.00** |
| BG | track | 0.75 | 2.20 | **144.70** | 0.20 €/m/24 h *(sourced)* | **60.00** |
| CH | track | 1.25 | 0.00 | **237.50** | default 0.20 €/m/day | **60.00** |
| CZ | track | 1.00 | *10.00* | **200.00** | default 0.20 €/m/day | **60.00** |
| DE | track | 1.25 | 10.80 | **248.30** | 6.02 €/h Abstellung I, length-indep. | **72.24** |
| DK | track | 1.25 | 0.00 | **237.50** | no charge levied | **0.00** |
| EE | track | 1.00 | *10.00* | **200.00** | default | **60.00** |
| ES | full | 1.00 | 148.00 | **148.00** | default | **60.00** |
| FI | track | 1.25 | *10.00* | **247.50** | default | **60.00** |
| FR | track | 1.25 | *10.00* | **247.50** | non-regulated (§5) | **60.00** |
| GR | crew | 0.75 | 30.00 | **112.50** | = 2 manoeuvres, no time term | **60.00** |
| HR | track | 0.75 | *10.00* | **152.50** | first 24 h free on side track | **0.00** |
| HU | full | 0.75 | 263.00 | **263.00** | default | **60.00** |
| IE | track | 1.25 | *10.00* | **247.50** | default | **60.00** |
| IT | track | 1.00 | *10.00* | **200.00** | 9.99 €/operation *(sourced)* | **9.99** |
| LT | track | 0.75 | *10.00* | **152.50** | default | **60.00** |
| LU | track | 1.25 | *10.00* | **247.50** | default | **60.00** |
| LV | track | 0.75 | *10.00* | **152.50** | default | **60.00** |
| NL | track | 1.25 | *10.00* | **247.50** | default | **60.00** |
| NO | track | 1.25 | *10.00* | **247.50** | first 48 h free, then 0.123 €/m/day | **0.00** |
| PL | track | 0.75 | 1.72 | **144.22** | default | **60.00** |
| PT | crew | 1.00 | 24.59 | **134.59** | 0.0405 €/min beyond first hour | **29.16** |
| RO | track | 0.75 | *10.00* | **152.50** | default | **60.00** |
| SE | track | 1.25 | *10.00* | **247.50** | default | **60.00** |
| SI | track | 1.00 | 13.27 | **203.27** | planned storage not charged | **0.00** |
| SK | track | 0.75 | *10.00* | **152.50** | default | **60.00** |
| UK | track | 1.25 | *10.00* | **247.50** | default | **60.00** |

*Italic* = assumed IM component (10 € default = the track-access-only level observed in DE 10.80, SI 13.27, PL 1.72).

---

## 5. Country notes on the changed entries

**DE — now fully sourced (APS 2027, valid from 13.12.2026).** The missing Abstellung I rate is **6.02 EUR per started use-hour** (Abstellung II 2.68, III 1.74); train formation is Zugbildung I 10.80 / II 7.67 / III 6.02 EUR/h. A 12 h layover on an Abstellung I object is therefore **72.24 €**, replacing the 50 € floor used previously — the INB's "minimum 50 EUR per uninterrupted usage period" applies only to stabling on running lines and is not binding here. Two further APS provisions matter for a night-train rotation:

- **Facilities with an Anlagendisponent price punitively by duration**: charge = hours × factor × Abstellung I, with the factor rising 1→10 over the first ten hours and constant at 10 thereafter. A 12 h stay costs **722.40 €** and a 24 h stay **1,444.80 €** — ten times the plain Abstellung I rate. Whether a given facility is disponent-managed is published in the Liste der Serviceeinrichtungen; routing a layover to a non-disponent facility is worth an order of magnitude.
- **Disposition tracks** are a flat 50 EUR per 2 h or 8 h slot, and unauthorised use is penalised at 20× the hourly rate plus 200 EUR fixed.

**BG — resolved.** The 0.20 € / 0.40 BGN charge is per **metre of length per 24 hours**, not per vehicle. For the 300 m reference train that is 60.00 €/day, and Bulgaria becomes the fourth explicitly length-based regime.

**FR — resolved, negatively.** DRR 2027 Appendix 5.4 does **not** contain a siding tariff, and none is missing by oversight: NS §7.4.2.2 classifies occupation of sidings without frequent rail movements as a **non-regulated service**, so no published scale exists. France also operates a night-specific product — stabling on main terminal tracks between 00:00 and 05:00, charged for the whole slot regardless of actual use. FR therefore carries the default rate with the note that the real price is bilaterally negotiated.

**PL — assumption retained and stated.** Shunting is 3.66 PLN/km (electric traction) applied to standardised distances tabulated in NS Appendix 2.8. Rather than transcribe that table, the model assumes **2 km per shunting movement** → 7.32 PLN ≈ 1.72 €. Since the market top-up dominates the PL all-in figure (142.50 of 144.22), the sensitivity of the total to this assumption is under 2 %.

**AT, ES, HU** keep their sourced full-service tariffs with no top-up. Hungary's 263 € exceeds what the labour index would predict for a 0.75-tier country; that is consistent with the general Hungarian charge escalation already flagged in `TAC_MODEL.md` and the sourced value is used as-is rather than being smoothed toward the benchmark.

---

## 6. Cross-checks against the two operator-side cost models

**nox model (night-train business case, 2030 scenario).** It isolates a line item *"213 — OPS Infrastructure Access"* at **307.55 € per trip**, i.e. 0.312 €/train-km on a 987 km trip, separate from *"212 — Track & Station Access"* (3,518.98 €/trip) and *"214 — Servicing"* (2,599.27 €/trip). That is the closest external analogue to this file's scope.

Testing the calibration against it, using Germany: one turnaround = 2 × 248.30 + 72.24 = 568.84 €, and a turnaround serves two trips → **284 € per trip**, against nox's 307.55 €. **Agreement within 8 %.** This is the strongest validation available and it is what justifies the market top-up: the IM-tariff-only figure for the same rotation would have been 2 × 10.80 + 72.24 = 93.84 €, i.e. **about a quarter of what the operator-side model books**.

**Ramboll/BMDV study.** It reports *Reinigung/Abstellung* as **14 % of total cost** at 44.51 €/train-km, i.e. ~6.2 €/train-km — but that block bundles cleaning with stabling and cannot be split. The comparable nox pair (Servicing 2.63 + OPS Infrastructure Access 0.31 = 2.95 €/train-km) is **roughly half** Ramboll's figure, and Ramboll itself notes the personnel/cleaning/stabling block sits "auf wesentlich höherem preislichem Niveau" than earlier studies assumed.

**So the two models do differ materially — by about a factor of two — but almost entirely in the cleaning/servicing component, not in infrastructure access.** Only nox separates stabling and shunting from cleaning, so it is the anchor used here; Ramboll's higher block is consistent with it once cleaning is included, and cleaning is out of scope for this file.

A useful by-product: Ramboll's own track-access assumptions (DE 2.76, CH 2.18, FR 4.26 €/train-km) sit very close to `TAC_MODEL.md` (DE 2.76 after the −17 % adjustment, FR 4.08), which independently supports the German re-approval assumption.

---

## 7. On indexing by RMMS infrastructure-charge revenue

This was tested and **rejected**. Combining RMMS Figure 64 (IM revenue from charges 2022) with Figures 5 and 69 (network length and utilisation) gives revenue per train-km, but the result is not usable as a price index:

| Country | RMMS revenue €/train-km | TAC_MODEL €/train-km |
|---|---|---|
| FR | 13.59 | 4.08 |
| ES | 5.97 | 1.73 |
| DE | 5.39 | 2.76 |
| CZ | 0.50 | 1.96 |
| HR | 0.46 | 2.15 |

France is inflated roughly threefold because SNCF Réseau's charge revenue includes the *redevance d'accès* — annual lump sums of 441 M€ from the State plus ~1.8 bn from the regions, which are not per-train-km charges at all. The RMMS *"other charges"* share is likewise unusable as a service-facility proxy: Denmark shows 57 % "other" while its network statement levies **nothing** on sidings, because the category is capturing the Storebælt and Øresund bridge tolls (already modelled as passage charges in `TAC_MODEL.md` §5a). Italy's 27 % and Norway's 11 % are similarly undecomposable.

The labour-cost index from the Ramboll driver-hour band is used instead: it is narrower, directly relevant to the cost driver, and does not mix freight, PSO lump sums and tolls into the signal.

---

## 8. Materiality and open items

For the reference rotation the all-in cost is now **200–620 € per turnaround** (≈100–310 € per one-way trip), against a daily track access charge of roughly 1,500–3,000 €. That is **7–15 % of infrastructure cost** — materially higher than the 2–7 % implied by IM tariffs alone, and high enough that the market top-up assumption deserves scrutiny before the model is used for route ranking.

1. **The 190 € / 110 € market top-ups are the single biggest assumption in this file.** They are calibrated to reproduce nox's per-trip figure for Germany and cross-checked against the three `full`-scope sourced tariffs (AT 99, ES 148, HU 263, mean ≈ 170). A single real quotation for third-party shunting in one country would materially tighten them.
2. **DE facility category and disponent status** — Abstellung I vs III is a 3.5× difference, and disponent-managed facilities are 10× on a 12 h stay. Both are published per facility in the Liste der Serviceeinrichtungen and should be resolved for the specific stabling locations a route uses.
3. **The twelve default-IM countries** (CZ, EE, FI, FR, IE, LT, LU, LV, NL, RO, SE, SK, UK plus CH) each need a service-facility price list. Worth doing only for countries a chosen route set actually touches — the top-up dominates the total in every case.
4. **Scope classification** is inferred from tariff wording for AT, DE, ES, GR, HU, PT and assumed `track` elsewhere. Any country that turns out to bundle a locomotive moves by roughly −190 € per event.
5. **Facility-operator vs IM boundary.** A zero in the IM column means the *infrastructure manager* charges nothing, not that the operator pays nothing — which is precisely why the top-up exists. In CH, DK, DE, NL and UK the stabling facility is typically operated by the incumbent's depot arm, and for an open-access night train that bilaterally negotiated depot access is the dominant cost in this file.
