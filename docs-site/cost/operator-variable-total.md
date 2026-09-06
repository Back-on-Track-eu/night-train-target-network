---
title: 'Variable operator cost'
description: 'The operator costs that scale with how much the train runs.'
---

# Variable operator cost

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

The operator costs that move with how much the train actually runs: hours
on duty, kilometres driven, tickets sold.

Add a stop and these grow. Run the service on fewer nights and they
shrink. They are the costs that respond to the timetable.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-operator_variable_total_eur"></a>

The operator costs that scale with how much the train runs.

### The formula

$$ C_{op,var} = C_{driver} + C_{crew} + C_{coach,maint} + C_{loco} + C_{svc} + C_{var,oh} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `C_driver` | Driver cost | €/year | [driver_eur](/cost/driver) |
| Input | `C_crew` | Cabin crew cost | €/year | [crew_eur](/cost/crew) |
| Input | `C_coach,maint` | Coach maintenance cost | €/year | [coach_maintenance_eur](/cost/coach-maintenance) |
| Input | `C_loco` | Locomotive rental cost | €/year | [loco_eur](/cost/loco) |
| Input | `C_svc` | Onboard service cost | €/year | [svc_stockings_eur](/cost/svc-stockings) |
| Input | `C_var,oh` | Variable overhead | €/year | [var_overhead_eur](/cost/var-overhead) |
| **Result** | `C_op,var` | Total variable operator cost | €/year | — |

**Feeds into:** [operator_total_eur](/cost/operator-total)
<!-- END GENERATED: formula -->

<FeedbackForm />
