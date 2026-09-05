---
title: Driver cost
description: What the drivers cost per year, including the relief driver a long trip needs.
---

# Driver cost

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-driver_eur"></a>

What the drivers cost per year, including the relief driver a long trip needs.

### The formula

$$ C_{driver} = \frac{c_{driver/h}}{\eta_{driver}} \times \left( \sum_{seg} t_{drive,h} \cdot f_{driver} + \sum_{stop} t_{dwell,h} \cdot f_{driver} \right) $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_driver/h` | Driver wage per productive hour | €/h | [operator_driver_costs_eur_h](/reference/parameters#p-input_params-operators-operator_driver_costs_eur_h) |
| Input | `eta_driver` | Share of paid driver hours that is productive | – | [roster_efficiency_driver](/reference/formulas#f-calc-roster_efficiency_driver) |
| Input | `t_drive,h` | Driving time between stops | h | computed upstream |
| Input | `t_dwell,h` | Waiting time at stops | h | [dwell_time_both](/reference/formulas#f-route-dwell_time_both) |
| Input | `f_driver` | Number of drivers the train needs | persons | [composition_type_driver_factor](/reference/parameters#p-input_params-composition_types-composition_type_driver_factor) |
| **Result** | `C_driver` | Annual driver cost | €/year | — |

**Feeds into:** [operator_variable_total_eur](/cost/operator-variable-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
