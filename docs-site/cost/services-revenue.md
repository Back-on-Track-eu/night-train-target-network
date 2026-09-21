---
title: "Additional services"
description: "What passengers pay for bicycles, oversized luggage and reservations alongside the ticket."
---

# Additional services

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

_Not yet written._

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-services_revenue_eur"></a>

What passengers pay for bicycles, oversized luggage and reservations alongside the ticket.

### The formula

$$ R_{svc} = \sum_{od} n_{places\_sold,od} \times s_{class} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `n_places_sold,od` | Places sold per connection and year | places/year | set by you |
| Input | `s_class` | Additional-services revenue per passenger of that class, overridable per proposal | €/passenger | [SERVICES_EUR_PER_PAX_BY_CLASS](/reference/standard-values#s-demand-services_eur_per_pax_by_class) |
| **Result** | `R_svc` | Annual additional-services revenue | €/year | — |

**Feeds into:** [total_revenue_eur](/cost/total-revenue)
<!-- END GENERATED: formula -->

<FeedbackForm />
