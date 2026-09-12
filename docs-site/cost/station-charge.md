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

This is the weakest-sourced line in the cost model. Only Germany has real
station charges in the database, and every other country falls back to a
single flat rate per call. For a route whose stops are mostly outside
Germany, this line is a placeholder carrying a number.

Germany's figures come from DB InfraGO's **Stationspreisliste 2026**,
transcribed in full for all 5,412 German stations. Station tariffs exist and
are public in most countries; seventeen simply have not been transcribed yet.
See [data sources](/sources/#shunting-stabling-and-station-charges).

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

<FeedbackForm />
