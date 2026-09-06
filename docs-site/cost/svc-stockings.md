---
title: 'Onboard service'
description: 'Bedding, breakfast and amenities, charged per ticket sold.'
---

# Onboard service

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Bedding, breakfast, and the amenities that make a night train a night
train — charged per passenger, at a rate that differs by accommodation
class.

A sleeper passenger costs more to serve than a seated one, which is part
of why the classes are priced differently.

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

<FeedbackForm />
