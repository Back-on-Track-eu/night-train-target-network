---
title: 'Cabin crew cost'
description: 'What the cabin crew costs per year, including the relief crew a long trip needs.'
---

# Cabin crew cost

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

What the on-board staff cost over a year — the people who make up berths,
serve breakfast and look after passengers overnight.

Priced the same way as the driver: a wage per productive hour divided by
the share of paid hours that is productive, times the hours the crew is on
board. Long trips need relief crew, which lowers that share and raises the
effective hourly cost.

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-crew_eur"></a>

What the cabin crew costs per year, including the relief crew a long trip needs.

### The formula

$$ C_{crew} = \frac{c_{crew/h}}{\eta_{crew}} \times \left( \sum_{seg} t_{drive,h} \cdot n_{crew} + \sum_{stop} t_{dwell,h} \cdot n_{crew} \right) $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `c_crew/h` | Crew wage per productive hour, per attendant | €/h | [operator_crew_costs_eur_h](/reference/parameters#p-input_params-operators-operator_crew_costs_eur_h) |
| Input | `eta_crew` | Share of paid crew hours that is productive | – | [roster_efficiency_driver](/reference/formulas#f-calc-roster_efficiency_driver) |
| Input | `t_drive,h` | Driving time between stops | h | computed upstream |
| Input | `t_dwell,h` | Waiting time at stops | h | [dwell_time_both](/reference/formulas#f-route-dwell_time_both) |
| Input | `n_crew` | Crew members on board (train manager counted with a factor) | persons | [coach_type_crew_factor](/reference/parameters#p-input_params-coach_types-coach_type_crew_factor) |
| **Result** | `C_crew` | Annual cabin crew cost | €/year | — |

**Feeds into:** [operator_variable_total_eur](/cost/operator-variable-total)
<!-- END GENERATED: formula -->

<FeedbackForm />
