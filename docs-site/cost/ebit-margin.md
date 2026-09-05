---
title: "Profit requirement (margin)"
description: "The operator's profit requirement: deducted in the net result, not paid to anyone."
---

# Profit requirement (margin)

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-ebit_margin_eur"></a>

The operator's profit requirement: deducted in the net result, not paid to anyone.

### The formula

$$ C_{EBIT} = \sum_{od} R_{od} \times q_{EBIT} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `R_od` | Ticket revenue per connection and year | €/year | [ticket_revenue_eur](/cost/ticket-revenue) |
| Input | `q_EBIT` | Required operating profit as a share of revenue | fraction | [operator_ebit_margin_per](/reference/parameters#p-input_params-operators-operator_ebit_margin_per) |
| **Result** | `C_EBIT` | Annual profit requirement | €/year | — |

**Feeds into:** [net_eur](/cost/net)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
