---
title: 'Net result'
description: 'Revenue minus costs minus profit requirement; if negative, the subsidy the route needs.'
---

# Net result

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Revenue minus every cost minus the operator's profit requirement.

When it is negative, the magnitude is
the annual subsidy the route would need at the fares and load factor you set.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-net_eur"></a>

Revenue minus costs minus profit requirement; if negative, the subsidy the route needs.

### The formula

$$ N = R_{total} - C_{total} - C_{EBIT} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `R_total` | Total annual revenue | €/year | [total_revenue_eur](/cost/total-revenue) |
| Input | `C_total` | Total annual cost | €/year | [total_cost_eur](/cost/total-cost) |
| Input | `C_EBIT` | The operator's profit requirement | €/year | [ebit_margin_eur](/cost/ebit-margin) |
| **Result** | `N` | Net annual result | €/year | — |
<!-- END GENERATED: formula -->

<FeedbackForm />
