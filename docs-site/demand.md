---
title: Demand and revenue
description: Why the revenue side of this model is an assumption you set, not a forecast.
---

# Demand and revenue

## What the model does today

Demand is a **manual input**, not a forecast (DEMAND 0.1.0). You set a
potential demand per year over both directions — four levels give a
starting figure (100 000, 200 000, 300 000, 500 000 passengers), any figure
can be typed — and the model seats it on each train by a fixed rule. How it
works:

- the potential demand splits into **five traveller groups** with a share
  each (leisure – comfort 50 %, leisure – group 25 %, senior leisure 10 %,
  leisure – budget 10 %, business 5 %; editable) and each group books only
  the classes on its list, in order of preference — a comfort traveller
  wants a sleeper, then a capsule, then a couchette; a budget traveller sits
  only in a seat
- **per departure** = per year ÷ departures, so a train that runs three days
  a week carries twice the load of one that runs daily; what no listed class
  can seat is **not served**
- the allocation runs in **four rounds** (50 / 20 / 20 / 10 % of each
  group's demand), the groups in a fixed order, 80 % of each group taking
  its first free listed class and 20 % spreading over its other listed
  classes — expected values, never random draws, so a recalculation
  reproduces the same figures
- sales spread over the **OD pairs** the route sells (a boarding stop before
  an alighting stop) by one weight per stop, filled from a preset (even, long
  journeys, mid distance, short hops) or typed; single pairs can be pinned
- every passenger is attributed by journey length to a **shift from the
  plane** (none under 300 km, a quarter at 300 km, everyone from 1 200 km)
  or to the car and induced travel (half and half) — this is what the CO₂
  saving rests on
- fares are a flat **two-part tariff** per class — a fixed part plus a
  distance part (seat 10 € + 0.06 €/km, couchette 75 € + 0.03, sleeper
  125 € + 0.04, capsule 75 € + 0.03), plus additional services and a net
  catering contribution per passenger — all editable per proposal

Nothing here predicts how many people would actually travel. The figures are
what follows from the demand you set; change it and see what follows. A
model that derives the potential demand from the corridor is the next step.

<FeedbackForm />
