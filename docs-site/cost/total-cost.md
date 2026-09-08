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

This is the number this tool is built to estimate, and the half of the
model with real evidence behind it. Each line below is computed from a
documented formula over parameters read from national network statements,
published tariffs and measured technical runs — not from a single
top-down figure per kilometre.

What it is **not** is a price. Nothing here says what a ticket would cost,
or whether the route would pay for itself. That comparison needs the
[revenue side](/cost/total-revenue), which rests on an assumption you set
rather than a forecast — see [how to read our numbers](/reading-the-numbers).

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
