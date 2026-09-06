---
title: 'Fixed overhead'
description: "Administration, management and planning, as a share of the operator's other costs."
---

# Fixed overhead

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

Administration, management, planning — the operator's own running costs,
charged as a share on top of its other costs.

The base deliberately excludes charges paid to infrastructure companies.
Marking up track access charges as though they were an operator cost would
inflate overhead on exactly the routes that cross the most borders, which
would be an artefact of the charging regime rather than a real cost.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-fix_overhead_eur"></a>

Administration, management and planning, as a share of the operator's other costs.

### The formula

$$ C_{fix,oh} = q_{fix,oh} \times \left(C_{op,var} - C_{var,oh} + C_{op,fix}\right) $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `q_fix,oh` | Fixed overhead share | fraction | [operator_fix_overhead_quota_per](/reference/parameters#p-input_params-operators-operator_fix_overhead_quota_per) |
| Input | `C_op,var` | All variable operator costs | €/year | computed upstream |
| Input | `C_var,oh` | Variable overhead (excluded from the base) | €/year | [var_overhead_eur](/cost/var-overhead) |
| Input | `C_op,fix` | All fixed operator costs | €/year | computed upstream |
| **Result** | `C_fix,oh` | Annual fixed overhead | €/year | — |

**Feeds into:** [operator_fixed_total_eur](/cost/operator-fixed-total)
<!-- END GENERATED: formula -->

<FeedbackForm />
