---
title: 'Ticket revenue'
description: 'Ticket income from places sold and average fare, both set by you rather than predicted.'
---

# Ticket revenue

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Places sold times the average fare.

Both are inputs rather than predictions. The demand model in this tool is a
placeholder: a flat load factor of 70% and flat fares per kilometre by
accommodation class. It does not model who would travel, between which
cities, at what price, or how many would switch from flying or driving. It
applies the same assumption to a Berlin to Paris service and to a route
nobody would ride.

A revenue figure here answers what the train would earn if it ran that full
at those fares. It does not answer whether it would.

That matters most for the numbers people quote. The net result and any
subsidy requirement are revenue minus costs, so they inherit this assumption
completely. The cost side stands on its own evidence; the gap between cost
and revenue does not.

A real demand model is the most valuable addition this tool could take. What
it would need is set out under [known gaps](/not-modelled).

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-ticket_revenue_eur"></a>

Ticket income from places sold and average fare — both set by you, not predicted.

### The formula

$$ R = \sum_{od} n_{places\_sold,od} \times \bar{f}_{od} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `n_places_sold,od` | Places sold per connection and year | places/year | set by you |
| Input | `f̄_od` | Average ticket price on the connection | €/ticket | set by you |
| **Result** | `R` | Annual ticket revenue | €/year | — |

**Feeds into:** [ebit_margin_eur](/cost/ebit-margin), [total_revenue_eur](/cost/total-revenue), [var_overhead_eur](/cost/var-overhead)
<!-- END GENERATED: formula -->

<FeedbackForm />
