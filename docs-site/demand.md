---
title: Revenue and demand
description: Why the revenue side of this model is an assumption you set, not a forecast.
---

# Revenue and demand

This is the weakest part of the model, and the page we would most like to
be able to rewrite.

## What the model currently does

The demand model is version `0.0.2` and is described in its own source
code as a placeholder. It does two things:

- assumes a **flat 70% load factor** — 70% of the places offered are sold,
  on every route, every night
- applies **flat fares per kilometre** by accommodation class: roughly
  0.10 €/km for a seat, 0.13 for a couchette, 0.18 for a sleeper, 0.12 for
  a capsule

That is the whole of it. It does not model who would travel, between which
cities, at what price, at what time of year, or how many would switch from
flying or driving. A Berlin–Paris service and a route between two towns
nobody wants to connect receive the same 70%.

## What that means for the numbers

Everything on the revenue side inherits it:

- [ticket revenue](/cost/ticket-revenue) is places sold × fare, and both
  are assumptions
- the [net result](/cost/net) is revenue minus cost, so it inherits the
  assumption entirely
- any **"necessary subsidy"** figure is the net result with its sign
  flipped, and inherits it too
- even one cost line is affected: [variable overhead](/cost/var-overhead)
  is charged as a share of ticket revenue, and the
  [track access charge](/cost/tac) includes a revenue share in some
  countries

So the honest reading of a result from this tool is: _given that this
train ran 70% full at these fares, here is what it would cost and here is
the gap._ The first clause is yours to set. Only the cost side is ours to
defend.

## Why publish it at all, then

Because the cost side stands up on its own. What a night train costs to
run is a genuinely useful and genuinely hard number, and it is calibrated
against real tariffs and measured energy. Withholding it until demand is
solved would withhold the part that works.

And because the alternative — presenting a forecast we do not have — would
be worse. A 70% load factor stated plainly is an assumption a reader can
argue with. The same number presented as a prediction would not be.

## What a real demand model would need

The intended replacement is a mode-shift model of the kind used in French
open-source night train work: a log-additive formulation in which the
share of travellers choosing the night train over flying or driving
depends on journey time, price, departure and arrival times, comfort
class, and the quality of the alternatives on that specific city pair.

That needs origin–destination travel data at city-pair level, current
prices and journey times for the competing modes, and calibration against
observed night train ridership. The data exists; the work has not been
done.

Until it is, treat the revenue side as a scenario dial, and read
[how to read our numbers](/reading-the-numbers) before quoting anything
derived from it.

<FeedbackForm />
