---
title: Fixed overhead
description: Administration, management and planning, as a share of the operator's other costs.
---

# Fixed overhead

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

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
