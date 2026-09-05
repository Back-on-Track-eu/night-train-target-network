---
title: "Overnight parking"
description: "Parking the train at each end of the route between two nights of service."
---

# Overnight parking

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-parking_eur"></a>

Parking the train at each end of the route between two nights of service.

### The formula

$$ C_{park} = \sum_{l \in \text{endpoints}} p_{park,country(l)} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `p_park,country(l)` | Daily parking rate in the end point's country | €/day | [track_parking_eur_day](/reference/parameters#p-input_params-track_infrastructures-track_parking_eur_day) |
| **Result** | `C_park` | Annual overnight parking cost | €/year | — |

**Feeds into:** [infrastructure_total_eur](/cost/infrastructure-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
