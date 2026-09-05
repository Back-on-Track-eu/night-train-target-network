---
title: Coach write-off
description: The coaches' annual write-off: purchase price spread over their useful life.
---

# Coach write-off

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-coach_amortisation_eur"></a>

The coaches' annual write-off: purchase price spread over their useful life.

### The formula

$$ C_{coach,amort} = \frac{C_{coach,purchase}}{T_{coach,amort}} \times n $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `C_coach,purchase` | Purchase price per coach | €/coach | [composition_type_purchase_coach_eur](/reference/parameters#p-input_params-composition_types-composition_type_purchase_coach_eur) |
| Input | `T_coach,amort` | Useful life over which the coach is written off | years | [composition_type_coach_amort_years](/reference/parameters#p-input_params-composition_types-composition_type_coach_amort_years) |
| Input | `n` | Coaches needed for the service, incl. reserve | coaches | computed upstream |
| **Result** | `C_coach,amort` | Annual coach write-off | €/year | — |

**Feeds into:** [operator_fixed_total_eur](/cost/operator-fixed-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
