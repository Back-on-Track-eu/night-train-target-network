---
title: Onboard service
description: Bedding, breakfast and amenities, charged per ticket sold.
---

# Onboard service

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-svc_stockings_eur"></a>

Bedding, breakfast and amenities, charged per ticket sold.

### The formula

$$ C_{svc} = \sum_{od} c_{svc,class(od)/place} \times n_{places\_sold,od} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_svc,class/place` | Service cost per sold place, by class | €/place | [operator_class_svc_stockings_eur_place](/reference/parameters#p-input_params-operator_class_costs-operator_class_svc_stockings_eur_place) |
| Input | `n_places_sold,od` | Places sold per connection and year | places/year | set by you |
| **Result** | `C_svc` | Annual onboard service cost | €/year | — |

**Feeds into:** [operator_variable_total_eur](/cost/operator-variable-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
