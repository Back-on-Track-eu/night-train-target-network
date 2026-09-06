---
title: 'Fixed operator cost'
description: 'The operator costs that stay the same however much the train runs.'
---

# Fixed operator cost

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

The operator costs that stay put however much the train runs — the
coaches have to be bought, financed and cleaned whether they are moving or
standing.

"Fixed" here means fixed with respect to the timetable, not fixed forever.
A longer train needs more coaches, so these still scale with the size of
the service; they just do not scale with how far it goes.

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

<FeedbackForm />
