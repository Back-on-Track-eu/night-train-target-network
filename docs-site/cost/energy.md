---
title: 'Traction electricity'
description: "The traction electricity drawn, at each country's price, plus the catenary supply charge."
---

# Traction electricity

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

The electricity the train draws, at each country's price, plus what the
infrastructure manager charges for delivering it through the overhead line.

Two separate things are being priced. How much energy the train uses comes
from a model calibrated against Deutsche Bahn Trassenfinder technical
runs: start-stop energy for the train's weight, rolling resistance over
the distance, air resistance rising with length and the square of speed,
and the on-board supply that keeps heating, air conditioning and light
running all night. What that energy costs comes from each country's
traction electricity tariff.

Like track access, electricity is split by the clock where a country has a
night tariff — only Austria, Switzerland and Croatia do.

One assumption worth naming: coach hotel power is an estimate, not a
measurement. The calibration runs were queried with it switched off, so
the figure for keeping a sleeping train warm and lit was added afterwards
rather than measured. See [how energy was calibrated](/methodology/energy).

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

<FeedbackForm />
