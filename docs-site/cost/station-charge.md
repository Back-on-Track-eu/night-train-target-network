---
title: Station charges
description: The fee paid for every scheduled stop at a station.
---

# Station charges

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-station_charge_eur"></a>

The fee paid for every scheduled stop at a station.

### The formula

$$ C_{station} = \sum_{stop} c_{stop,charge} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_stop,charge` | Station fee per scheduled stop | €/stop | [stop_charge_eur](/reference/parameters#p-input_params-stop_infrastructures-stop_charge_eur) |
| **Result** | `C_station` | Annual station charges | €/year | — |

**Feeds into:** [infrastructure_total_eur](/cost/infrastructure-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
