---
title: Traction electricity calibration
description: What the power costs, and what the infrastructure manager charges to deliver it.
---

# Traction electricity calibration

Two separate charges make up the [electricity line](/cost/energy):

## The two components

**The energy itself**, a price per kilowatt-hour set by each country's
traction electricity supply arrangement. Where a country operates a night
tariff band, both the day and night rates were collected.

**The delivery**, what the infrastructure manager charges for supplying power
through the overhead line, typically a separate per-kilometre or
per-kilowatt-hour term in the network statement.

## Provenance

**Thirty-five values read from a named locator.** As with track access, these
come from published network statements and supply tariffs rather than from
estimates.

The documents are listed under
[traction electricity](/sources/#traction-electricity): nineteen national
network statements and supply tariffs, plus Eurostat's non-household
electricity price series, CE Delft's European transport taxes database and
the UK fuel price tables, which fill in where no rail-specific price is
published.

## Night bands

Only Austria, Switzerland and Croatia operate a traction electricity night
tariff. Everywhere else there is one rate around the clock, and the night/day
split the model computes has no effect. Where a band exists, the share of the country run falling inside it is
applied to the kilowatt-hours drawn.

## Price basis

Escalated to the 2032 evaluation year at 2% a year, with currency converted
once at the pinned snapshot.

<FeedbackForm />
