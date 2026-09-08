---
title: 'Overnight parking'
description: 'Parking the train at each end of the route between two nights of service.'
---

# Overnight parking

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Stabling the train between two nights of service — a daily rate at each
end of the route.

A night train spends its day somewhere, and that somewhere charges for it.
The rate comes from the facility calibration, which prices each country on
its own basis against the scheduled layover and the train's length. Some
countries' free allowances cover a twelve-hour turnaround entirely, so
their parking cost is genuinely zero rather than missing.

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

<FeedbackForm />
