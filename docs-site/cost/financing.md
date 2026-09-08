---
title: 'Financing'
description: 'The annual cost of financing the coaches.'
---

# Financing

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

The annual cost of borrowing to buy the coaches — the purchase price times
a financing rate.

Kept separate from the [write-off](/cost/coach-amortisation) because they
answer different questions: amortisation is what the asset costs to
consume, financing is what the capital costs to raise. A public operator
with cheap capital and a private one with expensive capital differ here
and nowhere else.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-financing_eur"></a>

The annual cost of financing the coaches.

### The formula

$$ C_{fin} = C_{coach,purchase} \times q_{fin} \times n $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `C_coach,purchase` | Purchase price per coach | €/coach | [composition_type_purchase_coach_eur](/reference/parameters#p-input_params-composition_types-composition_type_purchase_coach_eur) |
| Input | `q_fin` | Annual financing rate on the purchase price | fraction/year | [operator_financing_quota_per](/reference/parameters#p-input_params-operators-operator_financing_quota_per) |
| Input | `n` | Coaches needed for the service, incl. reserve | coaches | computed upstream |
| **Result** | `C_fin` | Annual financing cost | €/year | — |

**Feeds into:** [operator_fixed_total_eur](/cost/operator-fixed-total)
<!-- END GENERATED: formula -->

<FeedbackForm />
