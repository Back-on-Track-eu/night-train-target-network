---
title: "Catering contribution"
description: "What the on-board catering adds up to, net of what it costs to run — positive or negative."
---

# Catering contribution

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

_Not yet written._

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-catering_contribution_eur"></a>

What the on-board catering adds up to, net of what it costs to run — positive or negative.

### The formula

$$ R_{cat} = \sum_{od} n_{places\_sold,od} \times c_{cat} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `n_places_sold,od` | Places sold per connection and year | places/year | set by you |
| Input | `c_cat` | Net catering contribution per passenger of that class, overridable per proposal | €/passenger | [CATERING_EUR_PER_PAX_BY_CLASS](/reference/standard-values#s-demand-catering_eur_per_pax_by_class) |
| **Result** | `R_cat` | Annual net catering contribution | €/year | — |

**Feeds into:** [total_revenue_eur](/cost/total-revenue)
<!-- END GENERATED: formula -->

<FeedbackForm />
