---
title: Price basis — 2032 prices
description: Every cost and fare in the tool is in 2032 money, escalated from its source's price year, except the rolling stock purchase price. How, at which rates, and why the exception.
---

# Price basis: 2032 prices

<!-- Linked from the "2032 prices" sticker on the builder's Details and
     Costs and revenue headlines (frontend/src/lib/docsLinks.ts,
     DOCS_PRICE_BASIS). The page id stays; change the sticker's link only
     together with docsLinks.ts. -->

The network is evaluated for **2032**. Every figure with a euro sign in the
tool — the necessary subsidy, every cost line of the breakdown, the ticket
revenue, the fares under Supply — is therefore **2032 money**: the source's
published price was carried from its own price year to 2032 at a rate set
and documented per cost domain. Comparing a figure here with a tariff or a
cost you know from today's price lists means comparing across six years of
inflation; the "2032 prices" sticker on the headlines is there so that
comparison is never made unknowingly.

The conversion happens exactly once, inside each domain's calibration,
before a value is seeded into the database. No calculation module ever sees
a currency or a price year; the model prices in plain euros of 2032. A
scenario for another year would change the target year in the calibration,
not the model.

## The one exception: rolling stock is bought now {#rolling-stock}

Rolling stock for a 2032 network is contracted in the late 2020s and paid
at the contract price. The [write-off](/cost/coach-amortisation) and
[financing](/cost/financing) of the coaches and locomotives therefore run
off that historical price, and the model keeps the **purchase price at the
2026 contract basis, deliberately not escalated**. Carrying it to 2032 as
well would count the same inflation twice: once in the contract, once in the
model.

Everything else the compositions calibration sets is a recurring rate and
follows the 2032 rule — with two conservative-side exceptions noted below.

## What is escalated, at which rate

| Domain                                | Rate to 2032                                                                                                 | Where it is set                                        |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------ |
| Driver and crew pay, locomotive lease | wage chain (labour) and 2 % a year (lease), from each source's year                                          | [rolling stock calibration](/methodology/compositions) |
| Track access charges                  | 3 % a year — the decade's European trend for passenger charges; Slovakia held flat as a documented deviation | [track access](/methodology/track-access)              |
| Traction electricity                  | 2 % a year                                                                                                   | [traction electricity](/methodology/energy-pricing)    |
| Shunting                              | 2.5 % a year                                                                                                 | [shunting and stabling](/methodology/facility)         |
| Stabling and hotel power              | 2 % a year                                                                                                   | [shunting and stabling](/methodology/facility)         |
| Ticket fares and catering             | stated directly at the 2032 price year                                                                       | [demand and revenue](/demand)                          |

Currency is converted first, at a pinned ECB reference-rate snapshot shared
by the calibrations, then the price year is carried forward; both steps are
recorded per value in the source registers.

## Deliberately not escalated

- **Rolling stock purchase price** — see above.
- **Coach maintenance and cleaning** — set at their observed 2026 level. The
  review showed every real observation below the escalated values, and the
  model's brief is to be optimistic where the evidence allows.
- **Service and stockings** (bed linen, breakfast) — kept at source level for
  the same reason.
- **Station charges** — carried at the year each price list publishes; their
  escalation across all countries is planned but not yet applied, so these
  few euros per call sit a little below 2032 money.

## What this means for a reader

Cost and revenue move together, so the necessary subsidy — a difference —
is less sensitive to the price year than either side alone. The ratios the
tool reports (cost per train-kilometre, revenue per passenger-kilometre,
subsidy per tonne of CO₂e) are all 2032 over 2032 and read as such. Only
when a single line is set against an outside benchmark does the year
matter, and then the benchmark has to be carried to 2032 first — which is
how every benchmark in the calibration documents is shown.
