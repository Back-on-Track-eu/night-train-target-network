---
title: Shunting
description: Coupling, uncoupling and parking moves in stations and yards.
---

# Shunting

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-shunting_eur"></a>

Coupling, uncoupling and parking moves in stations and yards.

### The formula

$$ C_{shunt} = c_{shunt/event} \times n_{events} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_shunt/event` | Cost per shunting movement | €/event | [track_shunting_eur_event](/reference/parameters#p-input_params-track_infrastructures-track_shunting_eur_event) |
| Input | `n_events` | Shunting movements per year | events/year | computed upstream |
| **Result** | `C_shunt` | Annual shunting cost | €/year | — |

**Feeds into:** [operator_fixed_total_eur](/cost/operator-fixed-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
