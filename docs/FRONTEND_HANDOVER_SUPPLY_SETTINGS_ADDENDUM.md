# Addendum — the backend §6 changes, as shipped

**Date:** 2026-09-12 · **Branch:** `backend-dev`
**Supplements:** `FRONTEND_HANDOVER_SUPPLY_SETTINGS.md` (revision 2), whose
§6 this replaces with what is actually on the wire.
**Design reference:** `design/2026-09-12_details-sketch.html`.

**Versions after this change**

| Constant | Was | Is |
|---|---|---|
| `CALC_VERSION` | 0.9.28 | **0.9.29** |
| `DEMAND_MODEL_VERSION` | 0.0.2 | **0.0.3** |
| `FAMILY_DOCUMENT_FORMAT` | 3 | **4** |
| `ROUTE_BUILDER_VERSION` | 0.9.35 | **0.9.36 — no output change** |

`ROUTE_BUILDER_VERSION` moves for a different reason than §7.1 expected. The
per-trip operations split did **not** need it: `operations.py` lives under
`models/evaluation/`, so `CALC_VERSION` gates it. The bump comes from a lint
cleanup riding along in the same batch — one unused import removed from
`route.py` — and the CI version gate treats any diff to a route-builder file
as a model change. **Every number a route produces is identical to 0.9.35**;
the changelog entry says so. Nothing on your side keys off the difference,
beyond a stored proposal now reading one patch version behind.

Every family key moves regardless — the calc version, the route-builder
version and the document format are all folded into it — so no cached
document survives this deploy.

---

## 1. `catering_eur_per_pax` — request field, signed (§6.1)

One number, either sign, optional. It is a **net** figure: the on-board
service's own sales less its own costs. The restaurant is not modelled as a
business of its own.

```jsonc
// POST /api/proposal/family  ·  POST /api/proposal/publish
"catering_eur_per_pax": -0.80        // optional; default 1.20
```

- Validation: any number, `null`, or absent. A bool or a string is 400.
  **Negative is not an error** — it is the ordinary night-train case.
- Canonicalised into the resolved echo at two decimals, exactly like the
  fares, so an omitted field and a posted default hash alike.
- **In the family key.** A different value is a different family.
- Survives publish and reload inside `compute_request`, like the fares and
  the schedule — no new persistence work on your side beyond §5 of the main
  document (`proposalPrefill.ts` still has to restore it).

**Default**, from `GET /api/models`:

```jsonc
"demand": {
  "version": "0.0.3",
  "defaults": {
    "fares_eur_per_km": { "Seat": 0.10, "Couchette": 0.13, "Sleeper": 0.18, "Capsule": 0.12 },
    "catering_eur_per_pax": 1.20,
    "utilization_per": 0.7
  }
}
```

1.20 is the sketch's value, kept deliberately: a documented stopgap, and
positive, so nothing about the figure's sign is implied by its default. The
field accepts negatives and the panel's sign reading handles all three cases.

### Where it lands in the numbers

`catering_contribution_eur = Σ_od places_sold × catering_eur_per_pax`.

- It is **revenue**: a second leaf beside `ticket_revenue_eur`, inside
  `total_revenue_eur` and therefore inside `net_eur`.
- It is **outside** `var_overhead_eur` and `margin.ebit_margin_eur`, which
  stay shares of ticket revenue — charging distribution overhead on a figure
  that already nets its own overhead would count it twice. §4.4's copy is
  correct as written.
- It is allocated across every view on the same key as ticket revenue, so
  the country, section, OD and stop cells still sum to the route total.

**Breakdown, every view, every normalisation:**

```jsonc
"revenue": {
  "ticket_revenue_eur": 4193280.0,
  "catering_contribution_eur": -106560.0,   // NEW — signed
  "total_eur": 4086720.0
}
```

**Summary row** (family document, gallery rows, `GET /api/proposal/<id>`):

```jsonc
"catering_contribution_eur": -106560.0,   // NEW — signed, already inside net_eur_per_year
"passengers_per_year": 133200             // NEW — places actually sold
```

`passengers_per_year` is the base the contribution multiplies: Σ `places_sold`
over every OD pair. **It is not `demand_trips_per_year`**, which stays the
placeholder derived from ticket revenue ÷ 120 € and is unaffected by this
change (the divisor now reads ticket revenue explicitly, so a catering
contribution cannot invent passengers who bought nothing). For §4.5's
"Passengers" row, use `passengers_per_year` — it is the only figure that
reconciles with the contribution beside it.

Two DB columns back these (`catering_contribution_eur`,
`passengers_per_year`); rows published before this deploy keep 0 for both.

**Formula entry** for the ⓘ catalogue: `calc.catering_contribution_eur`,
with `total_revenue_eur` reworded to `R_ticket + R_cat`. Both are in
`GET /api/models` and on the docs site
(`/docs/cost/catering-contribution`).

---

## 2. `operations` — per trip, plus the fleet basis (§6.2 + §6.3)

Unchanged: everything that was on `operations.trip_pairs[]` before —
`composition_id`, `trainsets`, `loco_hours` (per cycle), `staffing` (per
cycle). Additive only.

```jsonc
"operations": {
  "trip_pairs": [{
    "composition_id": "NEW-BAL-7",
    "trainsets": { "physical": 2, "theoretical": 2.3, "coach_avail_per": 0.87,
                   "cycle_days": 2, "peak_month": 1, "min_turnaround_min": 180 },

    // NEW — the basis behind the fleet receipt's lines
    "fleet": {
      "coaches_per_set": 7,
      "coaches_needed": 16.1,             // coaches_per_set x trainsets.theoretical — the cost model's own n
      "purchase_coach_eur": 3846642.86,
      "amort_years": 30,
      "financing_quota_per": 0.04,
      "coach_maint_eur_km": 7.0,
      "cleaning_eur_coach_day": 364.0,
      "shunting_events_per_trip_cycle": 4
    },

    "loco_hours": { "per_trip_cycle": 15.5, "per_year": 5673.0, "n_locos": 1 },
    "staffing": { "drivers": { … }, "train_chief": { … }, "attendants": { … }, "total": { … } },

    // NEW — the per-direction split
    "trips": [{
      "trip_id": "R1_T1",
      "direction": "outbound",
      "loco_hours": { "running": 6.0, "at_stops": 1.75, "total": 7.75 },
      "staffing": {
        "drivers":     { "on_board": 1, "factor": 1.0,  "hours_on_train": 7.25,
                         "roster_efficiency": 0.885, "paid_hours": 8.19, "eur": 443.7 },
        "train_chief": { "on_board": 1, "factor": 1.19, "hours_on_train": 1.72, … },
        "attendants":  { "on_board": 4, "factor": 1.0,  "hours_on_train": 5.53, … },
        "total": { "on_board": 6, "factor_equivalents": 6.19,
                   "hours_on_train": 14.5, "paid_hours": 16.38, "eur": 1489.2 }
      }
    }, { "direction": "return", … }]
  }],
  "route": {
    "operating_days_per_year": 366,       // NEW
    "departures_per_year": 732,           // NEW
    "trainsets_physical": 2, "trainsets_theoretical": 2.3,
    "loco_hours_per_year": 5673.0,
    "staff_hours_per_trip_cycle": 29.0, "staff_eur_per_year": 2180347.2
  }
}
```

### Three things that differ from the sketch — please read before F3

**1. Loco hours split as `running` + `at_stops`, not "at the terminals".**
The model has no terminal loco time. What a loco does at a terminal is
priced as **parking** (`ParkingCost`, an infrastructure leaf), not as lease
hours. Its hours are the time it spends moving plus the dwells at
intermediate stops where it stays coupled. The Locomotive panel's two rows
should read **Running** and **At stops** — labelling the second "at the
terminals" would be wrong twice over, and a reader checking it against the
Infrastructure tab's parking panel would find the same hours counted in two
places.

**2. `fleet` carries the basis, not the euros.** §6.3 was right that the
fleet receipt needs nothing new for its amounts: the five lines stay
per-year leaves of the `per_trip_pair` view (`coach_maintenance_eur`,
`cleaning_eur`, `shunting_eur`, `coach_amortisation_eur`, `financing_eur`)
÷ `departures_per_year`. What `fleet` adds is the **basis column** — the
rates and counts the sketch prints beside each line ("7.00 €/km", "364
€/coach·d", "4 × …", "3.85 M € · 30 a"), which the breakdown does not
carry. Emitting the euros here too would have been a second copy free to
drift from the first, so it is deliberately not there.

**3. `roster_efficiency` is per trip and per role, not per proposal.** It
depends on the trip's driving and on-train hours — that is the whole point
of the duty-boundary rule — so the two directions of a pair generally differ.
`paid_hours = hours_on_train / roster_efficiency`, and `eur` stays the cost
model's own figure rather than `paid_hours × a rate re-derived on the page`.
For the staff table's "effective rate" column, divide `eur` by
`hours_on_train` as the sketch does.

### Reading the receipts

- Per trip: a per-year breakdown leaf ÷ `operations.route.departures_per_year`.
  Use that field, not a departures figure derived from the schedule on the
  page — they agree today and the field is the one the backend actually used.
- Per cycle: × 2, or the `per_trip_cycle` figures already in `operations`.
- Per year: × `operations.route.operating_days_per_year`.
- A Y-route has more than one pair: take the pair by `composition_id` and
  the trip by `direction`. Never index `[0]` (main document §7.2, F3).

---

## 3. §6.4 — the overhead fields, confirmed

No code change was needed. `var_overhead_eur`, `fix_overhead_eur`,
`margin.ebit_margin_eur` and both operator subtotals (`operator.variable
.total_eur`, `operator.fixed.total_eur`) are on the `per_trip_pair` view as
§4.4 assumes. Two tests now pin it, including that
`fix_overhead_eur == q_fix,oh × (operator variable excl. variable overhead
+ operator fixed excl. the leaf itself)` — the base the Fixed overhead
receipt lists row by row, with infrastructure outside it.

---

## 4. §6.5 — Infrastructure is still not started

Unchanged from the main document: the "charged on" term list per country,
parking per terminal, and kWh + tariff per country are not on the wire yet.
F5 stays blocked. Nothing in this change moves it closer or further away.

---

## 5. What F6 adds to `types/api.ts`

Coordinate with Bjarne — this grows the pending coordination batch.

| Where | Key | Type |
|---|---|---|
| request | `catering_eur_per_pax` | `number` (optional, may be negative) |
| `GET /api/models` | `demand.defaults.catering_eur_per_pax` | `number` |
| `Breakdown.revenue` | `catering_contribution_eur` | `number` (signed) |
| summary | `catering_contribution_eur` | `number` (signed) |
| summary | `passengers_per_year` | `number` |
| gallery row | both of the above | `number \| null` (null on ONTD rows) |
| `operations.trip_pairs[]` | `fleet` | object, above |
| `operations.trip_pairs[]` | `trips[]` | array of two, above |
| `operations.route` | `operating_days_per_year`, `departures_per_year` | `number` |

`EvaluationViewsResponse` should stop being typed as views-only if it still
is: the member views endpoint has carried `operations` since 0.9.28, and
`useProposalFamily.views()` currently drops it
(`viewsCache.set(key, resp.views)`) — F3 needs it kept.

---

## 6. Deploy note

The migration adds two columns to `proposals.proposal_summaries`. The
publish projection writes every summary key as a column, so **the migration
must run before the api image that produces them** — which is what
`deploy.sh` already does. Detail in `DEPLOY_HANDOVER.md`.
