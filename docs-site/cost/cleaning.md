---
title: Cleaning
description: Cleaning and preparing the train for each night of service.
---

# Cleaning

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-cleaning_eur"></a>

Cleaning and preparing the train for each night of service.

### The formula

$$ C_{clean} = c_{clean/day} \times n \times d_{op} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_clean/day` | Cleaning and preparation rate per coach and day | €/coach/day | [composition_type_cleaning_eur_day](/reference/parameters#p-input_params-composition_types-composition_type_cleaning_eur_day) |
| Input | `n` | Coaches needed for the service | coaches | computed upstream |
| Input | `d_op` | Operating days per year | days/year | computed upstream |
| **Result** | `C_clean` | Annual cleaning cost | €/year | — |

**Feeds into:** [operator_fixed_total_eur](/cost/operator-fixed-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
