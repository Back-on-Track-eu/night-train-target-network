---
title: Coach maintenance
description: Maintaining the coaches, charged per kilometre driven.
---

# Coach maintenance

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-coach_maintenance_eur"></a>

Maintaining the coaches, charged per kilometre driven.

### The formula

$$ C_{coach,maint} = \sum_{seg} c_{coach,maint/km} \times d_{km,seg} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_coach,maint/km` | Maintenance rate for all coaches of the train, per kilometre | €/train-km | [composition_type_coach_maint_eur_km](/reference/parameters#p-input_params-composition_types-composition_type_coach_maint_eur_km) |
| Input | `d_km,seg` | Distance driven | km | computed upstream |
| **Result** | `C_coach,maint` | Annual coach maintenance cost | €/year | — |

**Feeds into:** [operator_variable_total_eur](/cost/operator-variable-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
