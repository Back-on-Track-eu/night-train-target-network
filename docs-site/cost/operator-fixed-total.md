---
title: Fixed operator cost
description: The operator costs that stay the same however much the train runs.
---

# Fixed operator cost

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-operator_fixed_total_eur"></a>

The operator costs that stay the same however much the train runs.

### The formula

$$ C_{op,fix} = C_{coach,amort} + C_{fin} + C_{fix,oh} + C_{clean} + C_{shunt} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `C_coach,amort` | Coach write-off | €/year | [coach_amortisation_eur](/cost/coach-amortisation) |
| Input | `C_fin` | Financing cost | €/year | [financing_eur](/cost/financing) |
| Input | `C_fix,oh` | Fixed overhead | €/year | [fix_overhead_eur](/cost/fix-overhead) |
| Input | `C_clean` | Cleaning cost | €/year | [cleaning_eur](/cost/cleaning) |
| Input | `C_shunt` | Shunting cost | €/year | [shunting_eur](/cost/shunting) |
| **Result** | `C_op,fix` | Total fixed operator cost | €/year | — |

**Feeds into:** [operator_total_eur](/cost/operator-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
