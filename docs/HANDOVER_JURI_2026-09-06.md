# Handover to Juri — cost parameters for compositions, what your feedback changed (2026-09-06)

Short version. Full derivation with all sources:
`backend/models/compositions/calib/CALIBRATION.md`.

## The result first

Operator cost per train-km (without track access, energy and stations — those
are priced per route separately), on our reference route of 1,000 km / 14.5 h:

| Train | before | after |
|---|---|---|
| **REF-PREM-12** — the European Sleeper consist you tested | **50.9** | **25.1** |
| **NEW-BAL-14** — the new Nightjet consist you tested (Berlin–Napoli) | **53.5** | **31.6** |
| Fleet average, all 12 compositions | 40.1 | 21.7 |

**What the tool then asks for in ticket revenue.** Two things are taken out of
every ticket euro before it can pay for the costs above: 8% for sales and
distribution, and the operator's profit margin. So a route with 100 € of
operating cost needed **122 €** of ticket revenue before (8% + 10% margin) and
needs **115 €** now (8% + 5% margin). That is the only effect of the EBIT
change — it does not touch the cost figures.

## Can we reach your numbers?

**European Sleeper: 32–40 k€ per train run, ~28 €/km all-in.** Take off track,
energy and stations (~6–7 €/km on Prague–Brussels) and ES runs at roughly
**21–22 €/km** for the operator part. We are now at **25.1** on the reference
route; on Prague–Brussels itself the tool will land lower than that, because
that route is longer and faster than our reference and the fixed costs spread
over more km. So we are now within ~10–15% of ES — from 80% above before.
What is left is the coach itself, explained at the end.

**RDC: 28 €/km all-in.** Same picture: our all-in figure on a comparable route
is now in the low-to-mid 30s instead of the 50s.

**Berlin–Napoli with a new Nightjet: you saw 52 €/km.** After the reseed the
same route should show roughly 33 — new stock is genuinely dearer per km than
ES's old coaches because it costs €3.4M per coach to buy; ES pays a fraction
of that. That gap is real and intended.

## Your points, one by one

**1. Maintenance is too high (Josua: the RIC KeV; you: the lessor).**
Before: 1.30 €/coach-km for refurbished, 1.00 for new — a constructed guess.
Now: **0.70 / 0.60**. Why not exactly the KeV's 0.95? Because the KeV is what
one railway pays another for *using* a coach — it covers maintenance **and**
part of the capital cost. Our model pays the capital separately, so the
maintenance share inside the KeV is about 0.5–0.7; we took the top of that.
Ramboll (2.5% of purchase price per year) and Italo's actual contract (0.38)
sit even lower. 0.60 for new stock keeps new visibly cheaper to run than old.

**1b. The refurbished coach itself.** Before: €1.40M per coach (buying a
ten-year-old CNL sleeper and giving it a full French-TET-grade renovation),
written off over 12 years. Now: **€1.19M written off over 15 years** — a
coach bought older and cheaper, refitted to the Swedish SJ scope, kept to the
end of the 10–15-year programme horizon both refit programmes state. Together
with the maintenance change, a refurbished coach now costs ~1.12 €/coach-km
to own and run at our reference mileage, against the KeV's ~1.0 for a
depreciated state-railway coach.

**2. Availability: 90% used / 85% new (the lessor).**
Before: 80% / 90.9%. Now: **87% / 92%**. We took the lessor's point for used
stock but not fully (he leases used stock), and kept new stock above it — no
operator publishes fleet availability, so the official BVWP figure stays the
anchor there.

**3. ES's target EBIT is 5%.** Before 10% (our reading of their plan). Now **5%**.

**4. Coach prices at 2026, not 2032.** They already were — bought now for a
2032 network — but the document said "contract window". Now it says 2026.

**5. ÖBB paid €2.86M per Nightjet coach in 2021, ~€3.4M today.** Before: our
model priced a new coach at €3.84M (145 k€ per metre — the middle of five
recent contracts). Now: **128 k€ per metre = €3.39M per coach**, which is the
25th percentile of those five contracts and is exactly your ÖBB figure. In
plain words: we now assume a buyer gets the price ÖBB actually paid, not the
average of everything on the market.

**6 + 7. The cost per train is far above ES/RDC.** Besides maintenance, three
other things were too high and are now sourced from operator data:

| what | before | after | source |
|---|---|---|---|
| Cleaning + laundry | 364 € per coach per night | **180** | Ramboll's Tab. 11 from a night operator's real bills: sleeper 225 €, couchette 165 €, seat 45 € per trip incl. laundry and water |
| Fixed overhead | 12% on all other costs | **8%** | ES plans 5–6%, Italo runs 10% |
| On-board staff | 1 per sleeper, 0.5 per couchette, 0.25 per seat coach, 2 in the dining car, train manager doubled on long trains | **0.5 per sleeper, 0.25 per couchette, 0 per seat coach, 1 catering, one train manager** | Ramboll's operator rule, taken one step leaner |
| Attendant wage | 81.65 €/h (a DB railway employee's wage, plus the cost of relief crews) | **40 €/h** on board | What Newrest — the company that actually staffs Nightjet coaches — offers in its job ads (€2,534–3,400/month incl. supplements), converted to cost per hour on board. Ramboll uses 42 €/h. We assume attendants are rostered for the whole trip with rest periods on board, so no relief crew is costed — one of the things to confirm with ES/RDC |

**8. Financing: interest every year = paying the coach twice.**
That is how the *Ramboll* study counts (6.5% on the full price every year for
30 years, plus writing it off). Ours is milder: write-off over 30 years plus 4%
of the price per year — together 7.3% per year, which is exactly what a normal
6.5% loan repaid over 30 years costs. Nothing changed here; the document now
explains it so it doesn't look like double counting.

## One thing we found ourselves

The Ramboll study's headline "44.51 € per train-km" is for a **14-coach train
of 696 places** (the study text says so on p. 46 and in Table 17; the slide
shows the 7-coach half train that the concept is built from, which is
confusing). Our earlier validation compared a 7-coach train against it and
concluded we were cheaper than Ramboll. Compared correctly, we were 30% above
Ramboll — consistent with what you saw against ES.

## What would settle the remaining 20–30%

Three numbers from ES or RDC, no breakdown needed beyond these:

1. **How many people are on board** a 12–14-coach summer train, whether they
   work the whole trip or are relieved en route, and what an attendant costs
   per month.
2. **What cleaning and laundry cost per train run** (we now carry ~2,500 €
   for 12 coaches).
3. **What ES's coaches cost all-in** per coach-km or per coach-month —
   maintenance and capital together. Ours is now ~1.12 €/coach-km for a
   properly refurbished coach; the KeV says ~1.0 for a depreciated one. ES runs
   lightly refreshed ex-CNL/ÖBB stock only ~200,000 km per coach-year, which
   only adds up if its coaches cost far less than any refit. If you confirm a
   figure near the KeV, we would add a third fleet type ("used, light refit",
   ~€0.65M per coach) rather than squeeze the refurbished one — that gives the
   advocacy case three honest points: cheap today with used stock, better with
   a proper refit, best with new stock.
