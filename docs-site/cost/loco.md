---
title: 'Locomotive rental'
description: 'Renting the locomotive by the hour, maintenance and insurance included.'
---

# Locomotive rental

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Renting the locomotive, charged by the hour with maintenance and
insurance included.

Hours in use, not hours owned: a locomotive shared between several trips
is counted once. That matters for a network of routes that can share
traction rather than each holding its own.

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

<FeedbackForm />
