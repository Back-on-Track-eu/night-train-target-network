---
title: How traction electricity was priced
description: What the power costs, and what the infrastructure manager charges to deliver it.
---

# How traction electricity was priced

Two separate charges make up the [electricity line](/cost/energy), and
they come from different places.

## The two components

**The energy itself** — a price per kilowatt-hour, set by each country's
traction electricity supply arrangement. Where a country operates a night
tariff band, both the day and night rates were collected.

**The delivery** — what the infrastructure manager charges for supplying
power through the overhead line, typically a separate per-kilometre or
per-kilowatt-hour term in the network statement. This is a real charge
distinct from the energy, and omitting it would understate the cost.

## Provenance

**Thirty-five values read from a named locator.** As with track access,
these come from published network statements and supply tariffs rather
than from estimates.

## Night bands

Only **Austria, Switzerland and Croatia** operate a traction electricity
night tariff. Everywhere else there is one rate around the clock, and the
night/day split the model computes has no effect.

Where a band exists, the share of the country run falling inside it is
applied to the kilowatt-hours drawn, rather than the whole leg being
priced one way based on when it started. A train crossing into the band
mid-country is billed as it actually runs.

**Croatia's band is assumed** at 22:00–06:00 — the tariff document does
not state it explicitly, and the neighbouring convention was adopted. It
is recorded as an assumption.

## Price basis

Escalated to the 2032 evaluation year at 2% a year, with currency
converted once at the pinned snapshot. Electricity prices are volatile and
this is a long extrapolation — a 2032 traction electricity price is a
projection, and treating it as a known quantity would be a mistake.

<FeedbackForm />
