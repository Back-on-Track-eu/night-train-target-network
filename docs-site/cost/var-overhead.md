---
title: Variable overhead
description: Ticket sales, distribution and customer service, as a share of ticket revenue.
---

# Variable overhead

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

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
