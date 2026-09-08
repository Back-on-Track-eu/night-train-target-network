---
title: What we don't yet model
description: The known gaps, in one place, ordered by how much they affect a result.
---

# What we don't yet model

Every model is incomplete. This page collects the gaps we know about, so
you do not have to find them by reading the other pages. They are roughly
ordered by how much they affect a number you might quote.

## Demand, and everything downstream of it

[The demand model is a placeholder](/demand): a flat 70% load factor and
flat fares per kilometre. It does not model who would travel, where, or at
what price.

Affects: [ticket revenue](/cost/ticket-revenue), the
[net result](/cost/net), any subsidy figure,
[variable overhead](/cost/var-overhead), and the revenue-share component
of [track access](/cost/tac). This is the largest single gap in the model.

## Station charges outside Germany

[Only Germany's station price list is transcribed](/cost/station-charge).
Seventeen countries fall back to one flat rate per call.

Affects: the station charge line on any route stopping outside Germany.
The tariffs are public — this is transcription work, not research.

## The scenario axis does nothing yet

[The 2026 and 2032 infrastructure scenarios are identical](/scenarios) in
the database. Selecting 2032 does not change your result.

Affects: any comparison you were hoping to make between today's network
and the upgraded one.

## Mode-shift shares for emissions

[Air 35% and car 20%](/emissions) are the same on every route, and are not
derived from data. The emission factors themselves are sourced; what
passengers would otherwise have done is not.

Affects: the CO2 saving figure, roughly proportionally.

## Shunting movement count

[Fixed at two per trip](/cost/shunting), rather than derived from whether
the service splits portions or reverses.

Affects: the shunting line on services with unusual shunting needs.

## Terrain and timetable buffers

[No value in this domain is sourced](/methodology/route-context): 131 of
them are assumed with bands, the rest derived or taken from a pan-European
statistic.

Affects: journey times, and therefore every time-based cost — drivers,
crew, locomotive hire.

## The shunting market top-up

[190/110 EUR per movement with a ±35% band](/methodology/facility), larger
than many of the published charges it sits on top of.

Affects: the shunting line everywhere.

## Locomotive mass

[Assumed at 90 tonnes with no source](/methodology/compositions).

Affects: per-tonne-kilometre track access terms and the start-stop term of
the energy model. Bounded — real machines are 80–90 t — but a judgement.

## Coach hotel power

[An assumption, not a measurement](/methodology/energy): the calibration
runs were queried with it switched off.

Affects: energy consumption over a whole night, where the load runs
continuously.

## Peak surcharges and the day of the week

[Charged at five-sevenths of the weekday rate](/methodology/track-access),
because the tool knows a departure's clock time but not its day.

Affects: Austrian and Swiss routes running only at weekends or only on
weekdays.

## Capacity and slot availability

The tool plans a technically coherent route. It does not check whether a
path is available at the time requested, whether the capacity exists, or
whether an infrastructure manager would grant the slot.

Affects: whether a proposal could actually be run, which is a different
question from what it would cost.

## Emissions from actual energy use

The [energy model](/methodology/energy) computes real per-country
electricity consumption. The [emissions figure](/emissions) does not use
it — it applies an EU-average rail factor instead. Connecting the two,
with per-country grid intensities, is an obvious improvement.

---

If something is missing from this list that you think should be on it,
that is worth telling us.

<FeedbackForm />
