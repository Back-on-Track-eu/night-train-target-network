---
title: 'Coach maintenance'
description: 'Maintaining the coaches, charged per kilometre driven.'
---

# Coach maintenance

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Keeping the coaches serviceable, charged as a rate per kilometre driven.

Locomotive maintenance is **not** here — it is bundled into the
[locomotive rental](/cost/loco), which is quoted all-inclusive. Counting
it in both places is a mistake worth naming, because the two lines look
like they should be symmetrical and are not.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-coach_maintenance_eur"></a>

Maintaining the coaches, charged per kilometre driven.

### The formula

$$ C_{coach,maint} = \sum_{seg} c_{coach,maint/km} \times d_{km,seg} $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_coach,maint/km` | Maintenance rate for all coaches of the train, per kilometre | €/train-km | [composition_type_coach_maint_eur_km](/reference/parameters#p-input_params-composition_types-composition_type_coach_maint_eur_km) |
| Input | `d_km,seg` | Distance driven | km | computed upstream |
| **Result** | `C_coach,maint` | Annual coach maintenance cost | €/year | — |

**Feeds into:** [operator_variable_total_eur](/cost/operator-variable-total)
<!-- END GENERATED: formula -->

<FeedbackForm />
