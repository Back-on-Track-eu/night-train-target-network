---
title: Known gaps
description: What the model does not yet cover, ordered by how much it affects a result.
---

# Known gaps

Every model is incomplete. This page collects the gaps we know about ordered by severity.

## Demand, and everything downstream

[The demand model is currently a placeholder](/demand): a flat 70% load factor and flat
fares per kilometre. This affects [ticket revenue](/cost/ticket-revenue), the [net result](/cost/net),
subsidy figures, [variable overhead](/cost/var-overhead), and the
revenue-share component of [track access](/cost/tac).

## Station charges outside Germany

[Only Germany's station price list is transcribed](/cost/station-charge).
Seventeen countries fall back to one flat rate per call.

## Shunting movement count

[Fixed at two per trip](/cost/shunting). This affects the shunting line on services with unusual shunting needs.

## The shunting market top-up

[190 or 110 EUR per movement with a ±35% band](/methodology/facility), larger
than many of the published charges it sits on top of.

Affects the shunting line everywhere.

## Peak surcharges and the day of the week

[Charged at five-sevenths of the weekday rate](/methodology/track-access),
because the tool knows a departure's clock time but not its day.

Affects Austrian and Swiss routes running only at weekends or only on
weekdays.

---

If something you would expect is missing from this list, tell us below.

<FeedbackForm />
