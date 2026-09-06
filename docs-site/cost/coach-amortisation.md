---
title: 'Coach write-off'
description: "The coaches' annual write-off: purchase price spread over their useful life."
---

# Coach write-off

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

The annual write-off of the coaches — their purchase price spread over the
years they will be in service.

The count includes a reserve: some coaches are always in the workshop, so
a service needs more of them than it puts on the rails on any given night.
Prices come from the composition cost calibration, which builds a
per-metre purchase cost for new and refurbished vehicles at 2032 prices.

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

<FeedbackForm />
