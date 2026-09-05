---
title: Financing
description: The annual cost of financing the coaches.
---

# Financing

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-financing_eur"></a>

The annual cost of financing the coaches.

### The formula

$$ C_{fin} = C_{coach,purchase} \times q_{fin} \times n $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `C_coach,purchase` | Purchase price per coach | €/coach | [composition_type_purchase_coach_eur](/reference/parameters#p-input_params-composition_types-composition_type_purchase_coach_eur) |
| Input | `q_fin` | Annual financing rate on the purchase price | fraction/year | [operator_financing_quota_per](/reference/parameters#p-input_params-operators-operator_financing_quota_per) |
| Input | `n` | Coaches needed for the service, incl. reserve | coaches | computed upstream |
| **Result** | `C_fin` | Annual financing cost | €/year | — |

**Feeds into:** [operator_fixed_total_eur](/cost/operator-fixed-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
