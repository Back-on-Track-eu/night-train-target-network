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
