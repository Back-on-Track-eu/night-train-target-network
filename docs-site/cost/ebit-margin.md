---
title: 'Profit requirement (margin)'
description: "The operator's profit requirement: deducted in the net result, not paid to anyone."
---

# Profit requirement (margin)

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

The operator's profit requirement: a share of ticket revenue that has to
remain as operating profit.

This is **not a cost paid to anyone**. Nobody sends an invoice for it. It
is the return an operator would need for the service to be worth running,
and it is deducted in the net result alongside the real costs — which is
why it sits as a peer of the operator and infrastructure totals rather
than inside either.

A state-owned operator run at cost and a commercial one seeking a return
differ here. Setting it to zero asks a different question: what would this
route cost to run, rather than what would it take to attract an operator.

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

<FeedbackForm />
