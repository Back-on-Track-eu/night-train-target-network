---
title: Traction electricity
description: The traction electricity drawn, at each country's price, plus the catenary supply charge.
---

# Traction electricity

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-energy_eur"></a>

The traction electricity drawn, at each country's price, plus the catenary supply charge.

### The formula

$$ C_{energy} = \sum_{seg} \sum_{c \in seg} \left[ E_{kWh,c} \left( (1-\nu^{E}_{c}) p_{c} + \nu^{E}_{c} p^{night}_{c} \right) + d_{c} \left( e_{c} + e^{gt}_{c} m_{gross} \right) \right] $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `E_kWh,c` | Energy used in the country (from the energy model) | kWh | [energy_per_leg](/reference/formulas#f-energy-energy_per_leg) |
| Input | `p_c` | The country's day traction electricity price | €/kWh | [track_energy_price_eur_kwh](/reference/parameters#p-input_params-track_infrastructures-track_energy_price_eur_kwh) |
| Input | `p^night_c` | Its night-band price, where the tariff is banded | €/kWh | [track_energy_price_night_eur_kwh](/reference/parameters#p-input_params-track_infrastructures-track_energy_price_night_eur_kwh) |
| Input | `nu^E_c` | Share of the country leg billed at the night rate | – | [energy_night_share](/reference/formulas#f-calc-energy_night_share) |
| Input | `e_c` | Charge for using the catenary and traction power-supply installations, per train-kilometre | €/train-km | [track_energy_catenary_eur_train_km](/reference/parameters#p-input_params-track_infrastructures-track_energy_catenary_eur_train_km) |
| Input | `e^gt_c` | The same charge where the country levies it on the weight moved instead | €/gross-tonne-km | [track_energy_catenary_eur_gross_tonne_km](/reference/parameters#p-input_params-track_infrastructures-track_energy_catenary_eur_gross_tonne_km) |
| Input | `m_gross` | Gross weight of the whole consist, coaches plus locomotives | t | computed upstream |
| Input | `d_c` | Kilometres run in the country on this segment | km | computed upstream |
| **Result** | `C_energy` | Annual traction energy cost | €/year | — |

**Feeds into:** [infrastructure_total_eur](/cost/infrastructure-total)
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
