---
title: 'Ticket revenue'
description: 'Ticket income from places sold and average fare — both set by you, not predicted.'
---

# Ticket revenue

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Places sold times the average fare.

**Both of those are inputs, not predictions.** The demand model in this
tool is a placeholder: a flat load factor of 70% and flat fares per
kilometre by accommodation class. It does not model who would travel,
between which cities, at what price, or how many would switch from flying
or driving. It applies the same assumption to a Berlin–Paris service and a
route nobody would ride.

So a revenue figure here answers: _if this train ran that full, at those
fares, this is what it would earn._ It does not answer whether it would.

This matters most for the numbers people quote. The net result and any
"necessary subsidy" figure are revenue minus costs — so they inherit this
assumption completely. The cost side stands on its own evidence; the gap
between cost and revenue does not.

A real demand model is the single most valuable thing that could be added
to this tool. What it would need to look like is set out in
[what we don't yet model](/not-modelled).

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
