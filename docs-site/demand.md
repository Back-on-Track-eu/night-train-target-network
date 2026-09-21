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
  or to the car and induced travel (half and half) — this is what the CO₂e
  saving rests on
- fares are a flat **two-part tariff** per class — a fixed part plus a
  distance part (seat 10 € + 0.06 €/km, couchette 75 € + 0.03, sleeper
  125 € + 0.04, capsule 75 € + 0.03), plus additional services and a net
  catering contribution per passenger — all editable per proposal

Nothing here predicts how many people would actually travel. The figures are
what follows from the demand you set; change it and see what follows. A
model that derives the potential demand from the corridor is the next step.

## The Details card, panel by panel

<!-- The anchors below are linked from the ⓘ overlays of the Details card
     (frontend/src/lib/docsLinks.ts, DOCS_DETAIL_PANEL). Change an id only
     together with docsLinks.ts. -->

### Schedule {#schedule}

How often the train runs, as an average over the year — one figure, no
seasons. Operating days are 366 (2032 is a leap year) times days per week
over seven; departures are operating days times two directions; train-km
and place-km follow from the route length and the formation. Trainsets are
the rakes the cycle needs at this frequency: a train that runs seven days a
week and takes two days to come back needs two. Which weekday the train
runs is not modelled.

### Places and prices {#prices}

What the train offers and what it charges. The tariff is three parts, each
per class. The **base fare** has a fixed term and a distance term — a berth
has a price of admission a short journey pays as surely as a long one, so
pricing on distance alone made short connections implausibly cheap.
**Additional services** is the revenue from bicycles, oversized luggage and
reservations sold with the ticket; it is ordinary ticket revenue, never
negative, and it carries overhead and the profit requirement like any other
fare. **Catering** is the odd one: one signed net figure per passenger, the
restaurant's own sales less its own costs, and therefore outside those two
bases. It differs by class because the classes differ in what their base
fare already includes. The two example columns price the berth only — fixed
plus distance — over the longest and shortest journey the route sells. How
many of these places actually sell is set under Demand. Fares have no
influence on demand in this model.

**VAT.** The fares are net; under each example fare the panel shows what the
passenger pays with VAT. Passenger transport is taxed where it takes place,
in proportion to the distance run in each country, and most countries exempt
the domestic leg of an international rail ticket while taxing a domestic
one — Germany (7 %), the Netherlands (9 %), Belgium (6 %), Spain (10 %),
Croatia (25 %) and Austria (10 %) tax their section of an international
ticket, the rest of Europe does not. A route's rate is therefore the sum
over its countries of distance share × that country's rate, with the
international rate whenever the route crosses a border. Hovering the rate
shows the per-country make-up. VAT enters no cost, revenue or subsidy figure:
the model prices net. Rates and sources:
`backend/models/demand/calib/vat/VAT_CALIBRATION.md`.

### Potential demand {#potential-demand}

Passengers per year, both directions, who would take this route. Four
levels give a starting figure; any figure can be typed, which makes the
level custom. The chosen level is saved with the proposal. The frequency
under Supply › Schedule turns the year into a load per departure: fewer
departures fill each train fuller, and what a train cannot seat is not
served.

### Traveller groups {#traveller-groups}

How the total splits into traveller groups, and which classes each group
books, in order. The allocation runs four rounds — every group in order
(Leisure – comfort, Leisure – group, Senior leisure, Leisure – budget,
Business) releases 50, then 20, 20 and 10 % of its demand; 80 % of that
seats along the preference list, first class until full, then the next,
and 20 % spread evenly over the group's other listed classes. A group sits
only in the classes it lists; what none of them can seat is not served.
Expected values, never random draws, so a recalculation reproduces the same
figures.

### Origin–destination matrix {#od-matrix}

The share of the demand each sellable OD pair gets — a boarding stop before
an alighting stop. The matrix is filled from one thing: a weight per stop in
the margins — a pair's share is its boarding weight times its alighting
weight. The presets write those weights by position along the route (long
journeys: early boarding, late alighting; short hops the reverse; mid: the
middle stops); any weight can be typed over, a big city pulling more. Any
cell can then be typed over: it is pinned and the rest rescales so the total
stays 100 %. A place is sold once per night, so the distribution moves
place-km and revenue, not passengers. One matrix for all classes.

### Utilisation by composition {#utilisation}

The same demand allocated to every composition of the family, so one demand
reads as a utilisation on each train. Fill is the places served, the
percentage its utilisation, the number after the bar the composition's
places; the faint dashed line below a bar is demand no listed class could
seat. Per trip is one departure, one direction; a month is a twelfth of the
year.

### What follows {#what-follows}

What the schedule and the prices earn with the committed demand:
passengers, place-km sold, utilisation and revenue per year, both
directions. Ticket revenue and the catering contribution are earned in
different ways and one of them can be negative, so they stay apart. A muted
line under the ticket revenue gives the same figure with VAT, what the
passengers pay in all; it stays outside the total and the cost and revenue
calculation.
Schedule and price edits preview in the panel; a demand edit does not — the
panel waits for the recalculation, so it never mixes a previewed demand with
a calculated one.

<FeedbackForm />
