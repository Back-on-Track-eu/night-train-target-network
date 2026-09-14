---
title: 'Total cost'
description: "The route's total annual cost: operator plus infrastructure."
---

# Total cost

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Everything running the route costs in a year: what the operator spends on
staff, rolling stock and service, plus what it pays the infrastructure
companies for track, electricity, stations and parking.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-total_cost_eur"></a>

The route's total annual cost: operator plus infrastructure.

### The formula

$$ C_{total} = C_{operator} + C_{infrastructure} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `C_operator` | All operator costs, fixed and variable | €/year | [operator_total_eur](/cost/operator-total) |
| Input | `C_infrastructure` | All charges paid to infrastructure companies | €/year | [infrastructure_total_eur](/cost/infrastructure-total) |
| **Result** | `C_total` | Total annual cost | €/year | — |

**Feeds into:** [net_eur](/cost/net)
<!-- END GENERATED: formula -->

<FeedbackForm />
