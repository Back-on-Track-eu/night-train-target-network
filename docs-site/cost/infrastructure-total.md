---
title: "Infrastructure cost"
description: "Everything paid to infrastructure companies: track, power, stations and parking."
---

# Infrastructure cost

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

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
