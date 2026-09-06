---
title: 'Variable overhead'
description: 'Ticket sales, distribution and customer service, as a share of ticket revenue.'
---

# Variable overhead

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Selling the tickets: distribution, payment handling, customer service.

Charged as a share of ticket revenue rather than a fixed sum, because
these costs genuinely scale with sales rather than with running the train.
Note the consequence: because it is a share of revenue, and revenue rests
on the [demand assumption](/cost/ticket-revenue), this line inherits that
assumption too.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-var_overhead_eur"></a>

Ticket sales, distribution and customer service, as a share of ticket revenue.

### The formula

$$ C_{var,oh} = \sum_{od} R_{od} \times q_{var,oh} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `R_od` | Ticket revenue per connection and year | €/year | [ticket_revenue_eur](/cost/ticket-revenue) |
| Input | `q_var,oh` | Overhead share of revenue | fraction | [operator_var_overhead_per](/reference/parameters#p-input_params-operators-operator_var_overhead_per) |
| **Result** | `C_var,oh` | Annual variable overhead | €/year | — |

**Feeds into:** [fix_overhead_eur](/cost/fix-overhead), [operator_variable_total_eur](/cost/operator-variable-total)
<!-- END GENERATED: formula -->

<FeedbackForm />
