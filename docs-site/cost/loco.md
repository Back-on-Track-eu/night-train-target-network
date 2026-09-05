---
title: "Locomotive rental"
description: "Renting the locomotive by the hour, maintenance and insurance included."
---

# Locomotive rental

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-loco_eur"></a>

Renting the locomotive by the hour, maintenance and insurance included.

### The formula

$$ C_{loco} = c_{loco,lease/h} \times \frac{t_{loco,propulsion,min}}{60} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_loco,lease/h` | All-inclusive locomotive rental rate per hour in use | €/h | [operator_loco_lease_eur_h](/reference/parameters#p-input_params-operator_loco_costs-operator_loco_lease_eur_h) |
| Input | `t_loco,propulsion,min` | Minutes the locomotive is in use | min | computed upstream |
| **Result** | `C_loco` | Annual locomotive rental cost | €/year | — |

**Feeds into:** [operator_variable_total_eur](/cost/operator-variable-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
