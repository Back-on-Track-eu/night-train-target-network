---
title: How track access was calibrated
description: Thirty network statements, twenty-eight countries, and what each charge is founded on.
---

# How track access was calibrated

[Track access](/cost/tac) is usually the largest infrastructure cost on a
cross-border night train, and it is the best-sourced part of this model.

## Provenance at a glance

Across twenty-eight countries: **35 values read from a named locator**
in a published document, **10 derived** by documented arithmetic from
sourced values, **1 assumed** with a stated band — drawn from **30 cited
network statements and price lists**.

That is the strongest ratio of any domain in the model. When a track
access figure here is wrong, it is far more likely to be wrong because a
tariff changed than because nobody looked it up.

## What was collected

Every European infrastructure manager must publish a network statement
setting out its charges. For each country the calibration extracts the
terms a passenger night train would actually pay:

- a rate per train-kilometre, and a separate night rate where one exists
- a rate per tonne of train weight and kilometre
- in some countries, a rate per seat and kilometre
- a flat administrative addition per train-kilometre
- a fee per stop made
- a share of the ticket revenue earned in that country
- a congestion or peak surcharge, and the multiplier it applies

A country that does not levy one of these has no such term. It is recorded
as _not levied_ rather than as zero, because the two mean different things
to anyone reading the data.

## Where judgement entered

Two kinds of gap needed a decision rather than a lookup.

**Line categories.** Several countries price by line category — a
mainline costs more than a branch. Mapping a routed path onto an
infrastructure manager's own category list is not reliably possible from
open data, so where charges depend on category the calibration makes a
**conservative fixed assumption**: main international corridors are
assumed to be in the higher-priced categories. Conservative here means _do
not understate the charge_. Portugal's Norte and Sul mainlines are
assumed category A on this basis, and it is recorded per country.

**Peak surcharges and the day of the week.** Austria and Switzerland
charge extra for running through congested areas at commuter peak, on
weekdays only. The tool knows a departure's clock time but not which day
of the week it runs. Rather than pretend the surcharge always applies or
never does, the model charges it at its **expected value** — five-sevenths
of the weekday rate. A route running Saturdays only is therefore slightly
overcharged here, and one running weekdays only slightly undercharged.

## Money, once

Network statements are published in local currency and in different price
years. Both conversions happen once, inside the calibration: currency at a
pinned exchange-rate snapshot, then escalation to the 2032 evaluation year
at 3% a year for track access. Everything downstream is plain euros.

## What would change these numbers

New network statements, mostly. Tariffs are revised annually and this
calibration is a snapshot. A figure that is right today will drift, which
is why every model version is dated and
[what changed](/reference/changelog) records when values moved.

<FeedbackForm />
