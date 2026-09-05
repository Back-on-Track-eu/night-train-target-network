---
title: Variable operator cost
description: The operator costs that scale with how much the train runs.
---

# Variable operator cost

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

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
