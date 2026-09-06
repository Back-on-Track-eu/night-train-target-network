---
title: 'Cleaning'
description: 'Cleaning and preparing the train for each night of service.'
---

# Cleaning

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Cleaning and preparing the train for the next night — a daily rate per
coach, over the operating days in a year.

Charged per coach rather than per train, so a longer train costs
proportionally more to turn around.

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

<FeedbackForm />
