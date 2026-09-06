---
title: 'Driver cost'
description: 'What the drivers cost per year, including the relief driver a long trip needs.'
---

# Driver cost

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

What the drivers cost over a year.

The subtlety is that paid hours exceed hours on the train. A driver signs
on before departure, signs off after arrival, travels to and from the
train, rests away from home base, and has to be covered by a reserve. The
model prices this through a roster efficiency: the share of paid hours
that is actually productive.

That share is not constant. A shift may not exceed a legal maximum, so a
long trip has to be split, and every additional shift boundary adds
another fixed allowance. A route just over the limit therefore costs
noticeably more per hour than one just under — which is a real effect, not
an artefact.

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

<FeedbackForm />
