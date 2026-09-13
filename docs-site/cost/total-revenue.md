---
title: 'Total revenue'
description: "The route's total annual revenue; ticket income is currently the only source."
---

# Total revenue

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

What the service would take in over a year through ticket sales.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-total_revenue_eur"></a>

The route's total annual revenue: the base fares, the extras sold with them, and what the catering nets.

### The formula

$$ R_{total} = R_{ticket} + R_{svc} + R_{cat} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `R_ticket` | Annual ticket revenue | €/year | [ticket_revenue_eur](/cost/ticket-revenue) |
| Input | `R_svc` | Annual additional-services revenue | €/year | [services_revenue_eur](/cost/services-revenue) |
| Input | `R_cat` | Annual net catering contribution, signed | €/year | [catering_contribution_eur](/cost/catering-contribution) |
| **Result** | `R_total` | Total annual revenue | €/year | — |

**Feeds into:** [net_eur](/cost/net)
<!-- END GENERATED: formula -->

<FeedbackForm />
