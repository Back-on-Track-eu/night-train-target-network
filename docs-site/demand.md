---
title: Demand and revenue
description: Why the revenue side of this model is an assumption you set, not a forecast.
---

# Demand and revenue

This is the weakest part of the model and the page we would most like to
replace.

## What the model does today

The demand model is version `0.0.2` and described in its own source code as a
placeholder. It does two things:

- assumes a **flat 70% load factor**, so 70% of the places offered are sold,
  on every route, every night
- applies **flat fares per kilometre** by accommodation class: roughly
  0.10 €/km for a seat, 0.13 for a couchette, 0.18 for a sleeper, 0.12 for a
  capsule

That is all of it. It does not model who would travel, between which cities,
at what price, at what time of year, or how many would switch from flying or
driving. A Berlin to Paris service and a route between two towns nobody wants
to connect both receive 70%.

## What that means for the numbers

Everything on the revenue side inherits the assumption:

- [ticket revenue](/cost/ticket-revenue) is places sold times fare, and both
  are set rather than predicted
- the [net result](/cost/net) is revenue minus cost, so it inherits the
  assumption entirely
- any subsidy requirement is the net result with its sign flipped
- one cost line is affected too: [variable overhead](/cost/var-overhead) is
  charged as a share of ticket revenue, and the
  [track access charge](/cost/tac) includes a revenue share in some countries

So the honest reading of a result is: given that this train ran 70% full at
these fares, here is what it would cost and here is the gap. The first clause
is yours to set. Only the cost side is ours to defend.

## Why publish it

Because the cost side stands on its own. What a night train costs to run is a
useful and genuinely hard number, calibrated against real tariffs and
measured energy, and withholding it until demand is solved would withhold the
part that works.

And because a 70% load factor stated openly is an assumption a reader can
argue with. The same number presented as a forecast would not be.

## What a real demand model needs

The intended replacement is a mode-shift model of the kind used in French
open-source night train work: a log-additive formulation in which the share
of travellers choosing the night train over flying or driving depends on
journey time, price, departure and arrival times, comfort class, and the
quality of the alternatives on that specific city pair.

That needs origin-destination travel data at city-pair level, current prices
and journey times for the competing modes, and calibration against observed
night train ridership. The data exists; the work has not been done.

Until then, treat the revenue side as a scenario dial, and see
[known gaps](/not-modelled) for what else rests on it.

<FeedbackForm />
