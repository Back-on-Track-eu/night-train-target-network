---
title: 'Station charges'
description: 'The fee paid for every scheduled stop at a station.'
---

# Station charges

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

The fee paid for each scheduled stop at a station.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-station_charge_eur"></a>

The fee paid for every scheduled stop at a station.

### The formula

$$ C_{station} = \sum_{stop} \left( c_{stop,charge} + c_{stop,tonne} \cdot m_{coaches} \right) $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_stop,charge` | Station fee per scheduled stop (fixed part) | €/stop | [stop_charge_eur](/reference/parameters#p-input_params-stop_infrastructures-stop_charge_eur) |
| Input | `c_stop,tonne` | Mass-based station fee per tonne of coach mass; zero where the tariff is per call only | €/stop/t | [stop_charge_per_tonne_eur](/reference/parameters#p-input_params-stop_infrastructures-stop_charge_per_tonne_eur) |
| Input | `m_coaches` | Coach mass of the composition, without traction that carries no passengers | t | [section_weight_t](/reference/parameters#p-input_params-coach_type_classes-section_weight_t) |
| **Result** | `C_station` | Annual station charges | €/year | — |

**Feeds into:** [infrastructure_total_eur](/cost/infrastructure-total)
<!-- END GENERATED: formula -->

<FeedbackForm />
