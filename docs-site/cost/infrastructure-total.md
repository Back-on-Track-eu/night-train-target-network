---
title: 'Infrastructure cost'
description: 'Everything paid to infrastructure companies: track, power, stations and parking.'
---

# Infrastructure cost

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Everything paid to the companies that own and run the railway itself:
track access, traction electricity, station stops and overnight parking.

This is the part of a night train's cost that policy moves most directly.
Each country sets its own charging regime, and they differ enormously in
both level and structure — some charge per kilometre, some per tonne, some
take a share of ticket revenue. A cross-border night train pays each of
them in turn, which is why this figure is so sensitive to the route.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-infrastructure_total_eur"></a>

Everything paid to infrastructure companies: track, power, stations and parking.

### The formula

$$ C_{infrastructure} = C_{TAC} + C_{energy} + C_{station} + C_{park} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `C_TAC` | Track access charges | €/year | [tac_eur](/cost/tac) |
| Input | `C_energy` | Traction electricity cost | €/year | [energy_eur](/cost/energy) |
| Input | `C_station` | Station charges | €/year | [station_charge_eur](/cost/station-charge) |
| Input | `C_park` | Overnight parking cost | €/year | [parking_eur](/cost/parking) |
| **Result** | `C_infrastructure` | Total infrastructure cost | €/year | — |

**Feeds into:** [total_cost_eur](/cost/total-cost)
<!-- END GENERATED: formula -->

<FeedbackForm />
