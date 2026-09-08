---
title: 'Shunting'
description: 'Coupling, uncoupling and parking moves in stations and yards.'
---

# Shunting

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Moving the train around stations and yards: coupling, uncoupling and
positioning moves.

Priced per movement, and the movement count is currently **fixed at two
per trip**. Real shunting depends on the shape of the service — whether
portions split, whether the train reverses — and the model does not yet
derive that from the route. A route with unusual shunting needs will be
priced as though it had ordinary ones. This is listed in
[what we don't yet model](/not-modelled).

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

<FeedbackForm />
